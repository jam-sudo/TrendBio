from datetime import date
from fnmatch import fnmatchcase
import re
import time
import xml.etree.ElementTree as ET

import httpx

from pipeline.models import Item, Source
from pipeline.sources.base import collected, load_config, matches_keywords, request

NS = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom',
      'opensearch': 'http://a9.com/-/spec/opensearch/1.1/'}


class ArxivAdapter:
    name: Source = 'arxiv'

    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else load_config()

    def fetch(self, start: date, end: date, client: httpx.Client) -> list[Item]:
        cfg = self.config['arxiv']
        categories = ' OR '.join(f'cat:{c}' for c in cfg['categories'] + cfg['keyword_filtered'])
        query = f'({categories}) AND submittedDate:[{start:%Y%m%d}0000 TO {end:%Y%m%d}2359]'
        items, offset = [], 0
        while True:
            if offset:
                time.sleep(3)  # arXiv asks clients to leave three seconds between calls.
            response = request(client, cfg['endpoint'], params={
                'search_query': query, 'start': offset, 'max_results': 100,
                'sortBy': 'submittedDate', 'sortOrder': 'ascending',
            })
            feed = ET.fromstring(response.content)
            total = feed.findtext('opensearch:totalResults', namespaces=NS)
            if total is None:
                raise ValueError('Invalid arXiv feed')
            entries = feed.findall('atom:entry', NS)
            for entry in entries:
                title = entry.findtext('atom:title', '', NS)
                abstract = entry.findtext('atom:summary', '', NS)
                tags = [tag.attrib['term'] for tag in entry.findall('atom:category', NS)]
                unfiltered = any(fnmatchcase(tag, pattern) for tag in tags for pattern in cfg['categories'])
                filtered = any(tag in cfg['keyword_filtered'] for tag in tags)
                if not unfiltered and not (filtered and matches_keywords(title + ' ' + abstract, self.config['keywords'])):
                    continue
                published_at = date.fromisoformat(entry.findtext('atom:published', namespaces=NS)[:10])
                if not start <= published_at <= end:
                    continue
                url = entry.findtext('atom:id', namespaces=NS)
                native_id = re.sub(r'v\d+$', '', url.split('/abs/')[-1])
                items.append(Item(
                    id=f'arxiv:{native_id}', source=self.name, type='preprint',
                    title=' '.join(title.split()), url=url,
                    doi=entry.findtext('arxiv:doi', namespaces=NS), published_at=published_at, first_seen=end,
                    authors=[a.text for a in entry.findall('atom:author/atom:name', NS)], org=None,
                    abstract=abstract, summary=None, primary_category=None, published_doi=None, preprint_id=None,
                    metadata={'arxiv_primary_category': entry.find('arxiv:primary_category', NS).attrib['term'],
                              'categories': tags, 'xml': ET.tostring(entry, encoding='unicode')},
                ))
            offset += len(entries)
            if offset >= int(total):
                break
            if not entries:
                raise ValueError('arXiv pagination ended before total')
        return collected(self.name, items)
