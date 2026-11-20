"""Check a recorded sample with the production classifier and a fresh decision store."""

import json
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from hashlib import sha256
from pathlib import Path

from pipeline.__main__ import build_deps
from pipeline.enrich import screen_window
from pipeline.llm import ENRICHMENT_MODEL
from pipeline.sources.arxiv import ArxivAdapter, NS
from pipeline.sources.base import load_config, request
from pipeline.store import Store


def main(protocol_path: Path, output: Path) -> None:
    protocol = json.loads(protocol_path.read_text())
    domain = protocol['domain']
    day = date.fromisoformat(protocol['date'])
    cases = [(group, case) for group in ('cases', 'holdouts', 'cross_field', 'final_holdouts')
             for case in protocol.get(group, [])]
    ids = [case['id'] for _, case in cases]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('The review requires a nonempty sample of distinct papers')
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp), domain)
        deps = build_deps(domain, store.root, synthesis_only=True)
        with deps.client:
            adapter = ArxivAdapter(load_config(domain))
            response = request(deps.client, adapter.config['arxiv']['endpoint'], params={
                'id_list': ','.join(case['source_version'] for _, case in cases), 'max_results': len(ids),
            })
            entries = ET.fromstring(response.content).findall('atom:entry', NS)
            papers = [adapter._item(entry, day) for entry in entries]
            by_id = {paper.id: paper for paper in papers if paper is not None}
            if set(by_id) != set(ids) or any(set(case['expected']) - set(deps.taxonomy.slugs()) for _, case in cases):
                raise ValueError('Missing source paper or unrecognized expected category')
            items = [by_id[key] for key in ids]
            inputs = sorted([item.id, item.url.split('/abs/')[-1], item.title, item.abstract,
                             item.metadata['arxiv_primary_category'], item.metadata['categories']] for item in items)
            digest = sha256(json.dumps(inputs, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            if digest != protocol['source_sha256']:
                raise ValueError('Benchmark source versions, texts or archive labels have changed')
            screen_window(items, store, deps.llm, deps.taxonomy, deps.hints_cfg, day)
        audit = json.loads((store.root / domain / 'audits' / f'screening-{day}.json').read_text())
        assert audit['requested'] == len(cases) and audit['reused'] == 0
        results = []
        for (group, case), item in zip(cases, items, strict=True):
            unavailable = audit['unavailable'].get(item.id)
            assigned = item.primary_category if item.relevant and not unavailable else None
            matches = not unavailable and item.relevant == bool(case['expected']) and (not item.relevant or assigned in case['expected'])
            results.append(dict(group=group, id=item.id, relevant=item.relevant if not unavailable else None,
                                assigned=assigned, unavailable=unavailable, matches=bool(matches)))
        report = dict(date=str(day), domain=domain, model=ENRICHMENT_MODEL, source_run=protocol['source_run'],
                      model_cost_usd=deps.budget.total_spend_usd(), cases=results)
    output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main(*(Path(arg) for arg in sys.argv[1:]))
