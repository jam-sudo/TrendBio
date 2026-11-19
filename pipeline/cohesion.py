"""Review the evidence of each candidate before it can contribute to a pilot ranking."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path


def review_clusters(clusters, papers, store, deps):
    template = Path(__file__).with_name('prompts').joinpath('cohesion.md').read_text()
    minimum = deps.cfg.min_cluster_size
    by_id = {p.id: p for p in papers}

    def review(ids):
        items = [by_id[i] for i in sorted(ids)]
        records = [{'id': i.id, 'title': i.title, 'abstract': i.abstract} for i in items]
        prompt = template.format(field=deps.taxonomy.label, minimum=minimum, records=json.dumps(records, ensure_ascii=False))
        key = sha256(('claude-haiku-5-5\n' + prompt).encode()).hexdigest()
        path = store.root / store.domain / 'cohesion' / (key + '.json')
        if path.exists():
            result = json.loads(path.read_text())
        else:
            result = deps.llm.review_cohesion(prompt, items, minimum, key)
            if result is None:
                return [], 'cohesion-review-failed:' + key
            store._write(path, {**result, 'candidates': sorted(ids)})
        return result['retained'], None

    with ThreadPoolExecutor(max_workers=deps.cfg.synthesis_workers) as pool:
        reviewed = list(pool.map(review, clusters))
    return [ids for ids, _ in reviewed if ids], [error for _, error in reviewed if error]
