import calendar
from datetime import date, timedelta
import os
import re
import time
import xml.etree.ElementTree as ET

import httpx

from pipeline.models import Item, Source
from pipeline.sources.base import collected, load_config, request


def _text(node: ET.Element | None) -> str:
    return ''.join(node.itertext()).strip() if node is not None else ''


def _date(node: ET.Element) -> date:
    year = node.findtext('Year')
    if year is None:
        # PubMed permits a season/range in MedlineDate; use its first month/year.
        raw = node.findtext('MedlineDate', '')
        year = re.search(r'\d{4}', raw).group()
        month = next((i for i, name in enumerate(calendar.month_abbr) if name and name in raw), 1)
        return date(int(year), month, 1)
    month = node.findtext('Month', '1')
    month = int(month) if month.isdigit() else list(calendar.month_abbr).index(month[:3].title())
    return date(int(year), month, int(node.findtext('Day', '1')))


class PubmedAdapter:
    name: Source = 'pubmed'

    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else load_config()

    def _search(self, term, start, end, client, auth):
        ids, offset = [], 0
        while True:
            time.sleep(0.11 if auth else 0.34)
            result = request(client, f"{self.config['pubmed']['endpoint']}/esearch.fcgi", method='POST', data={
                'db': 'pubmed', 'term': term, 'datetype': 'pdat',
                'mindate': start.isoformat(), 'maxdate': end.isoformat(),
                'retmode': 'json', 'retmax': 500, 'retstart': offset, **auth,
            }).json()['esearchresult']
            if 'ERROR' in result or 'errorlist' in result:
                raise ValueError('PubMed search failed')
            count = int(result['count'])
            if count > 9999:
                if start == end:
                    raise ValueError('PubMed daily result exceeds the 9999-record search limit')
                middle = start + (end - start) // 2
                return (self._search(term, start, middle, client, auth)
                        + self._search(term, middle + timedelta(days=1), end, client, auth))
            page = result['idlist']
            ids.extend(page)
            offset += len(page)
            if offset >= count:
                return ids
            if not page:
                raise ValueError('PubMed pagination ended before total')

    def fetch(self, start: date, end: date, client: httpx.Client) -> list[Item]:
        cfg = self.config['pubmed']
        auth = {'api_key': os.environ['NCBI_API_KEY']} if os.environ.get('NCBI_API_KEY') else {}
        journals = ' OR '.join(f'"{journal}"[Journal]' for journal in cfg['journals'])
        queries = [f'({journals})'] if journals else []
        if cfg['query']:
            queries.append(f"({cfg['query']})" + (f' NOT ({journals})' if journals else ''))
        ids = list(dict.fromkeys(pmid for query in queries for pmid in self._search(query, start, end, client, auth)))
        items = []
        for offset in range(0, len(ids), 200):
            time.sleep(0.11 if auth else 0.34)
            response = request(client, f"{cfg['endpoint']}/efetch.fcgi", method='POST', data={
                'db': 'pubmed', 'id': ','.join(ids[offset:offset + 200]), 'retmode': 'xml', **auth,
            })
            root = ET.fromstring(response.content)
            if root.tag != 'PubmedArticleSet' or root.find('.//ERROR') is not None:
                raise ValueError('PubMed fetch failed')
            for record in root.findall('PubmedArticle'):
                article = record.find('MedlineCitation/Article')
                pmid = record.findtext('MedlineCitation/PMID')
                doi = record.findtext('.//ArticleId[@IdType="doi"]') or article.findtext('ELocationID[@EIdType="doi"]')
                doi = re.sub(r'^https?://(?:dx\.)?doi.org/', '', doi).strip() if doi else None
                pubdate = article.find('ArticleDate')
                if pubdate is None:
                    pubdate = article.find('Journal/JournalIssue/PubDate')
                published_at = _date(pubdate)
                if not start <= published_at <= end:
                    continue
                journal = article.findtext('Journal/Title', '')
                authors = [a.findtext('CollectiveName') or ' '.join(filter(None, [
                    a.findtext('ForeName') or a.findtext('Initials'), a.findtext('LastName')
                ])) for a in article.findall('AuthorList/Author')]
                items.append(Item(
                    id=f'pubmed:{doi or "pmid:" + pmid}', source=self.name, type='published',
                    title=_text(article.find('ArticleTitle')), url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
                    doi=doi, published_at=published_at, first_seen=end, authors=authors, org=None,
                    abstract='\n'.join(_text(a) for a in article.findall('Abstract/AbstractText')),
                    summary=None, primary_category=None, published_doi=None, preprint_id=None,
                    metadata={'pmid': pmid, 'journal': journal, 'xml': ET.tostring(record, encoding='unicode')},
                ))
        return collected(self.name, items)
