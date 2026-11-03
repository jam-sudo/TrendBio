import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pipeline.jsonio import day_path, dump, embeddings_shard_path, item_path, load, topic_path
from pipeline.models import Day, Item, RunInfo, Topic


@pytest.fixture
def item():
    return Item(
        id="biorxiv:10.1101/2026.01.02.123456",
        source="biorxiv",
        type="preprint",
        title="Protein design — a fixture",
        url="https://example.org/preprint",
        doi="10.1101/2026.01.02.123456",
        published_at=date(2026, 1, 1),
        first_seen=date(2026, 1, 2),
        authors=["Example Author"],
        org=None,
        abstract="Synthetic abstract.",
        summary=None,
        primary_category=None,
        published_doi=None,
        preprint_id=None,
        metadata={"z": 1, "a": {"z": 2, "a": 3}},
    )


def test_item_roundtrip_sorted_keys(tmp_path, item):
    path = tmp_path / "nested" / "item.json"
    dump(item, path)
    raw = path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert "—" in raw
    pairs = json.loads(raw, object_pairs_hook=lambda pairs: pairs)
    assert [key for key, _ in pairs] == sorted(Item.model_fields)
    assert raw == json.dumps(item.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert load(Item, path) == item


def test_item_id_to_filename(item):
    assert item_path(Path("data"), "computational", item) == Path(
        "data/computational/items/2026/01/biorxiv_10.1101_2026.01.02.123456.json"
    )


def test_day_status_literal_rejects_other():
    with pytest.raises(ValidationError, match="status"):
        Day(
            domain="computational",
            date=date(2026, 11, 1),
            ranked=[],
            run=RunInfo(
                started=datetime(2026, 11, 1, 6, tzinfo=timezone.utc),
                finished=datetime(2026, 11, 1, 6, 1, tzinfo=timezone.utc),
                status="broken",
                backfilled=False,
                synthesis_model="claude-opus-5-5",
                source_status={"biorxiv": "ok"},
            ),
        )


def test_other_contract_paths():
    root = Path("data")
    assert topic_path(root, "computational", "protein-design-binders-a1b2") == root / "computational/topics/protein-design-binders-a1b2.json"
    assert day_path(root, "computational", date(2026, 11, 1)) == root / "computational/days/2026-11-01.json"
    assert embeddings_shard_path(root, "computational", "2026-11") == (
        root / "computational/embeddings/2026-11.npy",
        root / "computational/embeddings/2026-11.index.json",
    )


@pytest.mark.parametrize("field,value", [("source", "unknown"), ("type", "paper")])
def test_item_literals_reject_other(item, field, value):
    with pytest.raises(ValidationError, match=field):
        Item.model_validate({**item.model_dump(), field: value})


def test_item_mutable_defaults_are_independent(item):
    fields = item.model_dump(exclude={"metadata", "secondary_categories"})
    first, second = Item(**fields), Item(**fields)
    first.metadata["fixture"] = True
    first.secondary_categories.append("fixture-category")
    assert second.metadata == {}
    assert second.secondary_categories == []


def test_fixtures_validate(fixtures_root):
    root = fixtures_root / "data"
    domain = root / "computational"
    items, topics, days = {}, {}, {}
    for path in sorted(domain.rglob("*.json")):
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert raw == json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", path
        section = path.relative_to(domain).parts[0]
        if section == "items":
            item = load(Item, path)
            assert path == item_path(root, "computational", item)
            assert item.id not in items
            assert item.id.startswith(item.source + ":")
            items[item.id] = item
        elif section == "topics":
            topic = load(Topic, path)
            assert path == topic_path(root, "computational", topic.slug)
            topics[topic.slug] = topic
        else:
            assert section == "days", path
            day = load(Day, path)
            assert path == day_path(root, "computational", day.date)
            days[day.date] = day

    assert len(items) == 320
    assert len(topics) == 41
    assert sorted(days) == [date(2026, 10, 29), date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1)]
    assert {item.type for item in items.values()} == {"preprint", "published", "code", "industry"}
    assert {item.source for item in items.values()} == {"biorxiv", "arxiv", "pubmed", "github", "rss"}
    taxonomy = yaml.safe_load((fixtures_root.parent / "config/taxonomy/computational.yaml").read_text(encoding="utf-8"))
    categories = {entry["slug"] for entry in taxonomy["categories"]}
    assert len(categories) == 11
    papers = [item for item in items.values() if item.preprint_id]
    assert papers
    for paper in papers:
        preprint = items[paper.preprint_id]
        assert paper.type == "published" and preprint.type == "preprint"
        assert preprint.published_doi == paper.doi
        assert preprint.published_at <= paper.published_at
    for item in items.values():
        assert item.primary_category in categories
        assert set(item.secondary_categories) <= categories
        assert item.summary and len(item.summary) <= 160
    for topic in topics.values():
        assert topic.category in categories
        assert set(topic.secondary_categories) <= categories
        assert set(topic.related) <= topics.keys() - {topic.slug}
        assert len(topic.related) <= 3
        assert topic.item_one_liners.keys() <= items.keys()
        assert topic.headline and len(topic.headline) <= 90
        assert topic.summary and len(topic.summary) <= 160
        assert topic.synthesis and 80 <= len(topic.synthesis.split()) <= 160
        assert sum(value * value for value in topic.centroid) == pytest.approx(1)
        dates = [entry.date for entry in topic.history]
        assert dates == [dates[0] + timedelta(days=i) for i in range(len(dates))]
        for entry in topic.history:
            assert set(entry.item_ids) <= items.keys()
            assert len(entry.item_ids) == len(set(entry.item_ids))
            current = [items[item_id] for item_id in entry.item_ids]
            assert all(entry.date - timedelta(days=6) <= item.first_seen <= entry.date for item in current)
            linked = {item.preprint_id for item in current if item.preprint_id}
            counted = [item for item in current if item.id not in linked]
            assert entry.count_7d == len(counted)
            for kind in ("published", "preprint", "code", "industry"):
                assert getattr(entry.signals, kind) == sum(item.type == kind for item in counted)

    binder = topics["protein-design-binders-a1b2"]
    assert len(binder.history) == 70
    assert any(entry.rank is None for entry in binder.history)
    assert [entry.rank for entry in binder.history if entry.date in days] == [None, 1, 1, 2]
    assert all(getattr(binder.history[-1].signals, kind) > 0 for kind in ("published", "preprint", "code", "industry"))
    assert days[date(2026, 10, 30)].run.backfilled is True
    for day in days.values():
        assert day.domain == "computational"
        if day.date == date(2026, 10, 29):
            assert day.ranked == []
            assert day.run.status == "degraded"
            assert day.run.backfilled is True
            continue
        assert [row.rank for row in day.ranked] == list(range(1, 41 if day.date.month == 11 else 6))
        assert {row.slug for row in day.ranked} == {
            topic.slug for topic in topics.values() if any(entry.date == day.date and entry.rank is not None for entry in topic.history)
        }
        assert [row.scores.total for row in day.ranked] == sorted((row.scores.total for row in day.ranked), reverse=True)
        for row in day.ranked:
            topic = topics[row.slug]
            entry = next(entry for entry in topic.history if entry.date == day.date)
            assert (row.rank, row.signals, row.scores) == (entry.rank, entry.signals, entry.scores)
            assert (row.category, row.headline, row.summary) == (topic.category, topic.headline, topic.summary)
    notes = {path.stem for path in (fixtures_root / "notes").glob("*.md")}
    assert notes == {binder.slug, "nonexistent-topic-zzzz"}
    assert "nonexistent-topic-zzzz" not in topics


def test_fixtures_regenerate_identically(tmp_path, fixtures_root, monkeypatch):
    from fixtures_build import build

    monkeypatch.chdir(tmp_path)
    build(tmp_path)
    expected = {path.relative_to(fixtures_root): path.read_bytes()
                for folder in ("data", "notes") for path in (fixtures_root / folder).rglob("*") if path.is_file()}
    actual = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert actual.keys() == expected.keys()
    for path in sorted(expected):
        if path.parts[:3] == ('data', 'computational', 'items'):
            # Legacy fixtures omit the relevance flag, which defaults to true.
            data = json.loads(expected[path])
            data.setdefault('relevant', True)
            expected[path] = (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
        assert actual[path] == expected[path], path


def test_item_without_relevant_field_loads_as_relevant(item):
    raw = item.model_dump_json(exclude={'relevant'})
    assert 'relevant' not in json.loads(raw)
    assert Item.model_validate_json(raw).relevant is True
