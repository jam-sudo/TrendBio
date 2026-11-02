from datetime import date
import logging
import re

import httpx

from pipeline.models import Item, Source
from pipeline.sources.base import collected, load_config, matches_keywords, request


logger = logging.getLogger(__name__)


class BiorxivAdapter:
    name: Source = 'biorxiv'

    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else load_config()
        self.dropped_revisions: int = 0

    def fetch(self, start: date, end: date, client: httpx.Client) -> list[Item]:
        self.dropped_revisions = 0
        cfg = self.config['biorxiv']
        categories = {category.casefold() for category in cfg['categories']}
        filtered = {category.casefold() for category in cfg['keyword_filtered_categories']}
        items, cursor = [], 0
        while True:
            data = request(client, f"{cfg['endpoint']}/{start}/{end}/{cursor}").json()
            message = data['messages'][0]
            if message.get('status') == 'no posts found':
                break
            if message.get('status') != 'ok':
                raise ValueError('bioRxiv API failed')
            records = data['collection']
            for record in records:
                category = record['category'].casefold()
                version = int(record.get('version') or 1)
                if version > 1:
                    match = re.search(r'/(\d{4})\.(\d{2})\.(\d{2})\.\d+', record['doi'])
                    try:
                        published_at = date(*map(int, match.groups())) if match else None
                    except ValueError:
                        published_at = None
                    if published_at is None or not start <= published_at <= end:
                        self.dropped_revisions += 1
                        continue
                else:
                    published_at = date.fromisoformat(record['date'])
                if category not in categories or not start <= published_at <= end:
                    continue
                if category in filtered and not matches_keywords(
                    record['title'] + ' ' + record['abstract'], self.config['keywords']
                ):
                    continue
                published = record.get('published', '')
                published = re.sub(r'^https?://(?:dx\.)?doi.org/', '', published).strip()
                items.append(Item(
                    id=f"biorxiv:{record['doi']}", source=self.name, type='preprint',
                    title=record['title'], url=f"https://doi.org/{record['doi']}",
                    doi=record['doi'], published_at=published_at, first_seen=end,
                    authors=[name.strip() for name in record['authors'].split(';') if name.strip()],
                    org=record.get('author_corresponding_institution'), abstract=record['abstract'],
                    summary=None, primary_category=None, preprint_id=None,
                    published_doi=published if re.fullmatch(r'10\.\d{4,9}/\S+', published) else None,
                    metadata={**record, 'biorxiv_category': category},
                ))
            cursor += len(records)
            if cursor >= int(message['total']):
                break
            if not records:
                raise ValueError('bioRxiv pagination ended before total')
        logger.info('biorxiv: dropped %d revisions first posted outside the window', self.dropped_revisions)
        return collected(self.name, items)
