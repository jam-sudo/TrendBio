"""Command-line entry points for the TrendBio pipeline."""

import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import anthropic
import httpx
import typer
import yaml

from pipeline.budget import Budget
from pipeline.config import load_scoring, load_taxonomy
from pipeline.embed import Embedder
from pipeline.llm import LLM
from pipeline.jsonio import day_path
from pipeline.run import (
    Deps, _related, _stage, _staging, is_degraded, run_backfill, run_day, run_reprocess,
    run_repair_synthesis, synthesis_repair_targets,
)
from pipeline.sources.arxiv import ArxivAdapter
from pipeline.sources.base import load_config
from pipeline.sources.biorxiv import BiorxivAdapter
from pipeline.sources.crossref import CrossrefAdapter
from pipeline.sources.drops import DropsAdapter
from pipeline.sources.github import GithubAdapter
from pipeline.sources.pubmed import PubmedAdapter
from pipeline.sources.rss import RssAdapter
from pipeline.store import Store
from pipeline.topic_map import build_map
from pipeline.synthesize import synthesize_top
from pipeline.wipe import validate_month_range, wipe as wipe_store


app = typer.Typer(help='Collect, rank, and synthesize research trends.', no_args_is_help=True)
Domain = Annotated[str, typer.Option(help='Configured taxonomy domain.')]
DataRoot = Annotated[Path, typer.Option(help='Root directory for pipeline data.')]
FromDate = Annotated[datetime, typer.Option('--from', formats=['%Y-%m-%d'])]
ToDate = Annotated[datetime, typer.Option('--to', formats=['%Y-%m-%d'])]


@app.callback()
def configure_logging(ctx: typer.Context = None):
    stream = sys.stderr if ctx and ctx.invoked_subcommand in {'audit-edition', 'audit-beta', 'survey', 'trial-windows'} else sys.stdout
    logging.basicConfig(level=logging.INFO, stream=stream,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # HTTP request logs include query strings, which can contain API credentials.
    for name in ("httpx", "httpcore", "httpx2", "httpcore2"):
        logging.getLogger(name).setLevel(logging.WARNING)


def build_deps(domain: str, data_root: Path, *, synthesis_only: bool = False) -> Deps:
    cfg = load_scoring()
    taxonomy = load_taxonomy(domain)
    sources = load_config(domain)
    adapters = []
    for adapter in (BiorxivAdapter, ArxivAdapter, PubmedAdapter, GithubAdapter, RssAdapter, CrossrefAdapter, DropsAdapter):
        if adapter.name not in sources:
            continue
        if adapter is GithubAdapter:
            adapters.append(adapter(sources, star_counts=Store(data_root, domain).star_counts(),
                                    star_gain_threshold=cfg.star_gain_threshold))
        else:
            adapters.append(adapter(sources))
    budget = Budget(data_root / domain / 'llm_spend.json', cfg.monthly_ceiling_usd)
    return Deps(
        adapters=adapters,
        llm=LLM(anthropic.Anthropic(), budget, field=taxonomy.label,
                synthesis_guidance=taxonomy.synthesis_guidance),
        embedder=None if synthesis_only else Embedder(), budget=budget,
        cfg=cfg, taxonomy=taxonomy, hints_cfg=sources.get('hints', {}),
        client=httpx.Client(timeout=30),
    )


@contextmanager
def _dependencies(domain: str, data_root: Path, *, synthesis_only: bool = False):
    deps = None
    try:
        with _stage('initialize'):
            deps = (build_deps(domain, data_root, synthesis_only=True) if synthesis_only
                    else build_deps(domain, data_root))
        yield deps
    except Exception as error:
        message = str(error)
        for key, value in os.environ.items():
            if value and any(word in key.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
                message = message.replace(value, '[redacted]')
        typer.echo(f'{type(error).__name__}: {message}', err=True)
        raise typer.Exit(1) from None
    finally:
        if deps is not None:
            deps.client.close()


@app.command()
def run(domain: Domain = 'computational',
        run_date: Annotated[datetime | None, typer.Option('--date', formats=['%Y-%m-%d'])] = None,
        dry_run: Annotated[bool, typer.Option(help='Keep staged output and print usage and cost.')] = False,
        data_root: DataRoot = Path('data')):
    """Run collection, enrichment, clustering, ranking, and synthesis for one UTC day."""
    day = (run_date or datetime.now(timezone.utc)).date()
    with _dependencies(domain, data_root) as deps:
        run_day(domain, day, Store(data_root, domain), deps, dry_run=dry_run)


@app.command('trial-windows')
def trial_windows(domain: Domain, end: ToDate):
    """Run the same clustering on four disjoint weeks and on their union using public metadata and local embeddings."""
    from pipeline.window_trial import PILOT_DOMAINS, run_window_trial, trial_records

    fields = yaml.safe_load(Path('config/expansion-venues.yaml').read_text())
    if domain not in PILOT_DOMAINS and domain not in fields:
        raise typer.BadParameter('Unknown trial field')
    day = end.date()
    with httpx.Client(timeout=40, headers={'User-Agent': 'TrendBio metadata survey (https://trendbio.dev)'}) as client:
        records = list(trial_records(domain, fields.get(domain, []), day - timedelta(days=27), day, client))
    result = run_window_trial(domain, records, day, Embedder())
    result['survey_only'] = {v['subject']: v['survey_only'] for v in fields.get(domain, []) if v.get('survey_only')}
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command()
def survey(end: ToDate,
           domain: Annotated[str | None, typer.Option(help='Survey one field from config/expansion-venues.yaml.')] = None):
    """Compare four non-overlapping weeks against independent indexes and publisher records."""
    from pipeline.survey import survey_venue

    fields = yaml.safe_load(Path('config/expansion-venues.yaml').read_text())
    if domain and domain not in fields:
        raise typer.BadParameter('Unknown survey field')
    report = {'from': str(end.date() - timedelta(days=27)), 'to': str(end.date()), 'fields': {}}
    failed = False
    with httpx.Client(timeout=40, headers={'User-Agent': 'TrendBio metadata survey (https://trendbio.dev)'}) as client:
        for field, venues in fields.items():
            if domain and field != domain:
                continue
            results = []
            for venue in venues:
                try:
                    record = survey_venue(client, venue, end.date())
                except (httpx.HTTPError, KeyError, ValueError) as exc:
                    record = {**venue, 'status': 'failed', 'reason': str(exc)}
                failed |= record['status'] == 'failed' or (record.get('reference') or {}).get('status') == 'failed'
                results.append(record)
            report['fields'][field] = results
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise typer.Exit(1)


@app.command('map')
def topic_map(domain: Domain = 'computational', data_root: DataRoot = Path('data')):
    """Rebuild the topic map from stored centroids, without LLM calls."""
    load_taxonomy(domain)
    store = Store(data_root, domain)
    with _stage('map'):
        store.put_map(build_map(store, load_scoring(), previous=store.get_map()))


@app.command('audit-beta')
def audit_beta_cmd(domain: Domain, end: ToDate, data_root: DataRoot = Path('data')):
    """Report progress through the first 14 distinct live editions and their coverage gaps."""
    from pipeline.edition_audit import audit_beta

    typer.echo(json.dumps(audit_beta(Store(data_root, domain), end.date()), ensure_ascii=False, indent=2))


@app.command('audit-edition')
def audit_edition_cmd(start: FromDate, end: ToDate, domain: Domain, data_root: DataRoot = Path('data'),
                     references: Annotated[Path | None, typer.Option(help='JSON array of dated IDs or DOIs from independent lists.')] = None,
                     compare_windows: Annotated[bool, typer.Option(help='Recluster the last 28 days of available publication data.')] = False):
    """Measure field coverage, costs and selection. Emit review cases with their evidence IDs."""
    from pipeline.edition_audit import audit_edition, compare_windows as cluster_windows

    refs = json.loads(references.read_text()) if references else []
    if not isinstance(refs, list) or any(not isinstance(r, dict) or not all(
            isinstance(r.get(key), str) and r[key].strip() for key in ('date', 'id', 'source')) for r in refs):
        raise typer.BadParameter('Each reference needs a date, an ID or DOI, and its source')
    if any(not str(start.date()) <= r['date'] <= str(end.date()) for r in refs):
        raise typer.BadParameter('Reference date outside audit interval')
    store = Store(data_root, domain)
    report = audit_edition(store, start.date(), end.date(), refs)
    if compare_windows:
        report['window_comparison'] = cluster_windows(store, end.date())
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@app.command()
def backfill(start: FromDate, end: ToDate, domain: Domain = 'computational',
             resume: Annotated[bool, typer.Option(help='Continue from the saved checkpoint.')] = False,
             data_root: DataRoot = Path('data')):
    """Collect a historical range, batch-enrich it, then process days in order."""
    with _dependencies(domain, data_root) as deps:
        run_backfill(domain, start.date(), end.date(), Store(data_root, domain), deps, resume=resume)


@app.command()
def reprocess(start: FromDate, end: ToDate, domain: Domain = 'computational',
              reenrich: Annotated[bool, typer.Option('--reenrich/--no-reenrich', help='Replace enrichment for every stored item.')] = False,
              only_missing_synthesis: Annotated[bool, typer.Option(help='Preserve topics with an existing headline.')] = False,
              rebuild_topics: Annotated[bool, typer.Option(help='Reset topic history in range and discard affected syntheses.')] = False,
              model: Annotated[str, typer.Option(help='Batch enrichment model.')] = 'claude-haiku-5-5',
              data_root: DataRoot = Path('data')):
    """Re-scope and rebuild whole months from stored items, resuming interrupted work."""
    validate_month_range(start.date(), end.date())
    with _dependencies(domain, data_root) as deps:
        run_reprocess(domain, start.date(), end.date(), Store(data_root, domain), deps,
                      reenrich=reenrich, model=model, only_missing_synthesis=only_missing_synthesis,
                      rebuild_topics=rebuild_topics)


@app.command('repair-synthesis')
def repair_synthesis(start: FromDate, end: ToDate, domain: Domain = 'computational',
                     model: Annotated[str, typer.Option(help='Synthesis repair model.')] = 'claude-haiku-5-5',
                     retry_fallbacks: Annotated[bool, typer.Option(help='Retry complete item-title fallbacks as well.')] = False,
                     data_root: DataRoot = Path('data'),
                     dry_run: Annotated[bool, typer.Option(help='Count repair targets without LLM calls or writes.')] = False):
    """Repair missing or formerly truncated syntheses without reranking or collecting items."""
    if start > end:
        raise typer.BadParameter('start must not be after end')
    if dry_run:
        _, _, topics, rows, jobs, _ = synthesis_repair_targets(
            Store(data_root, domain), start.date(), end.date(), retry_fallbacks=retry_fallbacks,
        )
        typer.echo(f'repair_synthesis_targets rows={len(rows)} topics={len(topics)} estimated_jobs={len(jobs)}')
        return
    with _dependencies(domain, data_root, synthesis_only=True) as deps:
        run_repair_synthesis(domain, start.date(), end.date(), Store(data_root, domain), deps,
                             model=model, retry_fallbacks=retry_fallbacks)


@app.command()
def wipe(start: FromDate, end: ToDate, domain: Domain = 'computational',
         data_root: DataRoot = Path('data')):
    """Delete whole months of pipeline output before re-running a backfill."""
    counts = wipe_store(Store(data_root, domain), start.date(), end.date())
    typer.echo(' '.join(f'{name}={count}' for name, count in counts.items()))


@app.command()
def restatus(start: FromDate, end: ToDate, domain: Domain = 'computational',
             data_root: DataRoot = Path('data')):
    """Recompute stored run statuses without collection or LLM calls."""
    if start > end:
        raise typer.BadParameter('start must not be after end')
    cfg = load_scoring()
    store = Store(data_root, domain)
    by_publication = load_taxonomy(domain).window_by_publication
    budget = Budget(data_root / domain / 'llm_spend.json', cfg.monthly_ceiling_usd)
    days = degraded_days = 0
    day = start.date()
    while day <= end.date():
        result = store.get_day(day)
        if result is not None:
            window = store.items_between(day - timedelta(days=cfg.window_days - 1), day, by_publication=by_publication)
            degraded = is_degraded(
                result.run.notes, result.run.source_status,
                window_item_ids={item.id for item in window}, cfg=cfg,
                over_ceiling=budget.month_spend_usd(result.run.finished.strftime('%Y-%m')) > cfg.monthly_ceiling_usd,
            )
            status = 'degraded' if degraded else 'ok'
            if result.run.status != status:
                path = day_path(data_root, domain, day)
                payload = json.loads(path.read_text(encoding='utf-8'))
                payload['run']['status'] = status
                store._write(path, payload)
            days += 1
            degraded_days += degraded
        day += timedelta(days=1)
    typer.echo(f'restatus days={days} degraded={degraded_days} ok={days - degraded_days}')


@app.command()
def resynthesize(start: FromDate, end: ToDate, model: Annotated[str, typer.Option()],
                 domain: Domain = 'computational', data_root: DataRoot = Path('data')):
    """Replace synthesis for existing ranked topics using the requested model."""
    with _dependencies(domain, data_root) as deps:
        if start > end:
            raise ValueError('start must not be after end')
        store = Store(data_root, domain)
        with _staging(store, deps) as (staged, staged_deps):
            day = start.date()
            while day <= end.date():
                result = staged.get_day(day)
                if result is not None:
                    ranked, items_by_topic = [], {}
                    for row in result.ranked:
                        topic = staged.get_topic(row.slug)
                        if topic is None:
                            raise ValueError(f'missing topic: {row.slug}')
                        entry = next(entry for entry in topic.history if entry.date == day)
                        items = [staged.get_item(id) for id in entry.item_ids]
                        if any(item is None for item in items):
                            raise ValueError(f'missing items for topic: {row.slug}')
                        ranked.append((topic, row.signals, row.scores))
                        items_by_topic[topic.slug] = items
                    topics, selected, notes = synthesize_top(
                        ranked, items_by_topic, staged_deps.llm, staged_deps.budget,
                        deps.cfg, day, backfill=result.run.backfilled, model=model,
                    )
                    for row, topic in zip(result.ranked, topics, strict=True):
                        row.headline, row.summary = topic.headline, topic.summary
                        row.synthesis = topic.synthesis if topic.synthesized_on == day else None
                        staged.put_topic(topic)
                    result.run.synthesis_model = selected
                    result.run.notes = sorted(set([
                        note for note in result.run.notes if not note.startswith('synthesis-fallback:')
                    ] + notes))
                    window = staged.items_between(day - timedelta(days=deps.cfg.window_days - 1), day,
                                                  by_publication=deps.taxonomy.window_by_publication)
                    degraded = is_degraded(result.run.notes, result.run.source_status,
                                           over_ceiling=staged_deps.budget.over_ceiling(),
                                           window_item_ids={item.id for item in window}, cfg=deps.cfg)
                    result.run.status = 'degraded' if degraded else 'ok'
                    staged.put_day(result)
                day += timedelta(days=1)
            topics = staged.all_topics()
            _related(topics)
            for topic in topics:
                staged.put_topic(topic)


if __name__ == '__main__':
    app()
