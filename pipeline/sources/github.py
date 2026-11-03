from collections import Counter
from datetime import date, timedelta
import logging
import os
import re

import httpx

from pipeline.config import load_scoring
from pipeline.models import Item, Source
from pipeline.sources.base import load_config, request
from pipeline.store import Store

logger = logging.getLogger(__name__)


def collapse_duplicates(repos: list[dict]) -> list[dict]:
    """Keep the most-starred copy of a described repository family."""
    kept = []
    descriptions = {}
    for repo in sorted(repos, key=lambda repo: repo['stargazers_count'], reverse=True):
        description = ''.join(char for char in (repo.get('description') or '').casefold() if char.isalnum())
        name = repo['name'].casefold()
        variants = descriptions.setdefault(description, [])
        duplicate = False
        for other in variants if description else []:
            other_name = other['name'].casefold()
            related = (name.startswith(other_name) or name.endswith(other_name)
                       or other_name.startswith(name) or other_name.endswith(name)
                       or bool(set(re.split(r'[-_.]+', name)) & set(re.split(r'[-_.]+', other_name))))
            if related or (repo['description'] == other['description'] and repo['stargazers_count'] < 50):
                duplicate = True
                break
        if not duplicate:
            kept.append(repo)
            variants.append(repo)
    return kept


def _headers(accept: str = 'application/vnd.github+json') -> dict[str, str]:
    headers = {'Accept': accept, 'X-GitHub-Api-Version': '2022-11-28'}
    if os.environ.get('GITHUB_TOKEN'):
        headers['Authorization'] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return headers


def fetch_star_counts(repos: list[str], client: httpx.Client) -> dict[str, int]:
    endpoint = load_config()['github']['endpoint']
    counts = {repo: request(client, f'{endpoint}/repos/{repo}', headers=_headers()).json()['stargazers_count']
              for repo in dict.fromkeys(repos)}
    logger.info('github: fetched star counts for %d repos', len(counts))
    return counts


def fetch_star_history(repo: str, client: httpx.Client, max_stars: int = 40_000) -> list[tuple[date, int]]:
    """Daily cumulative surviving stars, through the last recorded star date."""
    endpoint = load_config()['github']['endpoint']
    data = request(client, f'{endpoint}/repos/{repo}', headers=_headers()).json()
    if data['stargazers_count'] >= max_stars:
        logger.info('github: skipped star history at cutoff')
        return []
    by_day = Counter()
    url = f'{endpoint}/repos/{repo}/stargazers?per_page=100'
    while url:
        response = request(client, url, headers=_headers('application/vnd.github.star+json'))
        for star in response.json():
            by_day[date.fromisoformat(star['starred_at'][:10])] += 1
        url = response.links.get('next', {}).get('url')
    result, total = [], 0
    if by_day:
        day, last = min(by_day), max(by_day)
        while day <= last:
            total += by_day[day]
            result.append((day, total))
            day += timedelta(days=1)
    logger.info('github: reconstructed %d days of stars', len(result))
    return result


class _HistoryRateLimit(Exception):
    def __init__(self, response: httpx.Response):
        self.response = response
        super().__init__('GitHub history rate limit reserve reached')


def seed_star_history(repos: list[str], client: httpx.Client) -> dict[str, list[tuple[date, int]]]:
    """Best-effort seeding; discard incomplete histories and reserve API capacity."""
    histories = {}
    remaining = None
    unavailable = 0

    def check_rate_limit(response):
        nonlocal remaining
        header = response.headers.get('X-RateLimit-Remaining')
        if header is not None:
            remaining = int(header)
            if remaining < 200:
                raise _HistoryRateLimit(response)

    client.event_hooks['response'].append(check_rate_limit)
    try:
        for repo in repos:
            try:
                history = fetch_star_history(repo, client)
                unavailable = 0
                if history:
                    histories[repo] = history
            except Exception as error:
                response = getattr(error, 'response', None)
                if isinstance(error, httpx.HTTPStatusError) and response.status_code in (401, 403, 404):
                    unavailable += 1
                    if unavailable == 3:
                        logger.warning('stage=github_history event=stopped reason=endpoint_unavailable status=%s',
                                       response.status_code)
                        break
                    logger.debug('stage=github_history event=failed repo=%s status=%s', repo, response.status_code)
                elif not isinstance(error, _HistoryRateLimit) or response.is_error:
                    unavailable = 0
                    logger.warning('stage=github_history event=failed repo=%s status=%s error=%s',
                                   repo, response.status_code if response is not None else 'unknown',
                                   type(error).__name__)
            if remaining is not None and remaining < 200:
                logger.warning('stage=github_history event=stopped remaining=%d', remaining)
                break
    finally:
        client.event_hooks['response'].remove(check_rate_limit)
    return histories


class GithubAdapter:
    name: Source = 'github'

    def __init__(self, config: dict | None = None, *, star_counts: dict[str, list[tuple[date, int]]] | None = None,
                 star_gain_threshold: int | None = None, store: Store | None = None):
        self.config = config if config is not None else load_config()
        self.star_counts = star_counts if star_counts is not None else {}
        self.star_gain_threshold = load_scoring().star_gain_threshold if star_gain_threshold is None else star_gain_threshold
        self.store = store
        self.repo_cache = {}
        self.observations: dict[str, int] = {}
        self.rest_calls = 0
        self.collapsed = 0

    def repos(self, day: date, client: httpx.Client) -> list[str]:
        cfg = self.config['github']
        cache = self.store.github_repos() if self.store is not None else self.repo_cache
        refreshed = date.fromisoformat(cache['refreshed']) if cache else None
        if refreshed is None or not 0 <= (day - refreshed).days < 7:
            records_by_name = {}
            limit = cfg['top_n_per_topic']
            if not 0 <= limit <= 1000:
                raise ValueError('GitHub topic limit must be between 0 and 1000')
            for topic in cfg['topics']:
                found, page = 0, 1
                while found < limit:
                    data = request(client, f"{cfg['endpoint']}/search/repositories", headers=_headers(), params={
                        'q': f'topic:{topic} fork:false archived:false', 'sort': 'updated', 'order': 'desc',
                        'per_page': min(100, limit), 'page': page,
                    }).json()
                    if data.get('incomplete_results'):
                        raise ValueError('GitHub repository search is incomplete')
                    records = data['items'][:limit - found]
                    records_by_name.update((record['full_name'], record) for record in records)
                    found += len(records)
                    if not records or found >= min(data['total_count'], limit):
                        break
                    page += 1
            cache = {'refreshed': day.isoformat(), 'repos': records_by_name}
        discovered = [record for record in cache['repos'].values()
                      if record['full_name'] not in cfg['watchlist'] and not record.get('fork')
                      and record['stargazers_count'] >= cfg.get('min_stars_for_discovery', 20)]
        kept = collapse_duplicates(discovered)
        self.collapsed = len(discovered) - len(kept)
        cache = {**cache, 'repos': {record['full_name']: record for record in kept}}
        if self.store is not None:
            self.store.put_github_repos(cache)
        self.repo_cache = cache
        return list(dict.fromkeys(cfg['watchlist'] + list(cache['repos'])))

    def fetch(self, start: date, end: date, client: httpx.Client) -> list[Item]:
        self.rest_calls = 0
        self.observations = {}

        def count_call(request):
            self.rest_calls += 1

        client.event_hooks['request'].append(count_call)
        try:
            return self._fetch(start, end, client)
        finally:
            client.event_hooks['request'].remove(count_call)
            logger.info('github: rest_calls=%d', self.rest_calls)

    def _fetch(self, start: date, end: date, client: httpx.Client) -> list[Item]:
        endpoint = self.config['github']['endpoint']
        items = []
        for repo in self.repos(end, client):
            if repo in self.config['github']['watchlist']:
                data = request(client, f'{endpoint}/repos/{repo}', headers=_headers()).json()
            else:
                # shortcut: topic metadata is weekly; add bulk refresh if daily topic star precision is needed.
                data = self.repo_cache['repos'][repo]
            self.observations[repo] = data['stargazers_count']
            history = dict(self.star_counts.get(repo, []))
            if end == date.today():
                history[end] = data['stargazers_count']
            gains = {day: max(0, count - history[day - timedelta(days=7)])
                     for day, count in history.items()
                     if start <= day <= end and day - timedelta(days=7) in history}
            gain = max(gains.values(), default=0)
            releases = []
            pushed = data.get('pushed_at')
            if pushed and start <= date.fromisoformat(pushed[:10]) <= end:
                # Reuse release pages for unchanged discovery snapshots between weekly refreshes.
                if repo in self.config['github']['watchlist'] or data.get('_release_pushed_at') != pushed:
                    response = request(client, f'{endpoint}/repos/{repo}/releases',
                                       headers=_headers(), params={'per_page': 100})
                    release_page = response.json()
                else:
                    release_page = data['_releases']
                for release in release_page:
                    if release.get('draft') or not release.get('published_at'):
                        continue
                    if start <= date.fromisoformat(release['published_at'][:10]) <= end:
                        releases.append(release)
                # Daily windows move forward; historical release bodies need not bloat the cache.
                data['_releases'] = releases
                data['_release_pushed_at'] = pushed
            if gain < self.star_gain_threshold and not releases:
                continue
            event_days = [day for day, value in gains.items() if value >= self.star_gain_threshold]
            event_days.extend(date.fromisoformat(release['published_at'][:10]) for release in releases)
            published_at = min(event_days)
            items.append(Item(
                id=f'github:{repo}', source=self.name, type='code', title=repo, url=data['html_url'],
                doi=None, published_at=published_at, first_seen=end, authors=[],
                org=data['owner']['login'], abstract=data.get('description') or '',
                summary=None, primary_category=None, published_doi=None, preprint_id=None,
                metadata={**{key: value for key, value in data.items() if not key.startswith('_')},
                          'github_topics': data.get('topics', []), 'star_gain_7d': gain, 'releases': releases},
            ))
        if self.store is not None:
            self.store.put_github_repos(self.repo_cache)
        logger.info('github: collected %d items collapsed=%d', len(items), self.collapsed)
        return items
