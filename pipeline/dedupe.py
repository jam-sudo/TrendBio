from datetime import date
import unicodedata

from pipeline.models import Item
from pipeline.store import Store


def normalize_title(s: str) -> str:
    text = unicodedata.normalize("NFKD", s).casefold()
    return " ".join("".join(
        char for char in text if not unicodedata.category(char).startswith("P")
    ).split())


def dedupe(new: list[Item], store: Store) -> list[Item]:
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
