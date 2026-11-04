from urllib.parse import urlsplit

from pipeline.config import Scoring, load_scoring, load_taxonomy
from pipeline.sources.base import load_config


def test_industry_source_config():
    config = load_config()
    assert len(config['industry_keywords']) >= 40
    assert all(isinstance(term, str) and term.strip() for term in config['industry_keywords'])
    assert config['rss']['feeds']
    for feed in config['rss']['feeds']:
        assert feed['name']
        url = urlsplit(feed['url'])
        assert url.scheme == 'https' and url.netloc
        assert feed['kind'] in {'company', 'news'}


def test_taxonomy_has_11_spec_slugs():
    assert load_taxonomy("computational").slugs() == [
        "genomics",
        "transcriptomics",
        "proteomics",
        "metabolomics",
        "epigenomics",
        "single-cell",
        "structural",
        "systems",
        "ml-ai",
        "tools-infra",
        "industry",
    ]


def test_scoring_defaults():
    expected = {
        "weights": {"rise": 0.45, "diversity": 0.25, "code_velocity": 0.15, "volume": 0.15},
        "yesterday_penalty": 0.05,
        "rise_k": 3,
        "rise_cap": 10.0,
        "history_days_for_own_baseline": 14,
        "cluster_distance_threshold": 0.10,
        "cluster_linkage": "complete",
        "min_cluster_size": 3,
        "continuity_threshold": 0.95,
        "continuity_min_jaccard": 0.25,
        "continuity_max_gap_days": 10,
        "window_days": 7,
        "top_n": 40,
        "max_per_category": 8,
        "category_floor": 1,
        "featured_n": 5,
        "display_open_n": 20,
        "synthesis_tiers": [
            {"to": 5, "model": "claude-opus-5-5"},
            {"to": 20, "model": "claude-sonnet-5-5"},
            {"to": 40, "model": "claude-haiku-5-5"},
        ],
        "backfill_synthesis_model": "claude-haiku-5-5",
        "synthesis_max_items": 40,
        "synthesis_workers": 12,
        "monthly_ceiling_usd": 50.0,
        "degraded_fallback_min": 3,
        "degraded_fallback_rate": 0.2,
        "star_gain_threshold": 100,
    }
    assert load_scoring().model_dump() == expected
    assert Scoring(weights=expected["weights"]).model_dump() == expected


def test_scoring_rejects_invalid_tiers_and_display():
    import pytest
    from pydantic import ValidationError

    for values in ({'synthesis_tiers': []}, {'synthesis_tiers': [{'to': 20, 'model': 'x'}]},
                   {'synthesis_tiers': [{'to': 40, 'model': 'x'}, {'to': 5, 'model': 'x'}]},
                   {'display_open_n': 4}, {'synthesis_workers': 0}, {'synthesis_workers': -1},
                   {'continuity_threshold': 1.1}, {'continuity_min_jaccard': -.1},
                   {'continuity_max_gap_days': -1}):
        with pytest.raises(ValidationError):
            Scoring(weights={}, **values)
