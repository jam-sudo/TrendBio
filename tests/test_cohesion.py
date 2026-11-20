from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pipeline.cohesion import review_clusters
from pipeline.config import load_scoring, load_taxonomy
from pipeline.llm import CohesionEvidence, CohesionGroup, CohesionReview, LLM, ResultComparison
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
    retry = llm._parse.call_args.args[1][0]['content']
    choices = json.loads(retry.splitlines()[-1])
    assert list(choices) == ['2'] and choices['2']['P2.0'] == changed[1].title
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


def test_quote_retry_resolves_only_a_passage_offered_for_that_paper(fixtures_root):
    items = Store(fixtures_root / 'data', 'physics').items_between(date.min, date.max)[:2]
    items[1].abstract = 'We measured the sensor response. The observed response was stable.'
    def answer(second):
        return CohesionReview(groups=[CohesionGroup(topic='Sensor response', evidence=[
            CohesionEvidence(paper=1, quote=items[0].title), CohesionEvidence(paper=2, quote=second)])])
    llm = LLM(Mock(), Mock())
    for invalid in ('P1.0', 'P2.9'):
        llm._parse = Mock(side_effect=[answer('Unmatched wording.'), answer(invalid)])
        assert llm.review_cohesion('Compare results.', items, 'retry') is None
    llm._parse = Mock(side_effect=[answer('Unmatched wording.'), answer('P2.2')])
    result = llm.review_cohesion('Compare results.', items, 'retry')
    anchor = result['groups'][0]['evidence'][1]
    assert anchor == {'id': items[1].id, 'field': 'abstract', 'start': 33, 'length': 33}
    assert items[1].abstract[anchor['start']:] == 'The observed response was stable.'


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


@pytest.mark.parametrize(('domain', 'compare_results'), [('physics-expanded', True), ('engineering', True), ('math', False)])
def test_comparison_retries_only_unverified_groups_and_passes_on_the_confirmed_question(tmp_path, fixtures_root, domain, compare_results):
    papers = Store(fixtures_root / 'data', 'physics').items_between(date.min, date.max)
    papers = papers + [papers[-1].model_copy(update={'id': 'extra', 'title': 'An unrelated detector target'})]
    papers[0].authors = ['Alex Example']
    papers[-1].authors = ['Alex Example']
    papers[0].url = 'https://arxiv.org/abs/2610.12345v1'
    xml = ('<entry xmlns="http://www.w3.org/2005/Atom" xmlns:a="http://arxiv.org/schemas/atom">'
           '<id>http://arxiv.org/abs/2610.12345v1</id><a:comment>Conference   contribution</a:comment></entry>')
    papers[0].metadata = {'xml': xml}
    papers[1].url = 'https://arxiv.org/abs/2610.12345v2'
    papers[1].metadata = {'xml': xml}
    papers[2].metadata = {'xml': '<incomplete'}
    ids = sorted(p.id for p in papers)
    good = ids[:3]
    question = 'Which physical quantity can the three sensors recover?'
    titles = {p.id: p.title for p in papers}
    def group(members, label):
        return {'topic': label, 'evidence': [{'id': i, 'field': 'title', 'start': 0, 'length': len(titles[i])}
                                            for i in members]}
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
    topic = group(good, question)
    if compare_results:
        topic['result_review'] = failed['review']
    expected = ([good], [], {tuple(good): topic})
    assert review_clusters([ids], papers, store, deps, day) == expected
    check = llm.review_cohesion.call_args
    options = {'model': 'claude-sonnet-5-5', 'effort': 'medium'}
    if compare_results:
        options['compare_results'] = True
    assert check.kwargs == options
    assert ('share a credited author name' in check.args[0]) == compare_results
    assert 'Original grouping hypothesis' in check.args[0]
    records = json.loads(check.args[0].split('\n\n')[-1])
    assert 'arxiv_submission_comment' not in llm.review_cohesion.call_args_list[0].args[0]
    assert [(r['title'], r['arxiv_submission_comment']) for r in records if 'arxiv_submission_comment' in r] == (
        [(papers[0].title, 'Conference contribution')] if domain == 'physics-expanded' else [])
    if compare_results:
        assert all(r['first_review_passage'] == r['title'] for r in records)
    else:
        assert all('first_review_passage' not in r for r in records)
    assert all(p.title in check.args[0] for p in papers)
    recovered = json.loads(audit_path.read_text())['candidates'][0]
    assert not recovered['failed'] and recovered['qualified'] == [good] and recovered['comparisons'][0]['items'] == ids
    assert review_clusters([ids[::-1]], papers, store, deps, day) == expected
    assert llm.review_cohesion.call_count == 3
    budget.over_ceiling.return_value = True
    llm.review_cohesion.side_effect = [{'groups': [group([member], 'Only one paper') for member in ids]}]
    assert review_clusters([ids], papers, store, deps, day) == ([], [], {})
    assert llm.review_cohesion.call_args.kwargs['model'] == 'claude-haiku-5-5'


def test_result_comparison_joins_every_paper_to_its_own_reported_passage(fixtures_root):
    papers = Store(fixtures_root / 'data', 'physics').items_between(date.min, date.max)
    entries = [{'paper': n, 'quote': p.title, 'result': 'Measured cavity readout'} for n, p in enumerate(papers, 1)]
    groups = [{'topic': 'How is cavity readout measured?', 'papers': [3, 1, 2]}]
    review = ResultComparison.model_validate({'observable': 'cavity readout', 'results': entries[::-1], 'groups': groups})
    llm = LLM(Mock(), Mock())
    llm._parse = Mock(return_value=review)
    def evaluate():
        return llm.review_cohesion('Compare reported outputs', papers, 'test', compare_results=True)

    stored, = evaluate()['groups']
    assert evaluate()['observable'] == 'cavity readout'
    assert llm._parse.call_args.args[0] is ResultComparison
    assert [e['id'] for e in stored['evidence']] == [papers[n - 1].id for n in groups[0]['papers']]
    assert all(e['field'] == 'title' and e['start'] == 0 and e['reported_output'] == 'Measured cavity readout'
               for e in stored['evidence'])
    for outputs, members in [(entries[:-1], [1, 2, 3]), (entries, [1, 1, 3]), (entries, [1, 2, 4])]:
        llm._parse.return_value = ResultComparison.model_validate({
            'observable': 'cavity readout', 'results': outputs, 'groups': [{'topic': 'Question', 'papers': members}]})
        assert evaluate() is None and llm.fallback_reasons['test'] == 'validation:cohesion-membership'
    llm._parse.return_value = review.model_copy(update={'observable': ' '})
    assert evaluate() is None and llm.fallback_reasons['test'] == 'validation:cohesion-group'
    review.results[0].quote = 'A passage belonging to no paper'
    llm._parse.return_value = review
    assert evaluate() is None and llm.fallback_reasons['test'] == 'validation:cohesion-evidence'
