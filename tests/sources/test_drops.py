from datetime import date

import httpx
import pytest

from pipeline.sources.drops import DropsAdapter, NS


DAY = date(2026, 11, 2)
PARENT = '10.4230/lipics.disc.2026'


def client_for(*, missing_child=False, missing_volume=False):
    namespace = NS['d']
    licenses = ['https://creativecommons.org/licenses/by/4.0/legalcode'] * 4 + ['https://example.org/terms']
    papers = []
    for n, (kind, license_url) in enumerate(zip(
        ['Front Matter', 'Regular Paper', 'Brief Announcement', 'Regular Paper', 'Regular Paper'], licenses, strict=True
    )):
        published = '2026-11-01' if n == 3 else str(DAY)
        papers.append(f'<article><category>{kind}</category><doi>{PARENT}.{n}</doi><publishedAt>{published}</publishedAt>'
                      f'<title>Graph <i>counting</i></title><abstract>A bound.</abstract><licenseUrl>{license_url}</licenseUrl>'
                      '<author><name>A. Smith</name></author></article>')

    def respond(req):
        if req.url.host == 'api.datacite.org':
            if missing_volume:
                return httpx.Response(404)
            children = [{'relationType': 'HasPart', 'relatedIdentifierType': 'DOI', 'relatedIdentifier': f'{PARENT}.{i}'}
                        for i in range(len(papers) + int(missing_child))]
            return httpx.Response(200, json={'data': {'id': PARENT, 'relationships': {'client': {'data': {'id': 'lzi.drops'}}},
                'attributes': {'container': {'volume': '397'}, 'types': {'resourceTypeGeneral': 'ConferenceProceeding'},
                               'relatedIdentifiers': children}}})
        assert req.url.path == '/entities/volume/LIPIcs-volume-397/metadata/xml'
        return httpx.Response(200, text=f'<metadata xmlns="{namespace}"><volume><volumeNo>397</volumeNo>'
            '<title>DISC</title><event><date>November 9</date></event></volume>' + ''.join(papers) + '</metadata>')
    return httpx.Client(transport=httpx.MockTransport(respond))


def test_regular_licensed_papers_use_publisher_day_and_reconcile_the_whole_volume():
    adapter = DropsAdapter({'drops': {'conferences': ['DISC']}})
    with client_for() as client:
        item, = adapter.fetch(DAY, DAY, client)
    assert (item.doi, item.title, item.authors) == (PARENT + '.1', 'Graph counting', ['A. Smith'])
    assert item.metadata['event_dates'] == 'November 9' and item.published_at == DAY
    with client_for(missing_child=True) as client, pytest.raises(ValueError, match='contents'):
        adapter.fetch(DAY, DAY, client)
    with client_for(missing_volume=True) as client:
        assert adapter.fetch(DAY, DAY, client) == []
