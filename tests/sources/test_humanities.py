from datetime import date
import json
from uuid import UUID

import httpx
import pytest

from pipeline.collect import intake_status
from pipeline.dedupe import dedupe, parallel_openedition_ids
from pipeline.sources.base import CC0, load_config
from pipeline.sources.openedition import OpenEditionAdapter
from pipeline.sources.thoth import ThothAdapter
from pipeline.window_trial import trial_records


DAY = date(2026, 11, 4)
ISBN = '9781805118695'
DOI = '10.1234/work'
BOOK = {
    'workId': str(UUID(int=1)), 'edition': 1, 'workType': 'EDITED_BOOK', 'workStatus': 'ACTIVE',
    'publicationDate': str(DAY), 'doi': None, 'relations': [], 'landingPage': None,
    'titles': [{'localeCode': 'FR', 'canonical': True, 'fullTitle': 'Écrits'},
               {'localeCode': 'EN', 'canonical': False, 'fullTitle': 'Writings'}],
    'languages': [{'languageCode': 'FRE', 'languageRelation': 'ORIGINAL'}],
    'abstracts': [{'localeCode': 'EN', 'abstractType': 'SHORT', 'content': '<p>Edited manuscripts.</p>'}],
    'contributions': [{'contributionType': 'EDITOR', 'fullName': 'A. Editor'}],
    'subjects': [{'subjectType': 'THEMA', 'subjectCode': 'DS'}],
    'publications': [{'isbn': ISBN}], 'imprint': {'imprintName': 'A Press'},
    'issues': [{'series': {'seriesName': 'Manuscript studies'}}],
    'license': 'https://creativecommons.org/licenses/by-nc/4.0/',
}
REGISTERED = {'DOI': DOI, 'type': 'edited-book', 'published': {'date-parts': [[2026, 11, 4]]},
              'title': ['Writings'], 'ISBN': [ISBN]}


def registry(records):
    return httpx.Response(200, json={'message': {'total-results': len(records), 'items': records}})


def test_thoth_confirms_the_whole_book_by_isbn_and_keeps_native_credit_and_rights():
    def reply(req):
        if req.url.host == 'api.thoth.pub':
            assert json.loads(req.content)['variables']['start'] == '2026-11-03T23:59:59Z'
            records = [BOOK, {**BOOK, 'workId': str(UUID(int=2)), 'edition': 2},
                       {**BOOK, 'workId': str(UUID(int=3)), 'relations': [{'relationType': 'IS_TRANSLATION_OF'}]},
                       {**BOOK, 'workId': str(UUID(int=4)), 'subjects': []}]
            return httpx.Response(200, json={'data': {'works': records}})
        assert 'isbn:' + ISBN in req.url.params['filter']
        return registry([REGISTERED, {**REGISTERED, 'DOI': DOI + '.1', 'type': 'book-chapter'}])

    cfg = load_config('humanities-arts')
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        adapter = ThothAdapter(cfg)
        item, = adapter.fetch(DAY, DAY, client)
    assert list(adapter.decisions.values()) == ['eligible', 'other-edition-or-type', 'other-edition-or-type', 'outside-pilot-subjects']
    assert (item.doi, item.title, item.abstract, item.authors) == (DOI, 'Writings', 'Edited manuscripts.', ['A. Editor'])
    assert (item.metadata['original_title'], item.metadata['original_languages'], item.metadata['publication_type']) == ('Écrits', ['fre'], 'Edited book')
    assert item.metadata['work_license'] == BOOK['license'] and item.metadata['metadata_license'] == CC0
    assert item.metadata['book_series'] == ['Manuscript studies']
    assert item.metadata['date_evidence'] == 'https://api.crossref.org/works/' + DOI
    other_language = item.model_copy(update={'source': 'openedition', 'id': 'openedition:other', 'doi': None, 'title': 'Écrits'})
    assert [w.id for w in dedupe([item, other_language])] == [item.id]


@pytest.mark.parametrize('change', [{'type': 'book-chapter'}, {'ISBN': ['9781805118688']}, {'title': ['Another work']},
                                    {'published': {'date-parts': [[2026, 11]]}}, {'edition-number': '2'},
                                    {'published-print': {'date-parts': [[2019]]}}, {'DOI': DOI + '.other'}])
def test_book_corroboration_requires_matching_edition_identity_and_exact_date(change):
    adapter = ThothAdapter(load_config('humanities-arts'))
    with httpx.Client(transport=httpx.MockTransport(lambda req: registry([{**REGISTERED, **change}]))) as client:
        assert adapter.book({**BOOK, 'doi': DOI}, DAY, DAY, client)[0] is None


def test_native_publisher_date_wins_over_a_later_catalogue_date():
    landing = 'https://books.ugp.rug.nl/ugp/catalog/book/9'
    html = f'<meta name="citation_publication_date" content="2026-09-25"><meta name="citation_title" content="Écrits"><meta name="citation_isbn" content="{ISBN}">'
    def reply(req):
        assert str(req.url) == landing
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        adapter = ThothAdapter(load_config('humanities-arts'))
        assert adapter.book({**BOOK, 'landingPage': landing}, DAY, DAY, client)[0] is None
        actual = date(2026, 9, 25)
        book, status = adapter.book({**BOOK, 'landingPage': landing}, actual, actual, client)
        assert status == 'eligible' and book.doi is None and book.metadata['date_evidence'] == landing


def test_portuguese_title_and_brazilian_portuguese_description_share_a_language():
    record = {**BOOK, 'titles': [{'localeCode': 'PT', 'canonical': True, 'fullTitle': 'Escritos'}],
              'subjects': [{'subjectType': 'BIC', 'subjectCode': 'DS'}],
              'abstracts': [{'localeCode': 'PT_BR', 'abstractType': 'LONG', 'content': 'Uma análise.'}]}
    with httpx.Client(transport=httpx.MockTransport(lambda req: registry([{**REGISTERED, 'title': ['Escritos']}]))) as client:
        book, status = ThothAdapter(load_config('humanities-arts')).book(record, DAY, DAY, client)
        assert status == 'eligible' and book.abstract == 'Uma análise.' and book.metadata['abstract_language'] == 'pt'


def test_transient_registry_outage_is_reported_and_other_books_survive(monkeypatch):
    def reply(req):
        if '9781805118688' in req.url.params['filter']:
            return httpx.Response(429)
        return registry([REGISTERED])
    delayed = {**BOOK, 'workId': str(UUID(int=7)), 'publications': [{'isbn': '9781805118688'}]}
    monkeypatch.setattr('pipeline.sources.thoth.catalog_books', lambda *args: [(delayed, DAY), (BOOK, DAY)])
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        a = ThothAdapter(load_config('humanities-arts'))
        book, = a.fetch(DAY, DAY, client)
        assert book.doi == DOI and intake_status(a) == 'partial'
        assert a.decisions[delayed['workId']] == 'book-date-source-unavailable'


def native_record(key, kind='article', issued='2026', platform='journals'):
    handle = '20.500.13089/' + key
    return f'''<record><header><identifier>{handle}</identifier><setSpec>{platform}:demo</setSpec></header>
    <metadata><mods xmlns="http://www.loc.gov/mods/v3">
    <identifier type="hdl">{handle}</identifier><identifier type="doi">{DOI}</identifier><identifier type="eisbn">{ISBN}</identifier>
    <location><url>https://{platform}.openedition.org/demo/22</url></location>
    <typeOfResource authority="openedition">{kind}</typeOfResource><language><languageTerm type="code">fr</languageTerm></language>
    <originInfo><dateIssued>{issued}</dateIssued><dateOther type="published_on_openedition">{DAY}</dateOther></originInfo>
    <titleInfo><title>Écrits</title></titleInfo><titleInfo type="translated"><title xml:lang="en">Writings</title></titleInfo>
    <abstract type="summary" xml:lang="en">One argument.</abstract><abstract type="excerpt" xml:lang="fr">Extrait.</abstract>
    <relatedItem type="host"><identifier type="hdl">20.500.13089/issue</identifier><part><detail type="volume"><number>30-3</number></detail></part></relatedItem>
    <name><namePart>A. Author</namePart><role><roleTerm>aut</roleTerm></role></name>
    <accessCondition type="license" valueURI="https://creativecommons.org/licenses/by-nc/4.0/"/>
    </mods></metadata></record>'''


def test_openedition_counts_parallel_language_versions_once_and_keeps_distinct_articles():
    english = native_record('english').replace('type="code">fr', 'type="code">en')
    translated = native_record('french').replace(DOI, DOI + '.fr').replace('</mods>', '''
        <name><namePart>Translator</namePart><role><roleTerm>trl</roleTerm></role></name></mods>''')
    controls = native_record('other-argument').replace('One argument.', 'Another argument.').replace(DOI, DOI + '.other')
    cfg = {'openedition': {'venues': [{'set': 'journals:demo', 'title': 'Journal'}]}}
    records = [translated, controls, english]
    def reply(req):
        return httpx.Response(200, text='<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>'
                              + ''.join(records) + '</ListRecords></OAI-PMH>')
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        adapter = OpenEditionAdapter(cfg)
        control, original = adapter.fetch(DAY, DAY, client)
        assert [p.id.rsplit('/', 1)[1] for p in [control, original]] == ['other-argument', 'english']
        assert adapter.decisions['20.500.13089/french'] == 'parallel-language-edition'
        records[:] = [translated]
        translation, = adapter.fetch(DAY, DAY, client)
        assert translation.metadata['has_translator'] and adapter.decisions['20.500.13089/french'] == 'eligible'

    legacy = translation.model_copy(update={'metadata': {k: v for k, v in translation.metadata.items() if k != 'has_translator'}})
    assert parallel_openedition_ids([original, legacy]) == {legacy.id}
    assert parallel_openedition_ids([legacy, original, control]) == {legacy.id}
    for metadata in [{'issue_url': 'another-issue'}, {'original_languages': ['en']}, {'original_languages': []}]:
        different = legacy.model_copy(update={'metadata': {**legacy.metadata, **metadata}})
        assert not parallel_openedition_ids([original, different])
    assert not parallel_openedition_ids([original, legacy.model_copy(update={'authors': ['Another author']})])
    assert parallel_openedition_ids([original.model_copy(update={'metadata': {**original.metadata, 'has_translator': True}}),
                                    legacy]) == {original.id}


def test_openedition_requires_scholarly_type_and_source_date_and_counts_a_volume_once(monkeypatch):
    venues = [{'set': p + ':demo', 'title': 'Publisher'} for p in ['journals', 'books']]
    cfg = {'openedition': {'venues': venues}, 'hints': {'collection': {'journals:demo': ['languages-literature']}}}
    def reply(req):
        if req.url.host == 'api.crossref.org':
            return registry([REGISTERED])
        assert req.url.params['from'] == '2026-11-04T00:00:00Z'
        if req.url.params['set'].startswith('books'):
            body = native_record('book', 'book', platform='books') + native_record('chapter', 'chapter', platform='books')
        else:
            body = native_record('article') + native_record('review', 'review') + native_record('old', issued='2023')
        return httpx.Response(200, text=f'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>{body}</ListRecords></OAI-PMH>')

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        adapter = OpenEditionAdapter(cfg)
        article, book = adapter.fetch(DAY, DAY, client)
        assert article.metadata['original_title'] == 'Écrits' and article.metadata['abstract_language'] == 'en'
        assert article.metadata['date_basis'] == 'Online publication date'
        assert article.metadata['issue'] == '30-3' and article.metadata['issue_url'] == 'https://hdl.handle.net/20.500.13089/issue'
        assert book.metadata['date_basis'] == 'Confirmed publication date' and book.metadata['metadata_license'] == CC0
        assert sorted(adapter.decisions.values()) == ['chapter', 'eligible', 'eligible', 'outside-window-or-backlist', 'review']
        monkeypatch.setattr('pipeline.window_trial.load_config', lambda domain: cfg)
        monkeypatch.setattr(OpenEditionAdapter, 'fetch', lambda *args: [article, book.model_copy(update={'doi': '10.1234/book'})])
        assert [r[4] for r in trial_records('humanities-arts', [], DAY, DAY, client)] == ['Journal article', 'Scholarly book']
