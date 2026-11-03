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

from pipeline.budget import Budget
from pipeline.config import load_scoring, load_taxonomy
from pipeline.embed import Embedder
from pipeline.llm import LLM
from pipeline.jsonio import day_path
from pipeline.run import Deps, _related, _stage, _staging, is_degraded, run_backfill, run_day, run_reprocess
from pipeline.sources.arxiv import ArxivAdapter
from pipeline.sources.base import load_config
from pipeline.sources.biorxiv import BiorxivAdapter
from pipeline.sources.github import GithubAdapter
from pipeline.sources.pubmed import PubmedAdapter
from pipeline.sources.rss import RssAdapter
from pipeline.store import Store
from pipeline.synthesize import synthesize_top
from pipeline.wipe import validate_month_range, wipe as wipe_store


app = typer.Typer(help='Collect, rank, and synthesize computational biology trends.', no_args_is_help=True)
Domain = Annotated[str, typer.Option(help='Configured taxonomy domain.')]
DataRoot = Annotated[Path, typer.Option(help='Root directory for pipeline data.')]
FromDate = Annotated[datetime, typer.Option('--from', formats=['%Y-%m-%d'])]
ToDate = Annotated[datetime, typer.Option('--to', formats=['%Y-%m-%d'])]


@app.callback()
def configure_logging():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # HTTP request logs include query strings, which can contain API credentials.
    for name in ("httpx", "httpcore", "httpx2", "httpcore2"):
        logging.getLogger(name).setLevel(logging.WARNING)


def build_deps(domain: str, data_root: Path) -> Deps:
    cfg = load_scoring()
    taxonomy = load_taxonomy(domain)
    sources = load_config()
    budget = Budget(data_root / domain / 'llm_spend.json', cfg.monthly_ceiling_usd)
    return Deps(
        adapters=[BiorxivAdapter(sources), ArxivAdapter(sources), PubmedAdapter(sources),
                  GithubAdapter(sources, star_counts=Store(data_root, domain).star_counts(),
                                star_gain_threshold=cfg.star_gain_threshold), RssAdapter(sources)],
        llm=LLM(anthropic.Anthropic(), budget), embedder=Embedder(), budget=budget,
        cfg=cfg, taxonomy=taxonomy, hints_cfg=sources.get('hints', {}),
        client=httpx.Client(timeout=30),
    )


@contextmanager
def _dependencies(domain: str, data_root: Path):
    deps = None
    try:
        with _stage('initialize'):
            deps = build_deps(domain, data_root)
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


@app.command()
def backfill(start: FromDate, end: ToDate, domain: Domain = 'computational',
             resume: Annotated[bool, typer.Option(help='Continue from the saved checkpoint.')] = False,
             data_root: DataRoot = Path('data')):
    """Collect a historical range, batch-enrich it, then process days in order."""
    with _dependencies(domain, data_root) as deps:
        run_backfill(domain, start.date(), end.date(), Store(data_root, domain), deps, resume=resume)


@app.command()
def reprocess(start: FromDate, end: ToDate, domain: Domain = 'computational',
              reenrich: Annotated[bool, typer.Option(help='Replace enrichment for every stored item.')] = False,
              model: Annotated[str, typer.Option(help='Batch enrichment model.')] = 'claude-haiku-5-5',
              data_root: DataRoot = Path('data')):
    """Re-scope and rebuild whole months from stored items, resuming interrupted work."""
    validate_month_range(start.date(), end.date())
    with _dependencies(domain, data_root) as deps:
        run_reprocess(domain, start.date(), end.date(), Store(data_root, domain), deps,
                      reenrich=reenrich, model=model)


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
    budget = Budget(data_root / domain / 'llm_spend.json', cfg.monthly_ceiling_usd)
    days = degraded_days = 0
    day = start.date()
    while day <= end.date():
        result = store.get_day(day)
        if result is not None:
            window = store.items_between(day - timedelta(days=cfg.window_days - 1), day)
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
                        staged.put_topic(topic)
                    result.run.synthesis_model = selected
                    result.run.notes = sorted(set([
                        note for note in result.run.notes if not note.startswith('synthesis-fallback:')
                    ] + notes))
                    window = staged.items_between(day - timedelta(days=deps.cfg.window_days - 1), day)
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
