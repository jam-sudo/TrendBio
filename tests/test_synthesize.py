from datetime import date, timedelta
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from pipeline.budget import Budget
from pipeline.config import load_scoring
from pipeline.llm import LLM, Synthesis
from pipeline.models import Item, Scores, Signals, Topic, TopicDay
from pipeline.synthesize import synthesize_top


TODAY = date(2026, 11, 2)
OUTPUT = dict(headline='Protein design advances', summary='New protein design evidence.',
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
            stop_reason=self.stop_reason, parsed_output=self.output,
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
    assert ctx.topic.category in prompt and ctx.topic.label in prompt
    assert '"preprint":1' in prompt and '"rise_ratio":2.0' in prompt
    assert '80–160 words' in prompt and 'expert' in prompt


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('backfill', [False, True])
def test_synthesis_failure_falls_back_to_label_headline_and_note(context, existing, backfill):
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
    assert ctx.topic.headline == (original.headline or ctx.topic.label.title())
    assert ctx.topic.summary == ''
    assert ctx.topic.synthesis == original.synthesis
    assert ctx.topic.synthesized_on == original.synthesized_on
    assert ctx.topic.synthesis_model == model
    assert notes == [f'synthesis-fallback:{ctx.topic.slug}']
    assert ctx.budget.month_spend_usd() > 0


@pytest.mark.parametrize('field,length', [('headline', 120), ('summary', 161)])
def test_headline_and_summary_length_limits_enforced_by_schema(context, field, length):
    ctx = context
    schema = Synthesis.model_json_schema()['properties']
    assert schema['headline']['maxLength'] == 90
    assert schema['summary']['maxLength'] == 160
    ctx.beta.output = {**OUTPUT, field: 'x' * length}
    _, _, notes = run(ctx)
    assert ctx.topic.headline == ctx.topic.label.title()
    assert ctx.topic.summary == '' and ctx.topic.synthesis is None
    assert notes == [f'synthesis-fallback:{ctx.topic.slug}']
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
    assert sleeps == ([1, 2, 4] if attempts == 4 else [])


def test_sdk_validation_error_is_not_retried(context):
    from pydantic import ValidationError

    ctx = context
    try:
        Synthesis(**{**OUTPUT, 'headline': 'x' * 120})
    except ValidationError as error:
        ctx.beta.error = error
    _, _, notes = run(ctx)
    assert notes == [f'synthesis-fallback:{ctx.topic.slug}']
    assert len(ctx.beta.calls) == 1


def test_explicit_model_overrides_backfill_selection(context):
    ctx = context
    topics, model, _ = synthesize_top(
        [(ctx.topic, ctx.sig, ctx.scores)], {ctx.topic.slug: [ctx.item]},
        ctx.llm, ctx.budget, load_scoring(), TODAY, backfill=True, model='claude-opus-5-5',
    )
    assert model == topics[0].synthesis_model == 'claude-opus-5-5'
    assert ctx.beta.calls[0]['model'] == model
    assert ctx.plain.calls == []
