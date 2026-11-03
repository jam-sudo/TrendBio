from collections import Counter
from datetime import date, timedelta
import logging
from math import log1p
from statistics import median

from pipeline.config import Scoring
from pipeline.models import Item, Scores, Signals, Topic


def signals_for(topic: Topic, items: list[Item],
                stars: dict[str, list[tuple[date, int]]]) -> Signals:
    linked = {item.preprint_id for item in items if item.type == 'published'}
    counts = Counter(item.type for item in items
                     if not (item.type == 'preprint' and item.id in linked))
    star_gain = 0
    for item in items:
        if item.type != 'code':
            continue
        history = dict(stars.get(item.id.split(':', 1)[1], []))
        if history:
            latest = max(history)
            earlier = latest - timedelta(days=7)
            # A missing comparison sample is not evidence of zero stars.
            if earlier in history:
                star_gain += max(history[latest] - history[earlier], 0)
    return Signals(published=counts['published'], preprint=counts['preprint'],
                   code=counts['code'], industry=counts['industry'],
                   star_gain_7d=star_gain, rise_ratio=0.0)


def rise(topic: Topic, count_7d: int, today: date, cfg: Scoring,
         global_median: float) -> float:
    history = {day.date: day.count_7d for day in topic.history if day.date <= today}
    baseline = global_median
    if history and (today - min(history)).days >= cfg.history_days_for_own_baseline:
        baseline = sum(history.get(today - timedelta(weeks=week), 0)
                       for week in range(1, 5)) / 4
    return min((count_7d + cfg.rise_k) / (baseline + cfg.rise_k), cfg.rise_cap)


def diversity(sig: Signals) -> float:
    return sum(count != 0 for count in (sig.published, sig.preprint, sig.code, sig.industry)) / 4


def code_velocity(sig: Signals) -> float:
    return min(log1p(sig.star_gain_7d) / log1p(10_000), 1.0)


def volume(count_7d: int) -> float:
    return min(log1p(count_7d) / log1p(50), 1.0)


def score_topics(topics_today: list[tuple[Topic, Signals, int]],
                 yesterday_ranked: set[str], cfg: Scoring,
                 today: date) -> list[tuple[Topic, Signals, Scores]]:
    global_median = median(count for _, _, count in topics_today) if topics_today else 0
    uncapped = cfg.model_copy(update={'rise_cap': float('inf')})
    scored = []
    for topic, signals, count in topics_today:
        ratio = rise(topic, count, today, uncapped, global_median)
        signals = signals.model_copy(update={'rise_ratio': ratio})
        components = dict(rise=min(ratio, cfg.rise_cap), diversity=diversity(signals),
                          code_velocity=code_velocity(signals), volume=volume(count))
        subtotal = sum(cfg.weights[key] * value for key, value in components.items())
        penalty = cfg.yesterday_penalty * subtotal if topic.slug in yesterday_ranked else 0.0
        scores = Scores(**components, penalty=penalty, total=subtotal - penalty)
        scored.append((topic, signals, scores))
    return sorted(scored, key=lambda entry: (-entry[2].total, entry[0].slug))


def rank(scored: list[tuple[Topic, Signals, Scores]],
         cfg: Scoring) -> list[tuple[Topic, Signals, Scores]]:
    selected, overflow = [], []
    counts = Counter()
    for row in scored:
        if len(selected) == cfg.top_n:
            break
        category = row[0].category
        if counts[category] >= cfg.max_per_category:
            overflow.append(row)
        else:
            selected.append(row)
            counts[category] += 1
    selected.extend(overflow[:max(0, cfg.top_n - len(selected))])
    slugs = {row[0].slug for row in selected}
    for topic, _, _ in scored[:cfg.top_n]:
        if topic.slug not in slugs:
            logging.getLogger(__name__).info(
                'stage=score_rank event=category_cap displaced=%s', topic.slug)
    return [row for row in scored if row[0].slug in slugs]
