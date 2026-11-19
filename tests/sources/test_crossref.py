from datetime import date

import httpx
import pytest

from pipeline.collect import all_paper_sources_failed
from pipeline.sources.crossref import CrossrefAdapter, crossref_works


def test_open_edition_requires_current_vor_license_abstract_and_publication_day():
    d = {'date-parts': [[2026, 11, 18]]}
    licence = {'content-version': 'vor', 'URL': 'https://creativecommons.org/licenses/by/4.0/', 'start': d}
    item = {'DOI': '10.5194/Example', 'title': ['Surface CO<sub>2</sub>'], 'abstract': '<jats:p>Ocean &amp; air.</jats:p>',
            'published': d, 'container-title': ['Ocean Science'], 'license': [licence], 'author': [{'name': 'Ocean Group'}],
            'relation': {'has-preprint': [{'id-type': 'doi', 'id': 'https://doi.org/10.5194/PRE'}],
                         'is-part-of': [{'id-type': 'doi', 'id': '10.1/data'}, {'id-type': 'doi', 'id': '10.1/book'}]}}
    cases = [item, {**item, 'DOI': '10.5194/month', 'published': {'date-parts': [[2026, 11]]}},
             {**item, 'DOI': '10.5194/closed', 'license': []}, {**item, 'DOI': '10.5194/empty', 'abstract': ''},
             {**item, 'DOI': '10.5194/future', 'license': [{**licence, 'start': {'date-parts': [[2027, 1, 1]]}}]},
             {**item, 'DOI': '10.5194/correction', 'update-to': [{'type': 'correction'}]}]
    def reply(req):
        if req.url.host == 'api.datacite.org':
            if req.url.path.endswith('/book'):
                return httpx.Response(404)
            return httpx.Response(200, json={'data': {'id': '10.1/data', 'attributes': {'types': {'resourceTypeGeneral': 'Dataset'}}}})
        assert 'from-pub-date:2026-11-18' in req.url.params['filter']
        return httpx.Response(200, json={'message': {'items': cases, 'total-results': len(cases)}})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        article, = CrossrefAdapter({'crossref': {'journals': ['test'], 'data_journals': ['test']}}).fetch(
            date(2026, 11, 18), date(2026, 11, 18), client)
    assert (article.id, article.title, article.abstract) == ('doi:10.5194/example', 'Surface CO2', 'Ocean & air.')
    assert article.metadata['preprint_doi'] == '10.5194/pre' and article.authors == ['Ocean Group']
    assert article.metadata['dataset_dois'] == ['10.1/data'] and article.metadata['unverified_related_dois'] == []
    assert all_paper_sources_failed({'crossref': 'failed', 'arxiv': 'skipped'})


def test_crossref_short_response_cannot_silently_truncate():
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
            'message': {'items': [], 'total-results': 1}}))) as client:
        with pytest.raises(ValueError, match='Incomplete Crossref'):
            list(crossref_works(client, 'https://example.org', 'type:journal-article'))
