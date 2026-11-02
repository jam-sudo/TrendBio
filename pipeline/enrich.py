import re
from concurrent.futures import ThreadPoolExecutor

from pipeline.config import Taxonomy
from pipeline.embed import l2_normalize
from pipeline.llm import Enrichment, LLM, truncate
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
    pending = sorted((item for item in items if item.summary is None), key=lambda item: item.id)
    notes = []

    def enrich(item):
        hints = hints_for(item, hints_cfg)
        return llm.enrich(item, taxonomy, hints)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(enrich, pending))
    for index, (item, result) in enumerate(zip(pending, results, strict=True)):
        if result is None:
            hints = hints_for(item, hints_cfg)
            results[index] = Enrichment(
                summary=truncate(first_sentence(item.abstract or item.title), 160),
                primary=hints[0] if hints else 'ml-ai', secondary=[],
            )
            notes.append(f'enrichment-fallback:{item.id}')
    if pending:
        # The daily runner embeds the whole window once inside its staging transaction.
        vectors = (l2_normalize(embedder.embed([item.title + '\n' + item.abstract for item in pending]))
                   if embedder is not None else [None] * len(pending))
        if len(vectors) != len(pending):
            raise ValueError('embedder returned the wrong number of rows')
        for item, result, vector in zip(pending, results, vectors, strict=True):
            # Outside a staging transaction, persist the embedding before marking enrichment complete.
            store.put_item(item)
            if vector is not None:
                store.put_embedding(item.id, vector)
            item.summary = result.summary
            item.primary_category = result.primary
            item.secondary_categories = result.secondary
            store.put_item(item)
    return items, notes
