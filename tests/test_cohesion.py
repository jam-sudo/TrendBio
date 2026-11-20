from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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
    deps = SimpleNamespace(cfg=load_scoring(), llm=llm, taxonomy=load_taxonomy('math').model_copy(
        update={'comparison_guidance': ''}))
    store = Store(tmp_path, 'math')
    day = date(2026, 11, 1)
    expected = ([[ids[0], ids[2], ids[4]], [ids[1], ids[3], ids[5]]], [], {})
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
        groups, notes, _ = review_clusters([ids], changed, store, deps, day)
        assert not groups and notes[0].startswith('cohesion-review-failed:')
    assert llm._parse.call_count == 5
    llm._parse.side_effect = [response, CohesionReview(groups=[group([n]) for n in range(1, 8)])]
    assert llm.review_cohesion('Original request', changed, 'retry')['groups']
    assert 'retry' not in llm.fallback_reasons
    llm._parse.side_effect = None
    llm._parse.return_value = CohesionReview(groups=[group([1, 2, 3]), group([1, 4, 5, 6])])
    assert review_clusters([ids], changed, store, deps, day)[1]
    llm._parse.side_effect = [CohesionReview(groups=[group([1, 2, 3])]),
                              CohesionReview(groups=[group([n]) for n in range(1, 8)])]
    assert llm.review_cohesion('Check the comparison', changed, 'missing', model='claude-sonnet-5-5', effort='medium')
    assert 'Use each of these numbers exactly once: 1, 2, 3, 4, 5, 6, 7' in llm._parse.call_args.args[1][0]['content']
    assert llm._parse.call_args.args[2:5] == ('claude-sonnet-5-5', 4096, 'medium')
    llm._parse.side_effect = None
    llm._parse.return_value = CohesionReview(groups=[group([n]) for n in range(1, 8)])
    assert review_clusters([ids], changed, store, deps, day) == ([], [], {})


def test_field_review_instructions_change_the_cached_partition(tmp_path, fixtures_root):
    papers = Store(fixtures_root / 'data', 'physics').items_between(date.min, date.max)
    ids = sorted(p.id for p in papers)
    taxonomy = load_taxonomy('physics-expanded').model_copy(update={'comparison_guidance': ''})
    guidance = taxonomy.cohesion_guidance
    assert guidance
    llm = Mock()
    llm.review_cohesion.return_value = {'groups': [{'topic': 'Cavity readout', 'evidence': [{'id': i} for i in ids]}]}
    deps = SimpleNamespace(cfg=load_scoring(), llm=llm, taxonomy=taxonomy.model_copy(update={'cohesion_guidance': ''}))
    store = Store(tmp_path, taxonomy.domain)
    day = date(2026, 11, 1)
    assert review_clusters([ids], papers, store, deps, day) == ([ids], [], {})
    original = llm.review_cohesion.call_args.args[0]
    deps.taxonomy = taxonomy
    llm.review_cohesion.return_value = {'groups': [{'topic': i, 'evidence': [{'id': i}]} for i in ids]}
    assert review_clusters([ids], papers, store, deps, day) == ([], [], {})
    assert llm.review_cohesion.call_args.args[0] == guidance + '\n\n' + original
    assert review_clusters([ids[::-1]], papers, store, deps, day) == ([], [], {})
    assert llm.review_cohesion.call_count == 2


@pytest.mark.parametrize('domain', ['physics-expanded', 'math'])
def test_comparison_retries_only_unverified_groups_and_passes_on_the_confirmed_question(tmp_path, fixtures_root, domain):
    papers = Store(fixtures_root / 'data', 'physics').items_between(date.min, date.max)
    papers = papers + [papers[-1].model_copy(update={'id': 'extra', 'title': 'An unrelated detector target'})]
    ids = sorted(p.id for p in papers)
    good = ids[:3]
    question = 'Which physical quantity can the three sensors recover?'
    def group(members, label):
        return {'topic': label, 'evidence': [{'id': i} for i in members]}
    llm, budget = Mock(), Mock()
    budget.over_ceiling.return_value = False
    llm.review_cohesion.side_effect = [
        {'groups': [group(ids, 'Original grouping hypothesis')]}, None,
        {'groups': [group(good, question), group([ids[-1]], 'Other target')]},
    ]
    taxonomy = load_taxonomy(domain)
    deps = SimpleNamespace(cfg=load_scoring(), llm=llm, taxonomy=taxonomy, budget=budget)
    store, day = Store(tmp_path, taxonomy.domain), date(2026, 11, 1)
    groups, notes, questions = review_clusters([ids], papers, store, deps, day)
    audit_path = tmp_path / taxonomy.domain / 'audits' / f'cohesion-{day}.json'
    failed = json.loads(audit_path.read_text())['candidates'][0]['comparisons'][0]
    assert failed['failed'] and not groups and not questions and notes == ['cohesion-review-failed:' + failed['review']]
    expected = ([good], [], {tuple(good): question})
    assert review_clusters([ids], papers, store, deps, day) == expected
    check = llm.review_cohesion.call_args
    assert check.kwargs == {'model': 'claude-sonnet-5-5', 'effort': 'medium'}
    assert 'Original grouping hypothesis' in check.args[0]
    assert all(p.title in check.args[0] for p in papers)
    recovered = json.loads(audit_path.read_text())['candidates'][0]
    assert not recovered['failed'] and recovered['qualified'] == [good] and recovered['comparisons'][0]['items'] == ids
    assert review_clusters([ids[::-1]], papers, store, deps, day) == expected
    assert llm.review_cohesion.call_count == 3
    budget.over_ceiling.return_value = True
    llm.review_cohesion.side_effect = [{'groups': [group([member], 'Only one paper') for member in ids]}]
    assert review_clusters([ids], papers, store, deps, day) == ([], [], {})
    assert llm.review_cohesion.call_args.kwargs['model'] == 'claude-haiku-5-5'
