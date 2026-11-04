import json
import logging
import shutil
from types import SimpleNamespace

import numpy as np
import pytest
from typer.testing import CliRunner

from pipeline.__main__ import app
from pipeline.config import load_scoring
from pipeline.models import MapData
from pipeline.store import Store
from pipeline.topic_map import build_map


@pytest.fixture
def map_store(tmp_path, fixtures_root):
    shutil.copytree(fixtures_root / 'data', tmp_path / 'data')
    return Store(tmp_path / 'data', 'computational')


def test_build_map_normalises_and_neighbors(map_store):
    result = build_map(map_store, load_scoring(), previous=None)
    topics = {topic.slug: topic for topic in map_store.all_topics()}
    assert len(result.points) == 40
    for point in result.points:
        assert 0 <= point.x <= 1 and 0 <= point.y <= 1
        assert len(point.neighbors) == 3 and point.slug not in point.neighbors
        assert len(set(point.neighbors)) == 3
        topic = topics[point.slug]
        assert point.months == sorted({str(entry.date)[:7] for entry in topic.history})
        assert point.size == sum(len(entry.item_ids) for entry in topic.history)
        ranked = [entry.date for entry in topic.history if entry.rank is not None]
        assert (point.first_ranked, point.last_ranked) == (min(ranked), max(ranked))
        vector = np.asarray(topic.centroid)
        nearest = sorted((p for p in result.points if p.slug != point.slug), key=lambda p: (
            -np.dot(vector, topics[p.slug].centroid) /
            (np.linalg.norm(vector) * np.linalg.norm(topics[p.slug].centroid)), p.slug))[:3]
        assert point.neighbors == [p.slug for p in nearest]
    map_store.put_map(result)
    assert map_store.get_map() == result


@pytest.mark.parametrize('count', [5, 16])
def test_build_map_transforms_into_previous_layout(map_store, monkeypatch, caplog, count):
    topics = map_store.all_topics()[:count + 1]
    rng = np.random.default_rng(42)
    for topic in topics:
        topic.centroid = rng.normal(size=5).tolist()
        topic.history[0].rank = 1
    store = SimpleNamespace(all_topics=lambda: topics[:count])
    calls = []
    if count >= 10:
        import umap

        class FakeUMAP:
            def __init__(self, **kwargs):
                assert kwargs == dict(n_neighbors=15, min_dist=0.1, metric='cosine', random_state=42)

            def fit_transform(self, vectors):
                calls.append(('fit', len(vectors)))
                self.embedding_ = vectors[:, :2].copy()
                return self.embedding_

            def transform(self, vectors):
                calls.append(('transform', len(vectors)))
                return np.repeat(self.embedding_.mean(axis=0, keepdims=True), len(vectors), axis=0)

        monkeypatch.setattr(umap, 'UMAP', FakeUMAP)
    previous = build_map(store, load_scoring(), previous=None)
    # An arbitrary previous orientation must be retained, even as centroids drift.
    for point in previous.points:
        point.x, point.y = point.y * 0.8 + 0.1, 1 - point.x
    for topic in topics:
        topic.centroid[0] += 0.01
    store.all_topics = lambda: topics
    with caplog.at_level(logging.INFO):
        result = build_map(store, load_scoring(), previous=previous)
    assert 'path=transform' in caplog.text
    saved = {point.slug: point for point in previous.points}
    for point in result.points:
        if point.slug in saved:
            assert point.x == pytest.approx(saved[point.slug].x, abs=1e-6)
            assert point.y == pytest.approx(saved[point.slug].y, abs=1e-6)
    if count >= 10:
        assert calls == [('fit', count), ('fit', count), ('transform', 1)]
    assert len(result.points) == count + 1


def test_map_refits_only_above_twenty_percent(map_store, caplog):
    topics = map_store.all_topics()[:6]
    for topic in topics:
        topic.history[0].rank = 1
    store = SimpleNamespace(all_topics=lambda: topics[:4])
    previous = build_map(store, load_scoring(), previous=None)
    store.all_topics = lambda: topics[:5]
    with caplog.at_level(logging.INFO):
        build_map(store, load_scoring(), previous=previous)
    assert 'path=transform' in caplog.text
    caplog.clear()
    store.all_topics = lambda: topics
    with caplog.at_level(logging.INFO):
        build_map(store, load_scoring(), previous=previous)
    assert 'path=refit' in caplog.text


@pytest.mark.parametrize('count,dimension', [(0, 1), (1, 1), (2, 1), (4, 5), (9, 768)])
def test_small_maps_and_arbitrary_dimensions(map_store, count, dimension):
    topics = map_store.all_topics()[:count]
    for i, topic in enumerate(topics):
        topic.centroid = [float(i + 1)] * dimension
        topic.history[0].rank = 1
    result = build_map(SimpleNamespace(all_topics=lambda: topics), load_scoring(), previous=None)
    assert len(result.points) == count
    assert all(len(p.neighbors) == min(3, count - 1) for p in result.points)
    assert all(0 <= p.x <= 1 and 0 <= p.y <= 1 for p in result.points)


def test_map_cli_writes_file(map_store, monkeypatch):
    monkeypatch.setattr('pipeline.__main__.build_deps', lambda *args: pytest.fail('map must not load LLMs'))
    result = CliRunner().invoke(app, ['map', '--domain', 'computational', '--data-root', str(map_store.root)])
    assert result.exit_code == 0, result.output
    payload = json.loads((map_store.root / 'computational/map.json').read_text())
    assert len(MapData.model_validate(payload).points) == 40


def test_invalid_centroid_does_not_replace_map(map_store):
    topic = next(t for t in map_store.all_topics() if any(h.rank is not None for h in t.history))
    topic.centroid = [float('nan')] * 5
    map_store.put_topic(topic)
    with pytest.raises(ValueError, match='finite'):
        build_map(map_store, load_scoring(), previous=None)
    assert map_store.get_map() is None
