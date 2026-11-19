"""Publication-day intake for the open Earth journals in the pilot."""
from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import quote

import httpx

from pipeline.models import Item, Source
from pipeline.sources.base import collected, request


def crossref_works(client, endpoint, filters):
    # Crossref returns language on full records but does not support it in select.
    params = {'filter': filters, 'rows': 200, 'cursor': '*'}
    seen = set()
    while True:
        page = request(client, endpoint, params=params).json()['message']
        rows = page['items']
        count = len(seen)
        for work in rows:
            doi = work['DOI'].strip().lower()
            if doi not in seen:
                seen.add(doi)
                yield doi, work
        if not rows or len(rows) < params['rows']:
            if len(seen) < page['total-results']:
                raise ValueError(f'Incomplete Crossref response: {len(seen)} of {page["total-results"]} records')
            return
        if len(seen) == count:
            raise ValueError('Crossref cursor repeated a page')
        params['cursor'] = page['next-cursor']


def full_date(work, field):
    parts = (work.get(field, {}).get('date-parts') or [[]])[0]
    return date(*parts) if len(parts) == 3 else None


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag.split(':')[-1] in {'p', 'div', 'title'}:
            self.parts.append(' ')


def plain_text(fragment):
    parser = _Text()
    parser.feed(fragment or '')
    parser.close()
    return ' '.join(''.join(parser.parts).split())


def related_dois(work, relation):
    return sorted({r['id'].strip().lower().removeprefix('https://doi.org/') for r in work.get('relation', {}).get(relation, [])
                   if r.get('id-type') == 'doi' and r.get('id')})


def related_work_dois(work):
    return sorted({doi for rel in ('is-part-of', 'has-part', 'is-supplemented-by', 'is-supplement-to')
                   for doi in related_dois(work, rel)})


def datacite_type(client, doi):
    try:
        record = request(client, 'https://api.datacite.org/dois/' + quote(doi, safe='/'), attempts=2, timeout=8).json()['data']
        if record['id'].lower() != doi:
            return 'unverified'
        return record['attributes']['types']['resourceTypeGeneral']
    except httpx.HTTPStatusError as exc:
        return 'not-in-public-datacite' if exc.response.status_code == 404 else 'unverified'
    except (httpx.TransportError, KeyError, ValueError):
        return 'unverified'


class CrossrefAdapter:
    name: Source = 'crossref'

    def __init__(self, config):
        self.config = config

    def fetch(self, start, end, client):
        items = {}
        resource_types = {}
        filters = f'type:journal-article,from-pub-date:{start},until-pub-date:{end}'
        for issn in self.config[self.name]['journals']:
            endpoint = f'https://api.crossref.org/journals/{issn}/works'
            for doi, work in crossref_works(client, endpoint, filters):
                day = full_date(work, 'published')
                if day is None or not start <= day <= end or work.get('update-to'):
                    continue
                licence = next((lic['URL'] for lic in work.get('license', [])
                                if lic.get('content-version') == 'vor'
                                and (full_date(lic, 'start') or date.max) <= end
                                and re.fullmatch(r'https?://creativecommons\.org/licenses/by/(?:3|4)\.0/?',
                                                 lic.get('URL', ''))), None)
                title = plain_text((work.get('title') or [''])[0])
                abstract = plain_text(work.get('abstract'))
                if not (licence and title and abstract):
                    continue
                journal = (work.get('container-title') or [issn])[0]
                authors = [a.get('name') or ' '.join(filter(None, [a.get('given'), a.get('family')]))
                           for a in work.get('author', [])]
                preprints = related_dois(work, 'has-preprint')
                metadata = {'journal': journal, 'issn': issn, 'license': licence, 'preprint_dois': preprints,
                            'language': work.get('language'), 'relations': work.get('relation', {})}
                if issn in self.config[self.name].get('data_journals', []):
                    links = related_work_dois(work)
                    for link in links:
                        if link not in resource_types:
                            resource_types[link] = datacite_type(client, link)
                    metadata['dataset_dois'] = [link for link in links if resource_types[link] == 'Dataset']
                    metadata['unverified_related_dois'] = [link for link in links if resource_types[link] == 'unverified']
                if preprints:
                    metadata['preprint_doi'] = preprints[0]
                items[doi] = Item(id=f'doi:{doi}', source=self.name, type='published', title=title,
                                  abstract=abstract, published_at=day, first_seen=end, url=f'https://doi.org/{doi}',
                                  doi=doi, authors=[a for a in authors if a], org=None, summary=None,
                                  primary_category=None, published_doi=None, preprint_id=None, metadata=metadata)
        return collected(self.name, list(items.values()))
