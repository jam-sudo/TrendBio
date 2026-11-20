"""ACM proceedings with author-deposited, licensed abstracts in a conference's HAL collection."""
from datetime import date
import re

import httpx

from pipeline.dedupe import normalize_title
from pipeline.models import Item
from pipeline.sources.base import request
from pipeline.sources.crossref import crossref_works, full_date, journal_corrections, plain_text, vor_license


def _deposits(client, collection):
    url = f'https://api.archives-ouvertes.fr/search/{collection}/'
    fields = ('halId_s,version_i,docType_s,doiId_s,authFullName_s,language_s,licence_s,openAccess_bool,'
              'releasedDate_s,title_s,en_title_s,fr_title_s,en_abstract_s,fr_abstract_s')
    records = {}
    while True:
        page = request(client, url, params={'q': 'docType_s:COMM', 'fl': fields, 'rows': 100,
                                            'start': len(records), 'sort': 'docid asc', 'wt': 'json'}).json()['response']
        before = len(records)
        if page['start'] != before:
            raise ValueError('Unexpected HAL page offset')
        records.update((doc['halId_s'], doc) for doc in page['docs'])
        if len(records) != before + len(page['docs']) or len(records) > page['numFound']:
            raise ValueError('HAL returned inconsistent records')
        if len(records) == page['numFound']:
            return list(records.values())
        if not page['docs']:
            raise ValueError('Incomplete HAL conference collection')


def _key(text):
    return ''.join(normalize_title(text).split())


def _matched_deposit(deposits, work, doi, authors):
    titles = {_key(plain_text(title)) for title in work.get('title', []) if title}
    matches = []
    for doc in deposits:
        if doc.get('docType_s') != 'COMM' or (doc.get('doiId_s') or '').lower() not in {'', doi}:
            continue
        byline = doc.get('authFullName_s') or []
        if len(byline) != len(authors) or _key(byline[0]) != _key(authors[0]):
            continue
        if any(_key(title) in titles for field in ('title_s', 'en_title_s', 'fr_title_s') for title in doc.get(field, [])):
            matches.append(doc)
    exact = [doc for doc in matches if doc.get('doiId_s')]
    candidates = exact or matches
    return candidates[0] if len(candidates) == 1 else None


def conference_papers(client, volume, start, end, decisions):
    filters = (f'type:proceedings-article,container-title:{volume["title"]},'
               f'from-online-pub-date:{start},until-online-pub-date:{end}')
    records = crossref_works(client, 'https://api.crossref.org/members/320/works', filters)
    eligible = []
    for doi, work in records:
        day = full_date(work, 'published-online')
        if (work.get('type') != 'proceedings-article' or work.get('member') != '320'
                or not doi.startswith(volume['volume_doi'] + '.') or volume['title'] not in work.get('container-title', [])
                or day is None or not start <= day <= end or (full_date(work, 'created') or date.max) > end):
            continue
        corrections = journal_corrections(work, doi)
        if corrections is None:
            decisions[doi] = 'publication-update'
            continue
        licence = vor_license(work, end)
        authors = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in work.get('author', [])]
        if not licence or not authors or not all(authors):
            continue
        eligible.append((doi, work, day, corrections, licence, authors))
    if not eligible:
        return
    try:
        deposits = _deposits(client, volume['collection'])
    except (httpx.HTTPError, ValueError, KeyError):
        decisions.update({row[0]: 'abstract-source-unavailable' for row in eligible})
        return
    for doi, work, day, corrections, licence, authors in eligible:
        doc = _matched_deposit(deposits, work, doi, authors)
        if not doc or doc.get('openAccess_bool') is not True or not re.fullmatch(
                r'https?://creativecommons\.org/licenses/by/(?:3|4)\.0/?', doc.get('licence_s') or ''):
            continue
        released = (doc.get('releasedDate_s') or '').split(' ')[0]
        if (not re.fullmatch(r'\d{4}-\d{2}-\d{2}', released) or date.fromisoformat(released) > end
                or not re.fullmatch(r'hal-\d+', doc['halId_s']) or not isinstance(doc.get('version_i'), int)
                or doc['version_i'] < 1):
            continue
        language = next((lang for lang in ('en', 'fr') if doc.get(lang + '_title_s') and doc.get(lang + '_abstract_s')), None)
        if language is None:
            continue
        title = plain_text(doc[language + '_title_s'][0])
        abstract = plain_text(doc[language + '_abstract_s'][0])
        if not title or not abstract:
            continue
        originals = doc.get('language_s') or []
        metadata = {'conference': volume['conference'], 'journal': volume['title'], 'volume_doi': volume['volume_doi'],
                    'publication_type': 'Conference paper', 'license': licence, 'original_languages': originals,
                    'abstract_language': language, 'abstract_url': f"https://hal.science/{doc['halId_s']}v{doc['version_i']}",
                    'abstract_license': doc['licence_s'], 'date_basis': 'Online publication date',
                    'date_evidence': 'https://api.crossref.org/works/' + doi}
        if originals and (original_title := doc.get(originals[0] + '_title_s')):
            metadata['original_title'] = plain_text(original_title[0])
        if corrections:
            metadata['correction_links'] = corrections
        yield Item(id='doi:' + doi, source='crossref', type='published', doi=doi, url='https://doi.org/' + doi,
                   title=title, abstract=abstract, authors=authors, published_at=day, first_seen=end, org=None,
                   summary=None, primary_category=None, published_doi=None, preprint_id=None, metadata=metadata)
