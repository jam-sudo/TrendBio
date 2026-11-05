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


def _dedupe_reference(new: list[Item], store: Store) -> list[Item]:
    def doi(value: str | None) -> str:
        return value.strip().casefold().removeprefix("https://doi.org/") if isinstance(value, str) else ""

    known = store.items_between(date.min, date.max)
    result = {}
    for item in new:
        title = normalize_title(item.title)
        duplicate = any(
            item.id == other.id or (
                {item.type, other.type} != {"preprint", "published"}
                and (
                    (doi(item.doi) and doi(item.doi) == doi(other.doi))
                    or (title and title == normalize_title(other.title)
                        and (
                            (item.source != other.source
                             and abs((item.published_at - other.published_at).days) <= 30)
                            or (item.type == other.type == "industry"
                                and item.published_at == other.published_at)
                        ))
                )
            )
            for other in known
        )
        if not duplicate:
            item = item.model_copy()
            known.append(item)
            result[item.id] = item

    # Link only canonical records, so a duplicate paper cannot replace a valid link.
    added = set(result)
    preprints = [item for item in known if item.type == "preprint"]
    new_preprints = [item for item in preprints if item.id in added]
    for paper in known:
        if paper.type != "published":
            continue
        identifiers = {doi(value) for value in (
            paper.preprint_id, paper.doi, paper.published_doi,
            *(paper.metadata.get(key) for key in ("preprint_id", "preprint_doi", "published_doi", "doi")),
        )} - {""}
        by_identifier = by_title = None
        for preprint in preprints if paper.id in added else new_preprints:
            if identifiers.intersection(map(doi, (preprint.id, preprint.doi, preprint.published_doi))):
                by_identifier = preprint
                break
            title = normalize_title(paper.title)
            if by_title is None and title and title == normalize_title(preprint.title):
                by_title = preprint
        preprint = by_identifier or by_title
        if preprint is not None:
            if paper.doi is not None and preprint.published_doi != paper.doi:
                preprint.published_doi = paper.doi
                result[preprint.id] = preprint
            if paper.preprint_id != preprint.id:
                paper.preprint_id = preprint.id
                result[paper.id] = paper
    return list(result.values())


def test_dedupe_is_linear_in_known(tmp_path, item, monkeypatch):
    from time import perf_counter

    store = Store(tmp_path, "computational")
    types = ("preprint", "published", "industry", "code")
    sources = ("biorxiv", "pubmed", "rss", "github")
    known = [item.model_copy(update={
        "id": f"known:{number}", "title": f"K {number}", "doi": f"10.0/{number}",
        "type": types[number % 4], "source": sources[number % 4],
    }) for number in range(20_000)]
    new = []
    for number in range(200):
        original = known[-200 + number]
        updates = {"id": f"new:{number}", "title": f"N {number}", "doi": None}
        mode = number % 8
        if mode == 0:
            updates["id"] = original.id
        elif mode == 1:
            updates["doi"] = f" HTTPS://DOI.ORG/{original.doi} "
        elif mode in (2, 3, 4):
            updates["title"] = f" {original.title.upper()}! "
            if mode != 3:
                updates["source"] = "arxiv"
            if mode == 4:
                updates["published_at"] = original.published_at + timedelta(days=31)
        elif mode == 5:
            updates.update(type="preprint", title=original.title)
        elif mode == 6:
            updates.update(type="published", metadata={"preprint_doi": known[0].doi})
        new.append(original.model_copy(update=updates))

    loads = []

    def load_known(start, end):
        loads.append((start, end))
        return [row.model_copy(deep=True) for row in known]

    monkeypatch.setattr(store, "items_between", load_known)
    started = perf_counter()
    actual = dedupe(new, store)
    elapsed = perf_counter() - started
    assert elapsed < 5
    assert loads == [(date.min, date.max)]
    assert actual == _dedupe_reference(new, store)


def test_link_indexes_preserve_priority_order_and_mutations(tmp_path, item, monkeypatch):
    store = Store(tmp_path, "computational")
    early = item.model_copy(update={"id": "preprint:early", "doi": "10.0/early"})
    later = item.model_copy(update={"id": "preprint:later", "doi": "10.0/later"})
    known = [early, later]
    paper = item.model_copy(update={"type": "published", "source": "pubmed"})
    new = [
        paper.model_copy(update={
            "id": "paper:identifier", "doi": "10.0/linked", "preprint_id": later.id,
        }),
        paper.model_copy(update={
            "id": "paper:added-alias", "title": "Renamed", "doi": "10.0/next",
            "metadata": {"doi": "10.0/linked"},
        }),
        paper.model_copy(update={
            "id": "paper:removed-alias", "title": "No match", "doi": "10.0/unlinked",
            "metadata": {"doi": "10.0/linked"},
        }),
        paper.model_copy(update={
            "id": "paper:order", "doi": "10.0/order", "title": "Another name",
            "metadata": {"preprint_doi": later.doi, "published_doi": early.doi},
        }),
        paper.model_copy(update={
            "id": "paper:title", "doi": "10.0/title", "published_at": date(2026, 12, 1),
        }),
    ]
    monkeypatch.setattr(store, "items_between", lambda *_: [row.model_copy(deep=True) for row in known])
    actual = dedupe(new, store)
    assert actual == _dedupe_reference(new, store)
    rows = {row.id: row for row in actual}
    assert rows["paper:identifier"].preprint_id == later.id
    assert rows["paper:added-alias"].preprint_id == later.id
    assert rows["paper:removed-alias"].preprint_id is None
    assert rows["paper:order"].preprint_id == early.id
    assert rows["paper:title"].preprint_id == early.id
    assert rows[later.id].published_doi == "10.0/next"
    assert rows[early.id].published_doi == "10.0/title"
