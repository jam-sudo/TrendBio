"""Collect regular research papers from the publisher's open LIPIcs proceedings."""
from datetime import date
import re
import xml.etree.ElementTree as ET

import httpx

from pipeline.models import Item, Source
from pipeline.sources.base import collected, request


NS = {'d': 'https://drops.dagstuhl.de/storage/schema/dagstuhl/dagpub.xsd'}


def _text(article, tag):
    node = article.find('d:' + tag, NS)
    return ' '.join(''.join(node.itertext()).split()) if node is not None else ''


class DropsAdapter:
    name: Source = 'drops'

    def __init__(self, config):
        self.conferences = config['drops']['conferences']

    def fetch(self, start, end, client):
        papers = []
        for year in range(start.year, end.year + 1):
            for conference in self.conferences:
                parent = f'10.4230/lipics.{conference.lower()}.{year}'
                try:
                    record = request(client, f'https://api.datacite.org/dois/{parent}').json()['data']
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        continue
                    raise
                details = record['attributes']
                number = str(details['container']['volume'])
                if (record['id'].lower() != parent or not number.isdecimal()
                        or record['relationships']['client']['data']['id'] != 'lzi.drops'
                        or details['types']['resourceTypeGeneral'] != 'ConferenceProceeding'):
                    raise ValueError('Unexpected LIPIcs volume identity')
                url = f'https://drops.dagstuhl.de/entities/volume/LIPIcs-volume-{number}/metadata/xml'
                root = ET.fromstring(request(client, url).content)
                volume = root.find('d:volume', NS)
                articles = root.findall('d:article', NS)
                if volume is None or volume.findtext('d:volumeNo', namespaces=NS) != number or not articles:
                    raise ValueError('Incomplete DROPS proceedings volume')
                identifiers = [(article.findtext('d:doi', '', NS)).lower() for article in articles]
                expected = {link['relatedIdentifier'].lower() for link in details['relatedIdentifiers']
                            if link['relationType'] == 'HasPart' and link['relatedIdentifierType'] == 'DOI'}
                if (len(set(identifiers)) != len(articles) or set(identifiers) != expected
                        or any(not key.startswith(parent + '.') for key in identifiers)):
                    raise ValueError('DROPS and DataCite disagree on the contents of the volume')
                for article, doi in zip(articles, identifiers, strict=True):
                    if article.findtext('d:category', namespaces=NS) != 'Regular Paper':
                        continue
                    day = date.fromisoformat(article.findtext('d:publishedAt', '', NS))
                    license_url = article.findtext('d:licenseUrl', '', NS)
                    if not start <= day <= end or not re.fullmatch(
                            r'https://creativecommons\.org/licenses/by/(?:3|4)\.0/(?:legalcode)?', license_url):
                        continue
                    title = _text(article, 'title')
                    abstract = _text(article, 'abstract')
                    authors = [node.findtext('d:name', '', NS).strip() for node in article.findall('d:author', NS)]
                    if not title or not abstract or not authors or not all(authors):
                        continue
                    papers.append(Item(
                        id=f'doi:{doi}', source=self.name, type='published', title=title, abstract=abstract,
                        published_at=day, first_seen=end, url=f'https://doi.org/{doi}', doi=doi, authors=authors,
                        org=None, summary=None, primary_category=None, published_doi=None, preprint_id=None,
                        metadata={'conference': conference, 'journal': volume.findtext('d:title', '', NS),
                                  'event_dates': volume.findtext('d:event/d:date', '', NS), 'volume_doi': parent,
                                  'license': license_url},
                    ))
        return collected(self.name, papers)
