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


def collect(
    domain: str, start: date, end: date, store: Store,
    adapters: list[SourceAdapter], client,
) -> tuple[list[Item], dict[str, str]]:
    source_status = dict.fromkeys(get_args(Source), "skipped")
    items = []
    for adapter in adapters:
        try:
            items.extend(adapter.fetch(start, end, client))
        except Exception as exc:
            logger.warning("%s failed (%s)", adapter.name, type(exc).__name__)
            source_status[adapter.name] = "failed"
        else:
            source_status[adapter.name] = "ok"
    if all(source_status[name] == "failed" for name in ("biorxiv", "arxiv", "pubmed")):
        raise AllPaperSourcesFailed("All paper sources failed")
    return dedupe(items, store), source_status
