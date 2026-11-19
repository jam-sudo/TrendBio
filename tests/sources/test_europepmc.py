from datetime import date
import json
from xml.etree import ElementTree as ET

import httpx
import pytest

from pipeline.collect import prepare_collected
from pipeline.sources.europepmc import EuropePmcAdapter, licensed_abstract, screen_record
from pipeline.store import Store


DAY = date(2026, 11, 4)
JOURNALS = {'europepmc': {'journals': [{'issn': '1234-5678', 'title': 'Rehabilitation'}]}}
RECORD = {'source': 'MED', 'pmid': '42', 'pmcid': 'PMC42', 'doi': '10.1234/study', 'title': 'Follow-up at three months',
          'firstPublicationDate': DAY.isoformat(), 'journalInfo': {'journal': {'essn': '1234-5678'}},
          'license': 'cc by', 'pubTypeList': {'pubType': ['Journal Article', 'Observational Study']},
          'commentCorrectionList': {'commentCorrection': [{'type': 'Erratum in', 'source': 'MED', 'id': '52'}]},
          'authorList': {'author': [{'fullName': 'A. Writer'}]}}
JATS = '''<article article-type="research-article" xml:lang="en" xmlns:xlink="http://www.w3.org/1999/xlink">
<front><article-meta><article-id pub-id-type="pmid">42</article-id><article-id pub-id-type="pmcid">PMC42</article-id>
<article-id pub-id-type="doi">10.1234/study</article-id><pub-date pub-type="epub"><year>2026</year><month>11</month><day>04</day></pub-date>
<permissions><license><license-p><ext-link xlink:href="https://creativecommons.org/licenses/by/4.0/">CC BY</ext-link></license-p></license></permissions>
<abstract><sec><title>Methods</title><p>A cohort of <italic>older</italic> adults.</p></sec><sec><title>Results</title><p>Uncertain estimates.</p></sec></abstract>
<abstract abstract-type="plain-language-summary"><p>A separate summary</p></abstract></article-meta></front></article>'''


def test_medical_collection_validates_fulltext_and_updates_existing_evidence(tmp_path):
    adapter = EuropePmcAdapter(JOURNALS)
    store = Store(tmp_path, 'medicine-health')
    records = [RECORD, {**RECORD, 'pmid': '99', 'pubTypeList': {'pubType': ['Published Erratum']}}]
    body = JATS

    def handle(req):
        if req.url.path.endswith('/search'):
            assert 'FIRST_PDATE:[2026-11-04 TO 2026-11-04]' in req.url.params['query']
            page = req.url.params['cursorMark']
            return httpx.Response(200, json={'hitCount': 2, 'resultList': {'result': records[:1] if page == '*' else records[1:]},
                                             'nextCursorMark': 'next'})
        assert req.url.path.endswith('/PMC42/fullTextXML')
        return httpx.Response(200, text=body)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        items = adapter.fetch(DAY, DAY, client)
        item, = prepare_collected(items, store, DAY, DAY, [adapter])
        assert item.metadata['correction_links'] == ['https://pubmed.ncbi.nlm.nih.gov/52/']
        assert item.metadata['publication_types'] == ['Journal Article', 'Observational Study']
        assert item.abstract == 'Methods\nA cohort of older adults.\nResults\nUncertain estimates.'
        assert item.authors == ['A. Writer']
        store.put_item(item.model_copy(update={'summary': 'Initial summary'}))
        assert prepare_collected(items, store, DAY, DAY, [adapter]) == []
        body = JATS.replace('Uncertain estimates.', 'Revised estimates.')
        changed, = prepare_collected(adapter.fetch(DAY, DAY, client), store, DAY, DAY, [adapter])
        assert changed.summary is None and changed.abstract.endswith('Revised estimates.')
        store.put_item(changed)
        records[0] = {**RECORD, 'commentCorrectionList': {'commentCorrection': [{'type': 'Retraction in', 'source': 'MED', 'id': '54'}]}}
        withdrawn, = prepare_collected(adapter.fetch(DAY, DAY, client), store, DAY, DAY, [adapter])
        assert not withdrawn.relevant and withdrawn.metadata['screening_status'] == 'retracted'
        decisions = json.loads(next((tmp_path/'medicine-health'/'audits').glob('europepmc-*.json')).read_text())
        assert decisions['42']['linked_notices'] == [{'type': 'Retraction in', 'pmid': '54'}]
        assert decisions['99']['status'] == 'notice-or-nonresearch'
        store.put_item(withdrawn)
        assert prepare_collected([], store, DAY, DAY, [adapter]) == []


@pytest.mark.parametrize(('old', 'new', 'reason'), [
    ('pub-type="epub"', 'pub-type="collection"', 'no-matching-exact-article-date'),
    ('<day>04</day>', '', 'no-matching-exact-article-date'),
    ('10.1234/study', '10.1234/unrelated', 'identifier-mismatch'),
    ('licenses/by/', 'licenses/by-nc/', 'unverified-article-license'),
    ('<permissions>', '<related-article related-article-type="retraction-forward"/><permissions>', 'retracted'),
    ('article-type="research-article"', 'article-type="editorial"', 'nonresearch-article-type'),
])
def test_medical_article_identity_rights_status_and_precise_dates(old, new, reason):
    assert licensed_abstract(ET.fromstring(JATS.replace(old, new)), RECORD) == (None, reason)


def test_protocol_concern_and_forward_correction():
    assert screen_record({**RECORD, 'title': 'Rehabilitation outcomes: study protocol'})[0] == 'protocol'
    assert screen_record({**RECORD, 'commentCorrectionList': {'commentCorrection': [{'type': 'Expression of concern in'}]}})[0] == 'concern'
    xml = JATS.replace('<permissions>', '<related-article related-article-type="correction-forward" xlink:href="PMC52"/><permissions>')
    evidence, status = licensed_abstract(ET.fromstring(xml), RECORD)
    assert status == 'eligible' and evidence['correction_links'] == ['https://pmc.ncbi.nlm.nih.gov/articles/PMC52/']


def test_incomplete_medical_index_cannot_retire_stored_records():
    adapter = EuropePmcAdapter(JOURNALS)
    page = {'hitCount': 2, 'resultList': {'result': [RECORD]}, 'nextCursorMark': 'next'}
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=page))) as client:
        with pytest.raises(ValueError, match='Incomplete'):
            adapter.fetch(DAY, DAY, client)
