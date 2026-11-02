import shutil
from datetime import date

import numpy as np
import pytest
from typer.testing import CliRunner

from pipeline.__main__ import app
from pipeline.store import Store


START = date(2026, 10, 1)
END = date(2026, 10, 31)
NOVEMBER = date(2026, 11, 1)


@pytest.fixture
def store(tmp_path, fixtures_root):
    root = tmp_path / 'data'
    shutil.copytree(fixtures_root / 'data', root)
    store = Store(root, 'computational')
    october_item = store.items_between(START, END)[0]
    november_item = october_item.model_copy(update={
        'id': 'biorxiv:november', 'published_at': NOVEMBER, 'first_seen': NOVEMBER,
    })
    store.put_item(november_item)
    for item in (october_item, november_item):
        store.put_embedding(item.id, np.ones(5))
    return store


def test_wipe_removes_month_items_days_embeddings_and_checkpoint(store):
    from pipeline.wipe import wipe

    root = store.root / store.domain
    checkpoint = root / '.backfill_state.json'
    checkpoint.write_text('{}')
    protected = ['llm_spend.json', 'github_repos.json', 'github_stars.json']
    for name in protected:
        (root / name).write_text('{"keep": true}\n')
    november = {path: path.read_bytes() for pattern in (
        'days/2026-11-*.json', 'items/2026/11/*.json', 'embeddings/2026-11.*',
    ) for path in root.glob(pattern)}
    n_items = len(list((root / 'items/2026/10').glob('*.json')))
    n_days = len(list((root / 'days').glob('2026-10-*.json')))
    counts = wipe(store, START, END)
    assert counts['items'] == n_items > 0
    assert counts['days'] == n_days > 0
    assert not (root / 'items/2026/10').exists()
    assert not list((root / 'embeddings').glob('2026-10.*'))
    assert not list((root / 'days').glob('2026-10-*.json'))
    assert not checkpoint.exists()
    assert (root / 'days/2026-11-01.json').exists()
    assert (root / 'items/2026/11').exists()
    assert all(path.read_bytes() == contents for path, contents in november.items())
    assert all((root / name).read_text() == '{"keep": true}\n' for name in protected)
    assert wipe(store, START, END) == dict.fromkeys(counts, 0)


def test_wipe_trims_topic_history_and_deletes_empty_topics(store):
    from pipeline.wipe import wipe

    deleted, kept, related_only = store.all_topics()[:3]
    deleted.history = [entry for entry in deleted.history if START <= entry.date <= END]
    kept.history = [entry for entry in kept.history if entry.date >= START]
    kept.related = [deleted.slug, related_only.slug]
    related_only.history = [entry for entry in related_only.history if entry.date == NOVEMBER]
    related_only.related = [deleted.slug, kept.slug]
    assert deleted.history and any(entry.date == NOVEMBER for entry in kept.history)
    for topic in (deleted, kept, related_only):
        store.put_topic(topic)
    trimmed = sum(any(START <= entry.date <= END for entry in topic.history)
                  for topic in store.all_topics() if topic.slug != deleted.slug)
    counts = wipe(store, START, END)
    assert store.get_topic(deleted.slug) is None
    assert [entry.date for entry in store.get_topic(kept.slug).history] == [NOVEMBER]
    assert store.get_topic(kept.slug).related == [related_only.slug]
    assert store.get_topic(related_only.slug).related == [kept.slug]
    assert counts['topics_deleted'] == 1
    assert counts['topics_trimmed'] == trimmed


@pytest.mark.parametrize('start,end', [
    (date(2026, 10, 2), END), (START, date(2026, 10, 30)),
    (date(2026, 11, 1), END),
])
def test_wipe_rejects_partial_months(store, start, end):
    from pipeline.wipe import wipe

    before = {path: path.read_bytes() for path in store.root.rglob('*') if path.is_file()}
    with pytest.raises(ValueError):
        wipe(store, start, end)
    assert all(path.read_bytes() == contents for path, contents in before.items())


def test_cli_wipe_prints_counts(store):
    result = CliRunner().invoke(app, ['wipe', '--domain', store.domain,
                                     '--from', str(START), '--to', str(END),
                                     '--data-root', str(store.root)])
    assert result.exit_code == 0, result.output
    assert len(result.output.strip().splitlines()) == 1
    counts = dict(field.split('=') for field in result.output.split())
    assert set(counts) == {'items', 'days', 'topics_deleted', 'topics_trimmed'}
    assert int(counts['items']) > 0 and int(counts['days']) > 0


def test_wipe_spans_year_boundary_and_leap_month(store):
    from pipeline.wipe import wipe

    item = store.items_between(START, END)[0]
    for day in (date(2027, 12, 1), date(2028, 1, 1), date(2028, 2, 29)):
        added = item.model_copy(update={'id': f'biorxiv:{day}', 'first_seen': day})
        store.put_item(added)
        store.put_embedding(added.id, np.ones(5))
    counts = wipe(store, date(2027, 12, 1), date(2028, 2, 29))
    assert counts['items'] == 3
    assert store.items_between(START, END)
    assert not store.items_between(date(2027, 12, 1), date(2028, 2, 29))
    assert not list((store.root / store.domain / 'embeddings').glob('2028-*'))
