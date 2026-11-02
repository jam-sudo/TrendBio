"""Remove whole months of collected and derived data before a fresh backfill."""

from calendar import monthrange
from datetime import date
import shutil

from pipeline.jsonio import embeddings_shard_path, topic_path
from pipeline.store import Store


def wipe(store: Store, start: date, end: date) -> dict[str, int]:
    # shortcut: whole months only, matching the embedding shard layout; upgrade if partial-range wipes are ever needed
    if start.day != 1 or end.day != monthrange(end.year, end.month)[1]:
        raise ValueError('wipe operates on whole months')
    if start > end:
        raise ValueError('start must not be after end')

    counts = {'items': 0, 'days': 0, 'topics_deleted': 0, 'topics_trimmed': 0}
    topics = store.all_topics()
    deleted = set()
    trimmed = set()
    for topic in topics:
        history = [entry for entry in topic.history if not start <= entry.date <= end]
        if not history:
            deleted.add(topic.slug)
        elif len(history) != len(topic.history):
            trimmed.add(topic.slug)
        topic.history = history

    root = store.root / store.domain
    for month_index in range(start.year * 12 + start.month - 1, end.year * 12 + end.month):
        year, month = divmod(month_index, 12)
        month += 1
        month_name = f'{year:04d}-{month:02d}'
        items = root / 'items' / f'{year:04d}' / f'{month:02d}'
        if items.exists():
            counts['items'] += len(list(items.glob('*.json')))
            shutil.rmtree(items)
        for path in embeddings_shard_path(store.root, store.domain, month_name):
            path.unlink(missing_ok=True)
        for path in (root / 'days').glob(f'{month_name}-*.json'):
            path.unlink()
            counts['days'] += 1

    for topic in topics:
        if topic.slug in deleted:
            topic_path(store.root, store.domain, topic.slug).unlink()
        else:
            related = [slug for slug in topic.related if slug not in deleted]
            if topic.slug in trimmed or related != topic.related:
                topic.related = related
                store.put_topic(topic)
    counts['topics_deleted'] = len(deleted)
    counts['topics_trimmed'] = len(trimmed)
    (root / '.backfill_state.json').unlink(missing_ok=True)
    return counts
