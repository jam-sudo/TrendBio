"""World Bank Policy Research Working Papers from the Open Knowledge Repository."""
from datetime import date
import re

from pipeline.models import Item, Source
from pipeline.sources.base import collected, request
from pipeline.sources.crossref import plain_text


class WorldBankAdapter:
    name: Source = 'worldbank'

    def __init__(self, config):
        self.series = config[self.name]['collection']

    def fetch(self, start, end, client):
        endpoint = 'https://openknowledge.worldbank.org/server/api/discover/search/objects'
        params = {'scope': self.series, 'f.dateIssued': f'[{start} TO {end}],equals',
                  'sort': 'dc.date.issued,DESC', 'size': 100, 'page': 0}
        seen, items = set(), {}
        while True:
            page = request(client, endpoint, params=params).json()['_embedded']['searchResult']
            count = len(seen)
            for hit in page.get('_embedded', {}).get('objects', []):
                entry = hit['_embedded']['indexableObject']
                seen.add(entry['uuid'])
                fields = {key: [v['value'].strip() for v in values if v.get('value')]
                          for key, values in entry.get('metadata', {}).items()}
                number = fields.get('okr.identifier.report', [])
                if len(number) != 1 or not re.fullmatch(r'WPS\d+', number[0]):
                    continue
                code = number[0]
                dois = fields.get('okr.identifier.doi', [])
                days = fields.get('dc.date.issued', [])
                rights = {r.rstrip('/').replace('http://', 'https://') for r in fields.get('dc.rights.uri', [])}
                if (len(dois) != 1 or not re.fullmatch(r'10\.1596/[A-Za-z0-9._/-]+', dois[0])
                        or (dois[0].startswith('10.1596/1813-9450-') and not dois[0].endswith('-' + code[3:]))
                        or len(rights) != 1
                        or not rights <= {'https://creativecommons.org/licenses/by/3.0/igo', 'https://creativecommons.org/licenses/by/4.0'}
                        or fields.get('dc.type') != ['Working Paper'] or len(days) != 1
                        or not re.fullmatch(r'\d{4}-\d\d-\d\d', days[0])):
                    continue
                issued = date.fromisoformat(days[0])
                abstracts, authors = fields.get('dc.description.abstract', []), fields.get('dc.contributor.author', [])
                title = plain_text(entry.get('name'))
                if not (start <= issued <= end and title and authors and len(abstracts) == 1):
                    continue
                if code in items and items[code].doi != dois[0]:
                    raise ValueError(f'Conflicting repository records for {code}')
                if code in items:
                    continue
                items[code] = Item(id='worldbank:' + code, source=self.name, type='preprint', title=title,
                                   url='https://doi.org/' + dois[0], doi=dois[0], abstract=plain_text(abstracts[0]),
                                   authors=authors, published_at=issued, first_seen=end, org=None, summary=None,
                                   primary_category=None, published_doi=None, preprint_id=None,
                                   metadata={'journal': 'World Bank Policy Research Working Papers', 'report': code,
                                             'license': rights.pop() + '/', 'countries': fields.get('okr.region.country', [])})
            if len(seen) == page['page']['totalElements']:
                break
            if len(seen) == count or params['page'] + 1 >= page['page']['totalPages']:
                raise ValueError('Incomplete World Bank repository response')
            params['page'] += 1
        return collected(self.name, list(items.values()))
