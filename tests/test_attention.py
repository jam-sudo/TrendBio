import json
from datetime import date, datetime, timedelta

import httpx
import pytest

from pipeline import attention
from pipeline.config import AttentionConfig, load_scoring
from pipeline.models import Item
from pipeline.store import Store
from test_bluesky_probe import post

DAY = date(2026, 11, 5)


def api_with(handler, budget=800, **kwargs):
    return attention.Bluesky(httpx.Client(transport=httpx.MockTransport(handler)),
                             sleep=lambda _: None, max_calls=budget, **kwargs)


@pytest.mark.parametrize('still_truncated', [False, True])
def test_daily_slices_and_per_host_truncation(still_truncated):
    requests = []
    shared = post(links=['https://biorxiv.org/content/10.1101/123'])
    def handler(request):
        params = dict(request.url.params)
        requests.append(params)
        assert params['q'] == '*' and params['sort'] == 'latest' and params['limit'] == '100'
        duration = datetime.fromisoformat(params['until']) - datetime.fromisoformat(params['since'])
        if duration < timedelta(days=1):
            assert len(requests) > 42 and params['domain'] == 'biorxiv.org'
            assert params['since'].endswith('+00:00')
        if (params['domain'] == 'biorxiv.org' and params['since'].startswith('2026-10-30')
                and (duration > timedelta(hours=1) or still_truncated)):
            return httpx.Response(200, json={'posts': [shared], 'hitsTotal': 1000})
        return httpx.Response(200, json={'posts': [shared] if params['domain'] == 'biorxiv.org' else []})
    api = api_with(handler)
    collected = attention.Attention({})
    hosts = attention.sweep_days(api, collected, DAY - timedelta(days=6), DAY + timedelta(days=1))
    assert len(collected.posts) == 1
    assert collected.unknown['10.1101/123']['engagement'] == 6
    assert len(requests) == 42 + 4 + 24
    assert {p['since'] for p in requests[:42]} == {str(DAY - timedelta(days=i)) for i in range(7)}
    assert hosts['biorxiv.org'] == {'partial': still_truncated,
                                   'truncated_days': ['2026-10-30'] if still_truncated else [],
                                   'split_days': 1}
    hourly = [p for p in requests[42:] if datetime.fromisoformat(p['until']) -
              datetime.fromisoformat(p['since']) == timedelta(hours=1)]
    assert [datetime.fromisoformat(p['since']).hour for p in hourly] == list(reversed(range(24)))
    assert all(not state['partial'] for host, state in hosts.items() if host != 'biorxiv.org')


def item(i, **updates):
    return Item(id=f'arxiv:2611.{i:05}', source='arxiv', type='preprint', title=f'Paper {i}',
                url=f'https://arxiv.org/abs/2611.{i:05}', doi=None, published_at=DAY,
                first_seen=DAY, authors=[], org=None, abstract='', summary='', primary_category=None,
                published_doi=None, preprint_id=None).model_copy(update=updates)


def setup_collect(tmp_path, monkeypatch, handler, cfg=None):
    monkeypatch.setenv('BLUESKY_HANDLE', 'private-handle')
    monkeypatch.setenv('BLUESKY_APP_PASSWORD', 'private-password')
    api = api_with(handler, (cfg or AttentionConfig()).max_search_calls)
    monkeypatch.setattr(attention, 'Bluesky', lambda *args, **kwargs: api)
    store = Store(tmp_path, 'computational')
    return store, api


@pytest.mark.parametrize("top_n", [1, 3])
def test_qualifying_papers_automation_threshold_order_and_private_output(tmp_path, monkeypatch, top_n):
    posts = []
    # Twenty distinct IDs across hosts, including unknown papers, exclude this account.
    for i in range(20):
        posts.append(post(uri=f'at://automated/{i}', author='did:plc:automated',
                          links=[f'https://arxiv.org/abs/2611.{i:05}']))
        posts[-1]['likeCount'] = 100
    for i in range(7):
        p = post(uri=f'at://human/{i}', author=f'did:plc:person-{i}',
                 links=[f'https://arxiv.org/abs/2611.{i:05}'])
        p.update(likeCount=2 if i == 0 else 3, repostCount=1, quoteCount=1)
        posts.append(p)
    posts.append(post(uri='at://second-person', author='did:plc:other', links=['https://arxiv.org/abs/2611.00002']))
    posts[-1].update(likeCount=0, repostCount=0, quoteCount=0)
    def handler(request):
        if request.url.path.endswith(attention.SESSION):
            return httpx.Response(200, json={'accessJwt': 'private-token'})
        return httpx.Response(200, json={'posts': posts})
    store, api = setup_collect(tmp_path, monkeypatch, handler)
    for i in range(6):
        store.put_item(item(i, relevant=i != 3, type='code' if i == 4 else 'published' if i == 5 else 'preprint'))
    result = attention.collect_attention(DAY, store, AttentionConfig(store_top_n=top_n), api.client)
    assert result['papers'] == [
        {'item_id': 'arxiv:2611.00002', 'engagement': 5, 'authors': 2},
        {'item_id': 'arxiv:2611.00001', 'engagement': 5, 'authors': 1},
        {'item_id': 'arxiv:2611.00005', 'engagement': 5, 'authors': 1},
    ][:top_n]
    assert result['posts_swept'] == 28 and result['automated_accounts'] == 1
    assert result['automated_post_share'] == 20 / 28
    assert result['search_calls'] == 42 and result['partial'] is False
    assert result['window_start'] == '2026-10-30'
    store.put_attention(result)
    output = (tmp_path / 'computational/attention/2026-11-05.json').read_text()
    assert json.loads(output) == result
    for private in ['private-handle', 'private-password', 'private-token', 'did:plc:', 'at://',
                    'private-person.bsky.social', 'PRIVATE FIXTURE POST TEXT', 'automated/']:
        assert private not in output


@pytest.mark.parametrize('failure', ['budget', 'http', 'unexpected'])
def test_partial_data_survives_failure(tmp_path, monkeypatch, failure):
    calls = []
    def handler(request):
        if request.url.path.endswith(attention.SESSION):
            return httpx.Response(200, json={'accessJwt': 'secret'})
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={'posts': [post(links=['https://biorxiv.org/content/10.1101/123'])]})
        if failure == 'unexpected':
            raise RuntimeError('private-password did:plc:secret')
        return httpx.Response(500, json={'message': 'private-password did:plc:secret'})
    cfg = AttentionConfig(max_search_calls=1 if failure == 'budget' else 800)
    store, api = setup_collect(tmp_path, monkeypatch, handler, cfg)
    result = attention.collect_attention(DAY, store, cfg, api.client)
    assert result['partial'] is True and result['posts_swept'] == 1
    assert 'secret' not in json.dumps(result)


def test_missing_credentials_makes_no_requests(tmp_path, monkeypatch):
    monkeypatch.delenv('BLUESKY_HANDLE', raising=False)
    monkeypatch.delenv('BLUESKY_APP_PASSWORD', raising=False)
    assert attention.collect_attention(DAY, Store(tmp_path, 'computational'), AttentionConfig(), None) is None


def test_attention_defaults():
    assert load_scoring().attention == AttentionConfig()
    assert load_scoring().attention.max_search_calls == 800


@pytest.mark.parametrize('budget', [6, 7, 10])
def test_split_collection_deduplicates_and_preserves_data_at_budget(tmp_path, monkeypatch, budget):
    shared = post(links=['https://biorxiv.org/content/10.1101/123'])
    recovered = post(uri='at://recovered', links=['https://biorxiv.org/content/10.1101/123'])
    def handler(request):
        if request.url.path.endswith(attention.SESSION):
            return httpx.Response(200, json={'accessJwt': 'secret'})
        params = request.url.params
        if params['domain'] != 'biorxiv.org':
            return httpx.Response(200, json={'posts': []})
        if 'T' not in params['since']:
            return httpx.Response(200, json={'posts': [shared], 'hitsTotal': 200})
        return httpx.Response(200, json={'posts': [shared, recovered]})
    cfg = AttentionConfig(max_search_calls=budget, window_days=1)
    store, api = setup_collect(tmp_path, monkeypatch, handler, cfg)
    store.put_item(item(1, doi='10.1101/123', relevant=True))
    result = attention.collect_attention(DAY, store, cfg, api.client)
    assert result['partial'] is (budget < 10)
    assert result['search_calls'] == budget
    assert result['posts_swept'] == (1 if budget == 6 else 2)
    assert result['papers'] == [{'item_id': item(1).id, 'engagement': 6 if budget == 6 else 12, 'authors': 1}]
    assert result['hosts']['biorxiv.org']['split_days'] == 1
    assert result['hosts']['biorxiv.org']['truncated_days'] == []
    assert 'at://' not in json.dumps(result)


def test_splits_recent_days_first_and_arxiv_last():
    requests = []
    def handler(request):
        params = dict(request.url.params)
        requests.append(params)
        return httpx.Response(200, json={'posts': [], 'hitsTotal': 200 if 'T' not in params['since'] else 0})
    api = api_with(handler)
    hosts = attention.sweep_days(api, attention.Attention({}), DAY - timedelta(days=1), DAY + timedelta(days=1))
    assert len(requests) == 12 + 12 * 4
    assert all('T' not in p['since'] for p in requests[:12])
    order = [(p['domain'], p['since'][:10]) for p in requests[12::4]]
    other_hosts = [host for host in attention.HOSTS if host != 'arxiv.org']
    assert order == [(host, str(day)) for day in [DAY, DAY - timedelta(days=1)] for host in other_hosts] + [
        ('arxiv.org', str(DAY)), ('arxiv.org', str(DAY - timedelta(days=1)))]
    assert all(state == {'partial': False, 'truncated_days': [], 'split_days': 2} for state in hosts.values())


@pytest.mark.parametrize('fail_at', [2, 8])
@pytest.mark.parametrize('status', [429, 500])
def test_api_failure_stops_immediately_even_during_splitting(tmp_path, monkeypatch, fail_at, status):
    calls = []
    def handler(request):
        if request.url.path.endswith(attention.SESSION):
            return httpx.Response(200, json={'accessJwt': 'secret'})
        calls.append(request)
        if len(calls) == fail_at:
            return httpx.Response(status, json={'message': 'secret did:plc:private'})
        return httpx.Response(200, json={'posts': [post(links=['https://biorxiv.org/content/10.1101/123'])],
                                         'hitsTotal': 200 if len(calls) == 1 else 0})
    monkeypatch.setenv('BLUESKY_HANDLE', 'private-handle')
    monkeypatch.setenv('BLUESKY_APP_PASSWORD', 'private-password')
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(attention, 'PAUSE', 0)
    result = attention.collect_attention(DAY, Store(tmp_path, 'computational'), AttentionConfig(window_days=1), client)
    assert len(calls) == result['search_calls'] == fail_at
    assert result['partial'] is True and result['posts_swept'] == 1
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('stop_at', [1, 7])
def test_wall_clock_limit_preserves_posts_and_stops_sweeps(stop_at):
    elapsed = 0
    requests = []
    def handler(request):
        nonlocal elapsed
        requests.append(request)
        if len(requests) == stop_at:
            elapsed = attention.MAX_SECONDS
        return httpx.Response(200, json={'posts': [post(links=['https://biorxiv.org/content/10.1101/123'])],
                                         'hitsTotal': 200 if len(requests) == 1 else 0})
    api = api_with(handler, clock=lambda: elapsed)
    collected = attention.Attention({})
    hosts = attention.sweep_days(api, collected, DAY, DAY + timedelta(days=1))
    assert len(requests) == api.calls == stop_at
    assert len(collected.posts) == 1
    assert all(state['partial'] for state in hosts.values())


def test_deadline_includes_pause_and_caps_request_timeout():
    elapsed = attention.MAX_SECONDS - 1
    requests = []
    api = api_with(lambda request: requests.append(request) or httpx.Response(200, json={'posts': []}),
                   clock=lambda: elapsed)
    api.deadline = attention.MAX_SECONDS
    api.search_response({})
    assert requests[0].extensions['timeout'] == dict.fromkeys(['connect', 'read', 'write', 'pool'], 1)
    sleeps = []
    def sleep(delay):
        nonlocal elapsed
        sleeps.append(delay)
        elapsed += delay
    api.sleep = sleep
    elapsed = attention.MAX_SECONDS - 0.1
    states, error = attention.sweep(api, attention.Attention({}), str(DAY), str(DAY + timedelta(days=1)), '*')
    assert len(requests) == 1 and error is None
    assert sleeps == [pytest.approx(0.1)]
    assert all(state['status'] == 'time limit' and state['partial'] for state in states.values())
