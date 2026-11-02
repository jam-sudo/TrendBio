from calendar import timegm
from datetime import date, datetime, timezone
from hashlib import sha256

import feedparser
import httpx

from pipeline.models import Item, Source
from pipeline.sources.base import collected, load_config, matches_keywords, request


class RssAdapter:
    name: Source = 'rss'

    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else load_config()

    def fetch(self, start: date, end: date, client: httpx.Client) -> list[Item]:
        items = []
        for spec in self.config['rss']['feeds']:
            response = request(client, spec['url'])
            feed = feedparser.parse(response.content)
            if not feed.version:
                raise ValueError('Invalid RSS/Atom feed')
            for entry in feed.entries:
                abstract = entry.get('summary') or '\n'.join(c['value'] for c in entry.get('content', []))
                if not matches_keywords(entry.get('title', '') + ' ' + abstract, self.config['keywords']):
                    continue
                parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                if parsed is None or not entry.get('link'):
                    continue
                published_at = datetime.fromtimestamp(timegm(parsed), tz=timezone.utc).date()
                if not start <= published_at <= end:
                    continue
                native_id = entry.get('id') or sha256(entry.link.encode()).hexdigest()
                items.append(Item(
                    id=f'rss:{native_id}', source=self.name, type='industry',
                    title=entry.get('title', ''), url=entry.link, doi=None,
                    published_at=published_at, first_seen=end,
                    authors=[a['name'] for a in entry.get('authors', []) if a.get('name')],
                    org=spec['name'], abstract=abstract, summary=None, primary_category=None,
                    published_doi=None, preprint_id=None,
                    metadata={**entry, 'feed_name': spec['name'], 'feed_kind': spec['kind'], 'feed_url': spec['url']},
                ))
        return collected(self.name, items)
