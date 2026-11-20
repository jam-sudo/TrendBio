"""First-edition books in Crossref with matching publisher catalogue evidence."""
import re

import httpx

from pipeline.dedupe import normalize_title
from pipeline.models import Item
from pipeline.sources.base import request
from pipeline.sources.crossref import CitationHead, crossref_works, first_book_edition, full_date, normalized_isbn, plain_text


class _BookPage(CitationHead):
    def __init__(self):
        super().__init__()
        self.abstracts = {}
        self.series = []
        self._series_depth = 0
        self._series_name = None

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        values = dict(attrs)
        if tag == 'meta' and (values.get('name') or '').lower() == 'citation_abstract':
            lang = values.get('xml:lang') or values.get('lang')
            if lang and (abstract := plain_text(values.get('content'))):
                self.abstracts[lang.lower()] = abstract
        if tag == 'div' and (self._series_depth or {'item', 'series'} <= set((values.get('class') or '').split())):
            self._series_depth += 1
        if tag == 'a' and self._series_depth and '/catalog/series/' in (values.get('href') or ''):
            self._series_name = []

    def handle_data(self, data):
        if self._series_name is not None:
            self._series_name.append(data)

    def handle_endtag(self, tag):
        if tag == 'div' and self._series_depth:
            self._series_depth -= 1
        if tag == 'a' and self._series_name is not None:
            name = ' '.join(''.join(self._series_name).split())
            if name and name not in self.series:
                self.series.append(name)
            self._series_name = None


def _book(client, press, doi, work, day, end):
    catalogue = httpx.URL(press['catalogue'])
    landing = httpx.URL(work.get('resource', {}).get('primary', {}).get('URL') or '')
    number = re.search(r'/catalog/book/(\d+)/?$', landing.path)
    if not number or landing.host != catalogue.host or landing.scheme != 'https':
        return None, 'outside-press-catalogue'
    if (not doi.startswith(press['prefix'] + '/') or not work.get('edition-number')
            or set(work.get('relation', {})) & {'is-translation-of', 'is-version-of', 'is-new-version-of', 'replaces'}):
        return None, 'unconfirmed-first-edition'
    url = press['catalogue'] + '/book/' + number[1]
    response = request(client, url, timeout=15)
    if response.url != httpx.URL(url):
        return None, 'unmatched-publisher-url'
    page = _BookPage()
    page.feed(response.text)
    page.close()
    fields = page.fields
    titles = list(dict.fromkeys(plain_text(title) for title in fields.get('citation_title', []) if title))
    languages = set(fields.get('citation_language', []))
    if (len(titles) != 1 or len(languages) != 1 or set(fields.get('dc.source', [])) != {press['title']}
            or set(fields.get('dc.type', [])) != {'Text.Book'} or {s.lower() for s in fields.get('citation_doi', [])} != {doi}
            or set(fields.get('citation_publication_date', [])) != {day.isoformat()}
            or not first_book_edition(work, day, {normalize_title(titles[0])})):
        return None, 'unconfirmed-book-edition-or-identity'
    isbns = {normalized_isbn(v) for v in work.get('ISBN', [])} - {''}
    publisher_isbns = {normalized_isbn(v) for v in fields.get('citation_isbn', [])} - {''}
    if isbns and publisher_isbns and isbns.isdisjoint(publisher_isbns):
        return None, 'unconfirmed-book-isbn'
    rights = {v.rstrip('/') for v in fields.get('dc.rights', []) if v.startswith(('https://', 'http://'))}
    if len(rights) != 1 or not re.fullmatch(r'https?://creativecommons\.org/licenses/by/(?:3|4)\.0', license_url := rights.pop()):
        return None, 'unconfirmed-book-license'
    lang = languages.pop().lower()
    authors = [who.get('name') or ' '.join(filter(None, (who.get('given'), who.get('family'))))
               for role in ('author', 'editor') for who in work.get(role, [])]
    credits = list(dict.fromkeys(filter(None, authors)))
    if not page.abstracts.get(lang) or not credits:
        return None, 'missing-paired-abstract-or-creators'
    kind = {'monograph': 'Monograph', 'edited-book': 'Edited book'}.get(work['type'], 'Scholarly book')
    return Item(id='doi:' + doi, source='crossref', type='published', doi=doi, preprint_id=None, published_doi=None,
                url=url, title=titles[0], abstract=page.abstracts[lang], authors=credits, published_at=day, first_seen=end,
                summary=None, org=None, primary_category=None, metadata={
                    'publication_type': kind, 'imprint': press['title'], 'original_title': titles[0],
                    'original_languages': [lang], 'abstract_language': lang, 'isbns': sorted(isbns | publisher_isbns),
                    'book_series': page.series, 'work_license': license_url + '/', 'date_basis': 'Confirmed publication date',
                    'date_evidence': 'https://api.crossref.org/works/' + doi, 'description_source': 'Publisher catalogue description',
                }), 'eligible'


def press_books(client, press, start, end, decisions):
    endpoint = f"https://api.crossref.org/prefixes/{press['prefix']}/works"
    filters = f'type:book,type:monograph,type:edited-book,from-pub-date:{start},until-pub-date:{end}'
    try:
        for doi, work in crossref_works(client, endpoint, filters):
            day = full_date(work, 'published')
            if not day or not start <= day <= end:
                decisions[doi] = 'imprecise-or-outside-window'
                continue
            try:
                book, decisions[doi] = _book(client, press, doi, work, day, end)
            except httpx.HTTPError as exc:
                decisions[doi] = ('unavailable-publisher-record' if isinstance(exc, httpx.HTTPStatusError)
                                  and exc.response.status_code in {404, 410} else 'book-date-source-unavailable')
                continue
            if book:
                yield book
    except (httpx.HTTPError, ValueError, KeyError):
        decisions[endpoint] = 'book-date-source-unavailable'
