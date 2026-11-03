from datetime import date

import httpx
import pytest

from pipeline.sources.github import GithubAdapter, collapse_duplicates, fetch_star_counts, fetch_star_history
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


def test_search_query_excludes_forks(source_config, respx_mock):
    cfg = source_config['github']
    cfg.update(watchlist=[], topics=['single-cell', 'genomics'])
    search = respx_mock.get(f"{cfg['endpoint']}/search/repositories").respond(json={'total_count': 0, 'items': []})
    with httpx.Client() as client:
        assert GithubAdapter(source_config).repos(date(2026, 10, 29), client) == []
    assert [call.request.url.params['q'] for call in search.calls] == [
        'topic:single-cell fork:false archived:false', 'topic:genomics fork:false archived:false',
    ]


@pytest.mark.parametrize('cached', [False, True])
def test_forked_search_result_is_skipped(cached, source_config, fixture_json, respx_mock):
    cfg = source_config['github']
    cfg.update(watchlist=[], topics=['single-cell'])
    repo = dict(fixture_json('github.json'), fork=True, pushed_at='2026-10-29T12:00:00Z')
    adapter = GithubAdapter(source_config)
    if cached:
        adapter.repo_cache = {'refreshed': '2026-10-29', 'repos': {repo['full_name']: repo}}
    else:
        respx_mock.get(f"{cfg['endpoint']}/search/repositories").respond(json={'total_count': 1, 'items': [repo]})
    with httpx.Client() as client:
        assert adapter.fetch(date(2026, 10, 29), date(2026, 10, 29), client) == []
    assert adapter.observations == {}


def test_collapse_duplicates_keeps_highest_star_variant():
    repos = [dict(name=name, description=description, stargazers_count=stars) for name, description, stars in [
        ('TxGNN', 'Drug discovery!', 100),
        ('TxGNN-korea', ' DRUG discovery. ', 300),
        ('txgnn_de', 'Drug-discovery', 200),
    ]]
    assert collapse_duplicates(repos) == [repos[1]]
    assert [repo['stargazers_count'] for repo in repos] == [100, 300, 200]


@pytest.mark.parametrize('name,description,stars,collapsed', [
    ('koreaTxGNN', 'Drug discovery!', 100, True),
    ('unrelated', 'Drug discovery!', 49, True),
    ('unrelated', 'Drug discovery!', 50, False),
    ('unrelated', 'DRUG DISCOVERY', 49, False),
    ('TxGNN-de', 'Different work', 49, False),
    ('TxGNN-de', None, 49, False),
    ('TxGNN-de', '', 49, False),
])
def test_collapse_duplicates_boundaries(name, description, stars, collapsed):
    original = dict(name='TxGNN', description='Drug discovery!', stargazers_count=300)
    candidate = dict(name=name, description=description, stargazers_count=stars)
    assert collapse_duplicates([candidate, original]) == ([original] if collapsed else [original, candidate])
    assert len(collapse_duplicates([dict(original, description=None), dict(candidate, description='')])) == 2


@pytest.mark.parametrize('stars,expected', [(19, []), (20, ['scverse/scanpy'])])
def test_discovery_minimum_stars(stars, expected, source_config, fixture_json, respx_mock):
    cfg = source_config['github']
    cfg.update(watchlist=[], topics=['single-cell'])
    repo = dict(fixture_json('github.json'), stargazers_count=stars)
    respx_mock.get(f"{cfg['endpoint']}/search/repositories").respond(json={'total_count': 1, 'items': [repo]})
    with httpx.Client() as client:
        assert GithubAdapter(source_config).repos(date(2026, 10, 29), client) == expected


def test_watchlist_bypasses_discovery_filters(source_config, fixture_json, respx_mock, caplog):
    caplog.set_level('INFO')
    cfg = source_config['github']
    cfg.update(watchlist=['scverse/scanpy'], topics=['single-cell'])
    repo = dict(fixture_json('github.json'), fork=True, stargazers_count=1, pushed_at='2026-10-29T12:00:00Z')
    discovered = [dict(repo, fork=False, name=name, full_name=f'other/{name}', stargazers_count=stars)
                  for name, stars in [('scanpy', 100), ('scanpy-de', 200)]]
    respx_mock.get(f"{cfg['endpoint']}/search/repositories").respond(json={'total_count': 3, 'items': [repo, *discovered]})
    respx_mock.get(f"{cfg['endpoint']}/repos/scverse/scanpy").respond(json=repo)
    for name in ['scverse/scanpy', 'other/scanpy-de']:
        respx_mock.get(f"{cfg['endpoint']}/repos/{name}/releases").respond(json=fixture_json('github_releases.json'))
    with httpx.Client() as client:
        items = GithubAdapter(source_config).fetch(date(2026, 10, 29), date(2026, 10, 29), client)
    assert [item.id for item in items] == ['github:scverse/scanpy', 'github:other/scanpy-de']
    assert 'github: collected 2 items collapsed=1' in caplog.text


@pytest.mark.parametrize('status', [200, 403, 429])
@pytest.mark.parametrize('stop_at', ['metadata', 'page'])
def test_github_history_stops_when_rate_limit_low(status, stop_at, caplog):
    from pipeline.sources.github import seed_star_history

    paths = []

    def respond(request):
        path = request.url.path
        paths.append(str(request.url))
        assert 'org/skipped' not in path
        if '/org/partial' in path and (
            stop_at == 'metadata' or request.url.params.get('page') == '2'
        ):
            return httpx.Response(status, json=[], headers={'X-RateLimit-Remaining': '199'})
        if path.endswith('/stargazers'):
            headers = {'X-RateLimit-Remaining': '200'}
            if '/org/partial' in path:
                headers['Link'] = f'<{request.url.copy_set_param("page", "2")}>; rel="next"'
            return httpx.Response(200, json=[{'starred_at': '2026-10-01T12:00:00Z'}], headers=headers)
        return httpx.Response(200, json={'stargazers_count': 2},
                              headers={'X-RateLimit-Remaining': '200'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        hooks = client.event_hooks['response'][:]
        histories = seed_star_history(['org/complete', 'org/partial', 'org/skipped'], client)
        assert client.event_hooks['response'] == hooks
    assert histories == {'org/complete': [(date(2026, 10, 1), 1)]}
    assert len(paths) == (3 if stop_at == 'metadata' else 5)
    assert 'stage=github_history event=stopped remaining=199' in caplog.text
    if status != 200:
        assert f'repo=org/partial status={status}' in caplog.text


@pytest.mark.parametrize('interruption', [200, 400])
def test_github_history_unavailable_count_resets(interruption, caplog):
    from pipeline.sources.github import seed_star_history

    statuses = iter([403, 403, interruption, 403, 403, 403])
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/stargazers'):
            return httpx.Response(next(statuses), json=[{'starred_at': '2026-10-01T12:00:00Z'}])
        return httpx.Response(200, json={'stargazers_count': 1})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        histories = seed_star_history([f'org/{i}' for i in range(7)], client)
    assert paths == [path for i in range(6) for path in (f'/repos/org/{i}', f'/repos/org/{i}/stargazers')]
    assert histories == ({'org/2': [(date(2026, 10, 1), 1)]} if interruption == 200 else {})
    warnings = [record.getMessage() for record in caplog.records if record.levelname == 'WARNING']
    assert len(warnings) == (1 if interruption == 200 else 2)
    assert warnings[-1] == 'stage=github_history event=stopped reason=endpoint_unavailable status=403'
