import json
from datetime import date, timedelta

import numpy as np
import pytest

from pipeline.jsonio import day_path, embeddings_shard_path, item_path, load, topic_path
from pipeline.models import Day, Item, Topic
from pipeline.store import Store


@pytest.fixture
def item():
    return Item(
        id="biorxiv:10.1101/2026.01.02.123456",
        source="biorxiv", type="preprint", title="Protein design — test",
        url="https://example.org/preprint", doi=None,
        published_at=date(2025, 12, 1), first_seen=date(2026, 1, 2),
        authors=[], org=None, abstract="Abstract.", summary=None,
        primary_category=None, published_doi=None, preprint_id=None,
    )


def test_put_get_item_roundtrip(tmp_path, item, fixtures_root, monkeypatch):
    store = Store(tmp_path, "computational")
    assert store.get_item(item.id) is None
    assert not store.has_item(item.id)
    assert store.all_topics() == store.all_days() == []
    assert store.get_topic("missing") is None
    assert store.get_day(date(2026, 11, 1)) is None
    store.put_item(item)
    topic = load(Topic, next((fixtures_root / "data/computational/topics").glob("*.json")))
    day = load(Day, day_path(fixtures_root / "data", "computational", date(2026, 11, 1)))
    store.put_topic(topic)
    store.put_day(day)
    store = Store(tmp_path, "computational")
    assert store.get_item(item.id) == item
    assert store.has_item(item.id)
    assert store.get_topic(topic.slug) == topic
    assert store.all_topics() == [topic]
    assert store.get_day(day.date) == day
    assert store.all_days() == [day]
    assert topic_path(tmp_path, "computational", topic.slug).exists()
    assert day_path(tmp_path, "computational", day.date).exists()
    assert Store(tmp_path, "another-domain").get_item(item.id) is None
    path = item_path(tmp_path, "computational", item)
    before = path.read_bytes()
    assert before.decode() == json.dumps(item.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def fail_replace(source, destination):
        assert source.parent == destination.parent
        raise OSError("interrupted replace")

    with monkeypatch.context() as patch:
        patch.setattr("pipeline.store.os.replace", fail_replace)
        with pytest.raises(OSError, match="interrupted"):
            store.put_item(item.model_copy(update={"summary": "Updated"}))
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_items_between_uses_first_seen(tmp_path, item):
    store = Store(tmp_path, "computational")
    for offset in range(4):
        store.put_item(item.model_copy(update={
            "id": f"arxiv:{offset}", "source": "arxiv",
            "first_seen": date(2026, 1, 31) + timedelta(days=offset),
        }))
    assert [row.id for row in store.items_between(date(2026, 1, 31), date(2026, 2, 1))] == ["arxiv:0", "arxiv:1"]
    assert store.items_between(item.published_at, item.published_at) == []
    assert store.items_between(date(2026, 2, 2), date(2026, 2, 1)) == []


def test_embedding_shard_by_month(tmp_path, item, monkeypatch):
    store = Store(tmp_path, "computational")
    second = item.model_copy(update={"id": "arxiv:second", "first_seen": date(2026, 2, 1)})
    third = item.model_copy(update={"id": "arxiv:third"})
    for row in (item, second, third):
        store.put_item(row)
    a, b, c = [np.array(values, dtype=np.float32) for values in ([1, 0.1], [0.2, 1], [0.3, 0.4])]
    store.put_embedding(item.id, a)
    store.put_embedding(second.id, b)
    store.put_embedding(third.id, c)
    january, index_path = embeddings_shard_path(tmp_path, "computational", "2026-01")
    february, _ = embeddings_shard_path(tmp_path, "computational", "2026-02")
    assert set(january.parent.glob("*.npy")) == {january, february}
    for path in (january, february):
        assert path.stat().st_size < 50_000_000
        assert np.load(path).dtype == np.float16
    assert json.loads(index_path.read_text()) == {item.id: 0, third.id: 1}
    store.put_embedding(item.id, b)
    assert json.loads(index_path.read_text()) == {item.id: 0, third.id: 1}
    assert np.load(january).shape == (2, 2)
    result = Store(tmp_path, "computational").get_embeddings([third.id, second.id, item.id, third.id])
    assert result.dtype == np.float32
    np.testing.assert_allclose(result, [c, b, b, c], atol=0.001)
    assert store.get_embeddings([]).shape == (0, 0)
    with pytest.raises(KeyError) as error:
        store.get_embeddings([item.id, "arxiv:missing", "arxiv:also-missing"])
    assert error.value.args == ("arxiv:missing",)
    with pytest.raises(KeyError):
        store.put_embedding("arxiv:missing", a)
    unembedded = item.model_copy(update={"id": "arxiv:unembedded"})
    store.put_item(unembedded)
    with pytest.raises(KeyError) as error:
        store.get_embeddings([unembedded.id, "arxiv:missing"])
    assert error.value.args == (unembedded.id,)
    for invalid in (np.ones((1, 2)), np.ones(3), np.array([]),
                    np.array([np.nan, 1]), np.array([70_000, 1])):
        with pytest.raises(ValueError):
            store.put_embedding(item.id, invalid)
    before = january.read_bytes()

    def fail_save(file, *args, **kwargs):
        file.write(b"partial")
        raise OSError("interrupted save")

    with monkeypatch.context() as patch:
        patch.setattr("pipeline.store.np.save", fail_save)
        with pytest.raises(OSError, match="interrupted"):
            store.put_embedding(item.id, a)
    assert january.read_bytes() == before
    assert len(list(january.parent.iterdir())) == 4

    from pipeline.store import os

    replace = os.replace

    def fail_index(source, destination):
        if destination == index_path:
            raise OSError("interrupted index")
        replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr("pipeline.store.os.replace", fail_index)
        with pytest.raises(OSError, match="interrupted index"):
            store.put_embedding(unembedded.id, a)
    np.testing.assert_allclose(store.get_embeddings([item.id, third.id]), [b, c], atol=0.001)
    with pytest.raises(KeyError):
        store.get_embeddings([unembedded.id])
    store.put_embedding(unembedded.id, a)
    assert json.loads(index_path.read_text()) == {item.id: 0, third.id: 1, unembedded.id: 2}
    assert np.load(january).shape == (3, 2)


def test_put_item_twice_overwrites_not_duplicates(tmp_path, item):
    store = Store(tmp_path, "computational")
    store.put_item(item)
    updated = item.model_copy(update={"summary": "Updated"})
    store.put_item(updated)
    assert store.get_item(item.id) == updated
    # Rediscovery cannot change first_seen or move an existing embedding's shard.
    store.put_item(updated.model_copy(update={"first_seen": date(2026, 2, 1)}))
    assert store.get_item(item.id) == updated
    assert store.items_between(date.min, date.max) == [updated]
    assert len(list(tmp_path.rglob("*.json"))) == 1


def test_star_counts_pruned_to_60_days(tmp_path):
    store = Store(tmp_path, "computational")
    assert store.star_counts() == {}
    # Anchor retention to the latest observation so historical backfills work.
    latest = date(2026, 1, 1)
    history = [(latest - timedelta(days=i), 100 - i) for i in range(65)]
    store.put_star_counts({"org/repo": history, "org/old": [history[-1]]})
    expected = sorted(history[:60])
    assert Store(tmp_path, "computational").star_counts() == {"org/repo": expected, "org/old": []}
    path = tmp_path / "computational/github_stars.json"
    raw = json.loads(path.read_text())
    assert raw["org/repo"] == [{"date": day.isoformat(), "stars": count} for day, count in expected]
    assert path.read_text() == json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    store.put_star_counts({})
    assert store.star_counts() == {}
