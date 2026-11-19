from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from pipeline.cohesion import review_clusters
from pipeline.config import load_scoring, load_taxonomy
from pipeline.llm import CohesionEvidence, CohesionReview, LLM
from pipeline.store import Store


def test_review_checks_citations_reuses_only_valid_results_and_removes_outliers(tmp_path, fixtures_root):
    papers = Store(fixtures_root / 'data', 'math').items_between(date.min, date.max)
    ids = [p.id for p in papers]
    extra = papers[0].model_copy(update={'id': 'unrelated', 'title': 'An unrelated problem'})
    response = CohesionReview(question='Which quadrature errors are bounded?',
                              evidence=[CohesionEvidence(id=p.id, quote=p.title) for p in papers])
    llm = LLM(Mock(), Mock())
    llm._parse = Mock(return_value=response)
    deps = SimpleNamespace(cfg=load_scoring(), llm=llm, taxonomy=load_taxonomy('math'))
    store = Store(tmp_path, 'math')
    candidates = [ids + [extra.id]]
    assert review_clusters(candidates, papers + [extra], store, deps) == ([sorted(ids)], [])
    assert review_clusters(candidates, papers + [extra], store, deps) == ([sorted(ids)], [])
    assert llm._parse.call_count == 1
    changed = extra.model_copy(update={'abstract': 'New text invalidates the previous review'})
    response.evidence[0].quote = 'Text absent from this paper'
    for _ in range(2):
        groups, notes = review_clusters(candidates, papers + [changed], store, deps)
        assert groups == [] and notes[0].startswith('cohesion-review-failed:')
    assert llm._parse.call_count == 3
    llm._parse.return_value = CohesionReview(question='', evidence=[])
    assert review_clusters(candidates, papers + [changed], store, deps) == ([], [])
