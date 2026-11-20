"""Report operating costs from the dated editions of the public service."""
import json
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from pathlib import Path


PUBLIC_FIELDS = ('computational', 'physics', 'biology')
TARGET_LIVE_DATES = 14


def _utc(stamp: datetime) -> datetime:
    return stamp.astimezone(UTC) if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def publication_kind(day: date, started: datetime, backfilled: bool) -> str:
    if backfilled:
        return 'backfill'
    return 'live' if _utc(started).date() == day else 'retrospective'


def project_month(daily_costs: list[float]) -> float | None:
    if len(daily_costs) < TARGET_LIVE_DATES:
        return None
    return round(sum(daily_costs[-TARGET_LIVE_DATES:]) * 30 / TARGET_LIVE_DATES, 4)


def _edition(root: Path, field: str, day: date) -> dict:
    path = root / field / 'days' / f'{day}.json'
    if not path.is_file():
        return {'kind': 'missing', 'status': None, 'elapsed_seconds': None, 'model_cost_usd': None,
                'source_issues': None}
    edition = json.loads(path.read_text(encoding='utf-8'))
    if (edition['domain'], edition['date']) != (field, str(day)):
        raise ValueError(f'Edition identity mismatch in {path}')
    run = edition['run']
    started = _utc(datetime.fromisoformat(run['started']))
    elapsed = (_utc(datetime.fromisoformat(run['finished'])) - started).total_seconds()
    cost = run.get('model_cost_usd')
    if elapsed < 0 or run['status'] not in {'ok', 'degraded'}:
        raise ValueError(f'Invalid run in {path}')
    if cost is not None and (type(cost) not in (float, int) or not isfinite(cost) or cost < 0):
        raise ValueError(f'Invalid model cost in {path}')
    return {'kind': publication_kind(day, started, run['backfilled']), 'status': run['status'],
            'elapsed_seconds': round(elapsed, 3), 'model_cost_usd': cost,
            'source_issues': {source: status for source, status in run['source_status'].items()
                              if status not in {'ok', 'skipped'}}}


def audit_operations(root: Path, end: date, start: date | None = None, *, actions_repo: str | None = None) -> dict:
    start = start or end - timedelta(days=29)
    if end < start:
        raise ValueError('End precedes start')
    days, matched = {}, {}
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        editions = {field: _edition(root, field, day) for field in PUBLIC_FIELDS}
        days[str(day)] = editions
        if all(e['kind'] == 'live' and e['model_cost_usd'] is not None for e in editions.values()):
            matched[str(day)] = round(sum(e['model_cost_usd'] for e in editions.values()), 7)
    fields = {}
    for field in PUBLIC_FIELDS:
        live = [d[field] for d in days.values() if d[field]['kind'] == 'live']
        costs = [e['model_cost_usd'] for e in live if e['model_cost_usd'] is not None]
        fields[field] = {'live_editions': len(live), 'ok': sum(e['status'] == 'ok' for e in live),
                         'degraded': sum(e['status'] == 'degraded' for e in live),
                         'measured_cost_days': len(costs), 'recorded_model_cost_usd': round(sum(costs), 7) if costs else None,
                         'mean_elapsed_seconds': round(sum(e['elapsed_seconds'] for e in live) / len(live), 3) if live else None}
    report_costs = matched
    workflow = {}
    if actions_repo:
        from pipeline.workflow_attempts import collect_attempts, summarize_attempts

        activity = summarize_attempts(collect_attempts(actions_repo, start, end), days)
        workflow['workflow_activity'] = activity
        unresolved = set(activity['unreconciled_cost_dates']) | {job['date'] for job in activity['unfinished_jobs']}
        report_costs = {day: round(amount + sum(field['additional_model_cost_usd'] or 0
                                                for field in activity['days'].get(day, {}).values()), 7)
                        for day, amount in matched.items() if day not in unresolved}
        workflow['reconciled_daily_cost_usd'] = report_costs
    basis = list(report_costs)[-TARGET_LIVE_DATES:] if len(report_costs) >= TARGET_LIVE_DATES else []
    return {'from': str(start), 'to': str(end), 'fields': fields, 'days': days,
            'matched_daily_cost_usd': matched, 'target_live_dates': TARGET_LIVE_DATES,
            'projection_basis_dates': basis,
            'projected_30d_usd': project_month(list(report_costs.values())), **workflow}
