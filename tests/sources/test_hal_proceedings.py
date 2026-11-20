from datetime import date

import httpx
import pytest

from pipeline.collect import intake_status
from pipeline.sources.crossref import CrossrefAdapter, vor_license
from pipeline.store import Store


DAY = date(2026, 11, 6)
STAMP = {'date-parts': [[2026, 11, 6]]}
VOLUME = {'conference': 'IHM', 'collection': 'IHM-2026', 'volume_doi': '10.1145/1234', 'title': 'IHM proceedings'}
CONFIG = {'crossref': {'journals': [], 'hal_proceedings': [VOLUME]}}
DOI = '10.1145/1234.5678'
LICENCE = 'https://creativecommons.org/licenses/by/4.0/'
WORK = {'type': 'proceedings-article', 'member': '320', 'DOI': DOI, 'container-title': ['IHM proceedings'],
        'published': {'date-parts': [[2026, 10, 19]]}, 'published-online': STAMP, 'created': STAMP,
        'title': ['Touch (and)Sound'], 'author': [{'given': 'Zoé', 'family': 'Franck'}],
        'license': [{'content-version': 'vor', 'URL': LICENCE + 'legalcode', 'start': STAMP}]}
DOC = {'docType_s': 'COMM', 'halId_s': 'hal-12345678', 'version_i': 1, 'openAccess_bool': True,
       'licence_s': LICENCE, 'authFullName_s': ['Zoé Franck'], 'language_s': ['fr'], 'releasedDate_s': '2026-09-28 12:00:00',
       'en_title_s': ['Touch (and) Sound'], 'en_abstract_s': ['We compared two accessible interfaces.'],
       'fr_title_s': ['Le toucher et le son'], 'fr_abstract_s': ['Nous avons comparé deux interfaces accessibles.']}


def client_for(works, docs, total=None):
    def reply(req):
        if req.url.host == 'api.crossref.org':
            assert req.url.path == '/members/320/works'
            assert 'container-title:IHM proceedings,from-online-pub-date:2026-11-06' in req.url.params['filter']
            return httpx.Response(200, json={'message': {'items': works, 'total-results': len(works)}})
        assert req.url.host == 'api.archives-ouvertes.fr' and req.url.path == '/search/IHM-2026/'
        start = int(req.url.params['start'])
        return httpx.Response(200, json={'response': {'start': start, 'numFound': len(docs) if total is None else total,
                                                      'docs': docs if not start else []}})
    return httpx.Client(transport=httpx.MockTransport(reply))


def test_published_date_author_provenance_original_title_and_reconciliation(tmp_path):
    adapter = CrossrefAdapter(CONFIG)
    with client_for([WORK], [DOC]) as client:
        paper, = adapter.fetch(DAY, DAY, client)
    assert (paper.id, paper.published_at, paper.title, paper.abstract) == ('doi:' + DOI, DAY, DOC['en_title_s'][0], DOC['en_abstract_s'][0])
    assert paper.authors == ['Zoé Franck'] and paper.metadata['original_languages'] == ['fr']
    assert paper.metadata['original_title'] == DOC['fr_title_s'][0] and paper.metadata['license'] == LICENCE
    assert paper.metadata['abstract_url'] == 'https://hal.science/hal-12345678v1'
    assert paper.metadata['abstract_language'] == 'en' and paper.metadata['volume_doi'] == VOLUME['volume_doi']
    store = Store(tmp_path, 'computer-information')
    store.put_item(paper.model_copy(update={'summary': 'A previous summary.'}))
    with client_for([WORK], [{**DOC, 'openAccess_bool': False}]) as client:
        assert adapter.fetch(DAY, DAY, client) == []
    stale, = adapter.reconcile(store, DAY, DAY, [])
    assert not stale.relevant and stale.metadata['screening_status'] == 'absent-from-eligible-proceedings'
    store.put_item(stale)
    with client_for([WORK], [dict(DOC, doiId_s=DOI)]) as client:
        fresh = adapter.fetch(DAY, DAY, client)
    restored, = adapter.reconcile(store, DAY, DAY, fresh)
    assert restored.relevant and restored.summary is None and 'screening_status' not in restored.metadata


@pytest.mark.parametrize('work_change,doc_change', [
    ({'container-title': ['IHM adjunct proceedings']}, {}), ({'DOI': '10.1145/9999.1'}, {}),
    ({'published-online': {'date-parts': [[2026, 11]]}}, {}), ({'created': {'date-parts': [[2026, 11, 7]]}}, {}),
    ({'update-to': [{'type': 'retraction'}]}, {}), ({}, {'doiId_s': '10.1145/other'}),
    ({}, {'authFullName_s': ['Other Author']}), ({}, {'en_title_s': ['Different work']}),
    ({}, {'releasedDate_s': '2026-11-07 01:00:00'}), ({}, {'licence_s': 'https://creativecommons.org/licenses/by-nc-nd/4.0/'}),
    ({}, {'en_abstract_s': [], 'fr_abstract_s': []}),
])
def test_ineligible_proceedings_work_yields_no_paper(work_change, doc_change):
    with client_for([{**WORK, **work_change}], [{**DOC, **doc_change}]) as client:
        assert CrossrefAdapter(CONFIG).fetch(DAY, DAY, client) == []


def test_ambiguous_title_match_and_incomplete_collection_are_distinct():
    adapter = CrossrefAdapter(CONFIG)
    other = dict(DOC, halId_s='hal-22222222')
    with client_for([WORK], [DOC, other]) as client:
        assert adapter.fetch(DAY, DAY, client) == [] and intake_status(adapter) == 'ok'
    with client_for([WORK], [DOC, dict(other, doiId_s=DOI)]) as client:
        paper, = adapter.fetch(DAY, DAY, client)
        assert 'hal-22222222v1' in paper.metadata['abstract_url']
    with client_for([WORK], [DOC], total=2) as client:
        assert adapter.fetch(DAY, DAY, client) == []
        assert adapter.decisions == {DOI: 'abstract-source-unavailable'} and intake_status(adapter) == 'partial'


def test_legal_code_url_keeps_the_version_and_rights_restrictions():
    for change in [{'content-version': 'unspecified'}, {'URL': 'https://creativecommons.org/licenses/by-nd/4.0/legalcode'},
                   {'URL': 'https://example.org/licenses/by/4.0/legalcode'}, {'start': {'date-parts': [[2027, 1, 1]]}}]:
        assert vor_license({'license': [{**WORK['license'][0], **change}]}, DAY) is None
