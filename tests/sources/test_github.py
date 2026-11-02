from datetime import date

import httpx
import pytest

from pipeline.sources.github import GithubAdapter, fetch_star_counts, fetch_star_history
from pipeline.store import Store


@pytest.mark.parametrize('gain,release,expected', [(99, False, 0), (100, False, 1), (0, True, 1)])
def test_github_threshold_or_release(gain, release, expected, source_config, fixture_json, respx_mock, monkeypatch, caplog):
    caplog.set_level('INFO')
    monkeypatch.setenv('GITHUB_TOKEN', 'test-github-secret')
    cfg = source_config['github']
    cfg.update(watchlist=['scverse/scanpy'], topics=[])
    repo = dict(fixture_json('github.json'), pushed_at='2026-10-29T12:00:00Z')
    route = respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy").respond(json=repo)
    respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy/releases").respond(json=fixture_json('github_releases.json') if release else [])
    history = {'scverse/scanpy': [(date(2026, 10, 22), repo['stargazers_count'] - gain), (date(2026, 10, 29), repo['stargazers_count'])]}
    with httpx.Client() as client:
        items = GithubAdapter(source_config, star_counts=history).fetch(date(2026,10,29),date(2026,10,29),client)
    assert len(items) == expected
    if items:
        item = items[0]
        assert (item.id,item.type,item.doi,item.published_at) == ('github:scverse/scanpy','code',None,date(2026,10,29))
        assert item.metadata['github_topics'] == repo['topics']
        assert item.metadata['star_gain_7d'] == gain
        assert item.summary is item.primary_category is None
        assert item.first_seen == date(2026,10,29)
    assert route.calls[0].request.headers['Authorization'] == 'Bearer test-github-secret'
    assert 'test-github-secret' not in caplog.text


def test_star_counts_and_history(source_config, fixture_json, respx_mock):
    base = source_config['github']['endpoint']
    repo = fixture_json('github.json')
    respx_mock.get(f'{base}/repos/scverse/scanpy').respond(json=repo)
    stars = respx_mock.get(f'{base}/repos/scverse/scanpy/stargazers').mock(side_effect=[
        httpx.Response(200, json=[{'starred_at':'2025-01-01T12:00:00Z'}, {'starred_at':'2025-01-01T14:00:00Z'}], headers={'Link':f'<{base}/repos/scverse/scanpy/stargazers?page=2>; rel="next"'}),
        httpx.Response(200, json=[{'starred_at':'2025-01-03T10:00:00Z'}])])
    with httpx.Client() as client:
        assert fetch_star_counts(['scverse/scanpy'], client) == {'scverse/scanpy': repo['stargazers_count']}
        assert fetch_star_history('scverse/scanpy', client) == [(date(2025,1,1),2),(date(2025,1,2),2),(date(2025,1,3),3)]
    assert stars.calls[0].request.headers['Accept'] == 'application/vnd.github.star+json'


@pytest.mark.parametrize('count', [40_000, 40_001])
def test_star_history_cutoff(count, source_config, fixture_json, respx_mock):
    repo = fixture_json('github.json'); repo['stargazers_count'] = count
    respx_mock.get(f"{source_config['github']['endpoint']}/repos/scverse/scanpy").respond(json=repo)
    with httpx.Client() as client:
        assert fetch_star_history('scverse/scanpy',client) == []


def test_topic_discovery_bound_and_weekly_cache(source_config, fixture_json, respx_mock):
    cfg=source_config['github']; cfg.update(watchlist=[], topics=['single-cell'],top_n_per_topic=1)
    repo=fixture_json('github.json')
    search=respx_mock.get(f"{cfg['endpoint']}/search/repositories").respond(json={'total_count':2,'items':[repo,dict(repo,full_name='other/repo')]})
    adapter=GithubAdapter(source_config)
    with httpx.Client() as client:
        for day in [29,30]: assert adapter.fetch(date(2026,10,day),date(2026,10,day),client) == []
    assert search.call_count == 1
    assert search.calls[0].request.url.params['sort'] == 'updated'


def test_backfill_detects_midrange_star_event(source_config, fixture_json, respx_mock):
    cfg = source_config['github']; cfg.update(watchlist=['scverse/scanpy'], topics=[])
    respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy").respond(json=fixture_json('github.json'))
    respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy/releases").respond(json=[])
    snapshots = {'scverse/scanpy': [(date(2025,1,1),10), (date(2025,1,8),110), (date(2025,1,31),110)]}
    with httpx.Client() as client:
        items = GithubAdapter(source_config,star_counts=snapshots).fetch(date(2025,1,1),date(2025,1,31),client)
    assert len(items) == 1
    assert items[0].published_at == date(2025,1,8)
    assert items[0].metadata['star_gain_7d'] == 100


def test_missing_baseline_does_not_invent_star_gain(source_config, fixture_json, respx_mock):
    cfg = source_config['github']; cfg.update(watchlist=['scverse/scanpy'], topics=[])
    respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy").respond(json=fixture_json('github.json'))
    respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy/releases").respond(json=[])
    with httpx.Client() as client:
        assert GithubAdapter(source_config).fetch(date.today(),date.today(),client) == []


def test_release_first_page_only(source_config, fixture_json, respx_mock):
    cfg = source_config['github']; cfg.update(watchlist=['scverse/scanpy'], topics=[])
    repo = dict(fixture_json('github.json'), pushed_at='2026-10-29T12:00:00Z')
    respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy").respond(json=repo)
    releases = respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy/releases").respond(
        json=fixture_json('github_releases.json')[:1],
        headers={'Link': f'<{cfg["endpoint"]}/repos/scverse/scanpy/releases?page=2>; rel="next"'},
    )
    with httpx.Client() as client:
        items = GithubAdapter(source_config).fetch(date(2026, 10, 29), date(2026, 10, 29), client)
    assert len(items) == 1
    assert items[0].metadata['releases'][0]['tag_name'] == '1.12.5'
    assert releases.call_count == 1
    assert releases.calls[0].request.url.params['per_page'] == '100'


@pytest.mark.parametrize('pushed', [None, '2026-10-28T23:59:59Z', '2026-10-30T00:00:00Z'])
def test_inactive_repo_skips_releases(pushed, source_config, fixture_json, respx_mock):
    cfg = source_config['github']; cfg.update(watchlist=['scverse/scanpy'], topics=[])
    repo = dict(fixture_json('github.json'), pushed_at=pushed)
    respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy").respond(json=repo)
    adapter = GithubAdapter(source_config)
    with httpx.Client() as client:
        assert adapter.fetch(date(2026, 10, 29), date(2026, 10, 29), client) == []
    assert adapter.observations == {'scverse/scanpy': repo['stargazers_count']}
    assert adapter.rest_calls == 1


def test_fresh_persisted_cache_skips_search(source_config, fixture_json, respx_mock, tmp_path):
    cfg = source_config['github']; cfg.update(watchlist=[], topics=['single-cell'])
    store = Store(tmp_path, 'computational')
    repo = dict(fixture_json('github.json'), pushed_at='2026-10-29T12:00:00Z')
    store.put_github_repos({'refreshed': '2026-10-29', 'repos': {repo['full_name']: repo}})
    adapter = GithubAdapter(source_config, store=Store(tmp_path, 'computational'))
    release = respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy/releases").respond(json=[])
    with httpx.Client() as client:
        adapter.fetch(date(2026, 10, 29), date(2026, 11, 4), client)
    assert adapter.observations == {'scverse/scanpy': repo['stargazers_count']}
    assert release.call_count == adapter.rest_calls == 1
    assert store.github_repos()['refreshed'] == '2026-10-29'


def test_discovery_persists_and_refreshes_after_seven_days(source_config, fixture_json, respx_mock, tmp_path):
    cfg = source_config['github']; cfg.update(watchlist=[], topics=['single-cell'])
    store = Store(tmp_path, 'computational')
    repo = fixture_json('github.json')
    search = respx_mock.get(f"{cfg['endpoint']}/search/repositories").respond(
        json={'total_count': 1, 'items': [repo]},
    )
    with httpx.Client() as client:
        for day in [date(2026, 10, 29), date(2026, 11, 5)]:
            assert GithubAdapter(source_config, store=store).repos(day, client) == [repo['full_name']]
            assert store.github_repos() == {'refreshed': day.isoformat(), 'repos': {repo['full_name']: repo}}
    assert search.call_count == 2


def test_search_metadata_avoids_repo_request(source_config, fixture_json, respx_mock):
    cfg = source_config['github']; cfg.update(watchlist=[], topics=['single-cell'])
    repo = dict(fixture_json('github.json'), pushed_at='2026-10-29T12:00:00Z')
    respx_mock.get(f"{cfg['endpoint']}/search/repositories").respond(json={'total_count': 1, 'items': [repo]})
    respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy/releases").respond(json=fixture_json('github_releases.json'))
    adapter = GithubAdapter(source_config)
    with httpx.Client() as client:
        items = adapter.fetch(date(2026, 10, 29), date(2026, 10, 29), client)
    assert items[0].metadata['stargazers_count'] == repo['stargazers_count']
    assert adapter.rest_calls == 2


def test_cached_release_page_is_reused_across_daily_runs(source_config, fixture_json, respx_mock, tmp_path):
    cfg = source_config['github']; cfg.update(watchlist=[], topics=['single-cell'])
    repo = dict(fixture_json('github.json'), pushed_at='2026-10-29T12:00:00Z')
    store = Store(tmp_path, 'computational')
    search = respx_mock.get(f"{cfg['endpoint']}/search/repositories").respond(
        json={'total_count': 1, 'items': [repo]},
    )
    releases = respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy/releases").respond(
        json=fixture_json('github_releases.json'),
    )
    with httpx.Client() as client:
        first = GithubAdapter(source_config, store=store)
        items = first.fetch(date(2026, 10, 29), date(2026, 10, 29), client)
        second = GithubAdapter(source_config, store=Store(tmp_path, 'computational'))
        cached = second.fetch(date(2026, 10, 29), date(2026, 10, 30), client)
    assert items[0].metadata['releases'] == cached[0].metadata['releases']
    assert not any(key.startswith('_') for key in cached[0].metadata)
    assert first.rest_calls == 2
    assert second.rest_calls == 0
    assert releases.call_count == search.call_count == 1
    assert len(store.github_repos()['repos']['scverse/scanpy']['_releases']) == 1
