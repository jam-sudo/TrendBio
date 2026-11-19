"""Review the evidence of each candidate before it can contribute to a pilot ranking."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path


def review_clusters(clusters, papers, store, deps, day):
    template = Path(__file__).with_name('prompts').joinpath('cohesion.md').read_text()
    minimum = deps.cfg.min_cluster_size
    by_id = {p.id: p for p in papers}

    def review(ids):
        items = [by_id[i] for i in sorted(ids)]
        records = [{'paper': n, 'title': i.title, 'abstract': i.abstract} for n, i in enumerate(items, 1)]
        prompt = template.format(field=deps.taxonomy.label, records=json.dumps(records, ensure_ascii=False))
        key = sha256(json.dumps(['claude-haiku-5-5', sorted(ids), prompt]).encode()).hexdigest()
        path = store.root / store.domain / 'cohesion' / (key + '.json')
        if path.exists():
            result = json.loads(path.read_text())
        else:
            result = deps.llm.review_cohesion(prompt, items, key)
            if result is None:
                return key, [], 'cohesion-review-failed:' + key
            store._write(path, {**result, 'candidates': sorted(ids)})
        groups = [sorted(e['id'] for e in g['evidence']) for g in result['groups'] if len(g['evidence']) >= minimum]
        return key, sorted(groups), None

    with ThreadPoolExecutor(max_workers=deps.cfg.synthesis_workers) as pool:
        reviewed = list(pool.map(review, clusters))
    candidates = [{'review': key, 'items': sorted(ids), 'qualified': groups, 'failed': bool(error)}
                  for ids, (key, groups, error) in zip(clusters, reviewed, strict=True)]
    store._write(store.root / store.domain / 'audits' / f'cohesion-{day}.json',
                 {'minimum': minimum, 'candidates': candidates})
    return [ids for _, groups, _ in reviewed for ids in groups], [error for _, _, error in reviewed if error]
