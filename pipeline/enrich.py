import re

from pipeline.config import Taxonomy
from pipeline.embed import l2_normalize
from pipeline.llm import Enrichment, LLM
from pipeline.models import Item
from pipeline.store import Store


def hints_for(item: Item, hints_cfg: dict) -> list[str]:
    metadata = item.metadata
    sources = [
        ('biorxiv_category', metadata.get('biorxiv_category')),
        ('arxiv_category', metadata.get('arxiv_primary_category')),
        ('journal', metadata.get('journal')),
        *(('github_topic', topic) for topic in metadata.get('github_topics', [])),
    ]
    hints = []
    for source, value in sources:
        for slug in hints_cfg.get(source, {}).get(value, []):
            if slug not in hints:
                hints.append(slug)
    return hints


def first_sentence(text: str) -> str:
    return re.split(r'(?<=[.!?])\s+', text.strip(), maxsplit=1)[0]


def enrich_items(
    items: list[Item], store: Store, llm: LLM, embedder, taxonomy: Taxonomy, hints_cfg: dict,
) -> tuple[list[Item], list[str]]:
    pending = []
    notes = []
    for item in items:
        if item.summary is not None:
            continue
        hints = hints_for(item, hints_cfg)
        result = llm.enrich(item, taxonomy, hints)
        if result is None:
            result = Enrichment(
                summary=first_sentence(item.abstract or item.title)[:160],
                primary=hints[0] if hints else 'ml-ai', secondary=[],
            )
            notes.append(f'enrichment-fallback:{item.id}')
        pending.append((item, result))
    if pending:
        vectors = l2_normalize(embedder.embed([item.title + '\n' + item.abstract for item, _ in pending]))
        if len(vectors) != len(pending):
            raise ValueError('embedder returned the wrong number of rows')
        for (item, result), vector in zip(pending, vectors, strict=True):
            # Persist the summary only after its embedding exists, allowing interrupted runs to retry.
            store.put_item(item)
            store.put_embedding(item.id, vector)
            item.summary = result.summary
            item.primary_category = result.primary
            item.secondary_categories = result.secondary
            store.put_item(item)
    return items, notes
