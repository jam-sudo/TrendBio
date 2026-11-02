from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch
import xml.etree.ElementTree as ET

import httpx
import pytest

from pipeline.sources.arxiv import ArxivAdapter, NS
from pipeline.sources.base import request


def test_arxiv_filters_categories(source_config, fixture_text, respx_mock):
    route = respx_mock.get(source_config['arxiv']['endpoint']).respond(text=fixture_text('arxiv.xml'))
    start, end = date(2017, 1, 1), date(2025, 6, 30)
    with httpx.Client() as client:
        items = ArxivAdapter(source_config).fetch(start, end, client)
    assert len(items) == 1
    item = items[0]
    assert (item.id, item.type, item.doi, item.published_at) == (
        'arxiv:2506.13344', 'preprint', None, date(2025, 6, 16))
    assert 'single-cell' in item.abstract.lower()
    assert item.metadata['arxiv_primary_category'] == 'cs.LG'
    assert item.summary is item.primary_category is None
    assert item.first_seen == end
    query = route.calls[0].request.url.params['search_query']
    assert 'submittedDate:[201701010000 TO 202506302359]' in query
    assert 'cat:q-bio.*' in query


def test_arxiv_pagination_and_dates(source_config, fixture_text, respx_mock):
    root = ET.fromstring(fixture_text('arxiv.xml'))
    entries = root.findall('atom:entry', NS)
    root.find('opensearch:totalResults', NS).text = '101'
    for entry in entries:
        root.remove(entry)
    root.extend([entries[0]] * 100)
    page1 = ET.tostring(root)
    for entry in root.findall('atom:entry', NS):
        root.remove(entry)
    root.append(entries[1])
    route = respx_mock.get(source_config['arxiv']['endpoint']).mock(side_effect=[
        httpx.Response(200, content=page1), httpx.Response(200, content=ET.tostring(root))])
    with httpx.Client() as client:
        items = ArxivAdapter(source_config).fetch(date(2025, 6, 1), date(2025, 6, 30), client)
    assert len(items) == 100
    assert route.calls[1].request.url.params['start'] == '100'


def test_arxiv_keyword_gate_without_qbio_crosslisting(source_config, fixture_text, respx_mock):
    root = ET.fromstring(fixture_text('arxiv.xml'))
    for entry in root.findall('atom:entry', NS):
        for tag in entry.findall('atom:category', NS):
            if tag.attrib['term'].startswith('q-bio.'):
                entry.remove(tag)
    respx_mock.get(source_config['arxiv']['endpoint']).respond(content=ET.tostring(root))
    with httpx.Client() as client:
        items = ArxivAdapter(source_config).fetch(date(2017,1,1), date(2025,6,30), client)
    assert [item.id for item in items] == ['arxiv:2506.13344']


def test_arxiv_qbio_does_not_need_keywords(source_config, fixture_text, respx_mock):
    source_config['keywords'] = []
    respx_mock.get(source_config['arxiv']['endpoint']).respond(text=fixture_text('arxiv.xml'))
    with httpx.Client() as client:
        items = ArxivAdapter(source_config).fetch(date(2017,1,1), date(2025,6,30), client)
    assert [item.id for item in items] == ['arxiv:2506.13344']


def test_arxiv_query_embeds_keywords_for_cs_categories(source_config, fixture_text, respx_mock):
    source_config['arxiv']['query_keywords_max'] = 2
    route = respx_mock.get(source_config['arxiv']['endpoint']).respond(text=fixture_text('arxiv.xml'))
    with httpx.Client() as client:
        ArxivAdapter(source_config).fetch(date(2025, 6, 1), date(2025, 6, 30), client)
    query = route.calls[0].request.url.params['search_query']
    assert query == ('((cat:q-bio.*) OR ((cat:cs.LG OR cat:cs.AI OR cat:stat.ML) '
                     'AND (abs:"bioinformatics" OR abs:"computational biology"))) '
                     'AND submittedDate:[202506010000 TO 202506302359]')


def test_arxiv_stops_at_max_results_cap_with_warning(source_config, fixture_text, respx_mock, caplog):
    source_config['arxiv']['max_results_per_query'] = 150
    root = ET.fromstring(fixture_text('arxiv.xml'))
    entries = root.findall('atom:entry', NS)
    root.find('opensearch:totalResults', NS).text = '5000'
    for entry in entries:
        root.remove(entry)

    def page(req):
        feed = ET.fromstring(ET.tostring(root))
        feed.extend([entries[0]] * int(req.url.params['max_results']))
        return httpx.Response(200, content=ET.tostring(feed))

    route = respx_mock.get(source_config['arxiv']['endpoint']).mock(side_effect=page)
    with httpx.Client() as client:
        items = ArxivAdapter(source_config).fetch(date(2025, 6, 1), date(2025, 6, 30), client)
    assert len(items) == 150
    assert [call.request.url.params['start'] for call in route.calls] == ['0', '100']
    assert route.calls[1].request.url.params['max_results'] == '50'
    assert 'event=query_truncated' in caplog.text and 'cap=150 total=5000' in caplog.text
    assert all(record.levelname == 'WARNING' for record in caplog.records)
    assert 'search_query' not in caplog.text


def test_arxiv_stops_on_short_page(source_config, fixture_text, respx_mock, caplog):
    root = ET.fromstring(fixture_text('arxiv.xml'))
    root.find('opensearch:totalResults', NS).text = '5000'
    route = respx_mock.get(source_config['arxiv']['endpoint']).respond(content=ET.tostring(root))
    with httpx.Client() as client:
        ArxivAdapter(source_config).fetch(date(2025, 6, 1), date(2025, 6, 30), client)
    assert route.call_count == 1
    assert 'query_truncated' not in caplog.text


@pytest.mark.parametrize('failures', [1, 4])
def test_request_honours_attempts_and_backoff(respx_mock, failures):
    route = respx_mock.get('https://example.org/api').mock(side_effect=[
        *[httpx.Response(500) for _ in range(failures)], httpx.Response(200)])
    with patch('pipeline.sources.base.time.sleep') as sleep, httpx.Client() as client:
        assert request(client, 'https://example.org/api', attempts=5, backoff=5.0).status_code == 200
    assert route.call_count == failures + 1
    assert [call.args[0] for call in sleep.call_args_list] == [5, 10, 20, 40][:failures]


@pytest.mark.parametrize('retry_after', ['120', 'date', 'invalid'])
def test_request_honours_retry_after(respx_mock, retry_after):
    value = (format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)
             if retry_after == 'date' else retry_after)
    respx_mock.get('https://example.org/api').mock(side_effect=[
        httpx.Response(503, headers={'Retry-After': value}), httpx.Response(200)])
    with patch('pipeline.sources.base.time.sleep') as sleep, httpx.Client() as client:
        request(client, 'https://example.org/api', attempts=5, backoff=5.0)
    assert sleep.call_count == 1
    if retry_after == 'invalid':
        assert sleep.call_args.args == (5.0,)
    else:
        assert 118 <= sleep.call_args.args[0] <= 120


def test_arxiv_uses_extended_retries(source_config, fixture_text, respx_mock):
    route = respx_mock.get(source_config['arxiv']['endpoint']).mock(side_effect=[
        *[httpx.Response(500) for _ in range(4)], httpx.Response(200, text=fixture_text('arxiv.xml'))])
    with patch('pipeline.sources.base.time.sleep') as sleep, httpx.Client() as client:
        ArxivAdapter(source_config).fetch(date(2025, 6, 1), date(2025, 6, 30), client)
    assert route.call_count == 5
    assert [call.args[0] for call in sleep.call_args_list] == [5, 10, 20, 40]
