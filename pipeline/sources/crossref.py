"""Publication-day intake for openly licensed journal articles in field pilots."""
from datetime import date, datetime
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


def vor_cc_by(work, as_of):
    return next((lic['URL'] for lic in work.get('license', [])
                 if lic.get('content-version') == 'vor' and (full_date(lic, 'start') or date.max) <= as_of
                 and re.fullmatch(r'https?://creativecommons\.org/licenses/by/(?:3|4)\.0/?', lic.get('URL', ''))), None)


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


class _ArticleHead(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            meta = dict(attrs)
            if meta.get('name') and meta.get('content'):
                self.fields.setdefault(meta['name'].lower(), []).append(meta['content'].strip())


def _publisher_abstract(client, base, doi, issn, day):
    response = request(client, base + quote(doi, safe='/') + '.html')
    head = _ArticleHead()
    head.feed(response.text)
    head.close()
    fields = head.fields
    dates = fields.get('citation_date', [])
    if (response.url.host != httpx.URL(base).host or [v.lower() for v in fields.get('citation_doi', [])] != [doi]
            or issn.replace('-', '') not in [v.replace('-', '') for v in fields.get('citation_issn', [])]
            or len(dates) != 1 or datetime.strptime(dates[0], '%Y/%m/%d').date() != day):
        raise ValueError('Publisher abstract does not match the registered article')
    descriptions = fields.get('dc.description', [])
    languages = fields.get('dc.language', [])
    return (plain_text(descriptions[0]) if len(descriptions) == 1 else '', str(response.url),
            languages[0] if len(languages) == 1 else None)


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
                licence = vor_cc_by(work, end)
                title = plain_text((work.get('title') or [''])[0])
                abstract = plain_text(work.get('abstract'))
                if not (licence and title):
                    continue
                abstract_url = None
                language = work.get('language')
                base = self.config[self.name].get('publisher_abstracts', {}).get(issn)
                if not abstract and base:
                    abstract, abstract_url, native_language = _publisher_abstract(client, base, doi, issn, day)
                    language = language or native_language
                if not abstract:
                    continue
                journal = (work.get('container-title') or [issn])[0]
                authors = [a.get('name') or ' '.join(filter(None, [a.get('given'), a.get('family')]))
                           for a in work.get('author', [])]
                preprints = related_dois(work, 'has-preprint')
                metadata = {'journal': journal, 'issn': issn, 'license': licence, 'preprint_dois': preprints,
                            'language': language, 'relations': work.get('relation', {})}
                if abstract_url:
                    metadata['abstract_url'] = abstract_url
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
