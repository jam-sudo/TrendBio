"""Dated medical research from the Europe PMC MED index and licensed article front matter."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import logging
import re
from xml.etree import ElementTree as ET

import httpx

from pipeline.dedupe import normalize_title
from pipeline.models import Item, Source
from pipeline.sources.base import collected, request
from pipeline.sources.crossref import CrossrefAdapter, plain_text

API = 'https://www.ebi.ac.uk/europepmc/webservices/rest'
HREF = '{http://www.w3.org/1999/xlink}href'
LANG = '{http://www.w3.org/XML/1998/namespace}lang'
RESEARCH_TYPES = {'research-article', 'review-article', 'brief-report', 'systematic-review', 'case-report'}
NOTICE_TYPES = {'published erratum', 'correction', 'retraction of publication', 'expression of concern',
                'retraction', 'editorial', 'comment', 'news', 'discussion'}
PROTOCOL = re.compile(r'\bstudy protocol\b|\bprotocol (?:for|of) (?:a|an|the|this)\b|'
                      r'\b(?:trial|review|cohort|evaluation) protocol\b', re.I)


def screen_record(record):
    types = {t.casefold() for t in record.get('pubTypeList', {}).get('pubType', [])}
    links = record.get('commentCorrectionList', {}).get('commentCorrection', [])
    relations = {r['type'].casefold() for r in links}
    corrections = sorted({r['id'] for r in links if r['type'].casefold() == 'erratum in'
                          and r.get('source') == 'MED' and re.fullmatch(r'\d+', r.get('id', ''))})
    if 'retracted publication' in types or relations & {'retraction in', 'partial retraction in'}:
        return 'retracted', corrections
    if 'expression of concern in' in relations:
        return 'concern', corrections
    if relations & {'corrected and republished in', 'republished in'}:
        return 'superseded', corrections
    if types & NOTICE_TYPES or relations & {'erratum for', 'retraction of', 'expression of concern for'}:
        return 'notice-or-nonresearch', corrections
    if types & {'protocol', 'clinical trial protocol', 'study protocol'} or PROTOCOL.search(record.get('title', '')):
        return 'protocol', corrections
    if not (record.get('license') == 'cc by' and record.get('doi') and
            re.fullmatch(r'PMC\d+', record.get('pmcid') or '')):
        return 'no-verified-open-article', corrections
    return 'candidate', corrections


def matched_medline_abstract(client, doi, issn, day, title):
    """Find the MED abstract for a journal article already licensed by its publisher."""
    page = request(client, API + '/search', params={
        'query': f'SRC:MED AND DOI:"{doi}"', 'format': 'json', 'resultType': 'core', 'pageSize': 2,
    }).json()
    if page['hitCount'] != 1:
        return None
    record, = page['resultList']['result']
    journal = record.get('journalInfo', {}).get('journal', {})
    pmid = record.get('pmid') or ''
    types = {v.casefold() for v in record.get('pubTypeList', {}).get('pubType', [])}
    status, corrections = screen_record(record)
    if (record.get('source') != 'MED' or not re.fullmatch(r'\d+', pmid) or record.get('id') != pmid
            or (record.get('doi') or '').lower() != doi or issn not in (journal.get('issn'), journal.get('essn'))
            or record.get('electronicPublicationDate') != day.isoformat()
            or normalize_title(plain_text(record.get('title'))) != normalize_title(title)
            or record.get('license') not in (None, '', 'cc by')
            or status not in {'candidate', 'no-verified-open-article'} or 'journal article' not in types
            or types & {'review', 'systematic review', 'scoping review', 'meta-analysis'}):
        return None
    abstract = plain_text(record.get('abstractText'))
    if abstract:
        return abstract, {'pmid': pmid, 'abstract_url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
                          'correction_links': [f'https://pubmed.ncbi.nlm.nih.gov/{pid}/' for pid in corrections]}
    return None


def article_text(node):
    return ' '.join(''.join(node.itertext()).split()) if node is not None else ''


def article_day(meta, indexed_day):
    # Collection and issue dates often describe a whole issue, sometimes with an invented day one.
    days, print_days = set(), set()
    for entry in meta.findall('pub-date'):
        if entry.get('pub-type') == 'collection' or entry.get('date-type') == 'collection':
            continue
        parts = [entry.findtext(part) for part in ('year', 'month', 'day')]
        if all(parts):
            printed = entry.get('pub-type') == 'ppub' or entry.get('publication-format') == 'print'
            try:
                day = date(*map(int, parts)).isoformat()
            except (TypeError, ValueError):
                continue
            (print_days if printed else days).add(day)
    return date.fromisoformat(indexed_day) if indexed_day in (days or print_days) else None


def licensed_abstract(root, record):
    meta = root.find('front/article-meta')
    if meta is None:
        return None, 'missing-article-metadata'
    ids = {x.get('pub-id-type'): article_text(x).lower() for x in meta.findall('article-id')}
    if (ids.get('doi') != record['doi'].lower() or ids.get('pmid') != record['pmid']
            or ids.get('pmcid') != record['pmcid'].lower()):
        return None, 'identifier-mismatch'
    corrections = []
    for link in meta.findall('related-article'):
        relation = link.get('related-article-type', '').lower()
        if relation in {'retraction-forward', 'partial-retraction-forward'}:
            return None, 'retracted'
        if relation == 'expression-of-concern-forward':
            return None, 'concern'
        if relation == 'correction-forward':
            identifier = link.get(HREF, '')
            if re.fullmatch(r'PMC\d+', identifier):
                corrections.append('https://pmc.ncbi.nlm.nih.gov/articles/' + identifier + '/')
            elif re.fullmatch(r'10\.\d{4,9}/\S+', identifier):
                corrections.append('https://doi.org/' + identifier)
            elif link.get('ext-link-type') == 'pubmed' and identifier.isdigit():
                corrections.append('https://pubmed.ncbi.nlm.nih.gov/' + identifier + '/')
            else:
                return None, 'unresolved-correction'
    licenses = {node.get(HREF).rstrip('/') for license_node in meta.findall('permissions/license')
                for node in license_node.iter() if node.get(HREF) and 'creativecommons.org/' in node.get(HREF)}
    if len(licenses) != 1 or not re.fullmatch(r'https?://creativecommons\.org/licenses/by/(?:3|4)\.0', next(iter(licenses))):
        return None, 'unverified-article-license'
    kind = root.get('article-type', '')
    if kind not in RESEARCH_TYPES:
        return None, 'nonresearch-article-type'
    pubday = article_day(meta, record['firstPublicationDate'])
    if not pubday:
        return None, 'no-matching-exact-article-date'
    abstract = next((a for a in meta.findall('abstract') if a.get('abstract-type', '') in {'', 'abstract', 'summary'}), None)
    paragraphs = [article_text(n) for n in abstract.iter() if n.tag in {'p', 'title'}] if abstract is not None else []
    text = '\n'.join(p for p in paragraphs if p) or article_text(abstract)
    if not text:
        return None, 'missing-abstract'
    return {'day': pubday, 'license': licenses.pop() + '/', 'abstract': text,
            'language': root.get(LANG) or record.get('language'), 'article_type': kind, 'correction_links': corrections}, 'eligible'


class EuropePmcAdapter:
    name: Source = 'europepmc'

    def __init__(self, config):
        self.journals = {j['issn']: j['title'] for j in config['europepmc']['journals']}
        self.screening = {}

    def reconcile(self, store, start, end, items):
        fresh = {item.id: item for item in items if item.source == self.name}
        for old in store.items_between(start, end, by_publication=True):
            if old.source != self.name:
                continue
            current = fresh.get(old.id)
            if current is not None:
                fields = ('title', 'abstract', 'authors', 'doi', 'metadata', 'published_at')
                if any(getattr(old, f) != getattr(current, f) for f in fields):
                    yield current.model_copy(update={'first_seen': old.first_seen})
            else:
                decision = self.screening.get(old.metadata['pmid'], {})
                status = decision.get('status', 'absent-from-current-index')
                meta = {**old.metadata, 'screening_status': status, 'correction_links': decision.get('correction_links', [])}
                if old.relevant or old.metadata != meta:
                    yield old.model_copy(update={'relevant': False, 'summary': old.summary or '', 'metadata': meta})
        store._write(store.root / store.domain / 'audits' / f'europepmc-{start}-{end}.json', self.screening)

    def fetch(self, start, end, client):
        self.screening = {}
        query = 'SRC:MED AND (' + ' OR '.join('ISSN:' + issn for issn in self.journals) + f') AND FIRST_PDATE:[{start} TO {end}]'
        cursor, records = '*', {}
        while True:
            page = request(client, API + '/search', params={'query': query, 'format': 'json', 'resultType': 'core',
                                                           'pageSize': 150, 'cursorMark': cursor}).json()
            before = len(records)
            for record in page['resultList']['result']:
                if record.get('source') != 'MED' or not re.fullmatch(r'\d+', record.get('pmid', '')):
                    raise ValueError('Europe PMC returned a record outside the MED query')
                records[record['pmid']] = record
            if len(records) == page['hitCount']:
                break
            next_cursor = page.get('nextCursorMark')
            if len(records) == before or not next_cursor or cursor == next_cursor:
                raise ValueError('Incomplete Europe PMC result set')
            cursor = next_cursor

        def process(record):
            status, corrections = screen_record(record)
            journal = record['journalInfo']['journal']
            issn = next((k for k in (journal.get('essn'), journal.get('issn')) if k in self.journals), None)
            detail = {'doi': record.get('doi'), 'date': record['firstPublicationDate'], 'issn': issn,
                      'correction_links': ['https://pubmed.ncbi.nlm.nih.gov/' + pmid + '/' for pmid in corrections],
                      'linked_notices': [{'type': r['type'], 'pmid': r['id']} for r in
                                         record.get('commentCorrectionList', {}).get('commentCorrection', [])
                                         if r.get('source') == 'MED' and re.fullmatch(r'\d+', r.get('id') or '')
                                         and any(term in r['type'].lower() for term in ('erratum', 'retract', 'concern', 'republished'))]}
            evidence = None
            if not issn or not start.isoformat() <= detail['date'] <= end.isoformat():
                status = 'outside-source-window'
            if status == 'candidate':
                try:
                    response = request(client, f"{API}/{record['pmcid']}/fullTextXML")
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                    status = 'fulltext-unavailable'
                else:
                    evidence, status = licensed_abstract(ET.fromstring(response.content), record)
                    if evidence:
                        detail['abstract_source'] = 'pmc'
            return record['pmid'], {**detail, 'status': status}, evidence

        evidence_by_id = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            for pmid, detail, evidence in pool.map(process, records.values()):
                self.screening[pmid] = detail
                if evidence:
                    evidence_by_id[pmid] = evidence

        # Publishers can deposit a licensed abstract before the full text receives a PMCID.
        pending = [pmid for pmid, decision in self.screening.items()
                   if decision['status'] in {'no-verified-open-article', 'fulltext-unavailable', 'missing-abstract'}
                   and records[pmid].get('license') in (None, '', 'cc by') and decision['doi']]
        if pending:
            issns = sorted({self.screening[pmid]['issn'] for pmid in pending})
            adapter = CrossrefAdapter({'crossref': {'journals': issns}})
            registry = {article.doi: article for article in adapter.fetch(start, end, client)}
            for pmid in pending:
                record, decision = records[pmid], self.screening[pmid]
                article = registry.get(decision['doi'].lower())
                if (article is None or article.metadata['issn'] != decision['issn']
                        or article.published_at.isoformat() != decision['date']
                        or normalize_title(article.title) != normalize_title(plain_text(record['title']))):
                    continue
                evidence_by_id[pmid] = {'day': article.published_at, 'abstract': article.abstract,
                                        'license': article.metadata['license'], 'language': article.metadata.get('language'),
                                        'article_type': 'journal-article', 'correction_links': [], 'authors': article.authors}
                decision.update(status='eligible', abstract_source='crossref-vor')

        items = []
        for pmid, evidence in evidence_by_id.items():
            record, detail = records[pmid], self.screening[pmid]
            if not detail['correction_links']:
                detail['correction_links'] = evidence['correction_links']
            authors = evidence.get('authors') or [a.get('fullName') or a.get('collectiveName') for a in
                                                  record.get('authorList', {}).get('author', [])]
            authors = [a for a in authors if a] or ([record['authorString']] if record.get('authorString') else [])
            metadata = {'journal': self.journals[detail['issn']], 'issn': detail['issn'], 'pmid': pmid,
                        'pmcid': record.get('pmcid'), 'language': evidence['language'], 'license': evidence['license'],
                        'publication_types': sorted(record.get('pubTypeList', {}).get('pubType', [])),
                        'article_type': evidence['article_type'], 'abstract_source': detail['abstract_source'],
                        'correction_links': detail['correction_links']}
            items.append(Item(id='med:' + pmid, source=self.name, type='published', title=plain_text(record['title']),
                              doi=record['doi'].lower(), url='https://pubmed.ncbi.nlm.nih.gov/' + pmid + '/',
                              published_at=evidence['day'], first_seen=end, abstract=evidence['abstract'], authors=authors,
                              org=None, summary=None, primary_category=None, published_doi=None, preprint_id=None, metadata=metadata))
        logging.getLogger(__name__).info('Europe PMC screening %s', dict(Counter(r['status'] for r in self.screening.values())))
        return collected(self.name, items)
