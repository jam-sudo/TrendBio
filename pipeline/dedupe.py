from collections import defaultdict
from datetime import date
from itertools import chain
import unicodedata

from pipeline.models import Item
from pipeline.store import Store


def normalize_title(s: str) -> str:
    text = unicodedata.normalize("NFKD", s).casefold()
    return " ".join("".join(
        char for char in text if not unicodedata.category(char).startswith("P")
    ).split())


def parallel_openedition_ids(items: list[Item]) -> set[str]:
    groups = defaultdict(list)
    for item in items:
        meta = item.metadata
        if (item.source == 'openedition' and meta.get('issue_url') and item.authors and item.title and item.abstract
                and meta.get('abstract_language') and len(meta.get('original_languages', [])) == 1):
            key = (meta['issue_url'], item.published_at, tuple(item.authors), normalize_title(item.title),
                   meta['abstract_language'], item.abstract)
            groups[key].append(item)

    duplicates = set()
    for versions in groups.values():
        languages = {v.metadata['original_languages'][0] for v in versions}
        if len(languages) < 2 or len(languages) != len(versions):
            continue
        # Older stored records predate translator credits. Prefer the version in the abstract's language on ties.
        keep = min(versions, key=lambda v: (bool(v.metadata.get('has_translator')),
                   v.metadata['original_languages'][0] != v.metadata['abstract_language'], v.id))
        duplicates.update(v.id for v in versions if v.id != keep.id)
    return duplicates


def dedupe(new: list[Item], store: Store | None = None) -> list[Item]:
    def doi(value: str | None) -> str:
        return value.strip().casefold().removeprefix("https://doi.org/") if isinstance(value, str) else ""

    known = store.items_between(date.min, date.max) if store is not None else []
    claims: dict[str, dict[str, str]] = {}
    for item in chain(known, new):
        if item.source == 'arxiv' and item.type == 'preprint':
            reported = doi(item.doi or item.metadata.get('arxiv_reported_doi'))
            if reported and item.title:
                claims.setdefault(reported, {})[item.id] = normalize_title(item.title)
    shared = {identifier for identifier, titles in claims.items() if len(set(titles.values())) > 1}

    def disambiguate(item: Item) -> Item:
        if item.source == 'arxiv' and item.type == 'preprint' and doi(item.doi) in shared:
            # Distinct arXiv reports can cite one repository deposit for the entire project.
            return item.model_copy(update={'doi': None, 'metadata': {**item.metadata, 'arxiv_reported_doi': item.doi}})
        return item

    by_id: dict[str, Item] = {}
    by_doi: dict[str, list[Item]] = {}
    by_title: dict[str, list[Item]] = {}
    book_isbns: set[str] = set()

    def index(item: Item, title: str, identifier: str) -> None:
        by_id[item.id] = item
        book_isbns.update(item.metadata.get('isbns', []))
        if identifier:
            by_doi.setdefault(identifier, []).append(item)
        if title:
            by_title.setdefault(title, []).append(item)

    result = {}
    for position, original in enumerate(known):
        item = disambiguate(original)
        if item is not original:
            known[position] = item
            result[item.id] = item
        index(item, normalize_title(item.title), doi(item.doi))

    for original in new:
        item = disambiguate(original)
        title = normalize_title(item.title)
        identifier = doi(item.doi)
        duplicate = item.id in by_id or bool(book_isbns.intersection(item.metadata.get('isbns', []))) or any(
            {item.type, other.type} != {"preprint", "published"}
            for other in by_doi.get(identifier, ())
        ) or any(
            {item.type, other.type} != {"preprint", "published"}
            and (
                (item.source != other.source
                 and abs((item.published_at - other.published_at).days) <= 30)
                or (item.type == other.type == "industry"
                    and item.published_at == other.published_at)
            )
            for other in by_title.get(title, ())
        )
        if not duplicate:
            item = item.model_copy()
            known.append(item)
            index(item, title, identifier)
            result[item.id] = item

    # Link only canonical records, so a duplicate paper cannot replace a valid link.
    added = set(result)
    preprint_order = {}
    by_identifier: dict[str, dict[int, Item]] = {}

    def preprint_identifiers(item: Item) -> set[str]:
        return {doi(value) for value in (item.id, item.doi, item.published_doi)} - {""}

    for position, item in enumerate(known):
        if item.type == "preprint":
            preprint_order[id(item)] = position
            for identifier in preprint_identifiers(item):
                by_identifier.setdefault(identifier, {})[position] = item

    for paper in known:
        if paper.type != "published":
            continue
        identifiers = {doi(value) for value in (
            paper.preprint_id, paper.doi, paper.published_doi,
            *(paper.metadata.get(key) for key in ("preprint_id", "preprint_doi", "published_doi", "doi")),
        )} - {""}
        # Identifier matches outrank titles; ties retain the original known order.
        _, preprint = min(
            ((position, candidate)
             for identifier in identifiers
             for position, candidate in by_identifier.get(identifier, {}).items()
             if paper.id in added or candidate.id in added),
            key=lambda match: match[0], default=(0, None),
        )
        if preprint is None:
            relation = doi(paper.metadata.get('preprint_doi'))
            if relation.startswith('10.48550/arxiv.'):
                native = by_id.get('arxiv:' + relation.removeprefix('10.48550/arxiv.'))
                if (native is not None and native.source == 'arxiv' and native.type == 'preprint'
                        and paper.preprint_id in (None, native.id) and native.published_doi in (None, paper.doi)):
                    preprint = native
        if preprint is None:
            preprint = next((
                candidate for candidate in by_title.get(normalize_title(paper.title), ())
                if candidate.type == "preprint" and (paper.id in added or candidate.id in added)
            ), None)
        if preprint is not None:
            if paper.doi is not None and preprint.published_doi != paper.doi:
                previous = preprint_identifiers(preprint)
                preprint.published_doi = paper.doi
                current = preprint_identifiers(preprint)
                position = preprint_order[id(preprint)]
                # Later papers must see link changes made by earlier papers in this pass.
                for identifier in previous - current:
                    del by_identifier[identifier][position]
                for identifier in current - previous:
                    by_identifier.setdefault(identifier, {})[position] = preprint
                result[preprint.id] = preprint
            if paper.preprint_id != preprint.id:
                paper.preprint_id = preprint.id
                result[paper.id] = paper
    return list(result.values())
