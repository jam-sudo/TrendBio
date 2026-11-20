from datetime import date, timedelta
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pipeline.__main__ import app
from pipeline.operations import PUBLIC_FIELDS, audit_operations


def put(root, field, day, **changes):
    run = {'started': f'{day}T01:00:00Z', 'finished': f'{day}T01:05:00Z', 'backfilled': False,
           'status': 'ok', 'model_cost_usd': 0.1, 'source_status': {'papers': 'ok'}}
    path = root / field / 'days' / f'{day}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'date': str(day), 'domain': field, 'run': {**run, **changes}}))
    return path


def test_service_requires_measured_live_costs_for_all_scheduled_fields(tmp_path):
    daily = yaml.safe_load(Path('.github/workflows/daily.yml').read_text())
    assert set(PUBLIC_FIELDS) == set(daily[True]['workflow_dispatch']['inputs']['domain']['options']) - {'all'}
    start = date(2026, 11, 1)
    for offset in range(15):
        day = start + timedelta(days=offset)
        for field in PUBLIC_FIELDS:
            put(tmp_path, field, day)
    put(tmp_path, 'physics', start, status='degraded', source_status={'one': 'failed', 'two': 'partial', 'three': 'ok'},
        started='2026-10-31T21:00:00-04:00', model_cost_usd=0)
    end = start + timedelta(days=13)
    put(tmp_path, 'biology', end, model_cost_usd=None)
    report = audit_operations(tmp_path, end, start)
    first = report['days'][str(start)]['physics']
    assert first == {'kind': 'live', 'status': 'degraded', 'elapsed_seconds': 300,
                     'model_cost_usd': 0, 'source_issues': {'one': 'failed', 'two': 'partial'}}
    assert report['fields']['physics']['degraded'] == 1
    assert report['matched_daily_cost_usd'][str(start)] == .2
    assert len(report['matched_daily_cost_usd']) == 13 and report['projected_30d_usd'] is None
    put(tmp_path, 'biology', end)
    assert audit_operations(tmp_path, end, start)['projected_30d_usd'] == 8.7857
    later = audit_operations(tmp_path, end + timedelta(days=1), start)
    assert later['projected_30d_usd'] == 9 and str(start) not in later['projection_basis_dates']


def test_cli_shows_missing_historical_and_backfilled_editions(tmp_path):
    day = date(2026, 11, 1)
    put(tmp_path, 'physics', day, started='2026-11-02T04:00:00Z', finished='2026-11-02T04:00:10Z')
    put(tmp_path, 'biology', day, backfilled=True)
    args = ['audit-operations', '--data-root', str(tmp_path), '--from', str(day), '--to', str(day)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.exception
    report = json.loads(result.stdout)
    assert [report['days'][str(day)][f]['kind'] for f in PUBLIC_FIELDS] == ['missing', 'retrospective', 'backfill']
    assert all(v['recorded_model_cost_usd'] is None for v in report['fields'].values())
    assert report['days'][str(day)]['computational']['elapsed_seconds'] is None
    path = put(tmp_path, 'computational', day, model_cost_usd=-1)
    with pytest.raises(ValueError, match='model cost'):
        audit_operations(tmp_path, day)
    path.write_text(path.read_text().replace('"domain": "computational"', '"domain": "biology"'))
    with pytest.raises(ValueError, match='identity'):
        audit_operations(tmp_path, day)


def test_failed_commit_with_model_work_keeps_its_date_out_of_the_cost_projection(tmp_path, monkeypatch):
    first = date(2026, 11, 1)
    for offset in range(15):
        for field in PUBLIC_FIELDS:
            put(tmp_path, field, first + timedelta(days=offset))
    issue = {'field': 'physics', 'kind': 'live', 'edition_date': str(first), 'started_at': f'{first}T01:00:00Z',
             'source_status': {}, 'elapsed_seconds': 30, 'reached_model_stage': True, 'attempt_model_cost_usd': None,
             'step_conclusion': 'success', 'commit_step': 'failure'}
    history = {'attempts': [issue], 'unfinished_jobs': []}
    monkeypatch.setattr('pipeline.workflow_attempts.collect_attempts', lambda *args: history)
    before = audit_operations(tmp_path, first + timedelta(days=13), first, actions_repo='owner/repo')
    assert len(before['matched_daily_cost_usd']) == 14 and before['projected_30d_usd'] is None
    after = audit_operations(tmp_path, first + timedelta(days=14), first, actions_repo='owner/repo')
    assert after['projected_30d_usd'] == 9 and after['projection_basis_dates'][0] == '2026-11-02'
    paid = {**issue, 'attempt_model_cost_usd': .05}
    saved = {**issue, 'commit_step': 'success', 'attempt_model_cost_usd': .1}
    history['attempts'] = [paid, saved]
    measured = audit_operations(tmp_path, first + timedelta(days=13), first, actions_repo='owner/repo')
    assert measured['matched_daily_cost_usd'][str(first)] == .3
    assert measured['reconciled_daily_cost_usd'][str(first)] == .35
    assert measured['projected_30d_usd'] == 9.1071
    history['unfinished_jobs'] = [{'date': str(first), 'url': 'https://example.org/jobs/3'}]
    provisional = audit_operations(tmp_path, first + timedelta(days=13), first, actions_repo='owner/repo')
    assert provisional['projected_30d_usd'] is None and str(first) not in provisional['reconciled_daily_cost_usd']
