from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pipeline.budget import Budget
from pipeline.config import load_taxonomy
from pipeline.enrich import enrich_items, hints_for
from pipeline.llm import Enrichment, LLM
from pipeline.models import Item
from pipeline.store import Store


@pytest.fixture
def item():
    return Item(
        id='biorxiv:10.1101/2026.01.02.123456', source='biorxiv', type='preprint',
        title='Comparative pathogen genomics', url='https://example.org/paper',
        doi=None, published_at=date(2026, 1, 2), first_seen=date(2026, 1, 2),
        authors=[], org=None, abstract='We compare pathogen genomes. A second sentence.',
        summary=None, primary_category=None, published_doi=None, preprint_id=None,
        metadata={'biorxiv_category': 'genomics'},
    )


@pytest.fixture
def taxonomy():
    return load_taxonomy('computational')


class FakeMessages:
    def __init__(self, stop_reason='end_turn', output=None):
        self.stop_reason = stop_reason
        self.output = output
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason, parsed_output=self.output,
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )


class FakeEmbedder:
    def __init__(self):
        self.texts = []

    def embed(self, texts):
        self.texts.extend(texts)
        return np.random.default_rng(7).normal(size=(len(texts), 8))


def test_enrich_sets_summary_and_categories_within_taxonomy(tmp_path, item, taxonomy):
    messages = FakeMessages(output=Enrichment(
        summary='Comparative analysis of pathogen genomes.', primary='genomics',
        secondary=['ml-ai', 'invented-category'], relevant=True,
    ))
    budget = Budget(tmp_path / 'spend.json', 50)
    store = Store(tmp_path, 'computational')
    embedder = FakeEmbedder()
    items, notes, irrelevant = enrich_items([item], store, LLM(SimpleNamespace(messages=messages), budget),
                                           embedder, taxonomy, {'biorxiv_category': {'genomics': ['genomics']}})
    assert items == [item]
    assert notes == []
    assert irrelevant == 0
    assert item.summary == 'Comparative analysis of pathogen genomes.'
    assert item.primary_category == 'genomics'
    assert item.secondary_categories == ['ml-ai']
    assert store.get_item(item.id) == item
    assert embedder.texts == [item.title + '\n' + item.abstract]
    call = messages.calls[0]
    assert call['model'] == 'claude-haiku-5-5'
    assert call['output_config'] == {'effort': 'low'}
    assert not {'thinking', 'budget_tokens', 'temperature'} & call.keys()
    schema = call['output_format'].model_json_schema()
    assert schema['properties']['primary']['enum'] == taxonomy.slugs()
    assert schema['properties']['secondary']['items']['enum'] == taxonomy.slugs()
    prompt = call['messages'][0]['content']
    assert item.title in prompt and item.abstract in prompt
    assert all(category.covers in prompt for category in taxonomy.categories)
    assert budget.month_spend_usd() == pytest.approx(0.00002)


def test_refusal_falls_back_to_abstract_sentence_and_hint_category(tmp_path, item, taxonomy):
    messages = FakeMessages(stop_reason='refusal')
    budget = Budget(tmp_path / 'spend.json', 50)
    store = Store(tmp_path, 'computational')
    _, notes, _ = enrich_items([item], store, LLM(SimpleNamespace(messages=messages), budget),
                              FakeEmbedder(), taxonomy, {'biorxiv_category': {'genomics': ['genomics']}})
    assert item.summary == 'We compare pathogen genomes.'
    assert item.primary_category == 'genomics'
    assert item.secondary_categories == []
    assert notes == [f'enrichment-fallback:{item.id}']
    assert store.get_item(item.id) == item
    assert budget.month_spend_usd() > 0


def test_already_enriched_items_skipped(tmp_path, item, taxonomy):
    item.summary = 'Existing summary'
    messages = FakeMessages()
    embedder = FakeEmbedder()
    llm = LLM(SimpleNamespace(messages=messages), Budget(tmp_path / 'spend.json', 50))
    assert enrich_items([item], Store(tmp_path, 'computational'), llm, embedder, taxonomy, {}) == ([item], [], 0)
    assert messages.calls == []
    assert embedder.texts == []
    assert not list(tmp_path.iterdir())


def test_embeddings_are_unit_norm(tmp_path, item, taxonomy):
    store = Store(tmp_path, 'computational')
    llm = SimpleNamespace(enrich=lambda *args: None)
    items = [item, item.model_copy(update={'id': 'arxiv:123'})]
    enrich_items(items, store, llm, FakeEmbedder(), taxonomy, {})
    matrix = store.get_embeddings([row.id for row in items])
    assert matrix.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(matrix, axis=1), 1, atol=0.001)


def test_hints_follow_source_order_and_deduplicate(item):
    item.metadata.update(arxiv_primary_category='q-bio.GN', journal='Nature Methods',
                         github_topics=['genomics', 'single-cell', 'unknown'])
    assert hints_for(item, {
        'biorxiv_category': {'genomics': ['genomics']},
        'arxiv_category': {'q-bio.GN': ['genomics', 'systems']},
        'journal': {'Nature Methods': ['tools-infra']},
        'github_topic': {'genomics': ['genomics'], 'single-cell': ['single-cell', 'systems']},
    }) == ['genomics', 'systems', 'tools-infra', 'single-cell']


def test_unknown_primary_falls_back_to_title_without_hints(tmp_path, item, taxonomy):
    item.abstract = ''
    messages = FakeMessages(output=Enrichment(relevant=True, summary='Summary', primary='unknown', secondary=[]))
    llm = LLM(SimpleNamespace(messages=messages), Budget(tmp_path / 'spend.json', 50))
    _, notes, _ = enrich_items([item], Store(tmp_path, 'computational'), llm, FakeEmbedder(), taxonomy, {})
    assert item.summary == item.title
    assert item.primary_category == 'ml-ai'
    assert notes == [f'enrichment-fallback:{item.id}']


@pytest.mark.parametrize('status,attempts', [(429, 4), (500, 4), (503, 4), (400, 1), (401, 1), (408, 1)])
def test_api_errors_retry_only_transient_statuses(tmp_path, item, taxonomy, monkeypatch, status, attempts):
    import anthropic
    import httpx

    calls = []
    sleeps = []
    error = anthropic.APIStatusError('failure', response=httpx.Response(
        status, request=httpx.Request('POST', 'https://example.org/messages'),
    ), body=None)

    def fail(**kwargs):
        calls.append(kwargs)
        raise error

    monkeypatch.setattr('pipeline.llm.time.sleep', sleeps.append)
    llm = LLM(SimpleNamespace(messages=SimpleNamespace(parse=fail)), Budget(tmp_path / 'spend.json', 50))
    assert llm.enrich(item, taxonomy, []) is None
    assert len(calls) == attempts
    assert sleeps == ([1, 2, 4] if attempts == 4 else [])
    assert llm.budget.month_spend_usd() == 0


def test_connection_error_then_success(tmp_path, item, taxonomy, monkeypatch):
    import anthropic
    import httpx

    messages = FakeMessages(output=Enrichment(relevant=True, summary='Summary', primary='genomics', secondary=[]))
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise anthropic.APIConnectionError(request=httpx.Request('POST', 'https://example.org/messages'))
        return messages.parse(**kwargs)

    monkeypatch.setattr('pipeline.llm.time.sleep', lambda seconds: None)
    llm = LLM(SimpleNamespace(messages=SimpleNamespace(parse=parse)), Budget(tmp_path / 'spend.json', 50))
    assert llm.enrich(item, taxonomy, []).primary == 'genomics'
    assert len(calls) == 2


def test_batch_chunks_maps_unordered_results_and_records_discount(tmp_path, item, taxonomy, monkeypatch):
    import json
    import re

    class Batches:
        def __init__(self):
            self.requests = []
            self.polls = 0

        def create(self, *, requests):
            self.requests.append(requests)
            return SimpleNamespace(id=str(len(self.requests) - 1))

        def retrieve(self, batch_id):
            self.polls += 1
            return SimpleNamespace(processing_status='in_progress' if self.polls == 1 else 'ended')

        def results(self, batch_id):
            for request in reversed(self.requests[int(batch_id)]):
                index = int(request['custom_id'])
                kind = {1: 'errored', 2: 'canceled', 3: 'expired'}.get(index, 'succeeded')
                message = SimpleNamespace(
                    stop_reason='refusal' if index == 4 else 'end_turn',
                    content=[] if index == 4 else [SimpleNamespace(type='text', text=(
                        'invalid json' if index == 5 else json.dumps({
                            'summary': 'evidence ' * 30 if index == 6 else 'Summary ' + str(index),
                            'primary': 'genomics', 'relevant': True,
                            'secondary': ['unknown', 'ml-ai', 'structural', 'systems'] if index == 6 else ['unknown'],
                        })
                    ))], usage=SimpleNamespace(input_tokens=100, output_tokens=20),
                )
                yield SimpleNamespace(custom_id=request['custom_id'], result=SimpleNamespace(type=kind, message=message))

    batches = Batches()
    sleeps = []
    monkeypatch.setattr('pipeline.llm.time.sleep', sleeps.append)
    budget = Budget(tmp_path / 'spend.json', 50)
    llm = LLM(SimpleNamespace(messages=SimpleNamespace(batches=batches)), budget)
    items = [item.model_copy(update={'id': f'biorxiv:10.1101/{index}'}) for index in range(2001)]
    results = llm.enrich_batch(items, taxonomy, {items[0].id: ['genomics']}, poll_seconds=0.1)
    assert [len(chunk) for chunk in batches.requests] == [2000, 1]
    assert sleeps == [0.1]
    assert len(results) == 2001
    assert results[items[0].id].summary == 'Summary 0'
    assert results[items[9].id].summary == 'Summary 9'
    assert results[items[2000].id].summary == 'Summary 0'
    assert all(results[items[index].id] is None for index in range(1, 6))
    assert results[items[0].id].secondary == []
    assert len(results[items[6].id].summary) <= 160
    assert results[items[6].id].summary.endswith('evidence…')
    assert results[items[6].id].secondary == ['ml-ai', 'structural']
    assert budget.month_spend_usd() == pytest.approx((2001 - 3) * 0.00001)
    for chunk in batches.requests:
        assert len({request['custom_id'] for request in chunk}) == len(chunk)
        assert all(re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', request['custom_id']) for request in chunk)
    params = batches.requests[0][0]['params']
    schema = params['output_config']['format']['schema']
    assert schema['additionalProperties'] is False
    assert set(schema['required']) == {'summary', 'primary', 'secondary', 'relevant'}
    assert schema['properties']['primary']['enum'] == taxonomy.slugs()
    assert schema['properties']['secondary']['items']['enum'] == taxonomy.slugs()
    assert 'maxLength' not in schema['properties']['summary']
    assert 'maxItems' not in schema['properties']['secondary']
    assert 'Source hints: ["genomics"]' in params['messages'][0]['content']


def test_embedder_uses_lazy_sentence_transformer_and_normalizes(monkeypatch):
    import sys
    from pipeline.embed import Embedder

    calls = []

    class FakeModel:
        def __init__(self, model_name):
            calls.append(model_name)

        def encode(self, texts, *, convert_to_numpy):
            assert convert_to_numpy
            return np.array([[3, 4]] * len(texts))

        def get_sentence_embedding_dimension(self):
            return 2

    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=FakeModel))
    embedder = Embedder()
    assert calls == ['allenai/specter2_base']
    vectors = embedder.embed(['a', 'b'])
    assert vectors.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1)
    assert embedder.embed([]).shape == (0, 2)


@pytest.mark.parametrize('vectors', [np.zeros((1, 2)), [[float('nan'), 1]], [1, 2]])
def test_invalid_embeddings_do_not_mark_items_enriched(tmp_path, item, taxonomy, vectors):
    store = Store(tmp_path, 'computational')
    with pytest.raises(ValueError):
        enrich_items([item], store, SimpleNamespace(enrich=lambda *args: None),
                     SimpleNamespace(embed=lambda texts: vectors), taxonomy, {})
    assert item.summary is None
    assert store.get_item(item.id) is None


def test_interrupted_embedding_write_is_retryable(tmp_path, item, taxonomy, monkeypatch):
    store = Store(tmp_path, 'computational')

    def fail(*args):
        raise OSError('interrupted')

    monkeypatch.setattr(store, 'put_embedding', fail)
    with pytest.raises(OSError, match='interrupted'):
        enrich_items([item], store, SimpleNamespace(enrich=lambda *args: None), FakeEmbedder(), taxonomy, {})
    assert store.get_item(item.id).summary is None
    assert item.summary is None


def test_enrichment_parallel_and_writes_sorted(tmp_path, item, taxonomy):
    from time import perf_counter, sleep
    from unittest.mock import Mock

    def slow_enrich(*args):
        sleep(0.05)
        return None

    items = [item.model_copy(update={'id': f'biorxiv:{i:02d}'}) for i in reversed(range(40))]
    store = Store(tmp_path, 'computational')
    store.put_item = Mock(wraps=store.put_item)
    embedder = FakeEmbedder()
    embedder.embed = Mock(wraps=embedder.embed)
    started = perf_counter()
    _, notes, _ = enrich_items(items, store, SimpleNamespace(enrich=slow_enrich), embedder, taxonomy, {})
    assert perf_counter() - started < 1.2  # Sequential calls alone would take 2 seconds.
    written = [call.args[0].id for call in store.put_item.call_args_list]
    assert written == sorted(written)
    assert notes == sorted(notes)
    assert len(store.items_between(date.min, date.max)) == 40
    embedder.embed.assert_called_once()


def test_long_summary_is_truncated_not_dropped(tmp_path, item, taxonomy):
    text = 'Comparative genomics reveals conserved pathogen evolution. ' * 4
    messages = FakeMessages(output={'summary': text, 'primary': 'genomics', 'relevant': True, 'secondary': []})
    llm = LLM(SimpleNamespace(messages=messages), Budget(tmp_path / 'spend.json', 50))
    result = llm.enrich(item, taxonomy, [])
    assert result is not None
    assert len(result.summary) <= 160 and result.summary.endswith('…')
    assert text.startswith(result.summary[:-1])
    assert text[len(result.summary) - 1].isspace()
    assert llm.fallback_reasons == {}
    assert 'maxLength' not in messages.calls[0]['output_format'].model_json_schema()['properties']['summary']


def test_three_secondaries_trimmed_to_two(tmp_path, item, taxonomy):
    messages = FakeMessages(output={
        'summary': 'Summary', 'primary': 'genomics', 'relevant': True,
        'secondary': ['unknown', 'ml-ai', 'structural', 'systems'],
    })
    llm = LLM(SimpleNamespace(messages=messages), Budget(tmp_path / 'spend.json', 50))
    assert llm.enrich(item, taxonomy, []).secondary == ['ml-ai', 'structural']
    assert 'maxItems' not in messages.calls[0]['output_format'].model_json_schema()['properties']['secondary']


@pytest.mark.parametrize('case,reason', [
    ('api', 'api_error:401'), ('retry', 'retries_exhausted'),
    ('sdk_validation', 'validation:primary'), ('validation', 'validation:primary'),
    ('unknown_primary', 'validation:primary'), ('empty', 'empty_output'),
    ('refusal', 'refusal:none'), ('categorized_refusal', 'refusal:bio'),
])
def test_fallback_reason_logged(tmp_path, item, taxonomy, monkeypatch, caplog, case, reason):
    import anthropic
    import httpx

    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        if case in ('api', 'retry'):
            raise anthropic.APIStatusError(item.abstract, response=httpx.Response(
                401 if case == 'api' else 429,
                request=httpx.Request('POST', 'https://example.org/messages'),
            ), body=None)
        if case == 'sdk_validation':
            Enrichment.model_validate({'summary': item.abstract, 'secondary': [], 'relevant': True})
        output = {'summary': item.abstract, 'secondary': [], 'relevant': True}
        if case == 'unknown_primary':
            output['primary'] = 'unknown'
        return SimpleNamespace(
            stop_reason='refusal' if 'refusal' in case else 'end_turn',
            stop_details=SimpleNamespace(category='bio') if case == 'categorized_refusal' else None,
            parsed_output=None if case == 'empty' else output,
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )

    monkeypatch.setattr('pipeline.llm.time.sleep', lambda seconds: None)
    llm = LLM(SimpleNamespace(messages=SimpleNamespace(parse=parse)), Budget(tmp_path / 'spend.json', 50))
    with caplog.at_level('WARNING', logger='pipeline.llm'):
        assert llm.enrich(item, taxonomy, []) is None
    warnings = [record for record in caplog.records if record.name == 'pipeline.llm']
    assert len(warnings) == 1
    assert warnings[0].levelname == 'WARNING'
    assert f'id={item.id} reason={reason}' in warnings[0].getMessage()
    assert item.abstract not in caplog.text and item.title not in caplog.text
    assert llm.fallback_reasons == {item.id: reason}
    assert len(calls) == (4 if case == 'retry' else 1)


@pytest.mark.parametrize('text,limit,expected', [
    ('short text', 10, 'short text'), ('word another', 6, 'word…'),
    ('word another', 5, 'word…'), ('abcdefgh', 5, 'abcd…'),
    ('word\tanother', 8, 'word…'),
])
def test_truncate_preserves_words_when_possible(text, limit, expected):
    from pipeline.llm import truncate

    assert truncate(text, limit) == expected


def test_irrelevant_item_keeps_categories_and_is_flagged(tmp_path, item, taxonomy):
    messages = FakeMessages(output={
        'summary': 'General machine-learning benchmark.', 'primary': 'ml-ai',
        'secondary': [], 'relevant': False,
    })
    store = Store(tmp_path, 'computational')
    llm = LLM(SimpleNamespace(messages=messages), Budget(tmp_path / 'spend.json', 50))
    items, notes, irrelevant = enrich_items([item], store, llm, None, taxonomy, {})
    saved = store.get_item(item.id)
    assert items == [item] and notes == []
    assert saved.relevant is False
    assert saved.primary_category == 'ml-ai'
    assert saved.summary == 'General machine-learning benchmark.'
    assert irrelevant == 1


def test_fallback_marks_item_relevant(tmp_path, item, taxonomy):
    item.relevant = False
    messages = FakeMessages(stop_reason='refusal')
    store = Store(tmp_path, 'computational')
    llm = LLM(SimpleNamespace(messages=messages), Budget(tmp_path / 'spend.json', 50))
    _, notes, irrelevant = enrich_items([item], store, llm, None, taxonomy, {})
    assert item.relevant is True
    assert store.get_item(item.id).relevant is True
    assert notes == [f'enrichment-fallback:{item.id}']
    assert irrelevant == 0


def test_enrich_prompt_defines_relevance():
    prompt = Path('pipeline/prompts/enrich.md').read_text(encoding='utf-8')
    assert 'relevant:' in prompt
    assert 'main contribution is computational' in prompt
