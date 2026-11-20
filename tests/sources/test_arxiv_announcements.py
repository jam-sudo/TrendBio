from datetime import date, timedelta
import xml.etree.ElementTree as ET

import httpx
import pytest

from pipeline.sources.arxiv import NS
from pipeline.sources.arxiv_announcements import PhysicsAnnouncements
from pipeline.sources.base import load_config


DAY = date(2026, 9, 18)


def listing(day, total, groups):
    parts = [f'<h1>Catchup results for Physics on {day:%a, %d %b %Y}</h1>',
             f'<div>Total of {total} entries for {day:%a, %d %b %Y}\nView page:</div>']
    for section, count, ids in groups:
        parts.append(f'<dl><h3>{section} submissions (showing {len(ids)} of {count} entries)</h3>')
        for key in ids:
            parts.append(f'<dt><a title="Abstract" id="{key}" href="/abs/{key}">arXiv:{key}</a></dt>')
        parts.append('</dl>')
    return ''.join(parts)


def first_versions(keys, *, wrong=False):
    a = '{' + NS['atom'] + '}'
    root = ET.Element(a + 'feed')
    for key in keys:
        entry = ET.SubElement(root, a + 'entry')
        url = 'https://arxiv.org/abs/' + key + ('v2' if wrong else 'v1')
        for name, content in {'id': url, 'published': '2026-07-29T15:27:12Z', 'updated': '2026-07-29T15:27:12Z',
                              'title': 'Original title ' + key, 'summary': 'Original abstract.'}.items():
            ET.SubElement(entry, a + name).text = content
        subject = 'math.NA' if key == '2609.00002' else 'physics.atom-ph'
        ET.SubElement(entry, a + 'category', term=subject)
        ET.SubElement(entry, '{' + NS['arxiv'] + '}primary_category', term=subject)
    return ET.tostring(root)


def test_mailing_pages_empty_days_crosslists_and_original_versions(monkeypatch):
    adapter = PhysicsAnnouncements(load_config('physics-expanded'))
    calls = []
    def reply(client, url, **params):
        calls.append((url, params))
        if 'id_list' in params:
            assert params == {'id_list': '2609.00001v1,2609.00002v1,2609.20286v1', 'max_results': 3}
            return httpx.Response(200, content=first_versions(['2609.20286', '2609.00002', '2609.00001']))
        when = date.fromisoformat(url.rsplit('/', 1)[1])
        if when == DAY:
            groups = ([('New', 2, ['2609.00001', '2609.00002'])] if params['page'] == 1
                      else [('Cross', 1, ['2609.20286']), ('Replacement', 1, ['hep-th/9912001'])])
            return httpx.Response(200, text=listing(when, 4, groups))
        return httpx.Response(200, text=listing(when, 0, []))

    monkeypatch.setattr(adapter, '_get', reply)
    items = adapter.fetch(DAY, DAY + timedelta(days=1), None)
    assert len(calls) == 4 and len(items) == 2
    paper = next(i for i in items if i.id == 'arxiv:2609.20286')
    assert paper.url.endswith('2609.20286v1') and paper.published_at == DAY and paper.first_seen == DAY + timedelta(days=1)
    assert paper.metadata['arxiv_listing'] == 'cross' and paper.metadata['arxiv_submitted'] == '2026-07-29'
    assert adapter.mailings == {'2026-09-18': {'new': 2, 'cross': 1, 'replacement': 1},
                                '2026-09-19': {'new': 0, 'cross': 0, 'replacement': 0}}


@pytest.mark.parametrize('error', ['wrong day', 'repeated page', 'missing version', 'later version', 'wrong section count'])
def test_fails_before_returning_a_partial_or_mislabeled_collection(error, monkeypatch):
    adapter = PhysicsAnnouncements(load_config('physics-expanded'))
    def reply(client, url, **params):
        if 'id_list' in params:
            return httpx.Response(200, content=first_versions([] if error == 'missing version' else ['2609.20286'],
                                                               wrong=error == 'later version'))
        when = DAY - timedelta(days=1) if error == 'wrong day' else DAY
        return httpx.Response(200, text=listing(when, 2 if error == 'repeated page' else 1,
                              [('New', 2 if error == 'wrong section count' else 1, ['2609.20286'])]))

    monkeypatch.setattr(adapter, '_get', reply)
    with pytest.raises(ValueError, match='arXiv'):
        adapter.fetch(DAY, DAY, None)


@pytest.mark.parametrize('body, expected', [
    ('<title>Invalid date. Catchup only allowed for past 90 days</title>', ValueError),
    ('Bad query', httpx.HTTPStatusError),
])
def test_expired_mailing_distinguished_from_other_bad_requests(body, expected, monkeypatch):
    adapter = PhysicsAnnouncements(load_config('physics-expanded'))
    monkeypatch.setattr('pipeline.sources.arxiv_announcements.time.sleep', lambda _: None)
    transport = httpx.MockTransport(lambda request: httpx.Response(400, text=body))
    with httpx.Client(transport=transport) as client, pytest.raises(expected) as error:
        adapter.fetch(DAY, DAY, client)
    if expected is ValueError:
        assert f'90 days of Physics mailings. {DAY} is outside the archive' in str(error.value)
    assert adapter.mailings == {}
