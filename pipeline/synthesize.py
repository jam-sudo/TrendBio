from datetime import date

from pipeline.budget import Budget
from pipeline.config import Scoring
from pipeline.llm import LLM
from pipeline.models import Item, Topic
from pipeline.score import Scores, Signals


def synthesize_top(
    ranked: list[tuple[Topic, Signals, Scores]], items_by_topic: dict[str, list[Item]],
    llm: LLM, budget: Budget, cfg: Scoring, today: date, *, backfill: bool,
) -> tuple[list[Topic], str, list[str]]:
    model = 'claude-haiku-5-5' if backfill or budget.over_ceiling() else 'claude-opus-5-5'
    topics, notes = [], []
    for topic, signals, _ in ranked:
        previous = topic.synthesis if any(day.rank is not None and day.date < today
                                          for day in topic.history) else None
        result = llm.synthesize(topic, items_by_topic[topic.slug], signals, previous, model)
        if result is None:
            topic.headline = topic.headline or topic.label.title()
            topic.summary = ''
            notes.append(f'synthesis-fallback:{topic.slug}')
        else:
            topic.headline = result.headline
            topic.summary = result.summary
            topic.synthesis = result.synthesis
            topic.synthesized_on = today
            topic.item_one_liners.update(result.item_one_liners)
        topic.synthesis_model = model
        topics.append(topic)
    return topics, model, notes
