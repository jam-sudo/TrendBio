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
from pipeline.llm import Enrichment, Synthesis
from pipeline.models import Item
from pipeline.store import Store
from pipeline.run import Deps, run_backfill, run_day
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

    def enrich(self, item, taxonomy, hints):
        self.budget.record('claude-haiku-5-5', 100, 20)
        return Enrichment(summary=item.title, primary='structural', secondary=[])

    def enrich_batch(self, items, taxonomy, hints_by_id):
        self.batches.append([item.id for item in items])
        self.budget.record('claude-haiku-5-5', 100 * len(items), 20 * len(items), batch=True)
        return {item.id: Enrichment(summary=item.title, primary='structural', secondary=[])
                for item in items}

    def synthesize(self, topic, items, signals, previous, model):
        self.calls.append(model)
        self.budget.record(model, 100, 20)
        if self.fallback:
            return None
        return Synthesis(headline='Protein design evidence', summary='New evidence.',
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


def test_degraded_when_fallback_note_present(ctx):
    ctx.deps.llm.fallback = True
    result = run_day('computational', TODAY, ctx.store, ctx.deps)
    assert result.run.status == 'degraded'
    assert any(note.startswith('synthesis-fallback:') for note in result.run.notes)
    before = tree(ctx.root)
    run_day('computational', TODAY, ctx.store, ctx.deps)
    assert tree(ctx.root) == before


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
    monkeypatch.setattr(runner, 'run_day', lambda domain, day, *args, **kwargs: calls.append(day))
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


def test_backfill_seeds_long_github_history_and_daily_run_prunes_it(ctx, monkeypatch):
    import pipeline.run as runner
    from pipeline.sources.github import GithubAdapter

    github = GithubAdapter({'github': {}}, star_gain_threshold=100)
    github.fetch = lambda *args: []
    github.repos = lambda *args: ['org/watchlist', 'org/topic']
    ctx.deps.adapters.append(github)
    history = [(TODAY - timedelta(days=300), 1), (TODAY - timedelta(days=7), 20), (TODAY, 30)]
    fetched = []

    def star_history(repo, client):
        fetched.append(repo)
        return history

    monkeypatch.setattr(runner, 'fetch_star_history', star_history)
    run_backfill('computational', TODAY, TODAY, ctx.store, ctx.deps, resume=False)
    assert fetched == ['org/watchlist', 'org/topic']
    assert ctx.store.star_counts() == dict.fromkeys(fetched, history)
    monkeypatch.setattr(runner, 'fetch_star_counts', lambda *args: dict.fromkeys(fetched, 31))
    run_day('computational', TODAY + timedelta(days=1), ctx.store, ctx.deps)
    assert ctx.store.star_counts() == dict.fromkeys(fetched, history[1:] + [(TODAY + timedelta(days=1), 31)])
