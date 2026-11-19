from datetime import date
from unittest.mock import patch
import xml.etree.ElementTree as ET

import httpx
import pytest

from pipeline.sources.arxiv import ArxivAdapter, NS
from pipeline.sources.base import load_config


def test_pilot_splits_capped_ranges_and_rejects_incomplete_pages(fixture_text):
    config = load_config('math')
    config['arxiv']['max_results_per_query'] = 1
    start, end = date(2025, 6, 15), date(2025, 6, 16)
    calls = []

    def reply(req):
        query = req.url.params['search_query']
        calls.append(query)
        feed = ET.fromstring(fixture_text('arxiv.xml'))
        entry, *others = feed.findall('atom:entry', NS)
        for extra in others:
            feed.remove(extra)
        single_day = '202506150000 TO 202506152359' in query or '202506160000 TO 202506162359' in query
        day = start if '202506150000' in query else end
        feed.find('opensearch:totalResults', NS).text = '1' if single_day else '2'
        entry.find('atom:id', NS).text = f'https://arxiv.org/abs/test-{day.day}v1'
        entry.find('atom:published', NS).text = f'{day}T00:00:00Z'
        entry.find('atom:category', NS).set('term', 'math.NA')
        return httpx.Response(200, content=ET.tostring(feed))

    with httpx.Client(transport=httpx.MockTransport(reply)) as client, patch('pipeline.sources.arxiv.time.sleep'):
        items = ArxivAdapter(config).fetch(start, end, client)
    assert len(calls) == 3
    assert [(i.id, i.first_seen) for i in items] == [('arxiv:test-15', end), ('arxiv:test-16', end)]

    def incomplete(req):
        feed = ET.fromstring(fixture_text('arxiv.xml'))
        for entry in feed.findall('atom:entry', NS):
            feed.remove(entry)
        feed.find('opensearch:totalResults', NS).text = '1'
        return httpx.Response(200, content=ET.tostring(feed))

    with httpx.Client(transport=httpx.MockTransport(incomplete)) as client, pytest.raises(ValueError, match='0 of 1'):
        ArxivAdapter(config).fetch(end, end, client)
