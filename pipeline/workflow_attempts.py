"""Measure the public daily workflow, including unsuccessful steps and same-day retries."""
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from math import isclose, isfinite

from pipeline.operations import PUBLIC_FIELDS


def _pages(endpoint):
    raw = subprocess.check_output(['gh', 'api', '--paginate', '--slurp', endpoint], text=True)
    return json.loads(raw)


def _log(endpoint):
    reply = subprocess.run(['gh', 'api', '--allow-escape-sequences', endpoint], capture_output=True)
    if reply.returncode:
        error = reply.stderr.decode(errors='replace')
        if re.search(r'HTTP (404|410)\b', error):
            return None
        raise RuntimeError(f'Could not read Actions job log at {endpoint}: {error.strip()}')
    return reply.stdout.decode('utf-8', errors='replace')


def _read_step(log, started, finished):
    env, sources, result = {}, {}, None
    reached_model_stage = None
    for line in (log or '').splitlines():
        stamp, _, message = line.partition(' ')
        if not started[:19] <= stamp[:19] <= finished[:19]:
            continue
        setting = re.fullmatch(r'  (DOMAIN|RUN_DATE|DRY_RUN):\s*(\S*)\s*', message)
        if setting:
            env.setdefault(setting[1], setting[2])
        marker = re.fullmatch(r'trendbio_daily_start field=([\w-]+) date=(\d{4}-\d\d-\d\d) dry=(true|false)', message)
        if marker:
            env.update(DOMAIN=marker[1], RUN_DATE=marker[2], DRY_RUN=marker[3])
        if ' INFO pipeline.run: stage=write event=end ' in message and ' status=ok edition_receipt=' in message:
            result = json.loads(message.split(' edition_receipt=', 1)[1])
        if ' INFO pipeline.run: stage=collect event=start ' in message:
            env.setdefault('FIRST_COLLECTION_DATE', stamp[:10])
            if reached_model_stage is None:
                reached_model_stage = False
        if re.search(r' INFO pipeline\.run: stage=(enrich|cluster|synthesize) event=start\b', message):
            reached_model_stage = True
        # Older daily jobs logged each adapter's result before the edition was saved.
        if ' INFO pipeline.run: stage=collect event=end ' in message:
            source = re.search(r'\bsource=(\w+)\b.*\bsource_status=(ok|partial|failed|skipped)\b', message)
            if source:
                sources[source[1]] = source[2]
    return env, sources, result, reached_model_stage


def measure_job(job, step, log):
    started, finished = step['started_at'], step['completed_at']
    env, sources, result, reached_model_stage = _read_step(log, started, finished)
    match = re.fullmatch(r'pipeline \(([\w-]+)\)', job['name'])
    field = match[1] if match else 'computational' if job['name'] == 'pipeline' else None
    if not field or env.get('DOMAIN', field) != field:
        raise ValueError(f'Inconsistent field for job {job["id"]}')
    target = env.get('RUN_DATE')
    if target == '' and (started[:10] == finished[:10] or env.get('FIRST_COLLECTION_DATE') == started[:10]):
        target = started[:10]
    target = str(date.fromisoformat(target)) if target else None
    dry = env.get('DRY_RUN')
    if dry == 'true':
        kind = 'dry_run'
    elif field not in PUBLIC_FIELDS:
        kind = 'pilot'
    elif dry in ('', 'false') and target:
        kind = 'live' if target == started[:10] else 'retrospective'
    else:
        kind = 'unknown'
    if result is not None:
        if (result['domain'], result['date']) != (field, target) or result['status'] not in {'ok', 'degraded'}:
            raise ValueError(f'Unexpected published edition in job {job["id"]}')
        sources = result['source_status']
        costs = [result.get(k) for k in ('attempt_model_cost_usd', 'cumulative_model_cost_usd')]
        if (not isinstance(sources, dict) or any(s not in {'ok', 'failed', 'partial', 'skipped'} for s in sources.values())
                or any(v is not None and (type(v) not in (int, float) or not isfinite(v) or v < 0) for v in costs)):
            raise ValueError(f'Invalid daily result in job {job["id"]}')
    seconds = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
    if seconds < 0:
        raise ValueError(f'Invalid step duration in job {job["id"]}')
    commit = next((s['conclusion'] for s in job['steps'] if s['name'] == 'Commit data'), None)
    return {'job_id': job['id'], 'url': job['html_url'], 'field': field, 'edition_date': target, 'kind': kind,
            'started_at': started, 'finished_at': finished, 'elapsed_seconds': seconds,
            'step_conclusion': step['conclusion'], 'commit_step': commit, 'source_status': sources,
            'edition_status': result['status'] if result else None,
            'cumulative_model_cost_usd': result.get('cumulative_model_cost_usd') if result else None,
            'attempt_model_cost_usd': result.get('attempt_model_cost_usd') if result else None,
            'log_available': log is not None, 'reached_model_stage': reached_model_stage}


def _jobs(api, start, end):
    # A workflow created before the window can be rerun for up to 30 days.
    runs = _pages(f'{api}/workflows/daily.yml/runs?branch=main&created={start - timedelta(days=30)}..{end}&per_page=100')
    seen = set()
    for run in (run for page in runs for run in page['workflow_runs']):
        if run['event'] not in {'workflow_dispatch', 'schedule'} or run['updated_at'][:10] < str(start):
            continue
        for number in range(1, run['run_attempt'] + 1):
            pages = _pages(f'{api}/runs/{run["id"]}/attempts/{number}/jobs?per_page=100')
            for job in (job for page in pages for job in page['jobs']):
                if job.get('run_attempt', number) == number and job['id'] not in seen:
                    seen.add(job['id'])
                    yield run, number, job


def collect_attempts(repo: str, start: date, end: date) -> dict:
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[\w.-]+', repo)
            or repo.split('/')[-1] in {'.', '..'} or end < start):
        raise ValueError('Invalid repository or operating window')
    api = f'repos/{repo}/actions'
    attempts, skips, unavailable, pending = [], Counter(), [], []
    for run, number, job in _jobs(api, start, end):
        step = next((s for s in job.get('steps', []) if s['name'] == 'Run pipeline'), {})
        stamp = step.get('started_at') or job.get('started_at') or run.get('run_started_at') or run['created_at']
        if not str(start) <= stamp[:10] <= str(end):
            continue
        if job['status'] != 'completed':
            pending.append({'url': job['html_url'], 'date': stamp[:10]})
        elif step.get('conclusion') == 'skipped' and job['conclusion'] == 'success':
            skips[stamp[:10]] += 1
        elif not step.get('started_at') or not step.get('completed_at') or step.get('conclusion') == 'skipped':
            unavailable.append({'url': job['html_url'], 'date': stamp[:10], 'conclusion': job['conclusion']})
        else:
            log = _log(f'{api}/jobs/{job["id"]}/logs')
            row = measure_job(job, step, log)
            attempts.append(dict(row, run_id=run['id'], run_attempt=number))
    return {'from': str(start), 'to': str(end), 'skipped_jobs_by_utc_date': dict(sorted(skips.items())),
            'jobs_without_a_measured_step': unavailable, 'unfinished_jobs': pending,
            'attempts': sorted(attempts, key=lambda row: (row['started_at'], row['job_id']))}


def _extra_spend(rows, saved_cost):
    """Reconcile metered work from an unsuccessful step with the saved edition ledger."""
    committed = uncommitted = 0.0
    missing_saved = False
    for row in rows:
        cost = row['attempt_model_cost_usd']
        if row['step_conclusion'] == row['commit_step'] == 'success':
            missing_saved = missing_saved or cost is None
            committed += cost or 0
        elif cost is None and row['reached_model_stage'] is not False:
            return None
        else:
            uncommitted += cost or 0
    if not uncommitted:
        return 0.0
    if saved_cost is not None and not missing_saved:
        if isclose(saved_cost, committed + uncommitted, rel_tol=0, abs_tol=1e-8):
            return 0.0
        if isclose(saved_cost, committed, rel_tol=0, abs_tol=1e-8):
            return uncommitted
    return None


def summarize_attempts(history, editions=None):
    live = defaultdict(list)
    unreconciled = set()
    for row in history['attempts']:
        if row['kind'] == 'live':
            live[(row['edition_date'], row['field'])].append(row)
        if row['kind'] == 'unknown' and row['field'] in PUBLIC_FIELDS and _extra_spend([row], None) is None:
            unreconciled.add(row['started_at'][:10])
    days = {}
    for (day, field), rows in sorted(live.items()):
        latest = rows[-1]
        saved_cost = (editions or {}).get(day, {}).get(field, {}).get('model_cost_usd')
        extra = _extra_spend(rows, saved_cost)
        if extra is None:
            unreconciled.add(day)
        earlier_issues = {source for row in rows[:-1] for source, status in row['source_status'].items()
                          if status in {'failed', 'partial'}}
        recovered = sorted(source for source in earlier_issues if latest['source_status'].get(source) == 'ok'
                           and latest['step_conclusion'] == latest['commit_step'] == 'success')
        days.setdefault(day, {})[field] = {
            'attempts': len(rows), 'retries': len(rows) - 1, 'step_seconds': sum(r['elapsed_seconds'] for r in rows),
            'unsuccessful_steps': sum(r['step_conclusion'] != 'success' for r in rows), 'recovered_sources': recovered,
            'unsaved_successful_steps': sum(r['step_conclusion'] == 'success' and r['commit_step'] != 'success' for r in rows),
            'additional_model_cost_usd': extra,
            'attempts_with_source_issues': sum(any(s in {'failed', 'partial'} for s in r['source_status'].values())
                                               for r in rows),
        }
    return {**history, 'days': days, 'unreconciled_cost_dates': sorted(unreconciled),
            'counts_by_kind': dict(Counter(r['kind'] for r in history['attempts']))}
