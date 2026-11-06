import json
from datetime import date, timedelta

import httpx
import pytest

from pipeline import attention
from pipeline.config import AttentionConfig, load_scoring
from pipeline.models import Item
from pipeline.store import Store
from test_bluesky_probe import post

DAY = date(2026, 11, 5)


def api_with(handler, budget=800):
    return attention.Bluesky(httpx.Client(transport=httpx.MockTransport(handler)),
                             sleep=lambda _: None, max_calls=budget)


def test_daily_slices_and_per_host_truncation():
    requests = []
    def handler(request):
        params = dict(request.url.params)
        requests.append(params)
        assert params['q'] == '*' and params['sort'] == 'latest' and params['limit'] == '100'
        assert date.fromisoformat(params['until']) - date.fromisoformat(params['since']) == timedelta(days=1)
        if params['domain'] == 'biorxiv.org' and params['since'] == '2026-10-30':
            return httpx.Response(200, json={'posts': [], 'hitsTotal': 1000})
        return httpx.Response(200, json={'posts': []})
    api = api_with(handler)
    hosts = attention.sweep_days(api, attention.Attention({}), DAY - timedelta(days=6), DAY + timedelta(days=1))
    assert len(requests) == 42
    assert {p['since'] for p in requests} == {str(DAY - timedelta(days=i)) for i in range(7)}
    assert hosts['biorxiv.org'] == {'partial': True, 'truncated_days': ['2026-10-30']}
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
