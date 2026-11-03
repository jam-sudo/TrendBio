from datetime import date
from urllib.parse import parse_qs

import httpx

from pipeline.sources.pubmed import PubmedAdapter, pubmed_in_scope
from pipeline.models import Item

import pytest


def test_pubmed(source_config, fixture_text, fixture_json, respx_mock, monkeypatch, caplog):
    source_config['pubmed']['journals'].extend(['Methods in molecular biology (Clifton, N.J.)', 'Cell regeneration (London, England)'])
    caplog.set_level('INFO')
    monkeypatch.setenv('NCBI_API_KEY', 'test-ncbi-secret')
    base = source_config['pubmed']['endpoint']
    search = respx_mock.post(f'{base}/esearch.fcgi').respond(json=fixture_json('pubmed_search.json'))
    fetch = respx_mock.post(f'{base}/efetch.fcgi').respond(text=fixture_text('pubmed.xml'))
    with httpx.Client() as client:
        items = PubmedAdapter(source_config).fetch(date(2020, 1, 1), date(2024, 12, 31), client)
    assert len(items) == 2
    item = items[0]
    assert (item.id, item.type, item.doi, item.published_at) == (
        'pubmed:10.1007/978-1-0716-3642-8_17', 'published',
        '10.1007/978-1-0716-3642-8_17', date(2024, 1, 1))
    assert item.metadata['journal'] == 'Methods in molecular biology (Clifton, N.J.)'
    assert items[1].published_at == date(2020, 7, 6)
    assert item.summary is item.primary_category is None
    assert item.first_seen == date(2024, 12, 31)
    assert search.call_count == 1
    assert fetch.call_count == 1
    assert all(parse_qs(c.request.content.decode())['api_key'][0] == 'test-ncbi-secret' for c in search.calls)
    assert '[Journal]' in parse_qs(search.calls[0].request.content.decode())['term'][0]
    assert 'test-ncbi-secret' not in caplog.text


def test_pubmed_pagination_and_missing_doi(source_config, fixture_text, fixture_json, respx_mock):
    import xml.etree.ElementTree as ET
    data = fixture_json('pubmed_search.json')
    ids = data['esearchresult']['idlist']
    first = {'esearchresult': {'count': '2', 'idlist': ids[:1]}}
    second = {'esearchresult': {'count': '2', 'idlist': ids[1:]}}
    source_config['pubmed']['journals'].extend(['Methods in molecular biology (Clifton, N.J.)', 'Cell regeneration (London, England)'])
    base = source_config['pubmed']['endpoint']
    route = respx_mock.post(f'{base}/esearch.fcgi').mock(side_effect=[httpx.Response(200,json=first),httpx.Response(200,json=second)])
    root = ET.fromstring(fixture_text('pubmed.xml'))
    for parent in root.iter():
        for child in list(parent):
            if child.attrib.get('IdType') == 'doi' or child.attrib.get('EIdType') == 'doi':
                parent.remove(child)
    respx_mock.post(f'{base}/efetch.fcgi').respond(content=ET.tostring(root))
    with httpx.Client() as client:
        items = PubmedAdapter(source_config).fetch(date(2020,1,1),date(2024,12,31),client)
    assert items[0].id == 'pubmed:pmid:38668977'
    assert items[0].doi is None
    assert parse_qs(route.calls[1].request.content.decode())['retstart'][0] == '1'


def test_pubmed_splits_ranges_above_search_limit(source_config, fixture_text, fixture_json, respx_mock):
    source_config['pubmed']['journals'].extend(['Methods in molecular biology (Clifton, N.J.)', 'Cell regeneration (London, England)'])
    base = source_config['pubmed']['endpoint']
    ids = fixture_json('pubmed_search.json')['esearchresult']['idlist']
    search = respx_mock.post(f'{base}/esearch.fcgi').mock(side_effect=[
        httpx.Response(200,json={'esearchresult':{'count':'10000','idlist':[]}}),
        httpx.Response(200,json={'esearchresult':{'count':'1','idlist':ids[:1]}}),
        httpx.Response(200,json={'esearchresult':{'count':'1','idlist':ids[1:]}}),
    ])
    respx_mock.post(f'{base}/efetch.fcgi').respond(text=fixture_text('pubmed.xml'))
    with httpx.Client() as client:
        items = PubmedAdapter(source_config).fetch(date(2020,1,1),date(2024,12,31),client)
    assert len(items) == 2
    ranges = [parse_qs(call.request.content.decode()) for call in search.calls]
    from datetime import timedelta
    assert date.fromisoformat(ranges[1]['maxdate'][0]) + timedelta(days=1) == date.fromisoformat(ranges[2]['mindate'][0])


def test_pubmed_unretrievable_daily_range_fails(source_config, respx_mock):
    import pytest
    respx_mock.post(f"{source_config['pubmed']['endpoint']}/esearch.fcgi").respond(
        json={'esearchresult':{'count':'10000','idlist':[]}})
    with httpx.Client() as client, pytest.raises(ValueError,match='9999'):
        PubmedAdapter(source_config).fetch(date(2025,1,1),date(2025,1,1),client)


def test_pubmed_month_and_medline_dates():
    import xml.etree.ElementTree as ET
    from pipeline.sources.pubmed import _date
    assert _date(ET.fromstring('<PubDate><Year>2024</Year><Month>Aug</Month></PubDate>')) == date(2024,8,1)
    assert _date(ET.fromstring('<PubDate><MedlineDate>2024 Jan-Feb</MedlineDate></PubDate>')) == date(2024,1,1)


def test_pubmed_xml_error_is_not_an_empty_success(source_config, fixture_json, respx_mock):
    import pytest
    base = source_config['pubmed']['endpoint']
    respx_mock.post(f'{base}/esearch.fcgi').respond(json=fixture_json('pubmed_search.json'))
    respx_mock.post(f'{base}/efetch.fcgi').respond(text='<ERROR>Unable to obtain query</ERROR>')
    with httpx.Client() as client, pytest.raises(ValueError, match='PubMed fetch failed'):
        PubmedAdapter(source_config).fetch(date(2020,1,1),date(2024,12,31),client)


def test_pubmed_query_is_built_from_journal_lists(source_config, respx_mock):
    base = source_config['pubmed']['endpoint']
    search = respx_mock.post(f'{base}/esearch.fcgi').respond(
        json={'esearchresult': {'count': '0', 'idlist': []}})
    with httpx.Client() as client:
        assert PubmedAdapter(source_config).fetch(date(2026, 10, 1), date(2026, 10, 31), client) == []
    assert search.call_count == 1
    params = parse_qs(search.calls[0].request.content.decode())
    term = params['term'][0]
    assert term == '(' + ' OR '.join(f'"{journal}"[Journal]' for journal in (
        source_config['pubmed']['journals'] + source_config['pubmed']['journals_keyword_filtered'])) + ')'
    assert 'MeSH' not in term and 'Title/Abstract' not in term
    assert params['mindate'] == ['2026-10-01'] and params['maxdate'] == ['2026-10-31']


def scope_item(journal, title='A new method', abstract=''):
    return Item(id='pubmed:test', source='pubmed', type='published', title=title,
                url='https://example.org', doi=None, published_at=date(2026, 10, 1),
                first_seen=date(2026, 10, 1), authors=[], org=None, abstract=abstract,
                summary=None, primary_category=None, published_doi=None, preprint_id=None,
                metadata={'journal': journal})


def test_pubmed_keyword_filtered_journal_requires_keyword(source_config):
    assert not pubmed_in_scope(scope_item('Nature'), source_config)
    assert pubmed_in_scope(scope_item('Nature', title='New GENOMICS method'), source_config)
    assert pubmed_in_scope(scope_item('Nature', abstract='A genomics resource'), source_config)
    assert pubmed_in_scope(scope_item('Bioinformatics (Oxford, England)'), source_config)
    assert pubmed_in_scope(scope_item('Proceedings of the National Academy of Sciences of the United States of America',
                                     abstract='Genomics resource'), source_config)
    assert pubmed_in_scope(scope_item('Database : the journal of biological databases and curation'), source_config)


@pytest.mark.parametrize('journal', ['PLoS one', 'Frontiers in immunology', '',
                                    'bioRxiv : the preprint server for biology', 'medRxiv',
                                    'medRxiv : the preprint server for health sciences'])
def test_pubmed_in_scope_rejects_unlisted_journal_and_preprint_server(source_config, journal):
    assert not pubmed_in_scope(scope_item(journal, title='Genomics method'), source_config)


def test_pubmed_adapter_filters_out_of_scope_records(source_config, fixture_text, fixture_json, respx_mock):
    base = source_config['pubmed']['endpoint']
    respx_mock.post(f'{base}/esearch.fcgi').respond(json=fixture_json('pubmed_search.json'))
    respx_mock.post(f'{base}/efetch.fcgi').respond(text=fixture_text('pubmed.xml'))
    with httpx.Client() as client:
        items = PubmedAdapter(source_config).fetch(date(2020, 1, 1), date(2024, 12, 31), client)
    assert items == []
