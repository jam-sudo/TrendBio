import hashlib
import json
import shutil
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from typer.testing import CliRunner

from pipeline.budget import Budget
from pipeline.config import load_scoring, load_taxonomy
from pipeline.jsonio import item_path
from pipeline.llm import Enrichment, Synthesis
from pipeline.models import Item
from pipeline.store import Store
from pipeline.run import Deps, is_degraded, run_backfill, run_day
from pipeline.__main__ import app


TODAY = date(2026, 11, 20)


class FakeAdapter:
    def __init__(self, name, items=(), error=None):
        self.name, self.items, self.error = name, items, error
        self.calls = []

    def fetch(self, start, end, client):
        self.calls.append((start, end))
        if self.error:
            raise self.error
        return [item.model_copy(deep=True) for item in self.items
                if start <= item.published_at <= end]


class FakeLLM:
    def __init__(self, budget):
        self.budget = budget
        self.fallback = False
        self.calls = []
        self.batches = []
        self.irrelevant_ids: set[str] = set()

    def enrich(self, item, taxonomy, hints):
        self.budget.record('claude-haiku-5-5', 100, 20)
        return Enrichment(summary=item.title, primary='structural', secondary=[],
                          relevant=item.id not in self.irrelevant_ids)

    def enrich_batch(self, items, taxonomy, hints_by_id):
        self.batches.append([item.id for item in items])
        self.budget.record('claude-haiku-5-5', 100 * len(items), 20 * len(items), batch=True)
        return {item.id: Enrichment(summary=item.title, primary='structural', secondary=[],
                                    relevant=item.id not in self.irrelevant_ids)
                for item in items}

    def synthesize(self, topic, items, signals, previous, model):
        self.calls.append(model)
        self.budget.record(model, 100, 20)
        if self.fallback:
            return None
        return Synthesis(label='Protein Design', headline='Protein design evidence', summary='New evidence.',
                         synthesis='Evidence from these items.', item_one_liners={})


class FakeEmbedder:
    def embed(self, texts):
        return np.array([[1, *(byte / 2550 for byte in hashlib.sha256(
            text.split('\n', 1)[0].encode()).digest()[:4])] for text in texts], dtype=np.float32)


def tree(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


@pytest.fixture
def ctx(tmp_path, fixtures_root):
    root = tmp_path / 'data'
    shutil.copytree(fixtures_root / 'data', root)
    store = Store(root, 'computational')
    items = [Item(id=f'biorxiv:test-{i}', source='biorxiv', type='preprint',
                  title=f'Protein binder experiment {i}', url=f'https://example.org/{i}',
                  doi=None, published_at=TODAY, first_seen=TODAY, authors=[], org=None,
                  abstract=f'Binder experiment {i}.', summary=None, primary_category=None,
                  published_doi=None, preprint_id=None) for i in range(3)]
    budget = Budget(root / 'computational/llm_spend.json', 50)
    llm = FakeLLM(budget)
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: pytest.fail(f'unexpected network: {request.url}')))
    deps = Deps([FakeAdapter('biorxiv', items), FakeAdapter('arxiv'), FakeAdapter('pubmed')],
                llm, FakeEmbedder(), budget, load_scoring(), load_taxonomy('computational'), {}, client)
    yield SimpleNamespace(store=store, deps=deps, items=items, root=root)
    client.close()


def test_run_day_writes_day_topics_items(ctx):
    result = run_day('computational', TODAY, ctx.store, ctx.deps)
    assert ctx.store.get_day(TODAY) == result
    assert result.ranked and result.run.status == 'ok'
    assert ctx.deps.adapters[0].calls == [(TODAY - timedelta(days=6), TODAY)]
    for item in ctx.items:
        assert ctx.store.get_item(item.id).summary
    assert ctx.store.get_embeddings([item.id for item in ctx.items]).shape == (3, 5)
    for topic in ctx.store.all_topics():
        entry = next(entry for entry in topic.history if entry.date == TODAY)
        assert len(topic.related) == 3 and topic.slug not in topic.related
        if topic.slug in {row.slug for row in result.ranked}:
            assert entry.rank and entry.signals.preprint == 3
        else:
            assert entry.rank is None and entry.count_7d == 0


def test_rerun_same_day_is_idempotent(ctx):
    run_day('computational', TODAY, ctx.store, ctx.deps)
    before = tree(ctx.root)
    run_day('computational', TODAY, ctx.store, ctx.deps)
    assert tree(ctx.root) == before
    topic = ctx.store.get_topic('protein-design-binders-a1b2')
    assert sum(entry.date == TODAY for entry in topic.history) == 1


def test_zero_clusters_writes_empty_ranked_ok_status(ctx):
    ctx.deps.adapters[0].items = ctx.items[:1]
    result = run_day('computational', TODAY, ctx.store, ctx.deps)
    assert result.ranked == [] and result.run.status == 'ok'


def test_all_paper_sources_failed_writes_nothing_and_exits_nonzero(ctx, monkeypatch):
    from pipeline.collect import AllPaperSourcesFailed

    for adapter in ctx.deps.adapters:
        adapter.error = RuntimeError('offline')
    before = tree(ctx.root)
    with pytest.raises(AllPaperSourcesFailed):
        run_day('computational', TODAY, ctx.store, ctx.deps)
    assert tree(ctx.root) == before
    monkeypatch.setattr('pipeline.__main__.build_deps', lambda *args: ctx.deps)
    result = CliRunner().invoke(app, ['run', '--domain', 'computational', '--date', str(TODAY),
                                    '--data-root', str(ctx.root)])
    assert result.exit_code == 1
    assert 'AllPaperSourcesFailed' in result.output
    assert tree(ctx.root) == before


def test_dry_run_leaves_data_untouched(ctx, capsys):
    before = tree(ctx.root)
    result = run_day('computational', TODAY, ctx.store, ctx.deps, dry_run=True)
    assert result.ranked and tree(ctx.root) == before
    output = json.loads(capsys.readouterr().out)
    assert output['estimated_usd'] > 0
    assert output['usage']['claude-haiku-5-5']['input_tokens'] == 300
    assert output['usage']['claude-opus-5-5']['output_tokens'] == 20
    assert Store(Path(output['staging_root']), 'computational').get_day(TODAY) == result


@pytest.mark.parametrize('count,attempted,expected', [
    pytest.param(3, 10, False, id='few_enrichment_fallbacks_do_not_degrade'),
    pytest.param(4, 100, False, id='fallbacks_above_floor_but_below_rate_do_not_degrade'),
    pytest.param(5, 10, True, id='many_enrichment_fallbacks_degrade'),
    pytest.param(4, 20, False, id='fallbacks_at_rate_do_not_degrade'),
])
def test_enrichment_fallback_threshold(count, attempted, expected):
    notes = [f'enrichment-fallback:{i}' for i in range(count)]
    sources = dict.fromkeys(('biorxiv', 'arxiv', 'pubmed', 'github', 'rss'), 'ok')
    assert is_degraded(notes, sources, over_ceiling=False,
                       window_item_ids={str(i) for i in range(attempted)}, cfg=load_scoring()) is expected


def test_synthesis_fallback_always_degrades():
    assert is_degraded(['synthesis-fallback:topic'], {},
                       over_ceiling=False, window_item_ids=set(), cfg=load_scoring())


def test_paper_source_failure_always_degrades():
    assert is_degraded([], {'pubmed': 'failed'},
                       over_ceiling=False, window_item_ids=set(), cfg=load_scoring())


@pytest.mark.parametrize('copies', [2, 5])
def test_duplicate_fallback_notes_count_once(copies):
    assert not is_degraded(['enrichment-fallback:x'] * copies, {},
                           over_ceiling=False, window_item_ids={'x'}, cfg=load_scoring())


def test_budget_over_ceiling_always_degrades():
    assert is_degraded([], {}, over_ceiling=True,
                       window_item_ids=set(), cfg=load_scoring())


@pytest.mark.parametrize('synthesis_fallback', [False, True])
def test_degraded_when_fallback_note_present(ctx, monkeypatch, synthesis_fallback):
    original = ctx.deps.llm.enrich
    monkeypatch.setattr(ctx.deps.llm, 'enrich', lambda item, *args:
                        None if item.id == ctx.items[0].id else original(item, *args))
    ctx.deps.llm.fallback = synthesis_fallback
    result = run_day('computational', TODAY, ctx.store, ctx.deps)
    assert result.run.status == ('degraded' if synthesis_fallback else 'ok')
    assert sum(note.startswith('enrichment-fallback:') for note in result.run.notes) == 1
    assert any(note.startswith('synthesis-fallback:') for note in result.run.notes) == synthesis_fallback
    before = tree(ctx.root)
    run_day('computational', TODAY, ctx.store, ctx.deps)
    assert tree(ctx.root) == before


def test_degraded_threshold_counts_window_before_relevance_filter(ctx, monkeypatch):
    ctx.items.extend(ctx.items[0].model_copy(update={
        'id': f'biorxiv:test-{i}', 'title': f'Protein binder experiment {i}',
        'url': f'https://example.org/{i}',
    }) for i in range(3, 20))
    ctx.deps.llm.irrelevant_ids = {item.id for item in ctx.items[4:]}
    fallback_ids = {item.id for item in ctx.items[:4]}
    original = ctx.deps.llm.enrich
    monkeypatch.setattr(ctx.deps.llm, 'enrich', lambda item, *args:
                        None if item.id in fallback_ids else original(item, *args))
    result = run_day('computational', TODAY, ctx.store, ctx.deps)
    assert sum(note.startswith('enrichment-fallback:') for note in result.run.notes) == 4
    assert result.run.status == 'ok'


def test_backfill_runs_days_in_order_and_resumes_from_checkpoint(ctx, monkeypatch):
    import pipeline.run as runner

    real_run = runner.run_day
    calls = []
    end = TODAY + timedelta(days=2)

    def interrupted(domain, day, store, deps, **kwargs):
        calls.append(day)
        assert kwargs == {'backfill': True, 'skip_collect': True}
        if day == end:
            raise RuntimeError('interrupted')
        return real_run(domain, day, store, deps, **kwargs)

    monkeypatch.setattr(runner, 'run_day', interrupted)
    with pytest.raises(RuntimeError, match='interrupted'):
        run_backfill('computational', TODAY, end, ctx.store, ctx.deps, resume=False)
    assert calls == [TODAY, TODAY + timedelta(days=1), end]
    checkpoint = ctx.root / 'computational/.backfill_state.json'
    assert json.loads(checkpoint.read_text())['last_day'] == str(TODAY + timedelta(days=1))
    assert json.loads(checkpoint.read_text())['range'] == {'from': str(TODAY), 'to': str(end)}
    batches = len(ctx.deps.llm.batches)
    source_calls = [len(adapter.calls) for adapter in ctx.deps.adapters]
    calls.clear()

    def resumed(domain, day, store, deps, **kwargs):
        calls.append(day)
        return real_run(domain, day, store, deps, **kwargs)

    monkeypatch.setattr(runner, 'run_day', resumed)
    run_backfill('computational', TODAY, end, ctx.store, ctx.deps, resume=True)
    assert calls == [end]
    assert len(ctx.deps.llm.batches) == batches
    assert [len(adapter.calls) for adapter in ctx.deps.adapters] == source_calls
    assert ctx.store.get_day(end).run.backfilled
    assert ctx.store.get_day(end).run.synthesis_model == 'claude-haiku-5-5'


@pytest.fixture
def october_checkpoint(ctx):
    path = ctx.root / 'computational/.backfill_state.json'
    state = {
        'range': {'from': '2026-10-01', 'to': '2026-10-31'},
        'stage': 'days', 'last_day': '2026-10-31',
        'done_sources': [adapter.name for adapter in ctx.deps.adapters],
        'next_chunk': {adapter.name: '2026-11-01' for adapter in ctx.deps.adapters},
        'failed_chunks': [{'source': 'arxiv', 'start': '2026-10-01', 'end': '2026-10-31'}],
    }
    ctx.store._write(path, state)
    return path


def test_resume_ignores_checkpoint_from_other_range(ctx, october_checkpoint, caplog):
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    run_backfill('computational', start, end, ctx.store, ctx.deps, resume=True)
    assert all(ctx.store.get_day(start + timedelta(days=i)) is not None for i in range(30))
    assert all(adapter.calls == [(start, end)] for adapter in ctx.deps.adapters)
    assert any(record.levelname == 'WARNING' and record.getMessage() == (
        'stage=backfill event=checkpoint_ignored reason=range_mismatch previous=2026-10-01..2026-10-31'
    ) for record in caplog.records)


def test_resume_ignores_legacy_checkpoint_without_range(ctx, october_checkpoint, caplog):
    state = json.loads(october_checkpoint.read_text())
    del state['range']
    ctx.store._write(october_checkpoint, state)
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    run_backfill('computational', start, end, ctx.store, ctx.deps, resume=True)
    assert all(ctx.store.get_day(start + timedelta(days=i)) is not None for i in range(30))
    assert all(adapter.calls == [(start, end)] for adapter in ctx.deps.adapters)
    assert any(record.levelname == 'WARNING' and record.getMessage() == (
        'stage=backfill event=checkpoint_ignored reason=range_mismatch previous=unknown..unknown'
    ) for record in caplog.records)


def test_completed_backfill_removes_checkpoint(ctx, caplog):
    caplog.set_level('INFO', logger='pipeline.run')
    run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
    assert ctx.store.get_day(TODAY) is not None
    assert not (ctx.root / 'computational/.backfill_state.json').exists()
    assert f'stage=backfill event=complete range={TODAY}..{TODAY}' in caplog.text


def test_backfill_without_resume_starts_fresh(ctx, october_checkpoint, monkeypatch):
    monkeypatch.setattr('pipeline.__main__.build_deps', lambda *args: ctx.deps)
    result = CliRunner().invoke(app, ['backfill', '--domain', 'computational',
                                    '--from', '2026-10-01', '--to', '2026-10-31',
                                    '--data-root', str(ctx.root)])
    assert result.exit_code == 0, result.output
    start, end = date(2026, 10, 1), date(2026, 10, 31)
    assert all(ctx.store.get_day(start + timedelta(days=i)) is not None for i in range(31))
    assert all(adapter.calls == [(start, end - timedelta(days=1)), (end, end)]
               for adapter in ctx.deps.adapters)
    assert not october_checkpoint.exists()


def test_unexpected_failure_rolls_back_items_and_budget(ctx, monkeypatch):
    before = tree(ctx.root)

    def fail(*args, **kwargs):
        raise RuntimeError('after enrichment')

    monkeypatch.setattr('pipeline.run.synthesize_top', fail)
    with pytest.raises(RuntimeError, match='after enrichment'):
        run_day('computational', TODAY, ctx.store, ctx.deps)
    assert tree(ctx.root) == before
    assert not list(ctx.root.parent.glob('.pipeline-stage-*'))


def test_commit_failure_restores_replaced_files(ctx, monkeypatch):
    import os

    before = tree(ctx.root)
    original_replace = os.replace
    committed = []

    def interrupted(source, target):
        if Path(target).is_relative_to(ctx.root):
            committed.append(Path(target))
            if Path(target).name == 'protein-design-binders-a1b2.json':
                raise OSError('commit interrupted')
        return original_replace(source, target)

    monkeypatch.setattr('pipeline.run.os.replace', interrupted)
    with pytest.raises(OSError, match='commit interrupted'):
        run_day('computational', TODAY, ctx.store, ctx.deps)
    assert len(committed) >= 4
    assert tree(ctx.root) == before


def test_cli_resynthesize_honors_model(ctx, monkeypatch):
    run_day('computational', TODAY, ctx.store, ctx.deps, backfill=True)
    monkeypatch.setattr('pipeline.__main__.build_deps', lambda *args: ctx.deps)
    result = CliRunner().invoke(app, ['resynthesize', '--domain', 'computational',
                                    '--from', str(TODAY), '--to', str(TODAY),
                                    '--model', 'claude-opus-5-5', '--data-root', str(ctx.root)])
    assert result.exit_code == 0, result.output
    day = ctx.store.get_day(TODAY)
    assert day.run.synthesis_model == ctx.deps.llm.calls[-1] == 'claude-opus-5-5'
    assert ctx.store.get_topic(day.ranked[0].slug).synthesis_model == 'claude-opus-5-5'


def test_cli_resynthesize_uses_threshold_rule(ctx, monkeypatch):
    day = run_day('computational', TODAY, ctx.store, ctx.deps, backfill=True)
    day.run.status = 'degraded'
    day.run.notes = [f'enrichment-fallback:{item.id}' for item in ctx.items[:2]]
    day.run.notes += [f'enrichment-fallback:outside-{i}' for i in range(60)]
    ctx.store.put_day(day)
    monkeypatch.setattr('pipeline.__main__.build_deps', lambda *args: ctx.deps)
    result = CliRunner().invoke(app, ['resynthesize', '--domain', 'computational',
                                    '--from', str(TODAY), '--to', str(TODAY),
                                    '--model', 'claude-opus-5-5', '--data-root', str(ctx.root)])
    assert result.exit_code == 0, result.output
    refreshed = ctx.store.get_day(TODAY)
    assert refreshed.run.status == 'ok'
    assert refreshed.run.notes == sorted(day.run.notes)


def test_cli_redacts_secret_exception_messages(ctx, monkeypatch):
    secret = 'test-key-never-log-this'
    monkeypatch.setenv('ANTHROPIC_API_KEY', secret)

    def fail(*args):
        raise RuntimeError(f'bad key: {secret}')

    monkeypatch.setattr('pipeline.__main__.build_deps', fail)
    result = CliRunner().invoke(app, ['run', '--data-root', str(ctx.root)])
    assert result.exit_code == 1
    assert 'RuntimeError: bad key: [redacted]' in result.output
    assert secret not in result.output


def test_partial_paper_failure_marks_day_degraded(ctx):
    ctx.deps.adapters[1].error = RuntimeError('offline')
    result = run_day('computational', TODAY, ctx.store, ctx.deps)
    assert result.run.status == 'degraded'
    assert result.run.source_status['arxiv'] == 'failed'


def test_backfill_chunks_dates_and_preserves_publication_day(ctx, monkeypatch):
    import pipeline.run as runner

    start = TODAY - timedelta(days=61)
    end = TODAY
    ctx.items[0].published_at = ctx.items[0].first_seen = start
    ctx.items[1].published_at = ctx.items[1].first_seen = start + timedelta(days=30)
    calls = []
    def record_day(domain, day, *args, **kwargs):
        calls.append(day)
        return SimpleNamespace(ranked=[])

    monkeypatch.setattr(runner, 'run_day', record_day)
    run_backfill('computational', start, end, ctx.store, ctx.deps, resume=False)
    assert ctx.deps.adapters[0].calls == [
        (start, start + timedelta(days=29)),
        (start + timedelta(days=30), start + timedelta(days=59)),
        (start + timedelta(days=60), end),
    ]
    assert calls == [start + timedelta(days=i) for i in range(62)]
    for item in ctx.items:
        assert ctx.store.get_item(item.id).first_seen == item.published_at
    assert ctx.deps.llm.batches
    assert all(len(batch) <= 2000 for batch in ctx.deps.llm.batches)


@pytest.mark.parametrize('setting', [{}, {'history_seeding': False}])
def test_backfill_skips_disabled_github_history(ctx, monkeypatch, caplog, setting):
    from pipeline.sources.github import GithubAdapter

    caplog.set_level('INFO', logger='pipeline.run')
    github = GithubAdapter({'github': {'watchlist': ['org/watchlist'], **setting}})
    github.fetch = lambda *args: []
    ctx.deps.adapters.append(github)
    before = ctx.store.star_counts()
    monkeypatch.setattr('pipeline.run.seed_star_history',
                        lambda *args: pytest.fail('disabled history seeding must not run'))
    run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
    messages = [record.getMessage() for record in caplog.records if 'stage=github' in record.getMessage()]
    assert messages == ['stage=github_history event=skipped reason=disabled_in_config']
    assert ctx.store.star_counts() == before
    assert ctx.store.get_day(TODAY).run.status == 'ok'


def test_backfill_seeds_long_github_history_and_daily_run_prunes_it(ctx, monkeypatch, caplog):
    caplog.set_level('INFO', logger='pipeline.run')
    import pipeline.run as runner
    from pipeline.sources.github import GithubAdapter

    github = GithubAdapter({'github': {'watchlist': ['org/watchlist'], 'history_seeding': True}},
                           star_gain_threshold=100)
    github.fetch = lambda *args: []
    github.repo_cache = {'repos': {'org/topic': {'full_name': 'org/topic', 'stargazers_count': 30}}}
    ctx.deps.adapters.append(github)
    history = [(TODAY - timedelta(days=300), 1), (TODAY - timedelta(days=7), 20), (TODAY, 30)]
    fetched = []

    def star_history(repo, client):
        fetched.append(repo)
        return history

    monkeypatch.setattr('pipeline.sources.github.fetch_star_history', star_history)
    run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
    assert fetched == ['org/watchlist', 'org/topic']
    assert any('stage=github_star_history event=end elapsed=' in record.getMessage()
               and 'repos=2' in record.getMessage() for record in caplog.records)
    assert ctx.store.star_counts() == dict.fromkeys(fetched, history)
    github.observations = dict.fromkeys(fetched, 31)
    run_day('computational', TODAY + timedelta(days=1), ctx.store, ctx.deps)
    assert ctx.store.star_counts() == dict.fromkeys(fetched, history[1:] + [(TODAY + timedelta(days=1), 31)])


@pytest.mark.parametrize('statuses', [(401, 401, 401), (403, 403, 403), (404, 404, 404), (401, 403, 404)])
def test_backfill_stops_unavailable_github_history(ctx, caplog, statuses):
    from pipeline.sources.github import GithubAdapter

    repos = [f'org/repo-{i}' for i in range(4)]
    github = GithubAdapter({'github': {'watchlist': repos, 'history_seeding': True}})
    github.fetch = lambda *args: []
    ctx.deps.adapters.append(github)
    paths = []
    failures = iter(statuses)

    def respond(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/stargazers'):
            return httpx.Response(next(failures), headers={'X-RateLimit-Remaining': '4863'})
        return httpx.Response(200, json={'stargazers_count': 10})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        ctx.deps.client = client
        run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
        assert client.event_hooks['response'] == []
    assert paths == [path for repo in repos[:3]
                     for path in (f'/repos/{repo}', f'/repos/{repo}/stargazers')]
    warnings = [record.getMessage() for record in caplog.records if record.levelname == 'WARNING']
    assert warnings == [f'stage=github_history event=stopped reason=endpoint_unavailable status={statuses[-1]}']
    assert ctx.store.get_day(TODAY).run.status == 'ok'


def test_stage_logs_have_timings_and_counts_without_item_content(ctx, caplog):
    caplog.set_level('INFO', logger='pipeline.run')
    run_day('computational', TODAY, ctx.store, ctx.deps)
    messages = [record.getMessage() for record in caplog.records if record.name == 'pipeline.run']
    for stage in ('collect', 'dedupe', 'enrich', 'embed', 'cluster', 'continuity',
                  'score_rank', 'synthesize', 'write', 'commit'):
        for event in ('start', 'end'):
            assert any(f'stage={stage} event={event} elapsed=' in message for message in messages)
    assert any('source=biorxiv items=3' in message for message in messages)
    assert any('new=3 llm_fallbacks=0' in message for message in messages)
    assert any('model=claude-opus-5-5' in message for message in messages)
    assert all(item.abstract not in caplog.text and item.url not in caplog.text for item in ctx.items)


def test_daily_embeds_new_and_existing_missing_embeddings_in_one_call(ctx):
    from unittest.mock import Mock

    existing = ctx.items[0].model_copy(update={'id': 'biorxiv:existing', 'summary': 'Already summarized'})
    ctx.store.put_item(existing)
    ctx.deps.embedder.embed = Mock(wraps=ctx.deps.embedder.embed)
    run_day('computational', TODAY, ctx.store, ctx.deps)
    ctx.deps.embedder.embed.assert_called_once()
    assert len(ctx.deps.embedder.embed.call_args.args[0]) == 4
    assert ctx.store.get_embeddings([existing.id]).shape == (1, 5)


def test_daily_embedding_failure_leaves_no_enrichment_committed(ctx):
    from unittest.mock import Mock

    before = tree(ctx.root)
    ctx.deps.embedder.embed = Mock(side_effect=RuntimeError('embedding failed'))
    with pytest.raises(RuntimeError, match='embedding failed'):
        run_day('computational', TODAY, ctx.store, ctx.deps)
    assert tree(ctx.root) == before


def test_cli_configures_safe_stdout_logging(monkeypatch):
    import logging
    from unittest.mock import Mock
    from pipeline.__main__ import configure_logging

    configure = Mock()
    monkeypatch.setattr(logging, 'basicConfig', configure)
    configure_logging()
    assert configure.call_args.kwargs['level'] == logging.INFO
    assert configure.call_args.kwargs['format'] == '%(asctime)s %(levelname)s %(name)s: %(message)s'
    for name in ('httpx', 'httpcore', 'httpx2', 'httpcore2'):
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING


def test_enrich_stage_logs_fallback_reason_counts(ctx, caplog):
    caplog.set_level('INFO', logger='pipeline.run')
    reasons = ['refusal:bio', 'api_error:401', 'refusal:bio']
    ctx.deps.llm.fallback_reasons = {item.id: reason for item, reason in zip(ctx.items, reasons)}
    ctx.deps.llm.enrich = lambda *args: None
    run_day('computational', TODAY, ctx.store, ctx.deps)
    message = next(record.getMessage() for record in caplog.records
                   if 'stage=enrich event=end' in record.getMessage())
    assert "llm_fallbacks=3 fallback_reasons={'refusal:bio': 2, 'api_error:401': 1}" in message
    assert all(item.abstract not in caplog.text for item in ctx.items)


def test_backfill_chunk_failure_is_logged_and_skipped(ctx, caplog, capsys):
    caplog.set_level('INFO', logger='pipeline.run')
    adapter = ctx.deps.adapters[0]
    adapter.config = {'biorxiv': {'backfill_chunk_days': 1}}
    for index, item in enumerate(ctx.items):
        item.published_at = TODAY + timedelta(days=index)
    fetch = adapter.fetch
    failed_day = TODAY + timedelta(days=1)

    def flaky(start, end, client):
        if start == failed_day:
            raise RuntimeError('https://example.org/?secret=must-not-log')
        return fetch(start, end, client)

    adapter.fetch = flaky
    run_backfill('computational', TODAY, TODAY + timedelta(days=2), ctx.store, ctx.deps, resume=False)
    assert ctx.store.get_item(ctx.items[0].id).summary
    assert ctx.store.get_item(ctx.items[1].id) is None
    assert ctx.store.get_item(ctx.items[2].id).summary
    state = json.loads((ctx.root / 'computational/.backfill_state.json').read_text())
    assert state['failed_chunks'] == [{'source': 'biorxiv', 'start': str(failed_day), 'end': str(failed_day)}]
    assert state['stage'] == 'days' and state['last_day'] == str(TODAY + timedelta(days=2))
    assert ctx.store.get_day(failed_day).run.source_status['biorxiv'] == 'failed'
    assert ctx.store.get_day(failed_day).run.status == 'degraded'
    assert (f'stage=collect event=chunk_failed source=biorxiv chunk={failed_day}..{failed_day} '
            'error=RuntimeError') in caplog.text
    assert 'secret' not in caplog.text
    summary = 'backfill_summary collected=2 failed_chunks=1'
    assert summary in capsys.readouterr().out
    assert any(record.levelname == 'WARNING' and record.getMessage() == summary for record in caplog.records)


def test_backfill_resume_retries_failed_chunks_first(ctx):
    adapter = ctx.deps.adapters[0]
    adapter.config = {'biorxiv': {'backfill_chunk_days': 1}}
    ctx.items[1].published_at = TODAY + timedelta(days=1)
    fetch = adapter.fetch
    interrupted = True
    calls = []

    def flaky(start, end, client):
        calls.append(('biorxiv', start))
        if interrupted:
            if start == TODAY:
                raise RuntimeError('temporary')
            if start == TODAY + timedelta(days=2):
                raise KeyboardInterrupt()
        return fetch(start, end, client)

    adapter.fetch = flaky
    with pytest.raises(KeyboardInterrupt):
        run_backfill('computational', TODAY, TODAY + timedelta(days=2), ctx.store, ctx.deps, resume=False)
    state = json.loads((ctx.root / 'computational/.backfill_state.json').read_text())
    assert state['next_chunk']['biorxiv'] == str(TODAY + timedelta(days=2))
    assert len(state['failed_chunks']) == 1
    interrupted = False
    calls.clear()
    run_backfill('computational', TODAY, TODAY + timedelta(days=2), ctx.store, ctx.deps, resume=True)
    assert calls == [('biorxiv', TODAY), ('biorxiv', TODAY + timedelta(days=2))]
    assert all(ctx.store.get_item(item.id).summary for item in ctx.items)
    assert not (ctx.root / 'computational/.backfill_state.json').exists()


def test_backfill_resume_after_days_enriches_recovered_items_and_updates_days(ctx):
    ctx.deps.adapters[0].error = RuntimeError('offline')
    run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
    assert ctx.store.get_day(TODAY).run.source_status['biorxiv'] == 'failed'
    other_calls = [len(adapter.calls) for adapter in ctx.deps.adapters[1:]]
    ctx.deps.adapters[0].error = None
    run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=True)
    assert [len(adapter.calls) for adapter in ctx.deps.adapters[1:]] == other_calls
    assert all(ctx.store.get_item(item.id).summary for item in ctx.items)
    assert ctx.store.get_day(TODAY).run.source_status['biorxiv'] == 'ok'
    assert ctx.store.get_day(TODAY).ranked


def test_backfill_all_paper_chunks_failed_raises(ctx):
    from pipeline.collect import AllPaperSourcesFailed

    for adapter in ctx.deps.adapters:
        adapter.config = {adapter.name: {'backfill_chunk_days': 1}}
        adapter.error = RuntimeError('offline')
    with pytest.raises(AllPaperSourcesFailed):
        run_backfill('computational', TODAY, TODAY + timedelta(days=1), ctx.store, ctx.deps, resume=False)
    assert ctx.store.get_day(TODAY) is None
    assert not ctx.deps.llm.batches
    state = json.loads((ctx.root / 'computational/.backfill_state.json').read_text())
    assert len(state['failed_chunks']) == 6
    assert state['stage'] == 'collect'
    assert all(len(adapter.calls) == 2 for adapter in ctx.deps.adapters)
    ctx.deps.adapters[1].error = None
    run_backfill('computational', TODAY, TODAY + timedelta(days=1), ctx.store, ctx.deps, resume=True)
    assert ctx.store.get_day(TODAY)
    state = json.loads((ctx.root / 'computational/.backfill_state.json').read_text())
    assert len(state['failed_chunks']) == 4


def test_backfill_per_source_chunk_sizes_and_github_whole_range(ctx, monkeypatch):
    ctx.deps.adapters[1].config = {'arxiv': {'backfill_chunk_days': 2}}
    github = FakeAdapter('github')
    ctx.deps.adapters.append(github)
    monkeypatch.setattr('pipeline.run.run_day', lambda *args, **kwargs: SimpleNamespace(ranked=[]))
    end = TODAY + timedelta(days=30)
    run_backfill('computational', TODAY, end, ctx.store, ctx.deps, resume=False)
    assert len(ctx.deps.adapters[0].calls) == 2
    assert len(ctx.deps.adapters[1].calls) == 16
    assert ctx.deps.adapters[1].calls[0] == (TODAY, TODAY + timedelta(days=1))
    assert ctx.deps.adapters[1].calls[-1] == (end, end)
    assert github.calls == [(TODAY, end)]


def test_backfill_stage_logs_and_fallback_reasons(ctx, caplog):
    caplog.set_level('INFO', logger='pipeline.run')
    ctx.deps.llm.enrich_batch = lambda *args: {}
    ctx.deps.llm.fallback_reasons = {ctx.items[0].id: 'refusal:bio',
                                     ctx.items[1].id: 'refusal:bio', ctx.items[2].id: 'api_error:401'}
    run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
    messages = [record.getMessage() for record in caplog.records if record.name == 'pipeline.run']
    for stage in ('collect', 'enrich_batch', 'day'):
        for event in ('start', 'end'):
            assert any(f'stage={stage} event={event} elapsed=' in message for message in messages)
    batch = next(message for message in messages if 'stage=enrich_batch event=end' in message)
    assert 'items=3 chunk=1 waited=' in batch
    assert "fallback_reasons={'refusal:bio': 2, 'api_error:401': 1} llm_fallbacks=3" in batch
    assert any(f'day={TODAY} topics=' in message and 'ranked=' in message for message in messages)
    assert all(item.abstract not in caplog.text and item.url not in caplog.text for item in ctx.items)


@pytest.mark.parametrize('status', [None, 404])
def test_github_history_failure_does_not_degrade_day(ctx, monkeypatch, caplog, status):
    from pipeline.sources.github import GithubAdapter

    caplog.set_level('DEBUG', logger='pipeline.sources.github')
    github = GithubAdapter({'github': {'watchlist': ['org/bad', 'org/good'], 'history_seeding': True}})
    code = ctx.items[0].model_copy(update={
        'id': 'github:org/good', 'source': 'github', 'type': 'code', 'title': 'org/good',
    })
    github.fetch = lambda *args: [code]
    ctx.deps.adapters.append(github)
    fetched = []

    def history(repo, client):
        fetched.append(repo)
        if repo == 'org/bad':
            if status is not None:
                httpx.Response(status, request=httpx.Request(
                    'GET', 'https://example.org/?secret=must-not-log')).raise_for_status()
            raise RuntimeError('https://example.org/?secret=must-not-log')
        return [(TODAY, 10)]

    monkeypatch.setattr('pipeline.sources.github.fetch_star_history', history)
    run_backfill('computational', TODAY, TODAY + timedelta(days=1), ctx.store, ctx.deps, resume=False)
    assert fetched == ['org/bad', 'org/good']
    assert not (ctx.root / 'computational/.backfill_state.json').exists()
    for day in [TODAY, TODAY + timedelta(days=1)]:
        assert ctx.store.get_day(day).run.source_status['github'] == 'ok'
        assert ctx.store.get_day(day).run.status == 'ok'
    assert ctx.store.get_item(code.id) is not None
    assert ctx.store.star_counts()['org/good'] == [(TODAY, 10)]
    assert f"repo=org/bad status={status or 'unknown'}" in caplog.text
    assert 'secret' not in caplog.text


def test_resynthesize_updates_topic_and_day(ctx, monkeypatch):
    days = [TODAY, TODAY + timedelta(days=1)]
    for day in days:
        run_day('computational', day, ctx.store, ctx.deps, backfill=True)
    for topic in ctx.store.all_topics():
        topic.related = ['missing-topic']
        ctx.store.put_topic(topic)
    outputs = []

    def synthesize(self, topic, items, signals, previous, model):
        assert model == 'claude-haiku-5-5'
        result = Synthesis(label=f'Grounded Biology {len(outputs)}',
                           headline=f'New scientific finding {len(outputs)}',
                           summary=f'New evidence {len(outputs)}',
                           synthesis=f'Common scientific thread {len(outputs)}')
        outputs.append((topic.slug, result))
        return result

    monkeypatch.setattr(FakeLLM, 'synthesize', synthesize)
    monkeypatch.setattr('pipeline.__main__.build_deps', lambda *args: ctx.deps)
    result = CliRunner().invoke(app, ['resynthesize', '--domain', 'computational',
                                    '--from', str(days[0]), '--to', str(days[-1]),
                                    '--model', 'claude-haiku-5-5', '--data-root', str(ctx.root)])
    assert result.exit_code == 0, result.output
    rows = [row for day in days for row in ctx.store.get_day(day).ranked]
    assert len(outputs) == len(rows) > 1
    for row, (slug, output) in zip(rows, outputs, strict=True):
        assert row.slug == slug
        assert (row.headline, row.summary) == (output.headline, output.summary)
    for slug, output in dict(outputs).items():
        topic = ctx.store.get_topic(slug)
        assert (topic.label, topic.headline, topic.summary, topic.synthesis) == (
            output.label, output.headline, output.summary, output.synthesis)
        assert topic.synthesized_on == days[-1]
    for topic in ctx.store.all_topics():
        assert len(topic.related) == 3
        assert all(ctx.store.get_topic(slug) is not None for slug in topic.related)


def test_github_history_seeding_caps_discovery_and_keeps_watchlist(ctx, monkeypatch):
    from pipeline.sources.github import GithubAdapter

    github = GithubAdapter({'github': {'watchlist': ['org/watch', 'org/104'], 'history_seeding': True}})
    github.fetch = lambda *args: []
    github.repo_cache = {'repos': {f'org/{i}': {'full_name': f'org/{i}', 'stargazers_count': i}
                                  for i in range(105)}}
    ctx.deps.adapters.append(github)
    seeded = []
    monkeypatch.setattr('pipeline.sources.github.fetch_star_history', lambda repo, client: seeded.append(repo))
    run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
    assert seeded == ['org/watch', 'org/104'] + [f'org/{i}' for i in range(103, 3, -1)]


@pytest.mark.parametrize('source,backfill,expected', [
    ('github', False, 'ok'), ('github', True, 'ok'), ('rss', False, 'ok'),
    ('rss', True, 'ok'),
])
def test_nonpaper_collection_failure_does_not_degrade_day(ctx, source, backfill, expected):
    ctx.deps.adapters.append(FakeAdapter(source, error=RuntimeError('offline')))
    result = run_day('computational', TODAY, ctx.store, ctx.deps, backfill=backfill)
    assert result.run.source_status[source] == 'failed'
    assert result.run.status == expected


@pytest.mark.parametrize('window_size', [20, 40, 1400])
def test_backfill_day_counts_only_window_fallbacks(ctx, monkeypatch, window_size):
    window = [ctx.items[0].model_copy(update={
        'id': f'biorxiv:window-{i}', 'relevant': False,
    }) for i in range(window_size)]
    notes = [f'enrichment-fallback:{item.id}' for item in window[:5]]
    notes += [f'enrichment-fallback:biorxiv:outside-{i}' for i in range(55)]
    ctx.store._write(ctx.root / 'computational/.backfill_state.json', {
        'done_sources': ['biorxiv', 'arxiv', 'pubmed'], 'failed_chunks': [], 'notes': notes,
    })
    monkeypatch.setattr(Store, 'items_between', lambda self, start, end: window)
    result = run_day('computational', TODAY, ctx.store, ctx.deps, backfill=True, skip_collect=True)
    assert result.run.status == ('degraded' if window_size == 20 else 'ok')


@pytest.mark.parametrize('source', ['rss', 'github'])
def test_rss_failure_does_not_degrade(source):
    assert not is_degraded([], {source: 'failed'}, over_ceiling=False,
                           window_item_ids=set(), cfg=load_scoring())


@pytest.mark.parametrize('source', ['biorxiv', 'arxiv', 'pubmed'])
def test_paper_source_failure_degrades(source):
    assert is_degraded([], {source: 'failed'}, over_ceiling=False,
                       window_item_ids=set(), cfg=load_scoring())


def test_backfilled_day_source_status_reflects_chunks(ctx):
    ctx.deps.adapters += [FakeAdapter('rss'), FakeAdapter('github')]
    run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
    assert ctx.store.get_day(TODAY).run.source_status == dict.fromkeys(
        ['biorxiv', 'arxiv', 'pubmed', 'rss', 'github'], 'ok')


def test_backfilled_day_failures_are_limited_to_affected_windows(ctx):
    ctx.store._write(ctx.root / 'computational/.backfill_state.json', {
        'done_sources': ['biorxiv', 'arxiv', 'rss'],
        'failed_chunks': [{'source': 'arxiv', 'start': str(TODAY), 'end': str(TODAY)}],
    })
    for offset in [0, 6, 7]:
        result = run_day('computational', TODAY + timedelta(days=offset), ctx.store, ctx.deps,
                         backfill=True, skip_collect=True)
        assert result.run.source_status == {
            'biorxiv': 'ok', 'arxiv': 'failed' if offset <= 6 else 'ok',
            'rss': 'ok', 'pubmed': 'skipped', 'github': 'skipped',
        }


def test_restatus_rewrites_only_status(ctx):
    for offset in [0, 1]:
        day = run_day('computational', TODAY + timedelta(days=offset), ctx.store, ctx.deps, backfill=True)
        day.run.status = 'degraded'
        day.run.source_status['rss'] = 'failed'
        day.run.notes = [f'enrichment-fallback:outside-{i}' for i in range(60)]
        if offset:
            day.run.notes.append('synthesis-fallback:topic')
        ctx.store.put_day(day)
    before = tree(ctx.root)
    result = CliRunner().invoke(app, ['restatus', '--domain', 'computational',
                                    '--from', str(TODAY), '--to', str(TODAY + timedelta(days=2)),
                                    '--data-root', str(ctx.root)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == 'restatus days=2 degraded=1 ok=1'
    path = f'computational/days/{TODAY}.json'
    before[path] = before[path].replace(b'"status": "degraded"', b'"status": "ok"')
    assert tree(ctx.root) == before


def test_restatus_preserves_budget_degradation(ctx):
    day = run_day('computational', TODAY, ctx.store, ctx.deps, backfill=True)
    day.run.status = 'degraded'
    ctx.store.put_day(day)
    ctx.store._write(ctx.deps.budget.path, {day.run.finished.strftime('%Y-%m'): 51})
    before = tree(ctx.root)
    result = CliRunner().invoke(app, ['restatus', '--from', str(TODAY), '--to', str(TODAY),
                                    '--data-root', str(ctx.root)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == 'restatus days=1 degraded=1 ok=0'
    assert tree(ctx.root) == before


def test_restatus_rejects_reversed_range(ctx):
    before = tree(ctx.root)
    result = CliRunner().invoke(app, ['restatus', '--from', str(TODAY),
                                    '--to', str(TODAY - timedelta(days=1)),
                                    '--data-root', str(ctx.root)])
    assert result.exit_code != 0
    assert tree(ctx.root) == before


@pytest.mark.parametrize('backfill', [False, True])
def test_collect_stage_logs_dropped_revisions(ctx, caplog, backfill):
    caplog.set_level('INFO', logger='pipeline.run')
    ctx.deps.adapters[0].dropped_revisions = 3
    if backfill:
        run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
    else:
        run_day('computational', TODAY, ctx.store, ctx.deps)
    assert any('stage=collect event=end' in record.getMessage()
               and 'source=biorxiv' in record.getMessage()
               and 'dropped_revisions=3' in record.getMessage() for record in caplog.records)


def test_irrelevant_items_are_excluded_from_clustering_and_signals(ctx):
    ctx.items.append(ctx.items[0].model_copy(update={
        'id': 'biorxiv:test-3', 'title': 'Protein binder experiment 3',
        'url': 'https://example.org/3', 'abstract': 'Binder experiment 3.',
    }))
    item = ctx.items[0]
    ctx.deps.llm.irrelevant_ids = {item.id}
    run_day('computational', TODAY, ctx.store, ctx.deps)
    topics = ctx.store.all_topics()
    assert all(item.id not in entry.item_ids for topic in topics for entry in topic.history)
    with pytest.raises(KeyError):
        ctx.store.get_embeddings([item.id])
    raw = json.loads(item_path(ctx.root, 'computational', item).read_text())
    assert raw['relevant'] is False
    entries = [entry for topic in topics for entry in topic.history if entry.date == TODAY]
    assert sum(entry.count_7d for entry in entries) == 3
    assert sum(entry.signals.preprint for entry in entries) == 3


def test_enrich_stage_logs_irrelevant_count(ctx, caplog):
    caplog.set_level('INFO', logger='pipeline.run')
    ctx.deps.llm.irrelevant_ids = {ctx.items[0].id}
    run_day('computational', TODAY, ctx.store, ctx.deps)
    message = next(record.getMessage() for record in caplog.records
                   if 'stage=enrich event=end' in record.getMessage())
    assert 'irrelevant=1' in message


def test_backfill_enrich_batch_sets_relevance_and_logs_count(ctx, caplog):
    caplog.set_level('INFO', logger='pipeline.run')
    item = ctx.items[0]
    ctx.deps.llm.irrelevant_ids = {item.id}
    run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
    assert ctx.store.get_item(item.id).relevant is False
    message = next(record.getMessage() for record in caplog.records
                   if 'stage=enrich_batch event=end' in record.getMessage())
    assert 'irrelevant=1' in message
