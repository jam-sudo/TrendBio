from datetime import date
import logging
from typing import get_args

from pipeline.dedupe import dedupe
from pipeline.models import Item, Source
from pipeline.sources.base import SourceAdapter
from pipeline.sources.crossref import CrossrefAdapter
from pipeline.sources.europepmc import EuropePmcAdapter
from pipeline.store import Store

logger = logging.getLogger(__name__)


class AllPaperSourcesFailed(Exception):
    pass


PAPER_SOURCES = {'biorxiv', 'arxiv', 'pubmed', 'crossref', 'drops', 'oai', 'europepmc', 'worldbank', 'thoth', 'openedition'}
PARTIAL_REASONS = {'book-date-source-unavailable', 'abstract-source-unavailable'}


def initial_source_status(adapters):
    # Older editions expose five source keys. Include the new intake only in editions that use it.
    return dict.fromkeys((name for name in get_args(Source) if name not in {'crossref', 'drops', 'oai', 'europepmc', 'worldbank', 'thoth', 'openedition'}
                          or any(a.name == name for a in adapters)), 'skipped')


def all_paper_sources_failed(status: dict[str, str]) -> bool:
    attempted = {status[name] for name in PAPER_SOURCES if status.get(name, 'skipped') != 'skipped'}
    return attempted == {'failed'}


def intake_status(adapter):
    return 'ok' if PARTIAL_REASONS.isdisjoint(getattr(adapter, 'decisions', {}).values()) else 'partial'


def prepare_collected(items, store, start, end, successful_adapters):
    result = {item.id: item for item in dedupe(items, store)}
    for adapter in successful_adapters:
        if isinstance(adapter, (CrossrefAdapter, EuropePmcAdapter)):
            for item in adapter.reconcile(store, start, end, items):
                if item.id in result:
                    linked = result[item.id]
                    item = item.model_copy(update={'preprint_id': linked.preprint_id, 'published_doi': linked.published_doi})
                result[item.id] = item
    return list(result.values())


def collect(
    domain: str, start: date, end: date, store: Store,
    adapters: list[SourceAdapter], client,
) -> tuple[list[Item], dict[str, str]]:
    source_status = initial_source_status(adapters)
    items = []
    for adapter in adapters:
        try:
            items.extend(adapter.fetch(start, end, client))
        except Exception as exc:
            logger.warning("%s failed (%s)", adapter.name, type(exc).__name__)
            source_status[adapter.name] = "failed"
        else:
            source_status[adapter.name] = intake_status(adapter)
    if all_paper_sources_failed(source_status):
        raise AllPaperSourcesFailed("All paper sources failed")
    successful = [a for a in adapters if source_status[a.name] == 'ok']
    return prepare_collected(items, store, start, end, successful), source_status
