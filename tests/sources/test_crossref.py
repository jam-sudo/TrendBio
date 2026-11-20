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


@pytest.mark.parametrize('publisher', ['plos', 'pensoft'])
def test_verified_journals_match_publisher_date_doi_issn_and_genre_before_using_cc0(publisher):
    day = date(2026, 11, 4)
    stamp = {'date-parts': [[2026, 11, 4]]}
    cc0 = 'https://creativecommons.org/publicdomain/zero/1.0/'
    base = 'https://example.org/article/' + ('?id={doi}' if publisher == 'plos' else '')
    work = {'published': stamp, 'title': ['Estuary water observations'], 'abstract': 'Field measurements.',
            'license': [{'content-version': 'vor', 'start': stamp, 'URL': cc0}]}
    cases = ['research', 'essay', 'other-day', 'other-doi', 'other-journal', 'accepted-manuscript', 'empty']
    rows = [{**work, 'DOI': '10.1234/' + case, 'resource': {'primary': {'URL': 'https://example.org/article/' + case}}}
            for case in cases]
    rows[-2]['license'] = [{**work['license'][0], 'content-version': 'am'}]
    rows[-1]['abstract'] = ''
    visited = []

    def reply(req):
        if req.url.host == 'api.crossref.org':
            return httpx.Response(200, json={'message': {'items': rows, 'total-results': len(rows)}})
        case = (req.url.params.get('id') or req.url.path).split('/')[-1]
        visited.append(case)
        genre = 'Essay' if case == 'essay' else ('Research Article' if publisher == 'plos' else 'Short Communication')
        day_field = 'citation_date' if publisher == 'plos' else 'citation_publication_date'
        genre_field = 'citation_article_type' if publisher == 'plos' else 'dc.type'
        native_date = 'Nov 4, 2026' if publisher == 'plos' else '2026/11/04'
        fields = {genre_field: genre, day_field: '2026/11/01' if case == 'other-day' else native_date,
                  'citation_issn': 'other' if case == 'other-journal' else '1234-5678',
                  'citation_doi': '10.1234/other' if case == 'other-doi' else '10.1234/' + case}
        return httpx.Response(200, text=''.join(f'<meta name="{name}" content="{value}">' for name, value in fields.items()))

    config = {'journals': ['1234-5678'], 'article_type_pages': {'1234-5678': base}}
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        paper, = CrossrefAdapter({'crossref': config}).fetch(day, day, client)
        assert not CrossrefAdapter({'crossref': {'journals': ['1234-5678']}}).fetch(day, day, client)
    assert paper.doi == '10.1234/research' and paper.metadata['license'] == cc0
    assert paper.metadata['article_type'] == ('Research Article' if publisher == 'plos' else 'Short Communication')
    assert paper.metadata['article_type_url'].startswith('https://example.org/article/')
    assert visited == cases[:5]


@pytest.mark.parametrize('page_doi', ['10.1234/test', '10.1234/other'])
def test_missing_registry_abstract_uses_the_matching_licensed_publisher_article(page_doi):
    day = date(2026, 11, 4)
    stamp = {'date-parts': [[2026, 11, 4]]}
    work = {'DOI': '10.1234/test', 'title': ['An orchard field trial'], 'published': stamp,
            'license': [{'content-version': 'vor', 'URL': 'https://creativecommons.org/licenses/by/4.0/', 'start': stamp}]}
    def reply(req):
        if req.url.host == 'api.crossref.org':
            return httpx.Response(200, json={'message': {'items': [work, {**work, 'DOI': '10.1234/closed', 'license': []}], 'total-results': 2}})
        assert req.url.path == '/doi/10.1234/test.html'
        return httpx.Response(200, text=f'''<meta name="citation_doi" content="{page_doi}">
          <meta name="citation_issn" content="12345678"><meta name="citation_date" content="2026/11/4">
          <meta name="description" content="Short preview..."><meta name="dc.Description" content="Full orchard measurements.">
          <meta name="DC.Language" content="en">''')

    config = {'crossref': {'journals': ['1234-5678'], 'publisher_abstracts': {'1234-5678': 'https://journal.example/doi/'}}}
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        if page_doi != work['DOI']:
            with pytest.raises(ValueError, match='does not match'):
                CrossrefAdapter(config).fetch(day, day, client)
        else:
            paper, = CrossrefAdapter(config).fetch(day, day, client)
            assert paper.abstract == 'Full orchard measurements.'
            assert paper.metadata['language'] == 'en'
            assert paper.metadata['abstract_url'] == 'https://journal.example/doi/10.1234/test.html'
