from datetime import date
import logging
from typing import get_args

from pipeline.dedupe import dedupe
from pipeline.models import Item, Source
from pipeline.sources.base import SourceAdapter
from pipeline.store import Store

logger = logging.getLogger(__name__)


class AllPaperSourcesFailed(Exception):
    pass


PAPER_SOURCES = {'biorxiv', 'arxiv', 'pubmed', 'crossref'}


def initial_source_status(adapters):
    # Older editions expose five source keys. Include the new intake only in editions that use it.
    return dict.fromkeys((name for name in get_args(Source) if name != 'crossref'
                          or any(a.name == name for a in adapters)), 'skipped')


def all_paper_sources_failed(status: dict[str, str]) -> bool:
    attempted = {status[name] for name in PAPER_SOURCES if status.get(name, 'skipped') != 'skipped'}
    return attempted == {'failed'}


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
            source_status[adapter.name] = "ok"
    if all_paper_sources_failed(source_status):
        raise AllPaperSourcesFailed("All paper sources failed")
    return dedupe(items, store), source_status
