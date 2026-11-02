from datetime import date, timedelta
import hashlib
import re

import numpy as np
import pytest

from pipeline.cluster import (
    append_history, cluster_items, fill_unranked_days, keyword_slug, match_or_create,
)
from pipeline.config import Scoring
from pipeline.embed import l2_normalize
from pipeline.models import Item, Topic


@pytest.fixture
def cfg():
    return Scoring(weights={})


@pytest.fixture
def topic():
    return Topic(
        slug='protein-design-abcd', label='protein design', category='structural',
        secondary_categories=[], centroid=[1.0, 0.0, 0.0], history=[],
        headline='Existing headline', summary=None, synthesis=None,
        synthesis_model=None, synthesized_on=None,
    )


@pytest.fixture
def items():
    return {
        str(i): Item(
            id=str(i), source='biorxiv', type='preprint', title=title,
            url='https://example.org/paper', doi=None, published_at=date(2026, 11, 1),
            first_seen=date(2026, 11, 1), authors=[], org=None, abstract='',
            summary='Enriched summary', primary_category=category,
            published_doi=None, preprint_id=None,
        )
        for i, (title, category) in enumerate([
            ('Protein design with diffusion', 'structural'),
            ('Protein design with language models', 'ml-ai'),
            ('Protein design of binders', 'structural'),
            ('Protein design benchmarks', 'ml-ai'),
        ])
    }


def test_two_tight_groups_form_two_clusters_and_singleton_dropped(cfg):
    ids = list('abcdefg')
    vectors = l2_normalize(np.array([
        [1, 0, 0], [1, .02, 0], [1, 0, .02],
        [0, 1, 0], [.02, 1, 0], [0, 1, .02], [0, 0, 1],
    ]))
    assert {frozenset(group) for group in cluster_items(ids, vectors, cfg)} == {
        frozenset('abc'), frozenset('def'),
    }
    assert cluster_items([], np.empty((0, 3)), cfg) == []
    assert cluster_items(['a'], vectors[:1], cfg) == []
    cfg.min_cluster_size = 1
    assert cluster_items(['a'], vectors[:1], cfg) == [['a']]


def test_cluster_items_respects_linkage_config(cfg):
    angles = np.deg2rad([0, 20, 40])
    vectors = np.column_stack([np.cos(angles), np.sin(angles)])
    cfg.min_cluster_size = 1
    cfg.cluster_distance_threshold = 0.18
    cfg.cluster_linkage = 'average'
    assert cluster_items(list('abc'), vectors, cfg) == [list('abc')]
    cfg.cluster_linkage = 'complete'
    assert sorted(map(len, cluster_items(list('abc'), vectors, cfg))) == [1, 2]


def test_continuity_matches_existing_topic_above_threshold(topic, items, cfg):
    today = date(2026, 11, 2)
    append_history(topic, today - timedelta(days=1), ['old'], 1)
    titles = [item.title for item in items.values()]
    centroid = np.array([.8, .6, 0], dtype=np.float32)
    worse = topic.model_copy(deep=True, update={'slug': 'worse', 'centroid': [0, 1, 0]})
    result = match_or_create(list(items), centroid, [worse, topic], today, cfg,
                             titles, titles, items)
    assert result is topic
    assert result.slug == 'protein-design-abcd'
    assert result.headline == 'Existing headline'
    assert len(result.history) == 1
    np.testing.assert_allclose(result.centroid, l2_normalize([[1.8, .6, 0]])[0])
    assert result.category == 'ml-ai'  # Alphabetical tie-break.
    assert result.secondary_categories == ['structural']
    assert worse.centroid == [0, 1, 0]


def test_continuity_creates_new_below_threshold(topic, items, cfg):
    ids = list(items)[:3]
    titles = [items[item_id].title for item_id in ids]
    corpus = [item.title for item in items.values()]
    centroid = np.array([0, 1, 0], dtype=np.float32)
    result = match_or_create(ids, centroid, [topic], date(2026, 11, 2), cfg,
                             titles, corpus, items)
    assert result is not topic
    assert (result.slug, result.label) == keyword_slug(titles, corpus, ids)
    assert result.category == 'structural'
    assert result.secondary_categories == ['ml-ai']
    assert result.centroid == [0, 1, 0]
    assert result.history == []
    assert result.headline is result.summary is result.synthesis is None
    assert result.synthesis_model is result.synthesized_on is None
    assert topic.centroid == [1, 0, 0]


def test_slug_is_keywords_plus_hash_and_stable(items):
    titles = [item.title for item in items.values()]
    corpus = titles + ['Genome assembly and variant calling', 'Cell atlas integration']
    ids = list(items)
    slug, label = keyword_slug(titles, corpus, ids)
    assert (slug, label) == keyword_slug(titles, corpus, ids)
    assert (slug, label) == keyword_slug(titles, corpus, ids[::-1])
    assert re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+){1,4}-[0-9a-f]{4}', slug)
    assert slug.rsplit('-', 1)[0] == label.replace(' ', '-')
    assert 'protein' in label or 'design' in label
    assert slug.endswith(hashlib.sha1('\n'.join(sorted(ids)).encode()).hexdigest()[:4])
    assert keyword_slug(titles, corpus, ids + ['another'])[0] != slug


@pytest.mark.parametrize('titles, corpus, expected_label', [
    (['the and of'], ['the and of'], 'untitled topic'),
    (['α β'], ['α β'], 'untitled topic'),
    (['unseen vocabulary'], ['protein design'], 'untitled topic'),
    (['genomics'], ['genomics'], 'genomics topic'),
])
def test_slug_with_few_scored_terms_has_stable_fallback(titles, corpus, expected_label):
    slug, label = keyword_slug(titles, corpus, ['a', 'b'])
    assert label == expected_label
    assert re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+){1,4}-[0-9a-f]{4}', slug)
    assert (slug, label) == keyword_slug(titles, corpus, ['b', 'a'])


@pytest.mark.parametrize('size, secondary', [(4, ['ml-ai']), (5, [])])
def test_secondary_category_requires_quarter_share(items, cfg, size, secondary):
    template = items['0']
    items = {
        str(i): template.model_copy(update={
            'id': str(i), 'primary_category': 'ml-ai' if i == 0 else 'structural',
        })
        for i in range(size)
    }
    titles = [item.title for item in items.values()]
    topic = match_or_create(list(items), np.array([1, 0, 0], dtype=np.float32), [],
                            date(2026, 11, 2), cfg, titles, titles, items)
    assert topic.category == 'structural'
    assert topic.secondary_categories == secondary


def test_append_history_replaces_same_day(topic):
    today = date(2026, 11, 2)
    append_history(topic, today, ['old'], 1)
    topic.history[0].rank = 1
    append_history(topic, today - timedelta(days=1), ['yesterday'], 2)
    append_history(topic, today, ['new'], 3)
    assert len(topic.history) == 2
    assert [entry.date for entry in topic.history] == [today - timedelta(days=1), today]
    entry = topic.history[-1]
    assert entry.item_ids == ['new'] and entry.count_7d == 3
    assert entry.rank is None
    assert all(value == 0 for value in entry.signals.model_dump().values())
    assert all(value == 0 for value in entry.scores.model_dump().values())


def test_fill_unranked_days_leaves_no_gaps(topic):
    first = date(2026, 11, 1)
    today = first + timedelta(days=7)
    fill_unranked_days(topic, today)
    assert topic.history == []
    append_history(topic, first, ['first'], 3)
    topic.history[0].rank = 1
    append_history(topic, today, ['today'], 4)
    topic.history[-1].rank = 2
    fill_unranked_days(topic, today)
    assert [entry.date for entry in topic.history] == [
        first + timedelta(days=offset) for offset in range(8)
    ]
    for entry in topic.history[1:-1]:
        assert entry.rank is None and entry.item_ids == [] and entry.count_7d == 0
        assert all(value == 0 for value in entry.signals.model_dump().values())
        assert all(value == 0 for value in entry.scores.model_dump().values())
    assert topic.history[0].rank == 1 and topic.history[-1].rank == 2
    original = topic.model_copy(deep=True)
    fill_unranked_days(topic, today)
    assert topic == original
    fill_unranked_days(topic, today + timedelta(days=3))
    assert topic.history[-1].date == today + timedelta(days=2)


def test_keyword_slug_prefers_terms_shared_across_titles():
    titles = ['genomics prediction', 'genomics mapping', 'genomics sequencing', 'myopia']
    corpus = titles + ['genomics prediction mapping sequencing'] * 100
    _, label = keyword_slug(titles, corpus, list('abcd'))
    assert label == 'genomics topic'


@pytest.mark.parametrize('titles', [
    ['cell death analysis', 'cells death study', 'human cell death', 'mouse death'],
    ['cell death death', 'cell death death'],
])
def test_keyword_slug_drops_fillers_and_repeated_words(titles):
    _, label = keyword_slug(titles, titles, [str(i) for i in range(len(titles))])
    assert label == 'death topic'


def test_keyword_slug_rejects_single_title_terms_in_large_clusters():
    titles = ['myopia', 'cancer', 'genomics', 'proteomics']
    _, label = keyword_slug(titles, titles, list('abcd'))
    assert label == 'untitled topic'
