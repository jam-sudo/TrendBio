from datetime import date

import httpx
import pytest

from pipeline.collect import all_paper_sources_failed, intake_status
from pipeline.sources.crossref import CrossrefAdapter, crossref_works, plain_text


def test_journal_equations_keep_one_notation_and_preserve_the_exponent():
    tex = r'<jats:tex-math><![CDATA[$$q^{-1} < x$$]]></jats:tex-math>'
    mathml = '<mml:math><mml:msup><mml:mi>q</mml:mi><mml:mn>-1</mml:mn></mml:msup></mml:math>'
    for pair in (tex + mathml, mathml + tex):
        assert plain_text('For <jats:alternatives>' + pair + '</jats:alternatives>, the bound holds.') == (
            'For $$q^{-1} < x$$, the bound holds.')
    assert plain_text('<alternatives><tex-math> </tex-math><math><mi>x</mi></math></alternatives>') == 'x'


def test_open_edition_requires_current_vor_license_abstract_and_publication_day():
    d = {'date-parts': [[2026, 11, 18]]}
    licence = {'content-version': 'vor', 'URL': 'https://creativecommons.org/licenses/by/4.0/', 'start': d}
    item = {'DOI': '10.5194/Example', 'title': ['Surface CO<sub>2</sub>'], 'abstract': '<jats:p>Ocean &amp; air.</jats:p>',
            'published': d, 'container-title': ['Ocean &amp;\nCoastal Science'], 'license': [licence], 'author': [{'name': 'Ocean Group'}],
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
    assert article.metadata['journal'] == 'Ocean & Coastal Science'
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


@pytest.mark.parametrize('change', [
    {}, {'doi': '10.1234/other'}, {'pmid': '999'}, {'source': 'PPR'}, {'title': 'Different target'},
    {'journalInfo': {'journal': {'issn': '8765-4321'}}}, {'electronicPublicationDate': '2026-11-01'},
    {'license': 'cc by-nc'}, {'pubTypeList': {'pubType': ['Review', 'Journal Article']}},
    {'commentCorrectionList': {'commentCorrection': [{'type': 'Retraction in', 'source': 'MED', 'id': '125'}]}},
])
def test_chemistry_uses_med_abstract_only_for_the_same_licensed_research_article(change):
    day = date(2026, 11, 4)
    stamp = {'date-parts': [[2026, 11, 4]]}
    work = {'DOI': '10.1234/test', 'title': ['Measuring calcium'], 'published': stamp,
            'license': [{'content-version': 'vor', 'URL': 'https://creativecommons.org/licenses/by/4.0/', 'start': stamp}]}
    med = {'source': 'MED', 'id': '123', 'pmid': '123', 'doi': work['DOI'], 'title': 'Measuring calcium.',
           'journalInfo': {'journal': {'essn': '1234-5678'}}, 'firstPublicationDate': '2026-11-01',
           'electronicPublicationDate': day.isoformat(), 'pubTypeList': {'pubType': ['Journal Article']},
           'abstractText': '<p>Agreement with an independent measurement.</p>',
           'commentCorrectionList': {'commentCorrection': [{'type': 'Erratum in', 'source': 'MED', 'id': '124'}]}, **change}
    def reply(req):
        if req.url.host == 'api.crossref.org':
            return httpx.Response(200, json={'message': {'items': [work, {**work, 'DOI': '10.1234/closed', 'license': []}],
                                                         'total-results': 2}})
        assert req.url.params['query'] == 'SRC:MED AND DOI:"10.1234/test"'
        return httpx.Response(200, json={'hitCount': 1, 'resultList': {'result': [med]}})

    config = {'crossref': {'journals': ['1234-5678'], 'medline_abstracts': ['1234-5678']}}
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        items = CrossrefAdapter(config).fetch(day, day, client)
    if change:
        assert not items
    else:
        paper, = items
        assert paper.abstract == 'Agreement with an independent measurement.' and paper.published_at == day
        assert paper.metadata['abstract_url'] == 'https://pubmed.ncbi.nlm.nih.gov/123/'
        assert paper.metadata['correction_links'] == ['https://pubmed.ncbi.nlm.nih.gov/124/']


def test_med_lookup_failure_preserves_registry_abstracts_and_retries_on_next_collection():
    day = date(2026, 11, 4)
    stamp = {'date-parts': [[2026, 11, 4]]}
    work = {'DOI': '10.1234/known', 'title': ['Known reference'], 'published': stamp,
            'license': [{'content-version': 'vor', 'URL': 'https://creativecommons.org/licenses/by/4.0/', 'start': stamp}]}
    responses = iter([httpx.Response(403), httpx.Response(200, json={'hitCount': 0, 'resultList': {'result': []}})])
    def reply(req):
        if req.url.host == 'api.crossref.org':
            return httpx.Response(200, json={'message': {'items': [{**work, 'abstract': 'Publisher text.'},
                                                                   {**work, 'DOI': '10.1234/missing'}], 'total-results': 2}})
        return next(responses)

    adapter = CrossrefAdapter({'crossref': {'journals': ['1234-5678'], 'medline_abstracts': ['1234-5678']}})
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        for status in ('partial', 'ok'):
            paper, = adapter.fetch(day, day, client)
            assert paper.doi == '10.1234/known' and paper.abstract == 'Publisher text.'
            assert intake_status(adapter) == status
