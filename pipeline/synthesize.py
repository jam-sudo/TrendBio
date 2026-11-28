import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from functools import cache
from threading import Condition

from pipeline.budget import Budget
from pipeline.config import Scoring
from pipeline.llm import LLM
from pipeline.models import Day, Item, Topic
from pipeline.score import Scores, Signals


logger = logging.getLogger(__name__)


def tier_model(rank: int, cfg: Scoring, backfill: bool, over_ceiling: bool) -> str:
    if over_ceiling:
        return 'claude-haiku-5-5'
    if backfill:
        return cfg.backfill_synthesis_model
    return next(tier.model for tier in cfg.synthesis_tiers if tier.to >= rank)


def top_evidence(items: list[Item]) -> Item:
    if not items:
        raise ValueError('synthesis requires evidence items')
    return min(items, key=lambda item: (
        item.type == 'preprint', -item.published_at.toordinal(), item.id,
    ))


def fallback_copy(item: Item) -> tuple[str, str]:
    summary = item.summary or ''
    has_english_summary = item.can_quote_in_english(summary)
    source_link_text = 'Open the supporting work to read the original publication.'
    if item.can_quote_in_english(item.title):
        return item.title, summary if has_english_summary else source_link_text
    if summary and has_english_summary:
        return 'Research summary', summary
    return 'English summary unavailable', source_link_text


def synthesize_top(
    ranked: list[tuple[Topic, Signals, Scores]], items_by_topic: dict[str, list[Item]],
    llm: LLM, budget: Budget, cfg: Scoring, today: date, *, backfill: bool,
    model: str | None = None, skip_slugs: set[str] | None = None,
    load_day: Callable[[date], Day | None] | None = None,
) -> tuple[list[Topic], str, list[str]]:
    started = time.monotonic()
    over_ceiling = budget.over_ceiling()
    override = model if not over_ceiling else None
    model = override or tier_model(1, cfg, backfill, over_ceiling)
    topics, notes = [row[0] for row in ranked], []
    workers, active = cfg.synthesis_workers, 0
    condition = Condition()
    throttled = False

    @cache
    def edition_rows(when):
        day = load_day(when) if load_day else None
        return {row.slug: (row, f'synthesis-fallback:{row.slug}' in day.run.notes)
                for row in day.ranked} if day else {}

    def previous_synthesis(topic):
        dates = sorted((entry.date for entry in topic.history
                        if entry.rank is not None and entry.date < today), reverse=True)
        for when in dates:
            row, fallback = edition_rows(when).get(topic.slug, (None, False))
            if fallback:
                continue
            if row and row.synthesis:
                return row.synthesis
            if topic.synthesized_on == when and topic.synthesis:
                return topic.synthesis
        return None

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
        previous = previous_synthesis(topic)
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
            entry = next((entry for entry in topic.history if entry.date == today), None)
            reviewed = {}
            if entry and entry.research_question:
                reviewed['research_question'] = entry.research_question
            if entry and entry.result_passages:
                reviewed['result_passages'] = entry.result_passages
            prompt_topic = topic
            if (topic.synthesized_on and topic.synthesized_on > today) or any(
                    h.rank is not None and h.date > today for h in topic.history):
                row, _ = edition_rows(today).get(topic.slug, (None, False))
                prompt_topic = topic.model_copy(update={
                    'category': row.category if row else (entry and entry.category) or topic.category,
                    'label': row.headline if row else topic.slug.rsplit('-', 1)[0].replace('-', ' '),
                })
            result = llm.synthesize(prompt_topic, items, signals, previous, topic_model,
                                    on_repeated_429=throttle, **reviewed)
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
            item = top_evidence(items_by_topic[topic.slug])
            topic.headline, topic.summary = fallback_copy(item)
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
