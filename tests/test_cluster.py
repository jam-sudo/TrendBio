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
    centroid = l2_normalize([[1, .1, 0]])[0]
    worse = topic.model_copy(deep=True, update={'slug': 'worse', 'centroid': [0, 1, 0]})
    result = match_or_create(list(items), centroid, [worse, topic], today, cfg,
                             titles, titles, items)
    assert result is topic
    assert result.slug == 'protein-design-abcd'
    assert result.headline == 'Existing headline'
    assert len(result.history) == 1
    np.testing.assert_allclose(result.centroid, centroid)
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


def match(topic, items, cfg, similarity):
    titles = [item.title for item in items.values()]
    centroid = np.array([similarity, np.sqrt(1 - similarity ** 2), 0])
    return match_or_create(list(items), centroid, [topic], date(2026, 11, 2), cfg,
                           titles, titles, items)


@pytest.mark.parametrize('offset', [-30, 30])
def test_continuity_requires_recent_entry(topic, items, cfg, offset):
    append_history(topic, date(2026, 11, 2) + timedelta(days=offset), list(items), 4)
    assert match(topic, items, cfg, .99) is not topic


@pytest.mark.parametrize('offset', [-1, 1, -10, 10])
def test_continuity_by_jaccard(topic, items, cfg, offset):
    append_history(topic, date(2026, 11, 2) + timedelta(days=offset), ['0', '1', 'old'], 3)
    assert match(topic, items, cfg, .7) is topic  # 2 / 5 = 0.4 overlap.


def test_continuity_rejects_loose_similarity(topic, items, cfg):
    append_history(topic, date(2026, 11, 1), ['old'], 1)
    assert match(topic, items, cfg, .85) is not topic


def test_continued_topic_centroid_tracks_today(topic, items, cfg):
    append_history(topic, date(2026, 11, 1), list(items), 4)
    assert match(topic, items, cfg, .7) is topic
    np.testing.assert_allclose(topic.centroid, [.7, np.sqrt(1 - .7 ** 2), 0])


def test_continuity_uses_union_of_adjacent_week_only(topic, items, cfg):
    append_history(topic, date(2026, 10, 26), ['0'], 1)
    append_history(topic, date(2026, 11, 1), ['old'], 1)
    assert match(topic, items, cfg, .7) is not topic  # 1 / 5 is below threshold.
    append_history(topic, date(2026, 10, 27), ['1'], 1)
    assert match(topic, items, cfg, .7) is topic
    topic.history[0].date = date(2026, 10, 25)
    assert match(topic, items, cfg, 0) is not topic  # Oct 25 is outside the week.


def test_continuity_prefers_overlap_to_similarity(topic, items, cfg):
    append_history(topic, date(2026, 11, 1), list(items), 4)
    similar = topic.model_copy(deep=True, update={'slug': 'closer', 'centroid': [0, 1, 0]})
    similar.history[0].item_ids = ['other']
    titles = [item.title for item in items.values()]
    result = match_or_create(list(items), np.array([0, 1, 0]), [similar, topic],
                             date(2026, 11, 2), cfg, titles, titles, items)
    assert result is topic


def test_new_topic_slug_cannot_overwrite_expired_identity(items, cfg):
    titles = [item.title for item in items.values()]
    centroid = np.array([1., 0, 0])
    old = match_or_create(list(items), centroid, [], date(2026, 10, 1), cfg, titles, titles, items)
    append_history(old, date(2026, 10, 1), list(items), 4)
    new = match_or_create(list(items), centroid, [old], date(2026, 11, 2), cfg, titles, titles, items)
    assert new.slug != old.slug and new.label == old.label
    assert new.slug.rsplit('-', 1)[0] == old.slug.rsplit('-', 1)[0]


@pytest.mark.parametrize('gap', [10, 11, 30])
def test_fill_unranked_days_respects_max_gap_in_both_directions(topic, gap):
    first = date(2026, 10, 1)
    last = first + timedelta(days=gap)
    append_history(topic, first, ['first'], 1)
    append_history(topic, last, ['last'], 1)
    fill_unranked_days(topic, first, 10)
    assert len(topic.history) == (gap + 1 if gap <= 10 else 2)


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


def test_attach_respects_threshold(cfg):
    from pipeline.cluster import attach_items
    from pipeline.models import Item

    cfg = cfg.model_copy(update={'attach_min_similarity': 0.8})
    items = [Item.model_construct(id=id, type=kind, relevant=relevant)
             for id, kind, relevant in [('edge', 'code', True), ('below', 'industry', True),
                                       ('other', 'industry', True), ('paper', 'preprint', True),
                                       ('irrelevant', 'code', False)]]
    vectors = {'edge': np.array([.8, .6, 0]), 'below': np.array([.79, 0, np.sqrt(1-.79**2)]),
               'other': np.array([0, 1, 0])}
    centroids = [np.array([1, 0, 0]), np.array([0, 1, 0])]
    assert attach_items(items, vectors, centroids, cfg) == [['edge'], ['other']]
    assert attach_items(items, vectors, [], cfg) == []


def test_old_history_entries_load_without_attached_ids(topic):
    from pipeline.models import TopicDay

    append_history(topic, date(2026, 11, 5), ['paper'], 1)
    raw = topic.history[0].model_dump()
    raw.pop('attached_item_ids')
    assert TopicDay.model_validate(raw).attached_item_ids == []
