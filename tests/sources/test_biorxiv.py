from datetime import date
from unittest.mock import patch

import httpx
import pytest

from pipeline.sources.biorxiv import BiorxivAdapter
from pipeline.sources.base import request

DAY = date(2025, 1, 6)


def test_biorxiv(source_config, fixture_json, respx_mock):
    data = fixture_json('biorxiv.json')
    # Keep keyword filtering independent of the revision cutoff.
    data['collection'][1]['version'] = '1'
    route = respx_mock.get(url__startswith=source_config['biorxiv']['endpoint']).respond(json=data)
    with httpx.Client() as client:
        items = BiorxivAdapter(source_config).fetch(DAY, DAY, client)
    assert len(items) == 2
    item = items[0]
    assert (item.id, item.type, item.doi, item.published_at) == (
        'biorxiv:10.1101/2024.09.30.615766', 'preprint', '10.1101/2024.09.30.615766', DAY)
    assert item.published_doi == '10.1093/bib/bbaf035'
    assert item.metadata['biorxiv_category'] == 'bioinformatics'
    assert item.summary is item.primary_category is None
    assert item.first_seen == DAY
    assert route.call_count == 1


@pytest.mark.parametrize('failure', [429, 503, 'connection'])
def test_retry_three_attempts(failure, respx_mock):
    error = httpx.ConnectError('offline') if failure == 'connection' else httpx.Response(failure)
    route = respx_mock.get('https://example.org/api').mock(side_effect=[error, error, httpx.Response(200)])
    with patch('pipeline.sources.base.time.sleep') as sleep, httpx.Client() as client:
        assert request(client, 'https://example.org/api').status_code == 200
    assert route.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


def test_retry_exhaustion_and_nonretryable(respx_mock):
    with patch('pipeline.sources.base.time.sleep'), httpx.Client() as client:
        route = respx_mock.get('https://example.org/api').respond(500)
        with pytest.raises(httpx.HTTPStatusError):
            request(client, 'https://example.org/api')
        assert route.call_count == 3
        route = respx_mock.get('https://example.org/missing').respond(404)
        with pytest.raises(httpx.HTTPStatusError):
            request(client, 'https://example.org/missing')
        assert route.call_count == 1


def test_biorxiv_pagination(source_config, fixture_json, respx_mock):
    data = fixture_json('biorxiv.json')
    data['collection'][1]['version'] = '1'
    first = {'messages': [{'status': 'ok', 'total': 4}], 'collection': data['collection'][:1]}
    second = {'messages': [{'status': 'ok', 'total': 4}], 'collection': data['collection'][1:]}
    endpoint = source_config['biorxiv']['endpoint']
    respx_mock.get(f'{endpoint}/{DAY}/{DAY}/0').respond(json=first)
    respx_mock.get(f'{endpoint}/{DAY}/{DAY}/1').respond(json=second)
    with httpx.Client() as client:
        assert len(BiorxivAdapter(source_config).fetch(DAY, DAY, client)) == 2


def test_biorxiv_no_published_doi_or_posts(source_config, fixture_json, respx_mock):
    data = fixture_json('biorxiv.json')
    data['collection'][0]['published'] = 'NA'
    respx_mock.get(url__startswith=source_config['biorxiv']['endpoint']).mock(side_effect=[
        httpx.Response(200, json=data),
        httpx.Response(200, json={'messages':[{'status':'no posts found'}], 'collection':[]}),
    ])
    with httpx.Client() as client:
        adapter = BiorxivAdapter(source_config)
        assert adapter.fetch(DAY, DAY, client)[0].published_doi is None
        assert adapter.fetch(DAY, DAY, client) == []


def test_source_config_is_complete(source_config):
    from pipeline.config import load_taxonomy
    assert len(source_config['keywords']) >= 40
    assert len(source_config['pubmed']['journals']) == 16
    assert len(source_config['github']['watchlist']) >= 15
    assert source_config['github']['top_n_per_topic'] == 50
    slugs = set(load_taxonomy('computational').slugs())
    for hints in source_config['hints'].values():
        assert hints
        assert all(set(values) <= slugs for values in hints.values())
    for feed in source_config['rss']['feeds']:
        assert feed['url'].startswith('https://')
        assert feed['kind'] in {'company', 'news'}


@pytest.fixture
def revisions(source_config, fixture_json, respx_mock):
    data = fixture_json('biorxiv_revisions.json')
    route = respx_mock.get(url__startswith=source_config['biorxiv']['endpoint']).respond(json=data)
    return BiorxivAdapter(source_config), route


def test_biorxiv_revision_outside_window_is_dropped(revisions):
    adapter, _ = revisions
    with httpx.Client() as client:
        items = adapter.fetch(date(2025, 1, 5), DAY, client)
    assert 'biorxiv:10.1101/2024.06.01.222222' not in {item.id for item in items}
    assert next(item for item in items if item.doi == '10.1101/2025.01.06.111111').published_at == DAY


def test_biorxiv_revision_inside_window_uses_doi_date(revisions):
    adapter, _ = revisions
    with httpx.Client() as client:
        items = adapter.fetch(date(2025, 1, 5), DAY, client)
    item = next(item for item in items if item.doi == '10.1101/2025.01.05.333333')
    assert item.published_at == date(2025, 1, 5)
    assert item.metadata['version'] == '2'


def test_biorxiv_undated_doi_revision_is_dropped(revisions):
    adapter, _ = revisions
    with httpx.Client() as client:
        items = adapter.fetch(date(2025, 1, 5), DAY, client)
    assert 'biorxiv:10.1101/123456' not in {item.id for item in items}


def test_biorxiv_logs_dropped_revisions(revisions, caplog):
    caplog.set_level('INFO', logger='pipeline.sources.biorxiv')
    adapter, route = revisions
    with httpx.Client() as client:
        adapter.fetch(date(2025, 1, 5), DAY, client)
        assert adapter.dropped_revisions == 2
        assert 'dropped 2 revisions' in caplog.text
        route.respond(json={'messages': [{'status': 'no posts found'}], 'collection': []})
        adapter.fetch(date(2025, 1, 5), DAY, client)
    assert adapter.dropped_revisions == 0
    assert 'dropped 0 revisions' in caplog.text


@pytest.mark.parametrize('doi,expected', [
    ('10.64898/2025.01.05.734591', date(2025, 1, 5)),
    ('10.1101/2025.02.30.123456', None),
])
def test_biorxiv_revision_doi_dates(source_config, fixture_json, respx_mock, doi, expected):
    record = fixture_json('biorxiv_revisions.json')['collection'][2]
    record['doi'] = doi
    respx_mock.get(url__startswith=source_config['biorxiv']['endpoint']).respond(
        json={'messages': [{'status': 'ok', 'total': 1}], 'collection': [record]})
    adapter = BiorxivAdapter(source_config)
    with httpx.Client() as client:
        items = adapter.fetch(date(2025, 1, 5), DAY, client)
    assert [item.published_at for item in items] == ([] if expected is None else [expected])
    assert adapter.dropped_revisions == (expected is None)
