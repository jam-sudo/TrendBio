"""Published articles and author-supplied abstract translations from journal OAI-PMH feeds."""
from datetime import date
import re
from xml.etree import ElementTree as ET

from pipeline.models import Item, Source
from pipeline.sources.base import collected, request
from pipeline.sources.crossref import plain_text


OAI = '{http://www.openarchives.org/OAI/2.0/}'
DC = '{http://purl.org/dc/elements/1.1/}'
OAI_DC = '{http://www.openarchives.org/OAI/2.0/oai_dc/}'
LANG = '{http://www.w3.org/XML/1998/namespace}lang'


def _language(label):
    code = label.strip().lower().replace('_', '-').split('-')[0]
    return {'eng': 'en', 'spa': 'es', 'por': 'pt'}.get(code, code)


def _paper(dc, journal, start, end):
    def values(tag):
        return [e.text.strip() for e in dc.findall(DC + tag) if e.text and e.text.strip()]

    dates = set(values('date'))
    types = set(values('type'))
    if (len(dates) != 1 or not {'info:eu-repo/semantics/article',
            'info:eu-repo/semantics/publishedVersion'} <= types):
        return None
    stamp = dates.pop()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', stamp) or not start <= (day := date.fromisoformat(stamp)) <= end:
        return None
    rights = {v.rstrip('/') for v in values('rights') if v.startswith(('http://', 'https://'))}
    if len(rights) != 1 or not re.fullmatch(r'https?://creativecommons\.org/licenses/by/(?:3|4)\.0', licence := rights.pop()):
        return None
    dois = {v.lower().removeprefix('https://doi.org/') for v in values('identifier')}
    dois = {v for v in dois if re.fullmatch(r'10\.\d{4,9}/[^\s]+', v)}
    authors = list(dict.fromkeys(values('creator')))
    if len(dois) != 1 or not authors or journal['issn'] not in values('source'):
        return None
    doi = dois.pop()
    original = list(dict.fromkeys(_language(v) for v in values('language')))

    def localized(tag):
        return {_language(e.get(LANG, '')): text for e in dc.findall(DC + tag) if (text := plain_text(e.text))}

    titles, abstracts = localized('title'), localized('description')
    common = titles.keys() & abstracts.keys()
    if not common:
        return None
    # Keep a title and abstract in the same language for the shared embedding model.
    lang = next(code for code in ['en', *original, *sorted(common)] if code in common)
    return Item(id='doi:' + doi, source='oai', type='published', doi=doi, url='https://doi.org/' + doi,
                title=titles[lang], abstract=abstracts[lang], authors=authors, published_at=day, first_seen=end,
                org=None, summary=None, primary_category=None, published_doi=None, preprint_id=None,
                metadata={'journal': journal['title'], 'issn': journal['issn'], 'license': licence + '/',
                          'language': original[0] if original else None, 'original_languages': original,
                          'abstract_language': lang or None, 'abstract_languages': sorted(k for k in abstracts if k)})


def oai_records(client, endpoint, params):
    seen, tokens = set(), set()
    expected = None
    while True:
        root = ET.fromstring(request(client, endpoint, params=params).content)
        error = root.find(OAI + 'error')
        if error is not None and error.get('code') == 'noRecordsMatch' and not tokens:
            break
        page = root.find(OAI + 'ListRecords')
        if error is not None or page is None or not page.findall(OAI + 'record'):
            raise ValueError('Incomplete OAI-PMH record list')
        for rec in page.findall(OAI + 'record'):
            header = rec.find(OAI + 'header')
            identifier = header.findtext(OAI + 'identifier') if header is not None else None
            if not identifier or identifier in seen:
                raise ValueError('Missing or repeated OAI record identifier')
            seen.add(identifier)
            if header.get('status') == 'deleted':
                continue
            yield identifier, rec
        cursor = page.find(OAI + 'resumptionToken')
        if cursor is not None and cursor.get('completeListSize') is not None:
            expected = int(cursor.get('completeListSize'))
        token = (cursor.text or '').strip() if cursor is not None else ''
        if not token:
            if expected is not None and len(seen) != expected:
                raise ValueError('OAI-PMH pagination ended before the declared record count')
            break
        if token in tokens:
            raise ValueError('Repeated OAI-PMH resumption token')
        tokens.add(token)
        params = {'verb': 'ListRecords', 'resumptionToken': token}


class OaiAdapter:
    name: Source = 'oai'

    def __init__(self, config):
        self.journals = config[self.name]['journals']

    def fetch(self, start, end, client):
        papers = {}
        for journal in self.journals:
            # OAI datestamps are updates. Later edits can describe an earlier publication.
            params = {'verb': 'ListRecords', 'metadataPrefix': 'oai_dc', 'from': start.isoformat()}
            section = journal.get('article_set')
            if section:
                params['set'] = section
            for _, rec in oai_records(client, journal['endpoint'], params):
                if section and section not in {s.text for s in rec.findall(f'{OAI}header/{OAI}setSpec')}:
                    raise ValueError('Journal record came from another OAI-PMH section')
                dc = rec.find(f'{OAI}metadata/{OAI_DC}dc')
                if dc is None:
                    raise ValueError('Missing OAI Dublin Core metadata')
                paper = _paper(dc, journal, start, end)
                if paper:
                    papers[paper.id] = paper
        return collected(self.name, list(papers.values()))
