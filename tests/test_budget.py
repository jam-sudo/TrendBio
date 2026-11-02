import json
from datetime import datetime, timezone

import pytest

from pipeline.budget import Budget


def test_budget_month_spend_and_ceiling(tmp_path):
    path = tmp_path / 'nested/spend.json'
    budget = Budget(path, ceiling_usd=5)
    assert budget.month_spend_usd() == 0
    budget.record('claude-opus-5-5', 1_000_000, 100_000)
    assert budget.month_spend_usd() == 6.0
    assert budget.over_ceiling()
    assert Budget(path, 5).month_spend_usd() == 6.0
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    assert json.loads(path.read_text())[month] == 6.0


def test_budget_batch_discount_and_other_months(tmp_path):
    path = tmp_path / 'spend.json'
    path.write_text('{"2000-01": 3.0}\n')
    budget = Budget(path, 1)
    budget.record('claude-haiku-5-5', 1_000_000, 1_000_000, batch=True)
    assert budget.month_spend_usd() == pytest.approx(0.3)
    assert budget.month_spend_usd('2000-01') == 3
    assert budget.month_spend_usd('1999-12') == 0
    assert not budget.over_ceiling()
    assert path.read_text() == json.dumps(json.loads(path.read_text()), indent=2, sort_keys=True) + '\n'


def test_budget_atomic_write_preserves_previous_spend(tmp_path, monkeypatch):
    path = tmp_path / 'spend.json'
    budget = Budget(path, 50)
    budget.record('claude-haiku-5-5', 100, 10)
    before = path.read_bytes()

    def interrupted(source, destination):
        assert source.parent == destination.parent
        raise OSError('interrupted')

    monkeypatch.setattr('pipeline.budget.os.replace', interrupted)
    with pytest.raises(OSError, match='interrupted'):
        budget.record('claude-opus-5-5', 1_000_000, 100_000)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_budget_month_rollover(tmp_path, monkeypatch):
    class Clock:
        month = '2026-10'

        @classmethod
        def now(cls, timezone):
            return datetime.fromisoformat(cls.month + '-01T00:00:00+00:00')

    monkeypatch.setattr('pipeline.budget.datetime', Clock)
    budget = Budget(tmp_path / 'spend.json', 5)
    budget.record('claude-opus-5-5', 1_000_000, 100_000)
    Clock.month = '2026-11'
    assert budget.month_spend_usd() == 0
    assert not budget.over_ceiling()
    budget.record('claude-haiku-5-5', 1_000_000, 0)
    assert budget.month_spend_usd() == 0.1
    assert budget.month_spend_usd('2026-10') == 6


def test_budget_rejects_invalid_inputs(tmp_path):
    with pytest.raises(ValueError):
        Budget(tmp_path / 'spend.json', float('nan'))
    budget = Budget(tmp_path / 'spend.json', 5)
    with pytest.raises(ValueError):
        budget.record('claude-haiku-5-5', -1, 0)
    with pytest.raises(KeyError):
        budget.record('unknown-model', 100, 10)
    assert not list(tmp_path.iterdir())


def test_budget_usage_is_additive_and_preserves_legacy_spend(tmp_path):
    path = tmp_path / 'spend.json'
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    path.write_text(json.dumps({month: 1.5}))
    budget = Budget(path, 50)
    assert budget.usage() == budget.usage('2000-01') == {}
    budget.record('claude-haiku-5-5', 100, 20)
    budget.record('claude-haiku-5-5', 200, 30, batch=True)
    budget.record('claude-opus-5-5', 10, 5)
    assert Budget(path, 50).usage() == {
        'claude-haiku-5-5': {'input_tokens': 300, 'output_tokens': 50},
        'claude-opus-5-5': {'input_tokens': 10, 'output_tokens': 5},
    }
    assert budget.month_spend_usd() == pytest.approx(1.5001775)
    assert json.loads(path.read_text())[month] == budget.month_spend_usd()


def test_concurrent_records_preserve_all_usage(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    budget = Budget(tmp_path / 'spend.json', 50)
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: budget.record('claude-haiku-5-5', 100, 20), range(100)))
    assert budget.usage() == {'claude-haiku-5-5': {'input_tokens': 10_000, 'output_tokens': 2_000}}
    assert budget.month_spend_usd() == pytest.approx(0.002)
