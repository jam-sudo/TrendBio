import json
import time
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from pipeline.budget import Budget
from pipeline.config import Taxonomy
from pipeline.models import Item


class Enrichment(BaseModel):
    model_config = ConfigDict(extra='forbid')

    summary: str = Field(max_length=160)
    primary: str
    secondary: list[str] = Field(max_length=2)


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
        output_model = _output_model(taxonomy)
        messages = _messages(item, taxonomy, hints)
        for attempt in range(4):
            try:
                response = self.client.messages.parse(
                    model=model, max_tokens=512, output_format=output_model,
                    messages=messages, output_config={'effort': 'low'},
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
            return _validate_categories(response.parsed_output, taxonomy)
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
