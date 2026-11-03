import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from threading import Condition

from pipeline.budget import Budget
from pipeline.config import Scoring
from pipeline.llm import LLM
from pipeline.models import Item, Topic
from pipeline.score import Scores, Signals


logger = logging.getLogger(__name__)


def tier_model(rank: int, cfg: Scoring, backfill: bool, over_ceiling: bool) -> str:
    if over_ceiling:
        return 'claude-haiku-5-5'
    if backfill:
        return cfg.backfill_synthesis_model
    return next(tier.model for tier in cfg.synthesis_tiers if tier.to >= rank)


def synthesize_top(
    ranked: list[tuple[Topic, Signals, Scores]], items_by_topic: dict[str, list[Item]],
    llm: LLM, budget: Budget, cfg: Scoring, today: date, *, backfill: bool,
    model: str | None = None, skip_slugs: set[str] | None = None,
) -> tuple[list[Topic], str, list[str]]:
    started = time.monotonic()
    over_ceiling = budget.over_ceiling()
    override = model if not over_ceiling else None
    model = override or tier_model(1, cfg, backfill, over_ceiling)
    topics, notes = [row[0] for row in ranked], []
    workers, active = cfg.synthesis_workers, 0
    condition = Condition()
    throttled = False

    def throttle():
        nonlocal workers, throttled
        with condition:
            if not throttled:
                workers = max(1, workers // 2)
                throttled = True
                logger.warning('stage=synthesize event=throttled workers=%d date=%s', workers, today)

    def synthesize(position, topic, signals):
        nonlocal active
        topic_model = tier_model(position, cfg, backfill, over_ceiling)
        if override:
            topic_model = override if position <= cfg.featured_n else 'claude-haiku-5-5'
        previous = topic.synthesis if any(day.rank is not None and day.date < today
                                          for day in topic.history) else None
        items = items_by_topic[topic.slug]
        if len(items) > cfg.synthesis_max_items:
            logger.warning('synthesis_truncated topic=%s items=%d selected=%d',
                           topic.slug, len(items), cfg.synthesis_max_items)
            items = sorted(items, key=lambda item: (
                item.type == 'preprint', -item.published_at.toordinal(), item.id,
            ))[:cfg.synthesis_max_items]
        with condition:
            condition.wait_for(lambda: active < workers)
            active += 1
        try:
            result = llm.synthesize(topic, items, signals, previous, topic_model,
                                    on_repeated_429=throttle)
        finally:
            with condition:
                active -= 1
                condition.notify_all()
        return position, topic_model, result

    with ThreadPoolExecutor(max_workers=cfg.synthesis_workers) as executor:
        futures = [executor.submit(synthesize, position, topic, signals)
                   for position, (topic, signals, _) in enumerate(ranked, 1)
                   if not skip_slugs or topic.slug not in skip_slugs]
        results = [future.result() for future in as_completed(futures)]
    # Apply results and collect fallback notes in rank order, regardless of completion order.
    for position, topic_model, result in sorted(results, key=lambda row: row[0]):
        topic = topics[position - 1]
        if result is None:
            topic.headline = topic.headline or topic.label.title()
            topic.summary = ''
            notes.append(f'synthesis-fallback:{topic.slug}')
        else:
            topic.label = result.label
            topic.headline = result.headline
            topic.summary = result.summary
            topic.synthesis = result.synthesis
            topic.synthesized_on = today
            topic.item_one_liners.update(result.item_one_liners)
        topic.synthesis_model = topic_model
    logger.info('stage=synthesize event=complete date=%s workers=%d elapsed=%.2f',
                today, workers, time.monotonic() - started)
    return topics, model, notes
