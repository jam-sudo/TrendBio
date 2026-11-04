"""Deterministic topic layouts, without embedding or language-model calls."""

import logging
from datetime import datetime, timezone

import numpy as np
from sklearn.decomposition import PCA
from sklearn.metrics.pairwise import cosine_similarity

from pipeline.config import Scoring
from pipeline.models import MapData
from pipeline.store import Store

logger = logging.getLogger(__name__)


def _layout(vectors, old_coordinates=None, new_vectors=None):
    if len(vectors) == 1:
        return np.full((1, 2), 0.5)
    if len(vectors) < 10:
        reducer = PCA(n_components=min(2, vectors.shape[1]))
    else:
        from umap import UMAP
        reducer = UMAP(n_neighbors=15, min_dist=0.1, metric='cosine', random_state=42)
    raw = reducer.fit_transform(vectors)
    if old_coordinates is not None:
        if isinstance(reducer, PCA):
            # Align PCA's changing axes to the saved layout, without moving its anchors.
            alignment = np.linalg.lstsq(np.c_[raw, np.ones(len(raw))], old_coordinates, rcond=None)[0]
            projected = reducer.transform(new_vectors)
            return np.clip(np.c_[projected, np.ones(len(projected))] @ alignment, 0, 1)
        low, span = raw.min(axis=0), np.ptp(raw, axis=0)
        span = np.where(span > 0, span, 1)
        # Transform against the saved anchors in UMAP's original coordinate scale.
        reducer.embedding_ = (old_coordinates * span + low).astype(np.float32)
        # shortcut: new outliers clip at fixed bounds; revisit if points crowd the edges.
        return np.clip((reducer.transform(new_vectors) - low) / span, 0, 1)
    low, span = raw.min(axis=0), np.ptp(raw, axis=0)
    coordinates = np.divide(raw - low, span, out=np.full_like(raw, 0.5), where=span > 0)
    return np.pad(coordinates, ((0, 0), (0, 2 - coordinates.shape[1])), constant_values=0.5)


def build_map(store: Store, cfg: Scoring, *, previous: MapData | None) -> MapData:
    topics = [topic for topic in store.all_topics() if any(entry.rank is not None for entry in topic.history)]
    result = MapData(generated_on=datetime.now(timezone.utc).date(), method='umap', points=[])
    if not topics:
        logger.info('topic_map path=empty points=0')
        return result
    vectors = np.asarray([topic.centroid for topic in topics], dtype=np.float64)
    if vectors.ndim != 2 or not vectors.shape[1] or not np.isfinite(vectors).all():
        raise ValueError('topic centroids must be nonempty finite vectors of equal dimension')
    saved = {point.slug: point for point in previous.points} if previous else {}
    old = [i for i, topic in enumerate(topics) if topic.slug in saved]
    new = [i for i, topic in enumerate(topics) if topic.slug not in saved]
    if old and len(new) / len(topics) <= 0.2:
        logger.info('topic_map path=transform points=%d new=%d', len(topics), len(new))
        coordinates = np.empty((len(topics), 2))
        coordinates[old] = [[saved[topics[i].slug].x, saved[topics[i].slug].y] for i in old]
        if new:
            coordinates[new] = _layout(vectors[old], coordinates[old], vectors[new])
    else:
        logger.info('topic_map path=refit reducer=%s points=%d new=%d',
                    'pca' if len(topics) < 10 else 'umap', len(topics), len(new))
        coordinates = _layout(vectors)
    similarities = cosine_similarity(vectors)
    for i, topic in enumerate(topics):
        ranked = [entry.date for entry in topic.history if entry.rank is not None]
        neighbors = sorted((j for j in range(len(topics)) if j != i),
                           key=lambda j: (-similarities[i, j], topics[j].slug))[:3]
        result.points.append(MapData.Point(
            slug=topic.slug, label=topic.label, headline=topic.headline or topic.label,
            category=topic.category, x=float(coordinates[i, 0]), y=float(coordinates[i, 1]),
            size=sum(len(entry.item_ids) for entry in topic.history),
            first_ranked=min(ranked), last_ranked=max(ranked),
            months=sorted({entry.date.strftime('%Y-%m') for entry in topic.history}),
            neighbors=[topics[j].slug for j in neighbors],
        ))
    return result
