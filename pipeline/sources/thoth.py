"""Scholarly books from Thoth's CC0 catalogue, with a corroborated edition date."""
from datetime import date, timedelta
import re
from uuid import UUID

import httpx

from pipeline.dedupe import normalize_title
from pipeline.models import Item, Source
from pipeline.sources.base import CC0, collected, request
from pipeline.sources.crossref import BookDateSourceUnavailable, CitationHead, normalized_isbn, plain_text, registered_book


_QUERY = '''query($start:Timestamp!, $offset:Int!, $limit:Int!) {
  works(limit:$limit, offset:$offset, workStatuses:[ACTIVE], workTypes:[MONOGRAPH,EDITED_BOOK],
        publicationDate:{timestamp:$start,expression:GREATER_THAN},order:{field:PUBLICATION_DATE,direction:ASC}) {
    workId workType workStatus edition doi publicationDate landingPage license imprint{imprintName}
    titles{localeCode canonical fullTitle} abstracts{localeCode abstractType content}
    languages{languageCode languageRelation} subjects{subjectType subjectCode}
    contributions{contributionType fullName} relations{relationType} publications{isbn}
  }
}'''


def catalog_books(client, start, end):
    earlier = (start - timedelta(days=1)).isoformat() + 'T23:59:59Z'
    seen, offset, last = set(), 0, start
    while True:
        data = request(client, 'https://api.thoth.pub/graphql', method='POST',
                       headers={'User-Agent': 'TrendBio scholarly book pilot (+https://github.com/jam-sudo/TrendBio)'},
                       json={'query': _QUERY,
                       'variables': {'start': earlier, 'offset': offset, 'limit': 40}}).json()
        if data.get('errors'):
            raise ValueError('Thoth could not complete the book catalogue query')
        works = data['data']['works']
        for work in works:
            day = date.fromisoformat(work['publicationDate'])
            if day < last or work['workId'] in seen:
                raise ValueError('Unordered or repeated Thoth record')
            if day > end:
                return
            seen.add(work['workId'])
            last = day
            yield work, day
        if len(works) < 40:
            return
        offset += len(works)


def _confirmation(client, work, day, titles, isbns, doi, hosts):
    landing = httpx.URL(work.get('landingPage') or '')
    if landing.scheme == 'https' and landing.host in hosts and '/catalog/book/' in landing.path:
        try:
            response = request(client, str(landing), attempts=2, timeout=10)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {403, 404, 410, 429} and exc.response.status_code < 500:
                raise
        except httpx.TransportError:
            pass
        else:
            if response.url.host != landing.host:
                return None
            head = CitationHead()
            head.feed(response.text)
            head.close()
            fields = head.fields
            dates = set(fields.get('citation_publication_date', []))
            ids = set(map(normalized_isbn, fields.get('citation_isbn', []))) - {''}
            dois = {d for v in fields.get('citation_doi', []) if re.fullmatch(r'10\.\d{4,9}/[^\s?#]+',
                    d := v.lower().removeprefix('https://doi.org/'))}
            if dates:
                if (dates != {day.isoformat()} or not any(normalize_title(v) in titles for v in fields.get('citation_title', []))
                        or (doi and dois and dois != {doi}) or not ((doi and doi in dois) or ids & isbns)):
                    return None
                return doi or (dois.pop() if len(dois) == 1 else None), str(response.url)
    return registered_book(client, day, titles, isbns, doi)


class ThothAdapter:
    name: Source = 'thoth'

    def __init__(self, config):
        self.hosts = set(config[self.name].get('publisher_date_hosts', []))
        self.subjects = config['hints']['book_subject']
        self.decisions = {}

    def book(self, work, day, end, client):
        if (work['workStatus'] != 'ACTIVE' or work['workType'] not in {'MONOGRAPH', 'EDITED_BOOK'} or work['edition'] != 1
                or any(r['relationType'] in {'REPLACES', 'IS_REPLACED_BY', 'IS_TRANSLATION_OF'} for r in work['relations'])):
            return None, 'other-edition-or-type'
        codes = [s['subjectType'] + ':' + s['subjectCode'] for s in work['subjects']]
        hints = [prefix for prefix in self.subjects if any(c.startswith(prefix) for c in codes)]
        if not hints:
            return None, 'outside-pilot-subjects'
        titles = {t['localeCode']: plain_text(t['fullTitle']) for t in work['titles'] if t['fullTitle']}
        originals = [t['localeCode'] for t in work['titles'] if t['canonical']]
        descriptions = {a['localeCode']: plain_text(a['content']) for a in sorted(work['abstracts'],
                        key=lambda a: a['abstractType'] == 'LONG') if a['abstractType'] in {'LONG', 'SHORT'} and a['content']}
        for locale, description in list(descriptions.items()):
            descriptions.setdefault(locale.split('_')[0], description)
        lang = next((l for l in ['EN', *originals, *titles] if titles.get(l) and
                     (descriptions.get(l) or descriptions.get(l.split('_')[0]))), None)
        authors = list(dict.fromkeys(c['fullName'] for c in work['contributions'] if c['fullName'] and c['contributionType'] in {'AUTHOR', 'EDITOR'}))
        if not lang or not authors:
            return None, 'missing-description-title-or-contributors'
        abstract = descriptions.get(lang) or descriptions[lang.split('_')[0]]
        isbns = {normalized_isbn(p['isbn']) for p in work['publications']} - {''}
        doi = (work.get('doi') or '').lower().removeprefix('https://doi.org/')
        if doi and not re.fullmatch(r'10\.\d{4,9}/[^\s?#]+', doi):
            return None, 'invalid-doi'
        confirmation = _confirmation(client, work, day, {normalize_title(v) for v in titles.values()}, isbns, doi, self.hosts)
        if confirmation is None:
            return None, 'unconfirmed-edition-date-or-identity'
        doi, proof = confirmation
        identifier = str(UUID(work['workId']))
        languages = [l['languageCode'].lower() for l in work['languages'] if l['languageRelation'] == 'ORIGINAL']
        return Item(id='thoth:' + identifier, source=self.name, type='published', doi=doi, published_doi=None,
                    preprint_id=None, title=titles[lang], abstract=abstract, published_at=day, first_seen=end,
                    authors=authors, org=None, primary_category=None, summary=None, url='https://thoth.pub/books/' + identifier,
                    metadata={'publication_type': 'Monograph' if work['workType'] == 'MONOGRAPH' else 'Edited book',
                              'imprint': work['imprint']['imprintName'], 'original_languages': languages,
                              'original_title': next((titles[l] for l in originals if l in titles), None),
                              'abstract_language': lang.split('_')[0].lower(), 'book_subjects': hints, 'isbns': sorted(isbns),
                              'metadata_license': CC0, 'work_license': work.get('license'),
                              'date_basis': 'Confirmed publication date', 'date_evidence': proof,
                              'description_source': 'Publisher catalogue description'}), 'eligible'

    def fetch(self, start, end, client):
        books = []
        self.decisions = {}
        for work, day in catalog_books(client, start, end):
            try:
                book, status = self.book(work, day, end, client)
            except BookDateSourceUnavailable:
                book, status = None, 'book-date-source-unavailable'
            self.decisions[work['workId']] = status
            if book:
                books.append(book)
        return collected(self.name, books)
