import json
import logging
import random
import re
import time
from collections.abc import Callable
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, field_validator

from pipeline import grounding
from pipeline.budget import Budget
from pipeline.config import Taxonomy
from pipeline.models import Item, Signals, Topic


logger = logging.getLogger(__name__)


def _validation_reason(error: ValidationError) -> str:
    location = '.'.join(str(part) for part in error.errors()[0]['loc']) or 'root'
    return f'validation:{location}'


def _refusal_reason(message) -> str:
    category = getattr(getattr(message, 'stop_details', None), 'category', None)
    return f'refusal:{category or "none"}'


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    prefix = text[:limit - 1]
    if not text[limit - 1].isspace() and not prefix[-1].isspace():
        prefix = prefix.rsplit(maxsplit=1)[0]
    return prefix.rstrip() + '…'


class Enrichment(BaseModel):
    model_config = ConfigDict(extra='forbid')

    summary: str
    primary: str
    secondary: list[str]
    relevant: bool

    @field_validator('summary')
    @classmethod
    def shorten_summary(cls, value: str) -> str:
        return truncate(value, 160)


class Synthesis(BaseModel):
    label: str
    headline: str
    summary: str
    synthesis: str
    item_one_liners: dict[str, str] = {}

    @field_validator('label')
    @classmethod
    def clean_label(cls, value: str) -> str:
        label = ' '.join(re.sub(r'[^\w\s]|_', ' ', value).split()[:5]).title()
        if not label:
            raise ValueError('label must contain words')
        return label

    @field_validator('headline', 'summary')
    @classmethod
    def shorten_text(cls, value: str, info) -> str:
        return truncate(value, 90 if info.field_name == 'headline' else 160)


def _output_model(taxonomy: Taxonomy) -> type[Enrichment]:
    slugs = taxonomy.slugs()
    return create_model(
        'TaxonomyEnrichment', __base__=Enrichment,
        primary=(str, Field(json_schema_extra={'enum': slugs})),
        secondary=(list[str], Field(json_schema_extra={
            'items': {'type': 'string', 'enum': slugs},
        })),
    )


def _messages(item: Item, taxonomy: Taxonomy, hints: list[str]) -> list[dict]:
    template = Path(__file__).with_name('prompts').joinpath('enrich.md').read_text(encoding='utf-8')
    prompt = template.format(
        categories='\n'.join(f'{c.slug}: {c.label} — {c.covers}' for c in taxonomy.categories),
        hints=json.dumps(hints, ensure_ascii=False),
        item=json.dumps({'title': item.title, 'abstract': item.abstract}, ensure_ascii=False),
    )
    return [{'role': 'user', 'content': prompt}]


def _validate_categories(result: Enrichment | None, taxonomy: Taxonomy) -> Enrichment | None:
    if result is None or result.primary not in taxonomy.slugs():
        return None
    return result.model_copy(update={
        'secondary': [slug for slug in result.secondary if slug in taxonomy.slugs()][:2],
    })


class LLM:
    def __init__(self, client: anthropic.Anthropic, budget: Budget):
        # Own retries here so the SDK does not multiply attempts or retry other statuses.
        self.client = client.with_options(max_retries=0) if isinstance(client, anthropic.Anthropic) else client
        self.budget = budget
        self.fallback_reasons: dict[str, str] = {}

    def _failure(self, entity_id: str, reason: str, detail: str | None = None) -> None:
        self.fallback_reasons[entity_id] = reason
        if detail is None:
            logger.warning('llm_fallback id=%s reason=%s', entity_id, reason)
        else:
            logger.warning('llm_fallback id=%s reason=%s detail=%s', entity_id, reason, detail)

    def enrich(
        self, item: Item, taxonomy: Taxonomy, hints: list[str], model: str = 'claude-haiku-5-5',
    ) -> Enrichment | None:
        self.fallback_reasons.pop(item.id, None)
        result = self._parse(_output_model(taxonomy), _messages(item, taxonomy, hints), model, 512, 'low',
                             entity_id=item.id)
        validated = _validate_categories(result, taxonomy)
        if result is not None and validated is None:
            return self._failure(item.id, 'validation:primary')
        if validated is not None:
            bad = grounding.unsupported(validated.summary, item.title + ' ' + item.abstract)
            if bad:
                return self._failure(item.id, 'grounding', detail=','.join(f'{v:g}' for v in bad))
        return validated

    def synthesize(
        self, topic: Topic, items: list[Item], signals: Signals, previous: str | None, model: str,
        *, on_repeated_429: Callable[[], None] | None = None,
    ) -> Synthesis | None:
        self.fallback_reasons.pop(topic.slug, None)
        template = Path(__file__).with_name('prompts').joinpath('synthesize.md').read_text(encoding='utf-8')
        prompt = template.format(
            category=topic.category, label=topic.label, signals=signals.model_dump_json(),
            items='\n'.join(
                f'{item.id} | {item.type} | {item.published_at} | {item.title} | {item.summary or ""}'
                for item in items
            ),
            previous=f'Previous synthesis (context only, not evidence):\n{previous}' if previous else '',
        )
        source = '\n'.join([
            signals.model_dump_json(), topic.label,
            *(text for item in items for text in (
                item.title, item.published_at.isoformat(), item.summary or '', item.abstract,
            )),
        ])
        for attempt in range(2):
            result = self._parse(Synthesis, [{'role': 'user', 'content': prompt}], model, 4096, 'high',
                                 entity_id=topic.slug, fallbacks=model in {'claude-opus-5-5', 'claude-sonnet-5-5'},
                                 on_repeated_429=on_repeated_429)
            if result is None:
                return None
            bad = grounding.unsupported('\n'.join([
                result.headline, result.summary, result.synthesis, *result.item_one_liners.values(),
            ]), source)
            if not bad:
                return result
            detail = ','.join(f'{v:g}' for v in bad)
            if attempt:
                return self._failure(topic.slug, 'grounding', detail=detail)
            logger.warning('llm_grounding_retry id=%s values=%s', topic.slug, detail)
            prompt += (
                '\n\nYour previous answer stated numbers not present in the items or signals: '
                f'{detail}. Remove or correct them. '
                'State only numbers that appear in the items, signals, or abstracts.'
            )

    def _parse[T: BaseModel](
        self, output_model: type[T], messages: list[dict], model: str, max_tokens: int,
        effort: str, *, entity_id: str, fallbacks: bool = False,
        on_repeated_429: Callable[[], None] | None = None,
    ) -> T | None:
        parse = self.client.beta.messages.parse if fallbacks else self.client.messages.parse
        options = {'betas': ['server-side-fallback-2026-07-01'], 'fallbacks': 'default'} if fallbacks else {}
        consecutive_429 = 0
        for attempt in range(4):
            try:
                response = parse(
                    model=model, max_tokens=max_tokens, output_format=output_model,
                    messages=messages, output_config={'effort': effort}, **options,
                )
            except anthropic.APIError as error:
                status = getattr(error, 'status_code', None)
                consecutive_429 = consecutive_429 + 1 if status == 429 else 0
                if consecutive_429 == 2 and on_repeated_429 is not None:
                    on_repeated_429()
                retryable = isinstance(error, anthropic.APIConnectionError) or status == 429 or (
                    status is not None and 500 <= status < 600
                )
                if not retryable or attempt == 3:
                    return self._failure(entity_id, 'retries_exhausted' if retryable else f'api_error:{status}')
                time.sleep(2 ** attempt + (random.uniform(0, 0.5) if status == 429 else 0))
                continue
            except ValidationError as error:
                return self._failure(entity_id, _validation_reason(error))
            refused = response.stop_reason == 'refusal'
            self.budget.record(model, response.usage.input_tokens, response.usage.output_tokens)
            if refused:
                return self._failure(entity_id, _refusal_reason(response))
            if response.parsed_output is None:
                return self._failure(entity_id, 'empty_output')
            try:
                return output_model.model_validate(response.parsed_output, from_attributes=True)
            except ValidationError as error:
                return self._failure(entity_id, _validation_reason(error))

    def enrich_batch(
        self, items: list[Item], taxonomy: Taxonomy, hints_by_id: dict[str, list[str]],
        model: str = 'claude-haiku-5-5', poll_seconds: float = 30,
    ) -> dict[str, Enrichment | None]:
        results = dict.fromkeys(item.id for item in items)
        schema = anthropic.transform_schema(_output_model(taxonomy))
        batches = self.client.messages.batches
        for start in range(0, len(items), 2_000):
            chunk = items[start:start + 2_000]
            # Source ids contain punctuation the Batches API does not allow in custom_id.
            ids = {str(index): item.id for index, item in enumerate(chunk)}
            requests = [Request(
                custom_id=str(index), params=MessageCreateParamsNonStreaming(
                    model=model, max_tokens=1024,
                    messages=_messages(item, taxonomy, hints_by_id.get(item.id, [])),
                    output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': schema}},
                ),
            ) for index, item in enumerate(chunk)]
            batch = batches.create(requests=requests)
            while batches.retrieve(batch.id).processing_status != 'ended':
                time.sleep(poll_seconds)
            for row in batches.results(batch.id):
                item_id = ids[row.custom_id]
                self.fallback_reasons.pop(item_id, None)
                if row.result.type != 'succeeded':
                    self._failure(item_id, f'batch:{row.result.type}')
                    continue
                message = row.result.message
                refused = message.stop_reason == 'refusal'
                self.budget.record(model, message.usage.input_tokens, message.usage.output_tokens, batch=True)
                if refused:
                    self._failure(item_id, _refusal_reason(message))
                    continue
                text = next((block.text for block in message.content if block.type == 'text'), None)
                if text is None:
                    self._failure(item_id, f'empty_output:{message.stop_reason}')
                    continue
                try:
                    result = Enrichment.model_validate_json(text)
                except ValidationError as error:
                    self._failure(item_id, _validation_reason(error))
                    continue
                results[item_id] = _validate_categories(result, taxonomy)
                if results[item_id] is None:
                    self._failure(item_id, 'validation:primary')
                    continue
                item = chunk[int(row.custom_id)]
                bad = grounding.unsupported(result.summary, item.title + ' ' + item.abstract)
                if bad:
                    self._failure(item_id, 'grounding', detail=','.join(f'{v:g}' for v in bad))
                    results[item_id] = None
        return results
