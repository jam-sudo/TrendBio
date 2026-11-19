from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import Mock

from pipeline.cohesion import review_clusters
from pipeline.config import load_scoring, load_taxonomy
from pipeline.llm import CohesionEvidence, CohesionGroup, CohesionReview, LLM
from pipeline.store import Store


def test_partition_checks_all_evidence_and_only_ranks_groups_with_three_sources(tmp_path, fixtures_root):
    originals = Store(fixtures_root / 'data', 'math').items_between(date.min, date.max)
    papers = [originals[i % 3].model_copy(update={'id': f'paper-{i+1}', 'title': f'An original result number {i+1}'})
              for i in range(7)]
    ids = [p.id for p in papers]
    def group(numbers):
        return CohesionGroup(topic='A specific comparison', evidence=[
            CohesionEvidence(paper=n, quote=papers[n-1].title) for n in numbers])
    response = CohesionReview(groups=[group([2, 4, 6]), group([1, 3, 5]), group([7])])
    llm = LLM(Mock(), Mock())
    llm._parse = Mock(return_value=response)
    deps = SimpleNamespace(cfg=load_scoring(), llm=llm, taxonomy=load_taxonomy('math'))
    store = Store(tmp_path, 'math')
    day = date(2026, 11, 1)
    expected = ([[ids[0], ids[2], ids[4]], [ids[1], ids[3], ids[5]]], [])
    assert review_clusters([ids], papers, store, deps, day) == expected
    assert review_clusters([ids[::-1]], papers, store, deps, day) == expected
    receipt = json.loads(next((tmp_path / 'math/cohesion').glob('*.json')).read_text())
    assert receipt['groups'][0]['evidence'][0] == {'id': ids[1], 'field': 'title', 'start': 0, 'length': len(papers[1].title)}
    audit = json.loads((tmp_path / f"math/audits/cohesion-{day}.json").read_text())
    assert audit["candidates"][0]["qualified"] == expected[0]
    assert audit["candidates"][0]["items"] == ids
    assert llm._parse.call_count == 1
    changed = papers[:-1] + [papers[-1].model_copy(update={'abstract': 'New source text'})]
    response.groups[0].evidence[0].quote = 'Invented supporting passage'
    for _ in range(2):
        groups, notes = review_clusters([ids], changed, store, deps, day)
        assert not groups and notes[0].startswith('cohesion-review-failed:')
    assert llm._parse.call_count == 5
    llm._parse.side_effect = [response, CohesionReview(groups=[group([n]) for n in range(1, 8)])]
    assert llm.review_cohesion('Original request', changed, 'retry')['groups']
    assert 'retry' not in llm.fallback_reasons
    llm._parse.side_effect = None
    llm._parse.return_value = CohesionReview(groups=[group([1, 2, 3]), group([1, 4, 5, 6])])
    assert review_clusters([ids], changed, store, deps, day)[1]
    llm._parse.return_value = CohesionReview(groups=[group([n]) for n in range(1, 8)])
    assert review_clusters([ids], changed, store, deps, day) == ([], [])
