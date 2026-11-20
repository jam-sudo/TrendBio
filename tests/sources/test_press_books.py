from datetime import date

import httpx
import pytest

from pipeline.collect import intake_status
from pipeline.sources.crossref import CrossrefAdapter


DAY = date(2026, 11, 4)
DOI = '10.5555/manuscripts'
ISBN = '9781805118695'
PRESS = {'prefix': '10.5555', 'title': 'University Press', 'catalogue': 'https://press.example/pt/catalog'}
WORK = {'DOI': DOI, 'type': 'edited-book', 'edition-number': '1', 'title': ['Manuscritos'], 'ISBN': [ISBN],
        'published': {'date-parts': [[2026, 11, 4]]}, 'editor': [{'given': 'Ana', 'family': 'Silva'}],
        'resource': {'primary': {'URL': 'https://press.example/index.php/press/catalog/book/32'}}}
PAGE = f'''<meta name="citation_title" content="Manuscritos"><meta name="citation_language" content="pt">
<meta name="citation_publication_date" content="{DAY}"><meta name="citation_doi" content="{DOI}">
<meta name="citation_isbn" content="{ISBN}"><meta name="dc.type" content="Text.Book">
<meta name="dc.source" content="University Press"><meta name="dc.rights" content="https://creativecommons.org/licenses/by/4.0">
<meta name="citation_abstract" xml:lang="pt" content="História dos manuscritos.">
<div class="item series"><div><a href="/pt/catalog/series/history">História</a></div></div>
<aside><a href="/pt/catalog/series/other">Other series</a></aside>'''


def collect(works, respond):
    def reply(req):
        if req.url.host == 'api.crossref.org':
            assert req.url.path == '/prefixes/10.5555/works' and 'type:edited-book' in req.url.params['filter']
            return httpx.Response(200, json={'message': {'items': works, 'total-results': len(works)}})
        assert req.url.host == 'press.example'
        return respond(req.url.path)
    adapter = CrossrefAdapter({'crossref': {'journals': [], 'book_presses': [PRESS]}})
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        return adapter, adapter.fetch(DAY, DAY, client)


def test_identifies_whole_book_by_doi_and_credited_editors_and_preserves_original_language_and_rights():
    adapter, [book] = collect([WORK], lambda path: httpx.Response(200, text=PAGE))
    assert intake_status(adapter) == 'ok'
    assert (book.id, book.title, book.abstract, book.authors) == ('doi:' + DOI, 'Manuscritos', 'História dos manuscritos.', ['Ana Silva'])
    assert book.url == PRESS['catalogue'] + '/book/32' and book.published_at == DAY
    assert (book.metadata['publication_type'], book.metadata['book_series'], book.metadata['isbns']) == ('Edited book', ['História'], [ISBN])
    assert book.metadata['work_license'].endswith('/by/4.0/') and 'metadata_license' not in book.metadata
    assert book.metadata['date_evidence'] == 'https://api.crossref.org/works/' + DOI and not book.can_quote_in_english()


@pytest.mark.parametrize(('change', 'before', 'after'), [
    ({'type': 'book-chapter'}, '', ''), ({'edition-number': '2'}, '', ''),
    ({'edition-number': None}, '', ''), ({'relation': {'is-translation-of': [{}]}}, '', ''),
    ({'published-print': {'date-parts': [[2024]]}}, '', ''),
    ({'resource': {'primary': {'URL': 'https://other.example/catalog/book/32'}}}, '', ''),
    ({}, 'Text.Book', 'Text.Chapter'), ({}, 'Manuscritos', 'Other title'), ({}, str(DAY), '2026-11-03'),
    ({}, DOI, DOI + '.1'), ({}, ISBN, '9781805118657'), ({}, '/by/4.0', '/by-nc/4.0'), ({}, 'xml:lang="pt"', 'xml:lang="en"'),
])
def test_rejects_a_different_edition_unmatched_metadata_or_missing_work_rights(change, before, after):
    adapter, books = collect([{**WORK, **change}], lambda _: httpx.Response(200, text=PAGE.replace(before, after)))
    assert not books and intake_status(adapter) == 'ok'


def test_publisher_outage_preserves_other_books_and_marks_collection_partial(monkeypatch):
    monkeypatch.setattr('pipeline.sources.base.time.sleep', lambda _: None)
    missing = {**WORK, 'DOI': DOI + '-delayed', 'resource': {'primary': {'URL': 'https://press.example/catalog/book/33'}}}
    adapter, books = collect([missing, WORK], lambda path: httpx.Response(503) if path.endswith('/33') else httpx.Response(200, text=PAGE))
    assert [b.doi for b in books] == [DOI] and intake_status(adapter) == 'partial'
