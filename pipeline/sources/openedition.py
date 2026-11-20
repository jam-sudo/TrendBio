"""OpenEdition publisher metadata from selected humanities journals and scholarly presses."""
from datetime import date
import re

from pipeline.dedupe import normalize_title, parallel_openedition_ids
from pipeline.models import Item, Source
from pipeline.sources.base import CC0, collected
from pipeline.sources.crossref import BookDateSourceUnavailable, normalized_isbn, plain_text, registered_book
from pipeline.sources.oai import LANG, OAI, oai_records


MODS = '{http://www.loc.gov/mods/v3}'
ENDPOINT = 'https://metadata.openedition.org/oai'


def _work(record, venue, identifier, start, end, client):
    doc = record.find(f'{OAI}metadata/{MODS}mods')
    if doc is None:
        raise ValueError('Missing OpenEdition MODS metadata')
    handles = {e.text for e in doc.findall(MODS + 'identifier[@type="hdl"]')}
    if handles != {identifier} or not re.fullmatch(r'20\.500\.13089/[\w.-]+', identifier):
        raise ValueError('Unmatched OpenEdition Handle')
    sets = record.findall(f'{OAI}header/{OAI}setSpec')
    if venue['set'] not in {s.text for s in sets}:
        raise ValueError('Record came from another OpenEdition set')
    platform, collection = venue['set'].split(':')
    kind = doc.findtext(MODS + 'typeOfResource[@authority="openedition"]')
    if kind != ('article' if platform == 'journals' else 'book'):
        return None, kind or 'unknown-type'
    origin = MODS + 'originInfo/' + MODS
    issued = doc.findtext(origin + 'dateIssued', '')
    online = doc.findtext(origin + 'dateOther[@type="published_on_openedition"]', '')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', online) or not re.fullmatch(r'\d{4}(?:-\d{2}){0,2}', issued):
        return None, 'undated'
    online_day = date.fromisoformat(online)
    if online_day > end or (len(issued) < 10 and not online.startswith(issued)):
        return None, 'outside-window-or-backlist'
    day = min(date.fromisoformat(issued), online_day) if len(issued) == 10 else online_day
    if not start <= day <= end:
        return None, 'outside-window-or-backlist'
    original = doc.findtext(f'{MODS}language/{MODS}languageTerm[@type="code"]', '').lower()
    titles = {}
    for node in doc.findall(MODS + 'titleInfo'):
        title = node.find(MODS + 'title')
        if title is not None and title.text and node.get('type') in {None, 'translated'}:
            lang = title.get(LANG) or node.get(LANG) or (original if node.get('type') is None else '')
            titles[lang] = plain_text(' '.join(v for v in [title.text, node.findtext(MODS + 'subTitle')] if v))
    descriptions = {e.get(LANG, original): plain_text(''.join(e.itertext())) for e in doc.findall(MODS + 'abstract[@type="summary"]')}
    lang = next((l for l in ('en', original, *titles) if l and titles.get(l) and descriptions.get(l)), None)
    names = []
    for n in doc.findall(MODS + 'name'):
        if any(e.text in {'aut', 'edt'} for e in n.findall(f'{MODS}role/{MODS}roleTerm')):
            names.append(' '.join(v.text for v in n.findall(MODS + 'namePart') if v.text))
    authors = list(dict.fromkeys(filter(None, names)))
    if not lang or not authors:
        return None, 'missing-paired-abstract-or-creators'
    doi = (doc.findtext(MODS + 'identifier[@type="doi"]') or '').lower()
    if doi and not re.fullmatch(r'10\.\d{4,9}/[^\s?#]+', doi):
        return None, 'invalid-doi'
    url = doc.findtext(f'{MODS}location/{MODS}url') or ''
    if not url.startswith(f'https://{platform}.openedition.org/{collection}/'):
        return None, 'unmatched-publisher-url'
    licence = doc.find(MODS + 'accessCondition[@type="license"]')
    meta = {'publication_type': 'Scholarly book' if kind == 'book' else 'Journal article',
            'journal' if kind == 'article' else 'imprint': venue['title'], 'collection': venue['set'],
            'original_title': titles.get(original), 'original_languages': [original] if original else [], 'abstract_language': lang,
            'metadata_license': CC0, 'work_license': licence.get('valueURI') if licence is not None else None,
            'date_basis': 'Online publication date' if len(issued) < 10 else 'Publication date',
            'original_issued': issued, 'online_date': online, 'description_source': 'Publisher-supplied abstract'}
    host = doc.find(MODS + 'relatedItem[@type="host"]')
    if kind == 'article' and host is not None:
        if any(e.text == 'trl' for e in doc.findall(f'{MODS}name/{MODS}role/{MODS}roleTerm')):
            meta['has_translator'] = True
        issue = host.findtext(f'{MODS}identifier[@type="hdl"]', '')
        if re.fullmatch(r'20\.500\.13089/[\w.-]+', issue):
            meta['issue_url'] = 'https://hdl.handle.net/' + issue
            meta['issue'] = host.findtext(f'{MODS}part/{MODS}detail[@type="volume"]/{MODS}number', '')
    if kind == 'book':
        isbns = {normalized_isbn(n.text) for n in doc.findall(MODS + 'identifier') if n.get('type') in {'eisbn', 'pisbn'}} - {''}
        if len(issued) < 10:
            confirmation = registered_book(client, day, {normalize_title(v) for v in titles.values()}, isbns, doi)
            if confirmation is None:
                return None, 'unconfirmed-original-book-date'
            doi, meta['date_evidence'] = confirmation
            meta['date_basis'] = 'Confirmed publication date'
        meta['isbns'] = sorted(isbns)
    return Item(id='openedition:' + identifier, source='openedition', type='published', doi=doi or None,
                title=titles[lang], url=url, authors=authors, abstract=descriptions[lang], published_at=day,
                first_seen=end, published_doi=None, preprint_id=None, org=None, primary_category=None,
                summary=None, metadata=meta), 'eligible'


class OpenEditionAdapter:
    name: Source = 'openedition'

    def __init__(self, config):
        self.venues = config[self.name]['venues']
        self.decisions = {}

    def fetch(self, start, end, client):
        items = []
        self.decisions = {}
        for venue in self.venues:
            params = {'verb': 'ListRecords', 'metadataPrefix': 'mods', 'set': venue['set'], 'from': f'{start}T00:00:00Z'}
            for identifier, record in oai_records(client, ENDPOINT, params):
                try:
                    item, status = _work(record, venue, identifier, start, end, client)
                except BookDateSourceUnavailable:
                    item, status = None, 'book-date-source-unavailable'
                self.decisions[identifier] = status
                if item:
                    items.append(item)
        translated = parallel_openedition_ids(items)
        for identifier in translated:
            self.decisions[identifier.removeprefix('openedition:')] = 'parallel-language-edition'
        return collected(self.name, [item for item in items if item.id not in translated])
