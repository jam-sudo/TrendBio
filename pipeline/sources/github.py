from collections import Counter
from datetime import date, timedelta
import logging
import os

import httpx

from pipeline.config import load_scoring
from pipeline.models import Item, Source
from pipeline.sources.base import collected, load_config, request

logger = logging.getLogger(__name__)


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


class GithubAdapter:
    name: Source = 'github'

    def __init__(self, config: dict | None = None, *, star_counts: dict[str, list[tuple[date, int]]] | None = None,
                 star_gain_threshold: int | None = None):
        self.config = config if config is not None else load_config()
        self.star_counts = star_counts if star_counts is not None else {}
        self.star_gain_threshold = load_scoring().star_gain_threshold if star_gain_threshold is None else star_gain_threshold
        self.topic_repos: list[str] = []
        self.topics_refreshed: date | None = None

    def repos(self, day: date, client: httpx.Client) -> list[str]:
        cfg = self.config['github']
        # shortcut: discovery cache is per instance; persist it when the runner owns cross-run state.
        if self.topics_refreshed is None or abs((day - self.topics_refreshed).days) >= 7:
            names = []
            limit = cfg['top_n_per_topic']
            if not 0 <= limit <= 1000:
                raise ValueError('GitHub topic limit must be between 0 and 1000')
            for topic in cfg['topics']:
                found, page = 0, 1
                while found < limit:
                    data = request(client, f"{cfg['endpoint']}/search/repositories", headers=_headers(), params={
                        'q': f'topic:{topic} archived:false', 'sort': 'updated', 'order': 'desc',
                        'per_page': min(100, limit), 'page': page,
                    }).json()
                    if data.get('incomplete_results'):
                        raise ValueError('GitHub repository search is incomplete')
                    records = data['items'][:limit - found]
                    names.extend(record['full_name'] for record in records)
                    found += len(records)
                    if not records or found >= min(data['total_count'], limit):
                        break
                    page += 1
            self.topic_repos, self.topics_refreshed = names, day
        return list(dict.fromkeys(cfg['watchlist'] + self.topic_repos))

    def fetch(self, start: date, end: date, client: httpx.Client) -> list[Item]:
        endpoint = self.config['github']['endpoint']
        items = []
        for repo in self.repos(end, client):
            data = request(client, f'{endpoint}/repos/{repo}', headers=_headers()).json()
            history = dict(self.star_counts.get(repo, []))
            if end == date.today():
                history[end] = data['stargazers_count']
            gains = {day: max(0, count - history[day - timedelta(days=7)])
                     for day, count in history.items()
                     if start <= day <= end and day - timedelta(days=7) in history}
            gain = max(gains.values(), default=0)
            releases, url = [], f'{endpoint}/repos/{repo}/releases?per_page=100'
            while url:
                response = request(client, url, headers=_headers())
                for release in response.json():
                    if release.get('draft') or not release.get('published_at'):
                        continue
                    if start <= date.fromisoformat(release['published_at'][:10]) <= end:
                        releases.append(release)
                url = response.links.get('next', {}).get('url')
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
                metadata={**data, 'github_topics': data.get('topics', []), 'star_gain_7d': gain, 'releases': releases},
            ))
        return collected(self.name, items)
