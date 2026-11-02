from datetime import date

import httpx

from pipeline.sources.arxiv import ArxivAdapter


def test_arxiv_filters_categories(source_config, fixture_text, respx_mock):
    route = respx_mock.get(source_config['arxiv']['endpoint']).respond(text=fixture_text('arxiv.xml'))
    start, end = date(2017, 1, 1), date(2025, 6, 30)
    with httpx.Client() as client:
        items = ArxivAdapter(source_config).fetch(start, end, client)
    assert len(items) == 1
    item = items[0]
    assert (item.id, item.type, item.doi, item.published_at) == (
        'arxiv:2506.13344', 'preprint', None, date(2025, 6, 16))
    assert 'single-cell' in item.abstract.lower()
    assert item.metadata['arxiv_primary_category'] == 'cs.LG'
    assert item.summary is item.primary_category is None
    assert item.first_seen == end
    query = route.calls[0].request.url.params['search_query']
    assert 'submittedDate:[201701010000 TO 202506302359]' in query
    assert 'cat:q-bio.*' in query


def test_arxiv_pagination_and_dates(source_config, fixture_text, respx_mock):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(fixture_text('arxiv.xml'))
    ns = {'a': 'http://www.w3.org/2005/Atom', 'o': 'http://a9.com/-/spec/opensearch/1.1/'}
    entries = root.findall('a:entry', ns)
    root.remove(entries[1])
    page1 = ET.tostring(root)
    root.remove(entries[0]); root.append(entries[1])
    route = respx_mock.get(source_config['arxiv']['endpoint']).mock(side_effect=[
        httpx.Response(200, content=page1), httpx.Response(200, content=ET.tostring(root))])
    with httpx.Client() as client:
        items = ArxivAdapter(source_config).fetch(date(2025, 6, 1), date(2025, 6, 30), client)
    assert len(items) == 1
    assert route.calls[1].request.url.params['start'] == '1'


def test_arxiv_keyword_gate_without_qbio_crosslisting(source_config, fixture_text, respx_mock):
    import xml.etree.ElementTree as ET
    from pipeline.sources.arxiv import NS
    root = ET.fromstring(fixture_text('arxiv.xml'))
    for entry in root.findall('atom:entry', NS):
        for tag in entry.findall('atom:category', NS):
            if tag.attrib['term'].startswith('q-bio.'):
                entry.remove(tag)
    respx_mock.get(source_config['arxiv']['endpoint']).respond(content=ET.tostring(root))
    with httpx.Client() as client:
        items = ArxivAdapter(source_config).fetch(date(2017,1,1), date(2025,6,30), client)
    assert [item.id for item in items] == ['arxiv:2506.13344']


def test_arxiv_qbio_does_not_need_keywords(source_config, fixture_text, respx_mock):
    source_config['keywords'] = []
    respx_mock.get(source_config['arxiv']['endpoint']).respond(text=fixture_text('arxiv.xml'))
    with httpx.Client() as client:
        items = ArxivAdapter(source_config).fetch(date(2017,1,1), date(2025,6,30), client)
    assert [item.id for item in items] == ['arxiv:2506.13344']
