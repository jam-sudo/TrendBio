"""Command-line entry points for the TrendBio pipeline."""

import os
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
from pipeline.run import Deps, _staging, run_backfill, run_day
from pipeline.sources.arxiv import ArxivAdapter
from pipeline.sources.base import load_config
from pipeline.sources.biorxiv import BiorxivAdapter
from pipeline.sources.github import GithubAdapter
from pipeline.sources.pubmed import PubmedAdapter
from pipeline.sources.rss import RssAdapter
from pipeline.store import Store
from pipeline.synthesize import synthesize_top


app = typer.Typer(help='Collect, rank, and synthesize computational biology trends.', no_args_is_help=True)
Domain = Annotated[str, typer.Option(help='Configured taxonomy domain.')]
DataRoot = Annotated[Path, typer.Option(help='Root directory for pipeline data.')]
FromDate = Annotated[datetime, typer.Option('--from', formats=['%Y-%m-%d'])]
ToDate = Annotated[datetime, typer.Option('--to', formats=['%Y-%m-%d'])]


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
                    degraded = (any('-fallback:' in note for note in result.run.notes)
                                or any(result.run.source_status.get(name) == 'failed'
                                       for name in ('biorxiv', 'arxiv', 'pubmed'))
                                or staged_deps.budget.over_ceiling())
                    result.run.status = 'degraded' if degraded else 'ok'
                    staged.put_day(result)
                day += timedelta(days=1)


if __name__ == '__main__':
    app()
