from datetime import date
import logging

import pytest

from pipeline.collect import AllPaperSourcesFailed, collect
from pipeline.models import Item
from pipeline.store import Store


class FakeAdapter:
    def __init__(self, name, items=(), error=None):
        self.name = name
        self.items = list(items)
        self.error = error
        self.calls = []

    def fetch(self, start, end, client):
        self.calls.append((start, end, client))
        if self.error is not None:
            raise self.error
        return self.items


def test_one_source_failing_continues(tmp_path, caplog):
    store = Store(tmp_path, "computational")
    start, end = date(2026, 1, 1), date(2026, 1, 2)
    item = Item(
        id="arxiv:one", source="arxiv", type="preprint", title="Study",
        url="https://example.org", doi=None, published_at=start, first_seen=end,
        authors=[], org=None, abstract="Abstract", summary=None,
        primary_category=None, published_doi=None, preprint_id=None,
    )
    adapters = [
        FakeAdapter("biorxiv", error=ValueError("https://example.org?api_key=SECRET Authorization: TOKEN")),
        FakeAdapter("arxiv", [item, item]),
        FakeAdapter("rss"),
    ]
    client = object()
    with caplog.at_level(logging.WARNING):
        items, statuses = collect("computational", start, end, store, adapters, client)
    assert items == [item]
    assert statuses == {"biorxiv": "failed", "arxiv": "ok", "pubmed": "skipped", "github": "skipped", "rss": "ok"}
    assert all(adapter.calls == [(start, end, client)] for adapter in adapters)
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert "biorxiv" in caplog.text and "ValueError" in caplog.text
    assert "SECRET" not in caplog.text and "TOKEN" not in caplog.text
    assert "https://" not in caplog.text and caplog.records[0].exc_info is None
    assert store.items_between(date.min, date.max) == []
    assert collect("computational", start, end, store, [], client) == (
        [], dict.fromkeys(statuses, "skipped"),
    )


def test_all_paper_sources_failing_raises(tmp_path):
    store = Store(tmp_path, "computational")
    day = date(2026, 1, 1)
    adapters = [FakeAdapter(name, error=RuntimeError("unavailable"))
                for name in ("biorxiv", "arxiv", "pubmed")]
    adapters.append(FakeAdapter("github"))
    client = object()
    with pytest.raises(AllPaperSourcesFailed):
        collect("computational", day, day, store, adapters, client)
    assert all(adapter.calls == [(day, day, client)] for adapter in adapters)
    assert store.items_between(date.min, date.max) == []
    adapters[2] = FakeAdapter("pubmed")
    assert collect("computational", day, day, store, adapters, client)[1]["pubmed"] == "ok"
