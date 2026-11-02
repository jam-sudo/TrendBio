from datetime import date, timedelta

import pytest

from pipeline.dedupe import dedupe, normalize_title
from pipeline.models import Item
from pipeline.store import Store


@pytest.fixture
def item():
    return Item(
        id="biorxiv:original", source="biorxiv", type="preprint",
        title="Protein design: a study", url="https://example.org/preprint",
        doi="10.1101/Example", published_at=date(2026, 1, 1),
        first_seen=date(2026, 6, 1), authors=[], org=None, abstract="Abstract.",
        summary="Existing summary", primary_category=None,
        published_doi=None, preprint_id=None,
    )


def test_same_doi_is_same_item(tmp_path, item):
    store = Store(tmp_path, "computational")
    duplicate = item.model_copy(update={
        "id": "arxiv:duplicate", "source": "arxiv", "title": "Different title",
        "doi": "HTTPS://DOI.ORG/10.1101/EXAMPLE", "summary": None,
        "published_at": date(2026, 12, 1),
    })
    assert dedupe([item, duplicate, item], store) == [item]
    store.put_item(item)
    assert dedupe([duplicate, item], store) == []
    assert store.get_item(item.id) == item


def test_same_title_within_30_days_merges(tmp_path, item):
    store = Store(tmp_path, "computational")
    assert normalize_title("  Ｐrotein DESIGN：\tA study! ") == "protein design a study"
    assert normalize_title("Straße — Café") == "strasse cafe\u0301"
    store.put_item(item)
    for offset in (-30, 0, 30):
        duplicate = item.model_copy(update={
            "id": "arxiv:duplicate", "source": "arxiv", "doi": None,
            "title": "  PROTEIN design a study! ",
            "published_at": item.published_at + timedelta(days=offset),
        })
        assert dedupe([duplicate], store) == []
        assert dedupe([item, duplicate], Store(tmp_path / "empty", "computational")) == [item]
    same_source = duplicate.model_copy(update={"source": "biorxiv", "id": "biorxiv:other"})
    assert dedupe([same_source], store) == [same_source]


def test_same_title_after_31_days_is_new(tmp_path, item):
    store = Store(tmp_path, "computational")
    store.put_item(item)
    for offset in (-31, 31):
        other = item.model_copy(update={
            "id": "arxiv:other", "source": "arxiv", "doi": None,
            "published_at": item.published_at + timedelta(days=offset),
        })
        assert dedupe([other], store) == [other]


def test_industry_same_title_same_day_merges_across_rss_feeds(tmp_path, item):
    company = item.model_copy(update={
        'id': 'rss:company', 'source': 'rss', 'type': 'industry', 'doi': None,
        'metadata': {'feed_kind': 'company', 'feed_url': 'https://company.example/feed'},
    })
    news = company.model_copy(update={
        'id': 'rss:news', 'title': '  PROTEIN design a study! ',
        'metadata': {'feed_kind': 'news', 'feed_url': 'https://news.example/feed'},
    })
    store = Store(tmp_path, 'computational')
    assert dedupe([company, news], store) == [company]
    assert dedupe([news, company], store) == [news]
    store.put_item(company)
    assert dedupe([news], store) == []
    for offset in (-1, 1):
        next_day = news.model_copy(update={'published_at': news.published_at + timedelta(days=offset)})
        assert dedupe([next_day], store) == [next_day]
    different_title = news.model_copy(update={'title': 'A different announcement'})
    assert dedupe([different_title], store) == [different_title]


def test_preprint_then_published_links_both_ways(tmp_path, item):
    paper = item.model_copy(update={
        "id": "pubmed:paper", "source": "pubmed", "type": "published",
        "doi": "10.1000/paper", "published_at": date(2026, 10, 1),
    })
    variants = [
        (item, paper),  # Title match has no 30-day restriction for publication links.
        (item, paper.model_copy(update={"title": "Renamed", "preprint_id": item.id})),
        (item.model_copy(update={"published_doi": "https://doi.org/10.1000/PAPER"}),
         paper.model_copy(update={"title": "Renamed"})),
        (item, paper.model_copy(update={"title": "Renamed", "doi": "https://doi.org/10.1101/EXAMPLE"})),
        (item, paper.model_copy(update={"title": "Renamed", "metadata": {"preprint_doi": item.doi}})),
        (item, paper.model_copy(update={"title": "Renamed", "metadata": {"doi": item.doi}})),
    ]
    for number, (preprint, published) in enumerate(variants):
        for mode in ("stored", "batch", "reversed", "paper_stored"):
            store = Store(tmp_path / str(number) / mode, "computational")
            if mode == "stored":
                store.put_item(preprint)
                new = [published, published.model_copy(update={"id": "pubmed:duplicate"})]
            elif mode == "paper_stored":
                store.put_item(published)
                new = [preprint]
            else:
                new = [preprint, published] if mode == "batch" else [published, preprint]
            result = {row.id: row for row in dedupe(new, store)}
            if mode != "stored" or preprint.published_doi != published.doi:
                assert preprint.id in result
            if mode != "paper_stored" or published.preprint_id != preprint.id:
                assert published.id in result
            for row in result.values():
                store.put_item(row)
            assert store.get_item(preprint.id).published_doi == published.doi
            assert store.get_item(published.id).preprint_id == preprint.id
            assert store.get_item(preprint.id).summary == preprint.summary
            assert len(store.items_between(date.min, date.max)) == 2
            assert dedupe(new, store) == []
    store = Store(tmp_path / "missing_doi", "computational")
    preprint = item.model_copy(update={"published_doi": "10.1000/known"})
    store.put_item(preprint)
    without_doi = paper.model_copy(update={"doi": None})
    result = dedupe([without_doi], store)
    assert result == [without_doi.model_copy(update={"preprint_id": preprint.id})]
    assert store.get_item(preprint.id).published_doi == "10.1000/known"
