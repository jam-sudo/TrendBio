"""Review the evidence of each candidate before it can contribute to a pilot ranking."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path


def review_clusters(clusters, papers, store, deps, day, *, share_decisions=False):
    template = Path(__file__).with_name('prompts').joinpath('cohesion.md').read_text()
    minimum = deps.cfg.min_cluster_size
    by_id = {p.id: p for p in papers}
    comparison = deps.taxonomy.comparison_guidance
    comparison_model = 'claude-haiku-5-5' if comparison and deps.budget.over_ceiling() else 'claude-sonnet-5-5'

    def partition(ids, *, proposal=None):
        items = [by_id[i] for i in sorted(ids)]
        evidence = [{'paper': n, 'title': item.title, 'abstract': item.abstract}
                    for n, item in enumerate(items, 1)]
        if proposal is not None and deps.taxonomy.compare_reported_results:
            anchors = {entry['id']: entry for entry in proposal['evidence']}
            for item, record in zip(items, evidence, strict=True):
                anchor = anchors[item.id]
                if anchor.get('field') in ('title', 'abstract'):
                    text = ' '.join(getattr(item, anchor['field']).split())
                    start, length = anchor['start'], anchor['length']
                    if 0 <= start and 12 <= length <= len(text) - start:
                        record['first_review_passage'] = text[start:start + length]
        records = json.dumps(evidence, ensure_ascii=False)
        if proposal is not None:
            prompt = comparison + '\n\nProposed topic: ' + json.dumps(proposal['topic'], ensure_ascii=False) + '\n\n' + records
            options = {'model': comparison_model, 'effort': 'medium'}
            cache_inputs = [comparison_model, 'medium', sorted(ids), prompt]
            if deps.taxonomy.compare_reported_results:
                options['compare_results'] = True
                cache_inputs.append('reported-results')
        else:
            prompt = template.format(field=deps.taxonomy.label, records=records)
            if deps.taxonomy.cohesion_guidance:
                prompt = deps.taxonomy.cohesion_guidance + '\n\n' + prompt
            options = {}
            cache_inputs = ['claude-haiku-5-5', sorted(ids), prompt]
        key = sha256(json.dumps(cache_inputs).encode()).hexdigest()
        root = store.root / store.domain
        receipt = root / 'cohesion' / (key + '.json')
        path = root / 'decisions' / 'cohesion' / receipt.name if share_decisions else receipt
        if path.exists():
            result = json.loads(path.read_text())
            if share_decisions:
                members = sorted(e['id'] for group in result['groups'] for e in group['evidence'])
                if result['candidates'] != sorted(ids) or members != sorted(ids):
                    raise ValueError('Cohesion receipt does not account for the requested papers')
        else:
            result = deps.llm.review_cohesion(prompt, items, key, **options)
            if result is None:
                return key, None
            result = {**result, 'candidates': sorted(ids), **options}
            store._write(path, result)
        if share_decisions:
            store._write(receipt, result)
        return key, {tuple(sorted(e['id'] for e in g['evidence'])): g
                     for g in result['groups'] if len(g['evidence']) >= minimum}

    def review(ids):
        key, groups = partition(ids)
        candidate = {'review': key, 'items': sorted(ids)}
        failures = [key] if groups is None else []
        accepted = groups or {}
        if comparison:
            accepted = {}
            candidate['comparisons'] = []
            for members in sorted(groups or {}):
                check, confirmed = partition(members, proposal=groups[members])
                candidate['comparisons'].append({'review': check, 'items': list(members), 'failed': confirmed is None})
                if confirmed is None:
                    failures.append(check)
                else:
                    accepted.update(confirmed)
        candidate.update(qualified=[list(group) for group in sorted(accepted)], failed=bool(failures))
        return candidate, failures, accepted

    with ThreadPoolExecutor(max_workers=deps.cfg.synthesis_workers) as pool:
        reviewed = list(pool.map(review, clusters))
    candidates = [candidate for candidate, _, _ in reviewed]
    store._write(store.root / store.domain / 'audits' / f'cohesion-{day}.json',
                 {'minimum': minimum, 'candidates': candidates})
    clusters = [group for candidate in candidates for group in candidate['qualified']]
    notes = ['cohesion-review-failed:' + key for _, failures, _ in reviewed for key in failures]
    comparisons = {ids: group for _, _, groups in reviewed for ids, group in groups.items()} if comparison else {}
    return clusters, notes, comparisons
