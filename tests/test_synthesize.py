from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from pipeline.budget import Budget
from pipeline.config import load_scoring
from pipeline.llm import LLM, Synthesis
from pipeline.models import Item, Scores, Signals, Topic, TopicDay
from pipeline.synthesize import synthesize_top, tier_model


TODAY = date(2026, 11, 2)
OUTPUT = dict(label='Protein Design', headline='Protein design advances', summary='New protein design evidence.',
              synthesis=' '.join(['Evidence'] * 80), item_one_liners={'biorxiv:paper': 'New one-liner.'})


class FakeMessages:
    def __init__(self, output=None, stop_reason='end_turn', error=None):
        self.output = OUTPUT if output is None else output
        self.stop_reason = stop_reason
        self.error = error
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            parsed_output=self.output[len(self.calls) - 1] if isinstance(self.output, list) else self.output,
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )


@pytest.fixture
def context(tmp_path):
    topic = Topic(slug='protein-design-abcd', label='protein design', category='structural',
                  secondary_categories=[], centroid=[1.0, 0.0], history=[], headline=None,
                  summary=None, synthesis=None, synthesis_model=None, synthesized_on=None)
    item = Item(id='biorxiv:paper', source='biorxiv', type='preprint', title='Protein design',
                url='https://example.org/paper', doi=None, published_at=TODAY, first_seen=TODAY,
                authors=[], org=None, abstract='Evidence from the paper.', summary='Original summary.',
                primary_category='structural', published_doi=None, preprint_id=None)
    sig = Signals(published=0, preprint=1, code=0, industry=0, rise_ratio=2.0, star_gain_7d=0)
    scores = Scores(rise=2, diversity=0.25, code_velocity=0, volume=0.2, penalty=0, total=1)
    plain, beta = FakeMessages(), FakeMessages()
    budget = Budget(tmp_path / 'spend.json', 50)
    llm = LLM(SimpleNamespace(messages=plain, beta=SimpleNamespace(messages=beta)), budget)
    return SimpleNamespace(topic=topic, item=item, sig=sig, scores=scores, plain=plain,
                           beta=beta, budget=budget, llm=llm)


def run(ctx, *, backfill=False):
    return synthesize_top([(ctx.topic, ctx.sig, ctx.scores)], {ctx.topic.slug: [ctx.item]},
                          ctx.llm, ctx.budget, load_scoring(), TODAY, backfill=backfill)


@pytest.mark.parametrize('backfill,over_ceiling', [(False, False), (True, False), (False, True)])
def test_uses_opus_normally_and_haiku_when_backfill_or_over_ceiling(context, backfill, over_ceiling):
    ctx = context
    if over_ceiling:
        ctx.budget.record('claude-opus-5-5', 20_000_000, 0)
    before = ctx.budget.month_spend_usd()
    topics, model, notes = run(ctx, backfill=backfill)
    haiku = backfill or over_ceiling
    assert model == ('claude-haiku-5-5' if haiku else 'claude-opus-5-5')
    calls = ctx.plain.calls if haiku else ctx.beta.calls
    assert [call['model'] for call in calls] == [model]
    assert (ctx.beta.calls if haiku else ctx.plain.calls) == []
    assert notes == [] and topics == [ctx.topic]
    assert ctx.topic.headline == OUTPUT['headline']
    assert ctx.topic.summary == OUTPUT['summary']
    assert ctx.topic.synthesis == OUTPUT['synthesis']
    assert ctx.topic.item_one_liners == OUTPUT['item_one_liners']
    assert ctx.topic.synthesis_model == model and ctx.topic.synthesized_on == TODAY
    assert ctx.budget.month_spend_usd() - before == pytest.approx(0.00002 if haiku else 0.0008)
    call = calls[0]
    assert call['output_format'] is Synthesis and call['max_tokens'] == 4096
    assert call['output_config'] == {'effort': 'high'}
    assert not {'thinking', 'budget_tokens', 'temperature'} & call.keys()
    if haiku:
        assert 'betas' not in call and 'fallbacks' not in call
    else:
        assert call['betas'] == ['server-side-fallback-2026-07-01']
        assert call['fallbacks'] == 'default'
    assert [message['role'] for message in call['messages']] == ['user']
    prompt = call['messages'][0]['content']
    assert f'{ctx.item.id} | preprint | {TODAY} | Protein design | Original summary.' in prompt
    assert ctx.topic.category in prompt and 'protein design' in prompt
    assert '"preprint":1' in prompt and '"rise_ratio":2.0' in prompt
    assert '80–160 words' in prompt and 'expert' in prompt


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('backfill', [False, True])
def test_synthesis_failure_falls_back_to_item_headline_and_note(context, existing, backfill):
    ctx = context
    if existing:
        ctx.topic.headline = 'Existing headline'
        ctx.topic.synthesis = 'Existing synthesis'
        ctx.topic.synthesized_on = TODAY - timedelta(days=1)
    ctx.topic.summary = 'Old summary'
    original = ctx.topic.model_copy(deep=True)
    ctx.plain.stop_reason = ctx.beta.stop_reason = 'refusal'
    # Refusals must be checked before attempting to validate this payload.
    ctx.plain.output = ctx.beta.output = {'headline': 'x' * 120}
    topics, model, notes = run(ctx, backfill=backfill)
    assert topics == [ctx.topic]
    assert ctx.topic.headline == ctx.item.title
    assert ctx.topic.summary == ctx.item.summary
    assert ctx.topic.synthesis == original.synthesis
    assert ctx.topic.synthesized_on == original.synthesized_on
    assert ctx.topic.synthesis_model == model
    assert notes == [f'synthesis-fallback:{ctx.topic.slug}']
    assert ctx.budget.month_spend_usd() > 0


@pytest.mark.parametrize('field,limit', [('headline', 120), ('summary', 220)])
def test_headline_and_summary_are_truncated_not_dropped(context, field, limit):
    ctx = context
    schema = Synthesis.model_json_schema()['properties']
    assert 'maxLength' not in schema[field]
    ctx.beta.output = {**OUTPUT, field: 'evidence ' * 30}
    _, _, notes = run(ctx)
    assert len(getattr(ctx.topic, field)) <= limit
    assert getattr(ctx.topic, field).endswith('evidence…')
    assert ctx.topic.synthesis == OUTPUT['synthesis']
    assert notes == []
    assert len(ctx.beta.calls) == 1


def test_unranked_topics_untouched(context):
    ctx = context
    unranked = ctx.topic.model_copy(update={'slug': 'unranked', 'headline': 'Saved headline',
                                          'synthesis': 'Saved synthesis'}, deep=True)
    before = unranked.model_dump()
    topics, _, _ = synthesize_top(
        [(ctx.topic, ctx.sig, ctx.scores)], {ctx.topic.slug: [ctx.item], unranked.slug: [ctx.item]},
        ctx.llm, ctx.budget, load_scoring(), TODAY, backfill=False,
    )
    assert topics == [ctx.topic] and unranked.model_dump() == before
    assert len(ctx.beta.calls) == 1


@pytest.mark.parametrize('ranked_before', [False, True])
def test_previous_synthesis_and_one_liner_merge(context, ranked_before):
    ctx = context
    ctx.topic.synthesis = 'Previously saved synthesis'
    ctx.topic.item_one_liners = {'older:item': 'Retained', ctx.item.id: 'Replaced'}
    ctx.topic.history = [TopicDay(date=TODAY - timedelta(days=1), rank=1 if ranked_before else None,
                                  item_ids=[ctx.item.id], count_7d=1, signals=ctx.sig, scores=ctx.scores)]
    run(ctx)
    prompt = ctx.beta.calls[0]['messages'][0]['content']
    assert ('Previously saved synthesis' in prompt) == ranked_before
    assert ctx.topic.item_one_liners == {'older:item': 'Retained', **OUTPUT['item_one_liners']}
    assert ctx.item.summary == 'Original summary.'


@pytest.mark.parametrize('status,attempts', [(429, 4), (500, 4), (400, 1)])
def test_synthesis_reuses_transient_error_retries(context, monkeypatch, status, attempts):
    ctx = context
    ctx.beta.error = anthropic.APIStatusError('failure', response=httpx.Response(
        status, request=httpx.Request('POST', 'https://example.org/messages'),
    ), body=None)
    sleeps = []
    monkeypatch.setattr('pipeline.llm.time.sleep', sleeps.append)
    _, _, notes = run(ctx)
    assert notes == [f'synthesis-fallback:{ctx.topic.slug}']
    assert len(ctx.beta.calls) == attempts
    if status == 429:
        assert len(sleeps) == 3
        assert all(base <= delay <= base + 0.5 for base, delay in zip([1, 2, 4], sleeps))
    else:
        assert sleeps == ([1, 2, 4] if attempts == 4 else [])


def test_sdk_validation_error_is_not_retried(context, caplog):
    from pydantic import ValidationError

    ctx = context
    try:
        Synthesis(**{**OUTPUT, 'headline': None})
    except ValidationError as error:
        ctx.beta.error = error
    _, _, notes = run(ctx)
    assert notes == [f'synthesis-fallback:{ctx.topic.slug}']
    assert len(ctx.beta.calls) == 1
    assert f'id={ctx.topic.slug} reason=validation:headline' in caplog.text


def test_explicit_model_overrides_backfill_selection(context):
    ctx = context
    topics, model, _ = synthesize_top(
        [(ctx.topic, ctx.sig, ctx.scores)], {ctx.topic.slug: [ctx.item]},
        ctx.llm, ctx.budget, load_scoring(), TODAY, backfill=True, model='claude-opus-5-5',
    )
    assert model == topics[0].synthesis_model == 'claude-opus-5-5'
    assert ctx.beta.calls[0]['model'] == model
    assert ctx.plain.calls == []


@pytest.mark.parametrize('limit', [40, 5, 2])
def test_synthesize_caps_items_at_config_limit(context, caplog, limit):
    from unittest.mock import Mock

    ctx = context
    cfg = load_scoring().model_copy(update={'synthesis_max_items': limit})
    preprints = [ctx.item.model_copy(update={
        'id': f'preprint:{i}', 'published_at': TODAY - timedelta(days=i),
    }) for i in range(50)]
    evidence = [ctx.item.model_copy(update={
        'id': f'{kind}:evidence', 'type': kind, 'published_at': TODAY - timedelta(days=100),
    }) for kind in ('published', 'code', 'industry')]
    items = preprints[::-1] + evidence
    original = items[:]
    ctx.llm.synthesize = Mock(return_value=Synthesis(**OUTPUT))
    synthesize_top([(ctx.topic, ctx.sig, ctx.scores)], {ctx.topic.slug: items},
                   ctx.llm, ctx.budget, cfg, TODAY, backfill=False)
    selected = ctx.llm.synthesize.call_args.args[1]
    expected = sorted(evidence, key=lambda item: item.id) + preprints
    assert selected == expected[:limit]
    assert items == original
    assert f'topic={ctx.topic.slug} items=53 selected={limit}' in caplog.text


def test_synthesis_limit_must_be_positive():
    from pydantic import ValidationError
    from pipeline.config import Scoring

    with pytest.raises(ValidationError):
        Scoring(weights={}, synthesis_max_items=0)


def test_synthesis_label_replaces_auto_label(context):
    context.topic.label = 'myopia genetic'
    slug = context.topic.slug
    topics, _, notes = run(context)
    assert topics[0].label == 'Protein Design'
    assert topics[0].slug == slug
    assert notes == []
    prompt = context.beta.calls[0]['messages'][0]['content']
    assert 'Noisy automatic keywords, not the topic name; name the topic from the items: myopia genetic' in prompt


def test_synthesis_label_is_trimmed_and_normalized():
    result = Synthesis(**{**OUTPUT, 'label': '  protein-design: with neural_networks and more! '})
    assert result.label == 'Protein Design With Neural Networks'
    with pytest.raises(ValueError):
        Synthesis(**{**OUTPUT, 'label': '... -- '})


def test_headline_prompt_forbids_counts():
    prompt = Path('pipeline/prompts/synthesize.md').read_text()
    assert 'No item counts or ratios in the headline.' in prompt
    assert 'at most 90 characters' in prompt
    assert '"cluster", "category",' in prompt
    assert '"signal", "items", or "rises" in the headline' in prompt


@pytest.mark.parametrize('field', ['headline', 'summary', 'synthesis', 'item_one_liners'])
def test_ungrounded_synthesis_retries_once_then_falls_back(context, caplog, field):
    ctx = context
    ctx.item.abstract = 'We used 12 datasets.'
    text = {ctx.item.id: '47 datasets'} if field == 'item_one_liners' else '47 datasets'
    ctx.beta.output = [{**OUTPUT, field: text}, {**OUTPUT, field: text}]
    _, _, notes = run(ctx)
    assert len(ctx.beta.calls) == 2
    first, second = ctx.beta.calls
    assert second['model'] == first['model']
    assert second['messages'][0]['content'].startswith(first['messages'][0]['content'])
    assert 'Your previous answer stated numbers not present in the items or signals: 47.' in second['messages'][0]['content']
    assert notes == [f'synthesis-fallback:{ctx.topic.slug}']
    assert ctx.topic.synthesis is None
    assert ctx.topic.headline == ctx.item.title
    assert ctx.llm.fallback_reasons[ctx.topic.slug] == 'grounding'
    assert f'llm_grounding_retry id={ctx.topic.slug} values=47' in caplog.text
    assert 'reason=grounding detail=47' in caplog.text
    assert ctx.budget.month_spend_usd() == pytest.approx(0.0016)


@pytest.mark.parametrize('backfill', [False, True])
def test_ungrounded_synthesis_retry_succeeds(context, backfill):
    ctx = context
    ctx.item.abstract = 'We used 12 datasets.'
    messages = ctx.plain if backfill else ctx.beta
    messages.output = [{**OUTPUT, 'synthesis': '47 datasets'}, {**OUTPUT, 'synthesis': '12 datasets'}]
    _, _, notes = run(ctx, backfill=backfill)
    assert ctx.topic.synthesis == '12 datasets'
    assert notes == []
    assert len(messages.calls) == 2
    assert ctx.topic.slug not in ctx.llm.fallback_reasons


def test_synthesis_counts_from_signals_are_supported(context):
    ctx = context
    ctx.sig.preprint = 7
    ctx.beta.output = {**OUTPUT, 'synthesis': 'seven preprints this week'}
    _, _, notes = run(ctx)
    assert notes == []
    assert len(ctx.beta.calls) == 1


@pytest.mark.parametrize('source', ['signals', 'label', 'title', 'published_at', 'summary', 'abstract'])
def test_synthesis_grounding_includes_all_evidence(context, source):
    ctx = context
    if source == 'signals':
        ctx.sig.preprint = 47
    elif source == 'label':
        ctx.topic.label = '47 datasets'
    elif source == 'published_at':
        ctx.item.published_at = date(2026, 11, 27)
    else:
        setattr(ctx.item, source, '47 datasets')
    ctx.beta.output = {**OUTPUT, 'synthesis': '27' if source == 'published_at' else '47 datasets'}
    _, _, notes = run(ctx)
    assert notes == []
    assert len(ctx.beta.calls) == 1


def test_previous_synthesis_is_not_grounding_source(context):
    ctx = context
    ctx.beta.output = [{**OUTPUT, 'synthesis': '47 datasets'}, OUTPUT]
    result = ctx.llm.synthesize(ctx.topic, [ctx.item], ctx.sig, '47 datasets', 'claude-opus-5-5')
    assert result.synthesis == OUTPUT['synthesis']
    assert '47 datasets' in ctx.beta.calls[0]['messages'][0]['content']
    assert len(ctx.beta.calls) == 2


@pytest.mark.parametrize('backfill,over_ceiling,override', [
    (False, False, None), (True, False, None), (False, True, None),
    (True, False, 'claude-opus-5-5'), (False, False, 'claude-haiku-5-5'),
    (True, True, 'claude-opus-5-5'),
])
def test_top_forty_uses_synthesis_tiers(context, backfill, over_ceiling, override):
    ctx = context
    if over_ceiling:
        ctx.budget.record('claude-opus-5-5', 20_000_000, 0)
    ranked = [(ctx.topic.model_copy(deep=True, update={'slug': str(i)}), ctx.sig, ctx.scores)
              for i in range(40)]
    topics, model, notes = synthesize_top(
        ranked, {row[0].slug: [ctx.item] for row in ranked}, ctx.llm, ctx.budget,
        load_scoring(), TODAY, backfill=backfill, model=override,
    )
    featured = 'claude-haiku-5-5' if over_ceiling else override or ('claude-haiku-5-5' if backfill else 'claude-opus-5-5')
    assert model == featured
    assert [topic.synthesis_model for topic in topics] == [featured] * 5 + [('claude-haiku-5-5' if backfill or over_ceiling or override else 'claude-sonnet-5-5')] * 15 + ['claude-haiku-5-5'] * 20
    assert all(topic.headline and topic.summary and topic.label and topic.synthesis for topic in topics)
    assert notes == []


def test_skipping_cached_topics_preserves_rank_tiers(context):
    ctx = context
    cfg = load_scoring().model_copy(update={'featured_n': 2})
    ranked = [(ctx.topic.model_copy(deep=True, update={'slug': str(i)}), ctx.sig, ctx.scores)
              for i in range(4)]
    before = [row[0].model_dump() for row in ranked[:2]]
    topics, model, _ = synthesize_top(
        ranked, {row[0].slug: [ctx.item] for row in ranked}, ctx.llm, ctx.budget,
        cfg, TODAY, backfill=False, skip_slugs={'0', '1'},
    )
    assert model == 'claude-opus-5-5'
    assert [topic.model_dump() for topic in topics[:2]] == before
    assert len(ctx.beta.calls) == 2
    assert ctx.plain.calls == []


@pytest.mark.parametrize('rank,model', [(1, 'opus'), (5, 'opus'), (6, 'sonnet'),
                                        (20, 'sonnet'), (21, 'haiku'), (40, 'haiku')])
def test_tier_model_by_rank(rank, model):
    assert tier_model(rank, load_scoring(), False, False) == f'claude-{model}-5-5'


def test_tier_model_backfill_and_ceiling_override():
    cfg = load_scoring()
    for rank in range(1, 41):
        assert tier_model(rank, cfg, True, False) == 'claude-haiku-5-5'
        assert tier_model(rank, cfg, False, True) == 'claude-haiku-5-5'
    cfg.backfill_synthesis_model = 'claude-sonnet-5-5'
    assert tier_model(1, cfg, True, False) == 'claude-sonnet-5-5'
    assert tier_model(1, cfg, True, True) == 'claude-haiku-5-5'


def test_sonnet_uses_sdk_beta_fallback_with_opus_limits(context):
    import inspect
    from anthropic.resources.beta.messages import Messages

    ctx = context
    ctx.llm.synthesize(ctx.topic, [ctx.item], ctx.sig, None, 'claude-sonnet-5-5')
    call = ctx.beta.calls[0]
    inspect.signature(Messages.parse).bind(None, **call)
    assert call['fallbacks'] == 'default'
    assert call['betas'] == ['server-side-fallback-2026-07-01']
    assert call['max_tokens'] == 4096
    assert call['output_config'] == {'effort': 'high'}
    assert ctx.plain.calls == []
    assert ctx.budget.month_spend_usd() == pytest.approx(0.0004)


def test_synthesize_top_parallel_preserves_order_and_models(context, caplog):
    from time import perf_counter, sleep

    ctx = context
    ranked = [(ctx.topic.model_copy(deep=True, update={
        'slug': str(i), 'item_one_liners': {'older:item': 'Retained'},
    }), ctx.sig, ctx.scores) for i in range(40)]
    calls = {}

    def synthesize(topic, items, signals, previous, model, *, on_repeated_429=None):
        sleep(0.05)
        calls[topic.slug] = model
        return Synthesis(**{**OUTPUT, 'headline': topic.slug,
                            'item_one_liners': {ctx.item.id: topic.slug}})

    caplog.set_level('INFO', logger='pipeline.synthesize')
    start = perf_counter()
    topics, model, notes = synthesize_top(
        ranked, {row[0].slug: [ctx.item] for row in ranked}, SimpleNamespace(synthesize=synthesize),
        ctx.budget, load_scoring(), TODAY, backfill=False,
    )
    assert perf_counter() - start < 1.2  # Sequential calls alone take two seconds.
    assert [topic.slug for topic in topics] == [str(i) for i in range(40)]
    expected = ['claude-opus-5-5'] * 5 + ['claude-sonnet-5-5'] * 15 + ['claude-haiku-5-5'] * 20
    assert [calls[topic.slug] for topic in topics] == expected
    assert [topic.synthesis_model for topic in topics] == expected
    assert model == expected[0] and notes == []
    for topic in topics:
        assert topic.headline == topic.slug
        assert topic.item_one_liners == {'older:item': 'Retained', ctx.item.id: topic.slug}
    assert f'stage=synthesize event=complete date={TODAY} workers=12 elapsed=' in caplog.text


def test_parallel_fallback_notes_follow_rank(context):
    from threading import Event

    ctx = context
    second_finished = Event()
    ranked = [(ctx.topic.model_copy(deep=True, update={'slug': slug}), ctx.sig, ctx.scores)
              for slug in ('z-first', 'a-second')]

    def synthesize(topic, *args, **kwargs):
        if topic.slug == 'z-first':
            assert second_finished.wait(2)
        else:
            second_finished.set()
        return None

    topics, _, notes = synthesize_top(
        ranked, {row[0].slug: [ctx.item] for row in ranked}, SimpleNamespace(synthesize=synthesize),
        ctx.budget, load_scoring(), TODAY, backfill=False,
    )
    assert notes == ['synthesis-fallback:z-first', 'synthesis-fallback:a-second']
    assert all(topic.headline == ctx.item.title and topic.summary == ctx.item.summary for topic in topics)


@pytest.mark.parametrize('workers', [1, 6])
def test_synthesize_top_throttles_after_repeated_429(context, monkeypatch, caplog, workers):
    from collections import Counter
    from threading import Barrier, Lock
    from time import sleep

    ctx = context
    cfg = load_scoring().model_copy(update={'synthesis_workers': workers})
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    caplog.set_level('INFO', logger='pipeline.synthesize')
    # Reusing the LLM on the next day must restore the configured concurrency.
    for day in (TODAY, TODAY + timedelta(days=1)):
        barrier, lock = Barrier(workers), Lock()
        attempts, active, peaks, later_starts = Counter(), 0, [], []

        def parse(**kwargs):
            nonlocal active
            prompt = kwargs['messages'][0]['content']
            with lock:
                index = list(attempts).index(prompt) if prompt in attempts else len(attempts)
                attempts[prompt] += 1
                attempt = attempts[prompt]
                active += 1
                peaks.append(active)
                if index >= workers:
                    later_starts.append(active)
            try:
                if index < workers and attempt == 1:
                    barrier.wait(timeout=2)
                if index == 0 and attempt <= 2:
                    raise anthropic.APIStatusError('rate limited', response=httpx.Response(
                        429, request=httpx.Request('POST', 'https://example.org/messages'),
                    ), body=None)
                sleep(0.03)
                return SimpleNamespace(stop_reason='end_turn', parsed_output=OUTPUT,
                                       usage=SimpleNamespace(input_tokens=100, output_tokens=20))
            finally:
                with lock:
                    active -= 1

        monkeypatch.setattr(ctx.plain, 'parse', parse)
        ranked = [(ctx.topic.model_copy(deep=True, update={'slug': str(i), 'label': f'Topic {i}'}),
                   ctx.sig, ctx.scores) for i in range(18)]
        topics, _, notes = synthesize_top(
            ranked, {row[0].slug: [ctx.item] for row in ranked}, ctx.llm, ctx.budget,
            cfg, day, backfill=True,
        )
        reduced = max(1, workers // 2)
        assert max(peaks) == workers
        assert later_starts and max(later_starts) <= reduced
        assert sorted(attempts.values()) == [1] * 17 + [3]
        assert len(topics) == 18 and notes == []
        assert all(topic.synthesis == OUTPUT['synthesis'] for topic in topics)
        assert f'stage=synthesize event=throttled workers={reduced} date={day}' in caplog.text
        assert f'date={day} workers={reduced} elapsed=' in caplog.text
    assert caplog.text.count('event=throttled') == 2


@pytest.mark.parametrize('statuses,notifications', [([429, 500, 429], 0), ([429, 429], 1)])
def test_repeated_429_notification_requires_consecutive_errors(context, monkeypatch, statuses, notifications):
    ctx = context
    responses = iter(statuses + [200])
    notified = []

    def parse(**kwargs):
        status = next(responses)
        if status != 200:
            raise anthropic.APIStatusError('failure', response=httpx.Response(
                status, request=httpx.Request('POST', 'https://example.org/messages'),
            ), body=None)
        return SimpleNamespace(stop_reason='end_turn', parsed_output=OUTPUT,
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20))

    monkeypatch.setattr(ctx.plain, 'parse', parse)
    monkeypatch.setattr('pipeline.llm.time.sleep', lambda _: None)
    result = ctx.llm.synthesize(ctx.topic, [ctx.item], ctx.sig, None, 'claude-haiku-5-5',
                                on_repeated_429=lambda: notified.append(True))
    assert result is not None
    assert len(notified) == notifications


@pytest.mark.parametrize('label', ['Mechanisms Viral', 'Untitled Topic'])
def test_synthesis_fallback_uses_top_item_title(context, label):
    ctx = context
    ctx.topic.label = label
    ctx.beta.stop_reason = 'refusal'
    published = ctx.item.model_copy(update={
        'id': 'pubmed:paper', 'type': 'published', 'published_at': TODAY - timedelta(days=10),
        'title': 'A specific published finding', 'summary': 'Published enrichment.',
    })
    older = published.model_copy(update={'id': 'pubmed:older', 'published_at': TODAY - timedelta(days=11)})
    synthesize_top([(ctx.topic, ctx.sig, ctx.scores)],
                   {ctx.topic.slug: [ctx.item, older, published]}, ctx.llm, ctx.budget,
                   load_scoring(), TODAY, backfill=False)
    assert ctx.topic.headline == published.title
    assert ctx.topic.headline not in {label, 'Untitled Topic'}
    assert ctx.topic.summary == published.summary


@pytest.mark.parametrize('length', [90, 91, 120])
def test_synthesis_headline_kept_up_to_120(length):
    headline = 'h' * length
    assert Synthesis(**{**OUTPUT, 'headline': headline}).headline == headline


@pytest.mark.parametrize('length', [160, 161, 220])
def test_synthesis_summary_kept_up_to_220(length):
    summary = 's' * length
    assert Synthesis(**{**OUTPUT, 'summary': summary}).summary == summary
