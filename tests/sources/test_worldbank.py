from datetime import date

import httpx
import pytest

from pipeline.dedupe import dedupe
from pipeline.sources.worldbank import WorldBankAdapter


DAY = date(2026, 11, 18)


def repository_item(uuid, report='11502', **fields):
    metadata = {'okr.identifier.report': ['WPS'+report], 'okr.identifier.doi': ['10.1596/1813-9450-'+report],
                'dc.date.issued': [str(DAY)], 'dc.rights.uri': ['https://creativecommons.org/licenses/by/3.0/igo/'],
                'dc.type': ['Working Paper'], 'dc.contributor.author': ['An Author'],
                'dc.description.abstract': ['This study examines access to rural credit.'], **fields}
    return {'_embedded': {'indexableObject': {'uuid': uuid, 'name': 'Rural credit access',
            'metadata': {k: [{'value': v} for v in values] for k, values in metadata.items()}}}}


def test_repository_working_papers_count_one_work_and_require_rights_and_an_exact_day():
    adapter = WorldBankAdapter({'worldbank': {'collection': 'wps'}})
    records = [repository_item('one'), repository_item('duplicate'),
               repository_item('outside', '11503', **{'dc.date.issued': ['2026-10']}),
               repository_item('restrictions', '11504', **{'dc.rights.uri': ['https://creativecommons.org/licenses/by-nc/4.0/']})]
    def handle(req):
        assert req.url.params['scope'] == 'wps' and req.url.params['f.dateIssued'] == f'[{DAY} TO {DAY}],equals'
        n = int(req.url.params['page'])
        return httpx.Response(200, json={'_embedded': {'searchResult': {
            '_embedded': {'objects': records[2*n:2*n+2]}, 'page': {'totalElements': 4, 'totalPages': 2}}}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        work, = adapter.fetch(DAY, DAY, client)
    assert work.id == 'worldbank:WPS11502' and work.type == 'preprint'
    assert work.metadata['license'] == 'https://creativecommons.org/licenses/by/3.0/igo/'
    journal = work.model_copy(update={'id': 'doi:10.1234/journal', 'source': 'crossref', 'type': 'published',
                                      'title': 'Revised analysis of rural credit', 'doi': '10.1234/journal',
                                      'metadata': {'preprint_doi': work.doi}})
    preprint, published = dedupe([work, journal])
    assert published.preprint_id == work.id and preprint.published_doi == journal.doi


def test_incomplete_repository_page_is_reported():
    adapter = WorldBankAdapter({'worldbank': {'collection': 'wps'}})
    def handle(req):
        return httpx.Response(200, json={'_embedded': {'searchResult': {'page': {'totalElements': 1, 'totalPages': 1}}}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match='Incomplete'):
            adapter.fetch(DAY, DAY, client)
