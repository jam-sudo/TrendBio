import json
import time
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from pipeline.budget import Budget
from pipeline.config import Taxonomy
from pipeline.models import Item, Signals, Topic


class Enrichment(BaseModel):
    model_config = ConfigDict(extra='forbid')

    summary: str = Field(max_length=160)
    primary: str
    secondary: list[str] = Field(max_length=2)


class Synthesis(BaseModel):
    headline: str = Field(max_length=90)
    summary: str = Field(max_length=160)
    synthesis: str
    item_one_liners: dict[str, str] = {}


def _output_model(taxonomy: Taxonomy) -> type[Enrichment]:
    slugs = taxonomy.slugs()
    return create_model(
        'TaxonomyEnrichment', __base__=Enrichment,
        primary=(str, Field(json_schema_extra={'enum': slugs})),
        secondary=(list[str], Field(max_length=2, json_schema_extra={
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
        'secondary': [slug for slug in result.secondary if slug in taxonomy.slugs()],
    })


class LLM:
    def __init__(self, client: anthropic.Anthropic, budget: Budget):
        # Own retries here so the SDK does not multiply attempts or retry other statuses.
        self.client = client.with_options(max_retries=0) if isinstance(client, anthropic.Anthropic) else client
        self.budget = budget

    def enrich(
        self, item: Item, taxonomy: Taxonomy, hints: list[str], model: str = 'claude-haiku-5-5',
    ) -> Enrichment | None:
        result = self._parse(_output_model(taxonomy), _messages(item, taxonomy, hints), model, 512, 'low')
        return _validate_categories(result, taxonomy)

    def synthesize(
        self, topic: Topic, items: list[Item], signals: Signals, previous: str | None, model: str,
    ) -> Synthesis | None:
        template = Path(__file__).with_name('prompts').joinpath('synthesize.md').read_text(encoding='utf-8')
        prompt = template.format(
            category=topic.category, label=topic.label, signals=signals.model_dump_json(),
            items='\n'.join(
                f'{item.id} | {item.type} | {item.published_at} | {item.title} | {item.summary or ""}'
                for item in items
            ),
            previous=f'Previous synthesis (context only, not evidence):\n{previous}' if previous else '',
        )
        return self._parse(Synthesis, [{'role': 'user', 'content': prompt}], model, 4096, 'high',
                           fallbacks=model == 'claude-opus-5-5')

    def _parse[T: BaseModel](
        self, output_model: type[T], messages: list[dict], model: str, max_tokens: int,
        effort: str, *, fallbacks: bool = False,
    ) -> T | None:
        parse = self.client.beta.messages.parse if fallbacks else self.client.messages.parse
        options = {'betas': ['server-side-fallback-2026-07-01'], 'fallbacks': 'default'} if fallbacks else {}
        for attempt in range(4):
            try:
                response = parse(
                    model=model, max_tokens=max_tokens, output_format=output_model,
                    messages=messages, output_config={'effort': effort}, **options,
                )
            except anthropic.APIError as error:
                status = getattr(error, 'status_code', None)
                retryable = isinstance(error, anthropic.APIConnectionError) or status == 429 or (
                    status is not None and 500 <= status < 600
                )
                if not retryable or attempt == 3:
                    return None
                time.sleep(2 ** attempt)
                continue
            except ValidationError:
                return None
            refused = response.stop_reason == 'refusal'
            self.budget.record(model, response.usage.input_tokens, response.usage.output_tokens)
            if refused:
                return None
            if response.parsed_output is None:
                return None
            try:
                return output_model.model_validate(response.parsed_output, from_attributes=True)
            except ValidationError:
                return None
        return None

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
                    model=model, max_tokens=512,
                    messages=_messages(item, taxonomy, hints_by_id.get(item.id, [])),
                    output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': schema}},
                ),
            ) for index, item in enumerate(chunk)]
            batch = batches.create(requests=requests)
            while batches.retrieve(batch.id).processing_status != 'ended':
                time.sleep(poll_seconds)
            for row in batches.results(batch.id):
                if row.result.type != 'succeeded':
                    continue
                message = row.result.message
                refused = message.stop_reason == 'refusal'
                self.budget.record(model, message.usage.input_tokens, message.usage.output_tokens, batch=True)
                if refused or not message.content or message.content[0].type != 'text':
                    continue
                try:
                    result = Enrichment.model_validate_json(message.content[0].text)
                except ValidationError:
                    continue
                results[ids[row.custom_id]] = _validate_categories(result, taxonomy)
        return results
