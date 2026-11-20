from datetime import date
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from pipeline import workflow_attempts as workflow


def job(number, start, end, *, field='computational', result='success', commit='success'):
    return {'id': number, 'name': f'pipeline ({field})', 'html_url': f'https://example.org/jobs/{number}',
            'started_at': start, 'completed_at': end, 'status': 'completed', 'conclusion': commit,
            'steps': [{'name': 'Run pipeline', 'started_at': start, 'completed_at': end, 'conclusion': result},
                      {'name': 'Commit data', 'conclusion': commit}]}


def step_log(stamp, *messages):
    return '\n'.join(f'{stamp} {message}' for message in messages)


def test_legacy_retry_recovers_a_source_and_counts_both_step_durations():
    first = job(1, '2026-11-20T06:07:32Z', '2026-11-20T06:19:54Z')
    second = job(2, '2026-11-20T07:29:14Z', '2026-11-20T07:39:23Z')
    first_log = step_log(first['started_at'], '  RUN_DATE: ', '  DRY_RUN: false',
                         '2026-11-20 INFO pipeline.run: stage=collect event=end source=arxiv source_status=failed')
    second_log = step_log(second['started_at'], '  RUN_DATE: 2026-11-20', '  DRY_RUN: false',
                          '2026-11-20 INFO pipeline.run: stage=collect event=end source=arxiv source_status=ok')
    rows = [workflow.measure_job(j, j['steps'][0], log) for j, log in [(first, first_log), (second, second_log)]]
    assert rows[0]['edition_status'] is None
    result = workflow.summarize_attempts({'attempts': rows})
    assert result['days']['2026-11-20']['computational'] == {
        'attempts': 2, 'retries': 1, 'step_seconds': 1351, 'unsuccessful_steps': 0,
        'attempts_with_source_issues': 1, 'unsaved_successful_steps': 0, 'recovered_sources': ['arxiv'],
        'additional_model_cost_usd': 0}
    assert result['unreconciled_cost_dates'] == []


def test_midnight_missing_log_and_historical_dispatch_do_not_invent_a_live_date():
    j = job(3, '2026-11-04T23:55:30Z', '2026-11-05T00:05:30Z')
    measure = lambda log: workflow.measure_job(j, j['steps'][0], log)
    headers = step_log(j['started_at'], '  RUN_DATE: ', '  DRY_RUN: false')
    assert measure(None)['kind'] == measure(headers)['kind'] == 'unknown'
    early = step_log(j['started_at'], '2026-11-04 INFO pipeline.run: stage=collect event=start source=arxiv')
    assert measure(headers + '\n' + early)['edition_date'] == '2026-11-04'
    assert measure(step_log(j['started_at'], '  RUN_DATE: 2026-07-15', '  DRY_RUN: false'))['kind'] == 'retrospective'
    assert measure(step_log(j['started_at'], '  RUN_DATE: 2026-11-04', '  DRY_RUN: true'))['kind'] == 'dry_run'


def test_dispatches_include_older_reruns_only_once_and_separate_skipped_jobs(monkeypatch):
    start = date(2026, 11, 19)
    run = {'id': 5, 'event': 'workflow_dispatch', 'updated_at': '2026-11-19T01:10:00Z',
           'run_started_at': '2026-10-30T01:00:00Z', 'run_attempt': 2}
    old = job(10, '2026-10-30T01:00:00Z', '2026-10-30T01:10:00Z')
    retry = job(11, '2026-11-19T01:00:00Z', '2026-11-19T01:10:00Z')
    skipped = job(12, retry['started_at'], retry['completed_at'], result='skipped')
    failed_setup = job(13, retry['started_at'], retry['completed_at'], result='skipped', commit='failure')
    pending = {**job(14, retry['started_at'], None), 'status': 'in_progress'}
    def pages(endpoint):
        if '/workflows/' in endpoint:
            assert 'created=2026-10-20..2026-11-19' in endpoint
            return [{'workflow_runs': [run]}]
        if 'attempts/1/' in endpoint:
            return [{'jobs': [old]}]
        return [{'jobs': [old, retry]}, {'jobs': [skipped, failed_setup, pending, retry]}]

    monkeypatch.setattr(workflow, '_pages', pages)
    monkeypatch.setattr(workflow, '_log', lambda endpoint: step_log(retry['started_at'],
                        'trendbio_daily_start field=computational date=2026-11-19 dry=false'))
    report = workflow.collect_attempts('owner/repo', start, start)
    assert [(r['job_id'], r['run_attempt']) for r in report['attempts']] == [(11, 2)]
    assert report['skipped_jobs_by_utc_date'] == {'2026-11-19': 1}
    assert report['jobs_without_a_measured_step'][0]['url'] == failed_setup['html_url']
    assert report['unfinished_jobs'] == [{'url': pending['html_url'], 'date': '2026-11-19'}]


def test_hosted_collection_passes_and_logs_the_same_resolved_date(tmp_path):
    steps = yaml.safe_load(Path('.github/workflows/daily.yml').read_text())['jobs']['pipeline']['steps']
    scripts = {s['name']: s.get('run', '') for s in steps if 'name' in s}
    for name in ('Run pipeline', 'Skip a scheduled field with complete paper sources',
                 'Record edition coverage and evidence samples', 'Commit data'):
        assert '$EDITION_DATE' in scripts[name] and 'date -u' not in scripts[name]
    day = '2026-11-19'
    gh = tmp_path / 'gh'
    gh.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > api-args\necho 2026-11-19\n')
    gh.chmod(0o755)
    target = tmp_path / 'env'
    env = dict(os.environ, GITHUB_ENV=str(target), GITHUB_REPOSITORY='owner/repo', GITHUB_RUN_ID='42',
               PATH=f'{tmp_path}:{os.environ["PATH"]}')
    resolver = ['bash', '-eo', 'pipefail', '-c', scripts['Resolve the UTC edition date']]
    for requested, expected in [('', day), ('2026-07-15', '2026-07-15')]:
        subprocess.run(resolver, env={**env, 'REQUESTED_DATE': requested}, cwd=tmp_path, check=True)
        assert target.read_text().splitlines() == [f'EDITION_DATE={expected}']
        target.unlink()
        api_args = tmp_path / 'api-args'
        if not requested:
            assert api_args.read_text().splitlines() == ['api', 'repos/owner/repo/actions/runs/42', '--jq', '.created_at[0:10]']
            api_args.unlink()
        assert not api_args.exists()
    for invalid in ('2026-11-31', '20261119', '2026-11-19\nEDITION_DATE=2030-01-01'):
        assert subprocess.run(resolver, env={**env, 'REQUESTED_DATE': invalid}, cwd=tmp_path, capture_output=True).returncode
        assert not target.exists()
    python = tmp_path / 'python'
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > args\n')
    python.chmod(0o755)
    env.update(EDITION_DATE=day, DOMAIN='physics')
    j = job(1, '2026-11-20T01:00:00Z', '2026-11-20T01:01:00Z', field='physics')
    for dry in ('false', 'true'):
        lines = subprocess.check_output(['bash', '-eo', 'pipefail', '-c', scripts['Run pipeline']],
                                        cwd=tmp_path, env={**env, 'DRY_RUN': dry}, text=True).splitlines()
        expected = ['-m', 'pipeline', 'run', '--domain', 'physics', '--date', day]
        assert (tmp_path / 'args').read_text().splitlines() == expected + (['--dry-run'] if dry == 'true' else [])
        receipt = workflow.measure_job(j, j['steps'][0], step_log(j['started_at'], *lines))
        assert receipt['edition_date'] == day
        assert receipt['kind'] == ('dry_run' if dry == 'true' else 'retrospective')


def test_receipt_provenance_and_uncommitted_model_work():
    j = job(1, '2026-11-19T18:00:00Z', '2026-11-19T18:10:00Z', field='physics', commit='failure')
    data = {'domain': 'physics', 'date': '2026-11-19', 'status': 'ok', 'source_status': {'arxiv': 'ok'},
            'attempt_model_cost_usd': .05, 'cumulative_model_cost_usd': .25}
    def measure():
        log = step_log(j['started_at'], 'trendbio_daily_start field=physics date=2026-11-19 dry=false',
                       '2026-11-19 INFO pipeline.run: stage=enrich event=start new=1',
                       '2026-11-19 INFO pipeline.run: stage=write event=end elapsed=0.001 status=ok edition_receipt='
                       + json.dumps(data))
        return workflow.measure_job(j, j['steps'][0], log)

    row = measure()
    assert (row['edition_status'], row['source_status'], row['attempt_model_cost_usd'],
            row['cumulative_model_cost_usd']) == ('ok', {'arxiv': 'ok'}, .05, .25)
    assert workflow.summarize_attempts({'attempts': [row]})['unreconciled_cost_dates'] == ['2026-11-19']
    retry = {**row, 'commit_step': 'success', 'attempt_model_cost_usd': .2}
    for saved, extra in [(.2, .05), (.25, 0), (.4, None)]:
        measured = workflow.summarize_attempts({'attempts': [row, retry]}, {'2026-11-19': {'physics': {'model_cost_usd': saved}}})
        assert measured['days']['2026-11-19']['physics']['additional_model_cost_usd'] == extra
        assert bool(measured['unreconciled_cost_dates']) == (extra is None)
    data['attempt_model_cost_usd'] = 0
    assert workflow.summarize_attempts({'attempts': [measure()]})['unreconciled_cost_dates'] == []
    data['domain'] = 'biology'
    with pytest.raises(ValueError, match='Unexpected published edition'):
        measure()
