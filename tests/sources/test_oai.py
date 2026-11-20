from datetime import date

import httpx
import pytest

from pipeline.sources.oai import OaiAdapter


JOURNAL = {'title': 'Farm Studies', 'issn': '1234-5678', 'endpoint': 'https://journal.example/oai'}
DAY = date(2026, 11, 4)
RECORD = """<record><header><identifier>article-{id}</identifier><datestamp>2026-11-18</datestamp></header>
  <metadata><oai_dc:dc>
    <dc:source>1234-5678</dc:source><dc:date>{day}</dc:date><dc:language>spa</dc:language>
    <dc:type>info:eu-repo/semantics/article</dc:type><dc:type>info:eu-repo/semantics/publishedVersion</dc:type>
    <dc:identifier>https://doi.org/10.1234/SAMPLE</dc:identifier><dc:creator>Pérez, Ana</dc:creator>
    <dc:title xml:lang="es">Riego</dc:title><dc:title xml:lang="en-US">Irrigation</dc:title>
    <dc:description xml:lang="en">Field measurements.</dc:description><dc:description xml:lang="es">Mediciones.</dc:description>
    <dc:rights>Copyright 2026</dc:rights><dc:rights>https://creativecommons.org/licenses/{rights}/4.0</dc:rights>
  </oai_dc:dc></metadata></record>"""


def envelope(body):
    return f'''<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
      xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
      xmlns:dc="http://purl.org/dc/elements/1.1/">{body}</OAI-PMH>'''


def test_journal_uses_publication_date_one_doi_and_a_paired_title_and_abstract():
    def reply(req):
        if 'resumptionToken' in req.url.params:
            assert dict(req.url.params) == {'verb': 'ListRecords', 'resumptionToken': 'next'}
            body = RECORD.format(id=3, day=DAY, rights='by-nc') + '<record><header status="deleted"><identifier>four</identifier></header></record>'
        else:
            assert dict(req.url.params) == {'verb': 'ListRecords', 'metadataPrefix': 'oai_dc', 'from': DAY.isoformat()}
            body = RECORD.format(id=1, day=DAY, rights='by') + RECORD.format(id=2, day='2026-10-01', rights='by')
            body += '<resumptionToken completeListSize="4">next</resumptionToken>'
        return httpx.Response(200, text=envelope('<ListRecords>' + body + '</ListRecords>'))

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        paper, = OaiAdapter({'oai': {'journals': [JOURNAL]}}).fetch(DAY, DAY, client)
    assert (paper.id, paper.title, paper.abstract, paper.published_at) == ('doi:10.1234/sample', 'Irrigation', 'Field measurements.', DAY)
    assert paper.authors == ['Pérez, Ana']
    assert (paper.metadata['language'], paper.metadata['abstract_language'], paper.metadata['abstract_languages']) == ('es', 'en', ['en', 'es'])


@pytest.mark.parametrize('section', ['journal:ART', 'journal:EDI'])
def test_requested_article_section_matches_each_record(section):
    journal = {**JOURNAL, 'article_set': 'journal:ART'}
    def reply(req):
        assert req.url.params.get('set') == 'journal:ART'
        record = RECORD.format(id=1, day=DAY, rights='by').replace('</header>', f'<setSpec>{section}</setSpec></header>')
        return httpx.Response(200, text=envelope('<ListRecords>' + record + '</ListRecords>'))

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        adapter = OaiAdapter({'oai': {'journals': [journal]}})
        if section == 'journal:ART':
            paper, = adapter.fetch(DAY, DAY, client)
            assert paper.doi == '10.1234/sample'
        else:
            with pytest.raises(ValueError, match='another OAI-PMH section'):
                adapter.fetch(DAY, DAY, client)


@pytest.mark.parametrize(('body', 'valid'), [
    ('<error code="noRecordsMatch">Empty</error>', True),
    ('<error code="badArgument">Bad date</error>', False),
    ('<ListRecords>' + RECORD.format(id=1, day=DAY, rights='by') + '<resumptionToken completeListSize="2"/></ListRecords>', False),
])
def test_journal_does_not_report_partial_or_failed_pages_as_empty(body, valid):
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=envelope(body)))) as client:
        adapter = OaiAdapter({'oai': {'journals': [JOURNAL]}})
        if valid:
            assert adapter.fetch(DAY, DAY, client) == []
        else:
            with pytest.raises(ValueError):
                adapter.fetch(DAY, DAY, client)
