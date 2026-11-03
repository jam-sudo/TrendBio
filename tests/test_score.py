from datetime import date, timedelta
from math import log1p

import pytest

from pipeline.cluster import append_history
from pipeline.config import load_scoring
from pipeline.models import Item, Signals, Topic
from pipeline.score import code_velocity, diversity, rank, rise, score_topics, signals_for, volume


TODAY = date(2026, 11, 2)


@pytest.fixture
def cfg():
    return load_scoring()


@pytest.fixture
def topic():
    return Topic(
        slug='protein-design-abcd', label='protein design', category='structural',
        secondary_categories=[], centroid=[1.0, 0.0], history=[], headline=None,
        summary=None, synthesis=None, synthesis_model=None, synthesized_on=None,
    )


@pytest.fixture
def sig():
    return Signals(published=0, preprint=7, code=0, industry=0,
                   rise_ratio=0.0, star_gain_7d=0)


@pytest.fixture
def preprint():
    return Item(
        id='biorxiv:paper', source='biorxiv', type='preprint', title='Protein design',
        url='https://example.org/paper', doi=None, published_at=TODAY, first_seen=TODAY,
        authors=[], org=None, abstract='', summary=None, primary_category='structural',
        published_doi=None, preprint_id=None,
    )


def test_new_topic_uses_global_median_baseline(topic, sig, cfg):
    assert rise(topic, 7, TODAY, cfg, global_median=7) == 1.0
    other = topic.model_copy(update={'slug': 'other'})
    scored = score_topics([(topic, sig, 7), (other, sig, 3)], set(), cfg, TODAY)
    assert scored[0][2].rise == 10 / 8  # Median of 3 and 7 is 5.
    assert scored[0][1].rise_ratio == 10 / 8
    assert sig.rise_ratio == 0.0


def test_established_topic_5_to_20_beats_new_7(topic, cfg):
    new = topic.model_copy(deep=True)
    for days_ago in (7, 14, 21, 28):
        append_history(topic, TODAY - timedelta(days=days_ago), [], 5)
    append_history(topic, TODAY, [], 20)
    assert rise(topic, 20, TODAY, cfg, 7) == 2.875
    assert rise(topic, 20, TODAY, cfg, 7) > rise(new, 7, TODAY, cfg, 7) == 1.0


def test_rise_capped_at_10(topic, sig, cfg):
    for days_ago in (7, 14, 21, 28):
        append_history(topic, TODAY - timedelta(days=days_ago), [], 0)
    assert rise(topic, 300, TODAY, cfg, 7) == 10.0
    _, signals, scores = score_topics([(topic, sig, 300)], set(), cfg, TODAY)[0]
    assert signals.rise_ratio == 101.0
    assert scores.rise == 10.0


def test_diversity_counts_linked_pair_once(topic, preprint):
    published = preprint.model_copy(update={
        'id': 'pubmed:paper', 'source': 'pubmed', 'type': 'published',
        'preprint_id': preprint.id,
    })
    signals = signals_for(topic, [preprint, published], {})
    assert signals == Signals(published=1, preprint=0, code=0, industry=0,
                              rise_ratio=0.0, star_gain_7d=0)
    assert diversity(signals) == 0.25
    unrelated = preprint.model_copy(update={'id': 'biorxiv:other'})
    assert diversity(signals_for(topic, [preprint, published, unrelated], {})) == 0.5
    assert signals_for(topic, [preprint], {}).preprint == 1


def test_yesterday_penalty_5_percent(topic, sig, cfg):
    fresh = score_topics([(topic, sig, 7)], set(), cfg, TODAY)[0][2]
    repeat = score_topics([(topic, sig, 7)], {topic.slug}, cfg, TODAY)[0][2]
    expected = 0.45 + 0.25 / 4 + 0.15 * log1p(7) / log1p(50)
    assert fresh.total == pytest.approx(expected)
    assert fresh.penalty == 0
    assert repeat.penalty == pytest.approx(0.05 * expected)
    assert repeat.total == pytest.approx(0.95 * expected)


def test_rank_empty_returns_empty(cfg):
    assert score_topics([], set(), cfg, TODAY) == []
    assert rank([], cfg) == []


def test_rank_returns_at_most_5(topic, sig, cfg):
    inputs = [(topic.model_copy(update={'slug': str(i)}), sig, 7)
              for i in reversed(range(7))]
    scored = score_topics(inputs, set(), cfg, TODAY)
    assert [entry[0].slug for entry in rank(scored, cfg)] == list('01234')
    assert rank(scored[:2], cfg) == scored[:2]
    cfg.top_n = 2
    assert rank(scored, cfg) == scored[:2]
    cfg.top_n = 0
    assert rank(scored, cfg) == []


@pytest.mark.parametrize('age, expected', [(13, 1.0), (14, 10 / 5)])
def test_rise_history_threshold_and_missing_weeks(topic, cfg, age, expected):
    append_history(topic, TODAY - timedelta(days=age), [], 4)
    append_history(topic, TODAY - timedelta(days=7), [], 4)
    append_history(topic, TODAY - timedelta(days=1), [], 100)
    assert rise(topic, 7, TODAY, cfg, 7) == expected


def test_star_gain_uses_latest_and_seven_days_earlier(topic, preprint):
    repos = ['growing', 'falling', 'missing', 'short']
    items = [preprint.model_copy(update={
        'id': f'github:org/{repo}', 'type': 'code', 'source': 'github',
    }) for repo in repos]
    stars = {
        'org/growing': [(TODAY, 250), (TODAY - timedelta(days=7), 100),
                        (TODAY - timedelta(days=1), 200)],
        'org/falling': [(TODAY - timedelta(days=7), 100), (TODAY, 50)],
        'org/short': [(TODAY, 1000)],
    }
    signals = signals_for(topic, items, stars)
    assert signals.code == 4
    assert signals.star_gain_7d == 150
    assert code_velocity(signals) == pytest.approx(log1p(150) / log1p(10_000))


def test_components_scale_and_cap(sig):
    assert code_velocity(sig) == volume(0) == 0.0
    sig.star_gain_7d = 10_000
    assert code_velocity(sig) == volume(50) == 1.0
    sig.star_gain_7d = 20_000
    assert code_velocity(sig) == volume(100) == 1.0
    sig.published = sig.code = sig.industry = 1
    assert diversity(sig) == 1.0


def test_rank_caps_two_per_category_and_backfills_with_other_categories(topic, sig, cfg, caplog):
    categories = ['ml-ai'] * 4 + ['structural', 'genomics', 'tools-infra']
    scored = score_topics([(topic.model_copy(update={'slug': str(i), 'category': category}), sig, 7)
                           for i, category in enumerate(categories)], set(), cfg, TODAY)
    with caplog.at_level('INFO'):
        ranked = rank(scored, cfg)
    assert [row[0].slug for row in ranked] == ['0', '1', '4', '5', '6']
    assert 'stage=score_rank event=category_cap displaced=2' in caplog.text
    assert 'stage=score_rank event=category_cap displaced=3' in caplog.text
    cfg.max_per_category = 1
    assert [row[0].slug for row in rank(scored, cfg)] == ['0', '1', '4', '5', '6']


def test_rank_overflows_when_not_enough_categories(topic, sig, cfg, caplog):
    categories = ['ml-ai'] * 5 + ['structural']
    scored = score_topics([(topic.model_copy(update={'slug': str(i), 'category': category}), sig, 7)
                           for i, category in enumerate(categories)], set(), cfg, TODAY)
    with caplog.at_level('INFO'):
        ranked = rank(scored, cfg)
    assert [row[0].slug for row in ranked] == ['0', '1', '2', '3', '5']
    assert 'displaced=4' in caplog.text
    assert 'displaced=2' not in caplog.text and 'displaced=3' not in caplog.text
    assert rank(scored[:4], cfg) == scored[:4]
