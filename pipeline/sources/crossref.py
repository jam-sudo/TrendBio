"""Publication-day intake for openly licensed journal articles in field pilots."""
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
import logging
import re
from urllib.parse import quote

import httpx

from pipeline.dedupe import normalize_title
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


def vor_license(work, as_of, *, allow_cc0=False):
    for lic in work.get('license', []):
        if lic.get('content-version') != 'vor' or (full_date(lic, 'start') or date.max) > as_of:
            continue
        url = lic.get('URL', '')
        if re.fullmatch(r'https?://creativecommons\.org/licenses/by/(?:3|4)\.0/?', url):
            return url
        if allow_cc0 and re.fullmatch(r'https?://creativecommons\.org/publicdomain/zero/1\.0/?', url):
            return url
    return None


@dataclass
class _Alternative:
    start: int
    tex_start: int | None = None
    tex_end: int | None = None


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.alternatives: list[_Alternative] = []

    def handle_starttag(self, tag, attrs):
        name = tag.split(':')[-1]
        if name == 'alternatives':
            self.alternatives.append(_Alternative(len(self.parts)))
        elif name == 'tex-math' and self.alternatives:
            self.alternatives[-1].tex_start = len(self.parts)

    def handle_data(self, data):
        self.parts.append(data)

    def unknown_decl(self, data):
        if data.startswith('CDATA['):
            self.parts.append(data[6:])

    def handle_endtag(self, tag):
        name = tag.split(':')[-1]
        if name == 'tex-math' and self.alternatives:
            self.alternatives[-1].tex_end = len(self.parts)
        elif name == 'alternatives' and self.alternatives:
            choice = self.alternatives.pop()
            if choice.tex_start is not None and choice.tex_end is not None:
                tex = self.parts[choice.tex_start:choice.tex_end]
                if ''.join(tex).strip():
                    self.parts[choice.start:] = tex
        elif name in {'p', 'div', 'title'}:
            self.parts.append(' ')


def plain_text(fragment):
    parser = _Text()
    parser.feed(fragment or '')
    parser.close()
    return ' '.join(''.join(parser.parts).split())


class CitationHead(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            meta = dict(attrs)
            if meta.get('name') and meta.get('content'):
                self.fields.setdefault(meta['name'].lower(), []).append(meta['content'].strip())


def _publisher_article_type(client, base, work, doi, issn, day):
    if '{doi}' in base:
        url = base.format(doi=quote(doi, safe='/'))
    else:
        url = work.get('resource', {}).get('primary', {}).get('URL', '')
        if not url.startswith(base):
            return None
    response = request(client, url)
    head = CitationHead()
    head.feed(response.text)
    head.close()
    fields = head.fields
    dates = fields.get('citation_publication_date') or fields.get('citation_date', [])
    allowed_dates = {day.strftime('%Y/%m/%d'), day.strftime('%b %d, %Y'), f'{day:%b} {day.day}, {day.year}'}
    if (response.url.host != httpx.URL(base).host or issn not in fields.get('citation_issn', [])
            or [v.lower() for v in fields.get('citation_doi', [])] != [doi]
            or len(dates) != 1 or dates[0] not in allowed_dates):
        return None
    types = fields.get('dc.type') or fields.get('citation_article_type', [])
    if len(types) == 1 and types[0] in {'Research Article', 'Short Communication', 'Data Paper'}:
        return {'article_type': types[0], 'article_type_url': str(response.url)}
    return None


def _publisher_abstract(client, base, doi, issn, day):
    response = request(client, base + quote(doi, safe='/') + '.html')
    head = CitationHead()
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


def normalized_isbn(code):
    value = (code or '').replace('-', '').replace(' ', '').upper()
    return value if re.fullmatch(r'(?:97[89]\d{10}|\d{9}[\dX])', value) else ''


def _registry_match(work, day, titles, isbns):
    raw = (work.get('title') or [''])[0]
    variants = [raw, raw + ' ' + ' '.join(work.get('subtitle') or [])]
    edition = str(work.get('edition-number') or '').strip().lower()
    dates = [(work.get(k, {}).get('date-parts') or [[]])[0] for k in ('published-print', 'published-online')]
    stamp = [day.year, day.month, day.day]
    return (work.get('type') in {'book', 'monograph', 'edited-book', 'reference-book'} and not work.get('update-to')
            and edition in {'', '1', '1st', '1st edition', 'first', 'first edition'} and full_date(work, 'published') == day
            and all(parts >= stamp[:len(parts)] for parts in dates)
            and any(normalize_title(plain_text(t)) in titles for t in variants)
            and bool(isbns & {normalized_isbn(i) for i in work.get('ISBN', [])}))


class BookDateSourceUnavailable(Exception):
    """The registry could not answer after retries."""


def registered_book(client, day, titles, isbns, doi):
    if not isbns:
        return None
    # Crossref joins alternative formats of the same filter with OR.
    filters = ['isbn:' + isbn for isbn in sorted(isbns)]
    filters += ['type:' + kind for kind in ('book', 'monograph', 'edited-book', 'reference-book')]
    try:
        matches = {key for key, rec in crossref_works(client, 'https://api.crossref.org/works', ','.join(filters))
                   if (not doi or key == doi) and _registry_match(rec, day, titles, isbns)}
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429 or exc.response.status_code >= 500:
            raise BookDateSourceUnavailable from exc
        raise
    except httpx.TransportError as exc:
        raise BookDateSourceUnavailable from exc
    if len(matches) == 1:
        identifier = matches.pop()
        return identifier, 'https://api.crossref.org/works/' + identifier
    return None


class CrossrefAdapter:
    name: Source = 'crossref'

    def __init__(self, config):
        self.config = config
        self.decisions = {}

    def fetch(self, start, end, client):
        from pipeline.sources.europepmc import matched_medline_abstract

        self.decisions.clear()
        items = {}
        resource_types = {}
        filters = f'type:journal-article,from-pub-date:{start},until-pub-date:{end}'
        for issn in self.config[self.name]['journals']:
            type_page = self.config[self.name].get('article_type_pages', {}).get(issn)
            endpoint = f'https://api.crossref.org/journals/{issn}/works'
            for doi, work in crossref_works(client, endpoint, filters):
                day = full_date(work, 'published')
                if day is None or not start <= day <= end or work.get('update-to'):
                    continue
                licence = vor_license(work, end, allow_cc0=bool(type_page))
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
                indexed = {}
                if not abstract and issn in self.config[self.name].get('medline_abstracts', []):
                    try:
                        match = matched_medline_abstract(client, doi, issn, day, title)
                    except (httpx.HTTPError, ValueError, KeyError) as exc:
                        self.decisions[doi] = 'abstract-source-unavailable'
                        logging.getLogger(__name__).warning('MED abstract lookup failed for %s (%s)', doi, type(exc).__name__)
                        continue
                    if match:
                        abstract, indexed = match
                if not abstract:
                    continue
                journal = plain_text((work.get('container-title') or [''])[0]) or issn
                authors = [a.get('name') or ' '.join(filter(None, [a.get('given'), a.get('family')]))
                           for a in work.get('author', [])]
                preprints = related_dois(work, 'has-preprint')
                metadata = {'journal': journal, 'issn': issn, 'license': licence, 'preprint_dois': preprints,
                            'language': language, 'relations': work.get('relation', {}), **indexed}
                if type_page:
                    genre = _publisher_article_type(client, type_page, work, doi, issn, day)
                    if genre is None:
                        continue
                    metadata.update(genre)
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
