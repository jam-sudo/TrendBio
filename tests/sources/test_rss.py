from datetime import date
import hashlib
import xml.etree.ElementTree as ET

import httpx
import pytest

from pipeline.sources.rss import RssAdapter


def test_company_feed_entries_are_not_keyword_filtered(source_config, fixture_text, respx_mock):
    source_config['keywords'] = []
    source_config['industry_keywords'] = []
    source_config['rss']['feeds'] = [{'name':'insitro','url':'https://www.insitro.com/feed/','kind':'company'}]
    respx_mock.get('https://www.insitro.com/feed/').respond(text=fixture_text('rss.xml'))
    with httpx.Client() as client:
        items=RssAdapter(source_config).fetch(date(2026,10,1),date(2026,10,31),client)
    assert len(items) == 3
    item=items[0]
    root=ET.fromstring(fixture_text('rss.xml'))
    assert (item.id,item.type,item.doi,item.published_at) == (
        'rss:'+root.findtext('channel/item/guid'),'industry',None,date(2026,10,15))
    assert item.org == 'insitro'
    assert item.metadata['feed_kind'] == 'company'
    assert item.summary is item.primary_category is None
    assert item.first_seen == date(2026,10,31)


@pytest.mark.parametrize('keyword', ['COLLABORATION', 'patient heterogeneity'])
def test_news_feed_uses_industry_keywords(source_config, fixture_text, respx_mock, keyword):
    source_config['keywords'] = ['extraterrestrial']
    source_config['industry_keywords'] = [keyword]
    source_config['rss']['feeds'] = [{'name': 'news', 'url': 'https://example.org/feed', 'kind': 'news'}]
    respx_mock.get('https://example.org/feed').respond(text=fixture_text('rss.xml'))
    with httpx.Client() as client:
        items = RssAdapter(source_config).fetch(date(2026, 10, 1), date(2026, 10, 31), client)
    assert len(items) == 1
    assert items[0].id == 'rss:https://www.insitro.com/?p=2697'
    assert items[0].metadata['feed_kind'] == 'news'


def test_rss_url_hash_and_date_filter(source_config, fixture_text, respx_mock):
    root=ET.fromstring(fixture_text('rss.xml')); first=root.find('channel/item');first.remove(first.find('guid'))
    url=first.findtext('link')
    source_config['rss']['feeds']=[{'name':'insitro','url':'https://www.insitro.com/feed/','kind':'company'}]
    respx_mock.get('https://www.insitro.com/feed/').respond(content=ET.tostring(root))
    with httpx.Client() as client:
        items=RssAdapter(source_config).fetch(date(2026,10,15),date(2026,10,15),client)
    assert len(items)==1
    assert items[0].id == 'rss:'+hashlib.sha256(url.encode()).hexdigest()


def test_bad_feed_is_failure(source_config,respx_mock):
    source_config['rss']['feeds']=[{'name':'broken','url':'https://example.org/feed','kind':'news'}]
    respx_mock.get('https://example.org/feed').respond(text='<html>Not a feed</html>')
    with httpx.Client() as client, pytest.raises(ValueError):
        RssAdapter(source_config).fetch(date(2026,1,1),date(2026,12,31),client)


@pytest.mark.parametrize('status', [200, 404])
def test_bad_feed_keeps_other_feeds(source_config, fixture_text, respx_mock, caplog, status):
    source_config['rss']['feeds'] = [
        {'name': 'broken', 'url': 'https://example.org/bad', 'kind': 'company'},
        {'name': 'insitro', 'url': 'https://example.org/good', 'kind': 'company'},
    ]
    respx_mock.get('https://example.org/bad').respond(status, text='<html>Not a feed</html>')
    respx_mock.get('https://example.org/good').respond(text=fixture_text('rss.xml'))
    with httpx.Client() as client:
        items = RssAdapter(source_config).fetch(date(2026, 10, 1), date(2026, 10, 31), client)
    assert len(items) == 3
    assert 'feed=broken' in caplog.text
    assert ('ValueError' if status == 200 else 'HTTPStatusError') in caplog.text


def test_successful_feed_without_historical_items_is_not_failure(source_config, fixture_text, respx_mock):
    source_config['rss']['feeds'] = [
        {'name': 'insitro', 'url': 'https://example.org/feed', 'kind': 'company'},
    ]
    respx_mock.get('https://example.org/feed').respond(text=fixture_text('rss.xml'))
    with httpx.Client() as client:
        assert RssAdapter(source_config).fetch(date(2020, 1, 1), date(2020, 1, 31), client) == []
