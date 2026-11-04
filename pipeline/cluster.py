from collections import Counter
from datetime import date, timedelta
from hashlib import sha1

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from pipeline.config import Scoring
from pipeline.embed import l2_normalize
from pipeline.models import Item, Scores, Signals, Topic, TopicDay


BIOMEDICAL_FILLERS = {
    'cell', 'cells', 'analysis', 'study', 'based', 'using', 'data', 'novel',
    'approach', 'method', 'methods', 'human', 'mouse', 'patients',
}


def cluster_items(ids: list[str], X: np.ndarray, cfg: Scoring) -> list[list[str]]:
    if len(ids) < 2:
        return [ids] if ids and len(ids) >= cfg.min_cluster_size else []
    labels = AgglomerativeClustering(
        metric='cosine', linkage=cfg.cluster_linkage,
        distance_threshold=cfg.cluster_distance_threshold, n_clusters=None,
    ).fit_predict(X)
    groups: dict[int, list[str]] = {}
    for item_id, label in zip(ids, labels, strict=True):
        groups.setdefault(label, []).append(item_id)
    return [group for group in groups.values() if len(group) >= cfg.min_cluster_size]


def keyword_slug(titles: list[str], corpus_titles: list[str],
                 item_ids: list[str]) -> tuple[str, str]:
    vectorizer = TfidfVectorizer(
        stop_words=sorted(ENGLISH_STOP_WORDS | BIOMEDICAL_FILLERS),
        ngram_range=(1, 2), strip_accents='ascii',
        token_pattern=r'(?u)\b[a-z0-9]{2,}\b',
    )
    try:
        vectorizer.fit(corpus_titles)
    except ValueError as exc:
        if 'empty vocabulary' not in str(exc):
            raise
        terms = []
    else:
        matrix = vectorizer.transform(titles)
        title_counts = np.asarray((matrix > 0).sum(axis=0)).ravel()
        scores = np.asarray(matrix.sum(axis=0)).ravel() * title_counts / max(1, len(titles))
        scores[title_counts < (2 if len(titles) >= 4 else 1)] = 0
        ranked = sorted(zip(vectorizer.get_feature_names_out(), scores),
                        key=lambda pair: (-pair[1], pair[0]))
        terms, words = [], set()
        for term, score in ranked:
            tokens = term.split()
            if score > 0 and not words.intersection(tokens) and len(set(tokens)) == len(tokens):
                terms.append(term)
                words.update(tokens)
                if len(terms) == 2:
                    break
    if not terms:
        terms = ['untitled', 'topic']
    elif len(terms) == 1 and len(terms[0].split()) == 1:
        terms.append('topic' if terms[0] != 'topic' else 'research')
    suffix = sha1('\n'.join(sorted(item_ids)).encode()).hexdigest()[:4]
    label = ' '.join(terms)
    return label.replace(' ', '-') + '-' + suffix, label


def continuity_candidates(cluster_ids: list[str], centroid: np.ndarray, topics: list[Topic],
                          today: date, cfg: Scoring) -> list[tuple[float, float, Topic]]:
    candidates = []
    cluster = set(cluster_ids)
    for topic in topics:
        if not topic.history:
            continue
        nearest = min((entry.date for entry in topic.history),
                      key=lambda day: (abs((day - today).days), day))
        if abs((nearest - today).days) > cfg.continuity_max_gap_days:
            continue
        # Read the adjacent week in either direction for newest-to-oldest backfills.
        start, end = ((nearest - timedelta(days=6), nearest) if nearest <= today
                      else (nearest, nearest + timedelta(days=6)))
        recent_ids = {item_id for entry in topic.history if start <= entry.date <= end
                      for item_id in entry.item_ids}
        jaccard = len(cluster & recent_ids) / len(cluster | recent_ids)
        similarity = float(l2_normalize([topic.centroid])[0] @ l2_normalize([centroid])[0])
        if jaccard >= cfg.continuity_min_jaccard or similarity >= cfg.continuity_threshold:
            candidates.append((jaccard, similarity, topic))
    return sorted(candidates, key=lambda row: (-row[0], -row[1], row[2].slug))


def match_or_create(cluster_ids: list[str], centroid: np.ndarray, topics: list[Topic],
                    today: date, cfg: Scoring, titles: list[str], corpus_titles: list[str],
                    items_by_id: dict[str, Item], *, excluded_slugs: set[str] | None = None) -> Topic:
    counts = Counter(items_by_id[item_id].primary_category for item_id in cluster_ids)
    category = min(counts, key=lambda name: (-counts[name], name))
    secondary = sorted(name for name, count in counts.items()
                       if name != category and count / len(cluster_ids) >= .25)
    candidates = continuity_candidates(cluster_ids, centroid, [
        topic for topic in topics if not excluded_slugs or topic.slug not in excluded_slugs
    ], today, cfg)
    if candidates:
        topic = candidates[0][2]
        topic.centroid = centroid.tolist()
        topic.category = category
        topic.secondary_categories = secondary
        return topic
    slug, label = keyword_slug(titles, corpus_titles, cluster_ids)
    occupied = {topic.slug for topic in topics}
    attempt = 0
    while slug in occupied:
        attempt += 1
        suffix = sha1(('\n'.join(sorted(cluster_ids)) + f'\n{today}\n{attempt}').encode()).hexdigest()[:4]
        slug = label.replace(' ', '-') + '-' + suffix
    return Topic(
        slug=slug, label=label, category=category, secondary_categories=secondary,
        centroid=centroid.tolist(), history=[], headline=None, summary=None,
        synthesis=None, synthesis_model=None, synthesized_on=None,
    )


def append_history(topic: Topic, today: date, item_ids: list[str], count_7d: int) -> None:
    entry = TopicDay(
        date=today, rank=None, item_ids=item_ids, count_7d=count_7d,
        signals=Signals(published=0, preprint=0, code=0, industry=0, rise_ratio=0.0, star_gain_7d=0),
        scores=Scores(rise=0, diversity=0, code_velocity=0, volume=0, penalty=0, total=0),
    )
    topic.history = sorted([day for day in topic.history if day.date != today] + [entry],
                           key=lambda day: day.date)


def fill_unranked_days(topic: Topic, today: date, max_gap_days: int = 10) -> None:
    if not topic.history:
        return
    dates = {entry.date for entry in topic.history}
    # Empty padding must never extend the lifetime of an inactive topic.
    anchors = sorted({entry.date for entry in topic.history if entry.item_ids} | {today})
    for first, last in zip(anchors, anchors[1:]):
        if (last - first).days > max_gap_days:
            continue
        day = first + timedelta(days=1)
        while day < last:
            if day not in dates:
                append_history(topic, day, [], 0)
            day += timedelta(days=1)
