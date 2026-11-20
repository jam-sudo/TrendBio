from datetime import date, timedelta
from fnmatch import fnmatchcase
import logging
import re
import time
import xml.etree.ElementTree as ET

import httpx

from pipeline.models import Item, Source
from pipeline.sources.base import collected, load_config, matches_keywords, request

NS = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom',
      'opensearch': 'http://a9.com/-/spec/opensearch/1.1/'}
logger = logging.getLogger(__name__)


def submission_comment(item: Item) -> str:
    """Read the author’s note from the same arXiv record that supplied the paper."""
    xml = item.metadata.get('xml')
    if item.source != 'arxiv' or not isinstance(xml, str):
        return ''
    try:
        entry = ET.fromstring(xml)
    except ET.ParseError:
        return ''
    version = item.url.partition('/abs/')[2]
    if not version or entry.findtext('atom:id', '', NS).partition('/abs/')[2] != version:
        return ''
    return ' '.join(entry.findtext('arxiv:comment', '', NS).split())


class ArxivAdapter:
    name: Source = 'arxiv'

    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else load_config()

    def _item(self, entry, seen: date, window: tuple[date, date] | None = None) -> Item | None:
        cfg = self.config['arxiv']
        title = entry.findtext('atom:title', '', NS)
        abstract = entry.findtext('atom:summary', '', NS)
        tags = [tag.attrib['term'] for tag in entry.findall('atom:category', NS)]
        unfiltered = any(fnmatchcase(tag, pattern) for tag in tags for pattern in cfg['categories'])
        filtered = any(tag in cfg['keyword_filtered'] for tag in tags)
        if not unfiltered and not (filtered and matches_keywords(title + ' ' + abstract, self.config['keywords'])):
            return None
        submitted = date.fromisoformat(entry.findtext('atom:published', namespaces=NS)[:10])
        if window and not window[0] <= submitted <= window[1]:
            return None
        url = entry.findtext('atom:id', namespaces=NS)
        native_id = re.sub(r'v\d+$', '', url.split('/abs/')[-1])
        return Item(
            id=f'arxiv:{native_id}', source=self.name, type='preprint', title=' '.join(title.split()), url=url,
            doi=entry.findtext('arxiv:doi', namespaces=NS), published_at=submitted,
            first_seen=seen, authors=[a.text for a in entry.findall('atom:author/atom:name', NS)], org=None,
            abstract=abstract, summary=None, primary_category=None, published_doi=None, preprint_id=None,
            metadata={'arxiv_primary_category': entry.find('arxiv:primary_category', NS).attrib['term'],
                      'categories': tags, 'xml': ET.tostring(entry, encoding='unicode')},
        )

    def fetch(self, start: date, end: date, client: httpx.Client) -> list[Item]:
        daily_page_size = self.config['arxiv'].get('daily_page_size')
        if daily_page_size is not None:
            if daily_page_size < 1:
                raise ValueError('arxiv.daily_page_size must be positive')
            items = []
            day = start
            while day <= end:
                if day != start:
                    time.sleep(3)
                items.extend(self._fetch_range(day, day, end, client))
                day += timedelta(days=1)
            return collected(self.name, items)
        return collected(self.name, self._fetch_range(start, end, end, client))

    def _fetch_range(self, start: date, end: date, seen: date, client: httpx.Client) -> list[Item]:
        cfg = self.config['arxiv']
        categories = ' OR '.join(f'cat:{c}' for c in cfg['categories'])
        filtered = ' OR '.join(f'cat:{c}' for c in cfg['keyword_filtered'])
        terms = self.config['keywords'][:cfg.get('query_keywords_max', 25)]
        keywords = ' OR '.join('abs:"' + term.replace('"', r'\"') + '"' for term in terms)
        clauses = [f'({categories})'] if categories else []
        if filtered and keywords:
            clauses.append(f'(({filtered}) AND ({keywords}))')
        if not clauses:
            return []
        query = f'({" OR ".join(clauses)}) AND submittedDate:[{start:%Y%m%d}0000 TO {end:%Y%m%d}2359]'
        cap = cfg.get('max_results_per_query', 2000)
        if cap < 1:
            raise ValueError('arxiv.max_results_per_query must be positive')
        items, offset = [], 0
        complete = cfg.get('require_complete', False)
        record_ids = set()
        while True:
            if offset:
                time.sleep(3)  # arXiv asks clients to leave three seconds between calls.
            max_results = min(cfg.get('daily_page_size', 100), cap - offset)
            logger.info('source=arxiv chunk=%s..%s offset=%d max_results=%d', start, end, offset, max_results)
            response = request(client, cfg['endpoint'], attempts=5, backoff=5.0, params={
                'search_query': query, 'start': offset, 'max_results': max_results,
                'sortBy': 'submittedDate', 'sortOrder': 'ascending',
            })
            feed = ET.fromstring(response.content)
            total = feed.findtext('opensearch:totalResults', namespaces=NS)
            if total is None:
                raise ValueError('Invalid arXiv feed')
            total = int(total)
            if complete and total > cap:
                if start == end:
                    raise ValueError(f'arXiv reported {total} records for {start}, above the {cap} record limit')
                middle = start + timedelta(days=(end - start).days // 2)
                time.sleep(3)
                earlier = self._fetch_range(start, middle, seen, client)
                time.sleep(3)
                return earlier + self._fetch_range(middle + timedelta(days=1), end, seen, client)
            entries = feed.findall('atom:entry', NS)
            for entry in entries:
                if complete:
                    identifier = entry.findtext('atom:id', '', NS)
                    if not identifier or '/abs/' not in identifier:
                        raise ValueError('arXiv returned an invalid record identifier')
                    record_ids.add(re.sub(r'v\d+$', '', identifier.split('/abs/')[-1]))
                item = self._item(entry, seen, (start, end))
                if item:
                    items.append(item)
            offset += len(entries)
            if offset >= total or len(entries) < max_results:
                if complete and len(record_ids) != total:
                    raise ValueError(f'Incomplete arXiv window {start}..{end}: {len(record_ids)} of {total} unique IDs')
                break
            if offset >= cap:
                logger.warning('source=arxiv event=query_truncated chunk=%s..%s offset=%d cap=%d total=%s',
                               start, end, offset, cap, total)
                break
        return items
