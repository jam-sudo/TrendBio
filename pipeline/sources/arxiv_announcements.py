"""Read the dated Physics mailing and retrieve first-version metadata from arXiv."""
from collections import Counter
from datetime import date, timedelta
from html.parser import HTMLParser
from itertools import batched
import re
import time
import xml.etree.ElementTree as ET

import httpx

from pipeline.models import Item
from pipeline.sources.arxiv import ArxivAdapter, NS
from pipeline.sources.base import collected, request


class _Mailing(HTMLParser):
    def __init__(self, day):
        super().__init__()
        self.day_label = day.strftime('%a, %d %b %Y')
        self.total = None
        self.sections = {}
        self.rows = {}
        self.heading = self.in_entry = self.title = self.correct_title = False
        self.section = None

    def handle_starttag(self, tag, attrs):
        if tag == 'h1':
            self.title = True
        elif tag == 'h3':
            self.heading, self.section = True, None
        elif tag == 'dt':
            self.in_entry = True
        elif tag == 'a' and self.in_entry:
            attrs = dict(attrs)
            if attrs.get('title') == 'Abstract':
                key = attrs.get('id', '')
                if (self.section is None or key in self.rows or attrs.get('href') != '/abs/' + key
                        or not re.fullmatch(r'(?:[a-z][\w.-]*/\d{7}|\d{4}\.\d{4,5})', key)):
                    raise ValueError('Invalid or duplicate arXiv mailing entry')
                self.rows[key] = self.section

    def handle_endtag(self, tag):
        if tag == 'h1':
            self.title = False
        elif tag == 'h3':
            self.heading = False
        elif tag == 'dt':
            self.in_entry = False
        elif tag == 'dl':
            self.section = None

    def handle_data(self, data):
        text = data.strip()
        if self.title and text == 'Catchup results for Physics on ' + self.day_label:
            self.correct_title = True
        if self.heading:
            label = re.fullmatch(r'(New|Cross|Replacement) submissions \(showing .+ of (\d+) entr(?:y|ies)\)', text)
            if label:
                self.section = label[1].lower()
                self.sections[self.section] = int(label[2])
        total = re.match(r'Total of (\d+) entries for ' + re.escape(self.day_label) + r'(?:\s|$)', text)
        if total:
            if self.total not in (None, int(total[1])):
                raise ValueError('Inconsistent arXiv mailing total')
            self.total = int(total[1])


class PhysicsAnnouncements(ArxivAdapter):
    def _get(self, client, url, **params):
        time.sleep(3)
        return request(client, url, attempts=5, backoff=5.0, params=params)

    def _listing(self, client, day):
        url = f'https://arxiv.org/catchup/grp_physics/{day}'
        rows, sections, total, page = {}, {}, None, 1
        while total is None or len(rows) < total:
            result = _Mailing(day)
            try:
                response = self._get(client, url, page=page)
            except httpx.HTTPStatusError as exc:
                limit = re.search(r'Catchup only allowed for past (\d+) days', exc.response.text)
                if exc.response.status_code == 400 and limit:
                    raise ValueError(f'arXiv retains {limit[1]} days of Physics mailings. {day} is outside the archive. '
                                     'Choose a recent window or replay a saved edition.') from exc
                raise
            result.feed(response.text)
            result.close()
            if (not result.correct_title or result.total is None or total not in (None, result.total) or rows.keys() & result.rows.keys()
                    or (not result.rows and result.total)):
                raise ValueError(f'Incomplete or repeated arXiv mailing page for {day}')
            total = result.total
            for section, count in result.sections.items():
                if sections.setdefault(section, count) != count:
                    raise ValueError(f'Inconsistent arXiv mailing section for {day}')
            rows.update(result.rows)
            page += 1
        if len(rows) != total or Counter(rows.values()) != Counter(sections):
            raise ValueError(f'Incomplete arXiv mailing for {day}')
        return rows

    def fetch(self, start: date, end: date, client: httpx.Client) -> list[Item]:
        first, items = {}, []
        self.mailings = {}
        for offset in range((end - start).days + 1):
            day = start + timedelta(days=offset)
            rows = self._listing(client, day)
            counts = Counter(rows.values())
            self.mailings[str(day)] = {s: counts[s] for s in ('new', 'cross', 'replacement')}
            for key, section in rows.items():
                if section != 'replacement':
                    first.setdefault(key + 'v1', (day, section))

        for batch in batched(sorted(first), 100):
            feed = self._get(client, self.config['arxiv']['endpoint'], id_list=','.join(batch), max_results=len(batch))
            versions = set()
            for entry in ET.fromstring(feed.content).findall('atom:entry', NS):
                key = entry.findtext('atom:id', '', NS).partition('/abs/')[2]
                submitted = entry.findtext('atom:published', '', NS)
                if (key not in batch or key in versions or submitted != entry.findtext('atom:updated', '', NS)
                        or date.fromisoformat(submitted[:10]) > first[key][0]):
                    raise ValueError('arXiv returned an unexpected version or submission date')
                versions.add(key)
                item = self._item(entry, end)
                if item:
                    day, section = first[key]
                    item.metadata.update(arxiv_submitted=str(item.published_at), arxiv_listing=section)
                    items.append(item.model_copy(update={'published_at': day, 'url': f'https://arxiv.org/abs/{key}'}))
            if versions != set(batch):
                raise ValueError(f'Incomplete arXiv first-version response: {len(versions)} of {len(batch)}')
        return collected(self.name, items)
