import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from pipeline.config import Taxonomy
from pipeline.embed import l2_normalize
from pipeline.llm import Enrichment, LLM, enrichment_key, truncate
from pipeline.models import Item
from pipeline.store import Store


def hints_for(item: Item, hints_cfg: dict) -> list[str]:
    metadata = item.metadata
    sources = [
        ('biorxiv_category', metadata.get('biorxiv_category')),
        ('arxiv_category', metadata.get('arxiv_primary_category')),
        ('journal', metadata.get('journal')),
        ('conference', metadata.get('conference')),
        ('collection', metadata.get('collection')),
        *(('book_subject', code) for code in metadata.get('book_subjects', [])),
        ('issn', metadata.get('issn')),
        *(('github_topic', topic) for topic in metadata.get('github_topics', [])),
    ]
    hints = []
    for source, value in sources:
        for slug in hints_cfg.get(source, {}).get(value, []):
            if slug not in hints:
                hints.append(slug)
    return hints


def fallback_summary(item: Item) -> str:
    text = item.abstract or item.title
    if not item.can_quote_in_english(text):
        return 'An English summary is unavailable.'
    return re.split(r'(?<=[.!?])\s+', text.strip(), maxsplit=1)[0]


def _apply(item: Item, result: Enrichment) -> bool:
    values = (result.summary, result.primary, result.secondary, result.relevant)
    if (item.summary, item.primary_category, item.secondary_categories, item.relevant) == values:
        return False
    item.summary, item.primary_category, item.secondary_categories, item.relevant = values
    return True


def enrich_items(
    items: list[Item], store: Store, llm: LLM, embedder, taxonomy: Taxonomy, hints_cfg: dict,
) -> tuple[list[Item], list[str], int]:
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
                summary=truncate(fallback_summary(item), 160),
                primary=hints[0] if hints else taxonomy.fallback_category, secondary=[],
                relevant=item.type in {'preprint', 'published'},
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
            _apply(item, result)
            store.put_item(item)
    return items, notes, sum(not item.relevant for item in pending)


def screen_window(items: list[Item], store: Store, llm: LLM, taxonomy: Taxonomy,
                  hints_cfg: dict, day: date) -> tuple[list[str], int]:
    root = store.root / store.domain
    directory = root / 'decisions' / 'classifications'
    slugs = set(taxonomy.slugs())
    withheld = Enrichment(summary='Classification unavailable.', primary=taxonomy.fallback_category,
                          secondary=[], relevant=False)

    def classify(item):
        hints = hints_for(item, hints_cfg)
        key = enrichment_key(item, taxonomy, hints)
        path = directory / (key + '.json')
        if path.exists():
            record = json.loads(path.read_text(encoding='utf-8'))
            if record['id'] != item.id:
                raise ValueError('Classification receipt has a different paper ID')
            if 'refusal' in record:
                if not record['refusal'].startswith('refusal:'):
                    raise ValueError('Invalid refusal in classification receipt')
                return key, True, withheld, record['refusal']
            result = Enrichment.model_validate(record['result'])
            if result.primary not in slugs or not set(result.secondary) <= slugs:
                raise ValueError('Classification receipt contains an unknown category')
            return key, True, result, None

        # A summary in an older store does not establish which request produced it.
        result = llm.enrich(item, taxonomy, hints)
        if result is None:
            reason = getattr(llm, 'fallback_reasons', {}).get(item.id, 'unknown')
            if reason.startswith('refusal:'):
                store._write(path, {'id': item.id, 'refusal': reason})
            return key, False, withheld, reason
        store._write(path, {'id': item.id, 'result': result.model_dump()})
        return key, False, result, None

    keys, failures, reused = {}, {}, 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for item, (key, hit, result, reason) in zip(items, pool.map(classify, items), strict=True):
            keys[item.id] = key
            reused += hit
            if reason:
                failures[item.id] = reason
            if _apply(item, result):
                store.put_item(item)
    store._write(root / 'audits' / f'screening-{day}.json', {
        'papers': keys, 'requested': len(items) - reused, 'reused': reused, 'unavailable': failures,
    })
    return [f'enrichment-fallback:{key}' for key in sorted(failures)], sum(not item.relevant for item in items)
