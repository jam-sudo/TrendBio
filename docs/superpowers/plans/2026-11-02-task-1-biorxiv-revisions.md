# Task 1: bioRxiv revisions are counted as new preprints

Date: 2026-11-02. Reviewed and approved by two planner sessions (trendbio-03, trendbio-e4). Highest priority of the four tasks; land this first because it changes ranking inputs.

## Problem

The bioRxiv details API returns one record per *version* posted in the requested window. `pipeline/sources/biorxiv.py` never reads `record['version']`, so a v5 of a paper first posted in 2023 becomes a `preprint` item with `published_at` equal to the revision date. In the committed October data, 380 of 1,903 bioRxiv items (20%) have `metadata.version > 1`, all with dated DOIs. Example: `biorxiv:10.1101/2023.12.08.570811`, `published_at` 2026-10-27, version 5. These revisions inflate `rise` and `volume` with old papers.

## Fix

In `BiorxivAdapter.fetch`, for every record:

1. `version = int(record.get('version') or 1)`.
2. If `version == 1`: `published_at = date.fromisoformat(record['date'])` (current behaviour).
3. If `version > 1`: parse the submission date embedded in new-style DOIs with the regex `r'/(\d{4})\.(\d{2})\.(\d{2})\.\d+'` (matches both `10.1101/2024.05.01.592123` and `10.64898/2026.06.25.734591`; wrap `date(...)` in `try/except ValueError` for impossible dates and treat as no match).
   - No match (old-style DOI, no date): drop the record.
   - Match: `published_at = that date`. If `published_at` is outside `start..end`: drop the record. Otherwise keep it with that `published_at` (the v1 was posted inside this window; its abstract is the newer text, which is fine).
4. Count dropped records in `self.dropped_revisions: int` (reset to 0 at the start of each `fetch`) and log once per fetch at INFO: `biorxiv: dropped %d revisions first posted outside the window`.
5. Keep `id = f"biorxiv:{doi}"` unchanged so a v2 kept in-window dedupes onto its v1 by id via the existing `dedupe`. `metadata` already carries `version` through the record spread; leave it.

In `pipeline/run.py`, add the count to the collect stage line in both places an adapter is fetched (daily collect stage in `run_day` and `collect_chunk` in `run_backfill`): `counts['dropped_revisions'] = getattr(adapter, 'dropped_revisions', 0)` after a successful fetch. No other change to `run.py`.

## Wipe command

The committed October data was built with the bug, and resynthesis is not enough because clustering and ranking inputs change. Add a CLI command so the coordinator can delete the backfilled range and re-run it:

```
python -m pipeline wipe --domain computational --from 2026-10-01 --to 2026-10-31 [--data-root data]
```

Implement `wipe(store: Store, start: date, end: date) -> dict[str, int]` in a new module `pipeline/wipe.py`, called from a new `wipe` command in `pipeline/__main__.py`. Semantics:

- Whole months only: `start` must be the 1st and `end` must be the last day of a month, else raise `ValueError('wipe operates on whole months')`. Add a code comment `# shortcut: whole months only, matching the embedding shard layout; upgrade if partial-range wipes are ever needed`.
- Delete `items/YYYY/MM/` directories and `embeddings/YYYY-MM.npy` + `embeddings/YYYY-MM.index.json` for every month in range.
- Delete `days/YYYY-MM-DD.json` for every day in range.
- For every topic: remove `history` entries with `date` in range. Delete the topic file if its history becomes empty; otherwise rewrite it and drop deleted slugs from its `related` list.
- Delete `.backfill_state.json` if present.
- Leave `llm_spend.json`, `github_repos.json` and `github_stars.json` untouched.
- Return counts `{'items': n, 'days': n, 'topics_deleted': n, 'topics_trimmed': n}` and print them as one line.
- The command must NOT be run against the real `data/` directory by the worker. Tests only.

Document the command in `README.md` next to the existing `python -m pipeline` commands, with one sentence on when to use it (re-running a backfilled month after a collection fix).

## Files the worker may edit

- `pipeline/sources/biorxiv.py`
- `pipeline/run.py` (only the two `counts['dropped_revisions']` lines)
- `pipeline/wipe.py` (new)
- `pipeline/__main__.py` (new `wipe` command only)
- `tests/sources/test_biorxiv.py`
- `tests/sources/fixtures/biorxiv.json` (set record 0's `"version"` to `"1"` so existing assertions stay true; do not change anything else in it)
- `tests/sources/fixtures/biorxiv_revisions.json` (new)
- `tests/test_wipe.py` (new)
- `README.md`

Do not touch `data/`, `config/`, `site/`, or other pipeline modules.

## Tests (write first, see them fail, then implement)

`tests/sources/test_biorxiv.py`, using the new fixture `biorxiv_revisions.json` whose `collection` holds four records all with `"date": "2025-01-06"` and `"category": "bioinformatics"`. All four new tests fetch with the window `date(2025, 1, 5)..DAY` (DAY = 2025-01-06):

- A: `"version": "1"`, doi `10.1101/2025.01.06.111111` → kept, `published_at == date(2025, 1, 6)`.
- B: `"version": "3"`, doi `10.1101/2024.06.01.222222` → dropped (DOI date outside window).
- C: `"version": "2"`, doi `10.1101/2025.01.05.333333` → kept, `published_at == date(2025, 1, 5)` when the window is `2025-01-05..2025-01-06`.
- D: `"version": "2"`, doi `10.1101/123456` → dropped (undated DOI).

Tests:

- `test_biorxiv_revision_outside_window_is_dropped` (B absent from results).
- `test_biorxiv_revision_inside_window_uses_doi_date` (C present with DOI date; `metadata['version'] == '2'`).
- `test_biorxiv_undated_doi_revision_is_dropped` (D absent).
- `test_biorxiv_logs_dropped_revisions` (`caplog` contains `dropped 2 revisions`; `adapter.dropped_revisions == 2`).
- Existing tests must keep passing with record 0's version changed to `"1"`.

`tests/test_wipe.py` (build a store in `tmp_path` by copying `fixtures/data`, as `tests/test_run.py`'s `ctx` fixture does; the fixture data covers 2026-10-29..2026-11-01, so wipe October and check November survives):

- `test_wipe_removes_month_items_days_embeddings_and_checkpoint`: after `wipe(store, date(2026,10,1), date(2026,10,31))`, no `items/2026/10`, no `embeddings/2026-10.*`, no `days/2026-10-*.json`, `.backfill_state.json` gone (create one before), `days/2026-11-01.json` and `items/2026/11` still present, `llm_spend.json` untouched if created before.
- `test_wipe_trims_topic_history_and_deletes_empty_topics`: a topic whose history is entirely in October is deleted; one with a November entry keeps only that entry and no longer lists deleted slugs in `related`.
- `test_wipe_rejects_partial_months`: `date(2026,10,2)..date(2026,10,31)` raises `ValueError`.
- `test_cli_wipe_prints_counts`: `CliRunner` on `python -m pipeline wipe ... --data-root tmp` exits 0 and prints the four counts.

`tests/test_run.py`: add `test_collect_stage_logs_dropped_revisions` using the existing `ctx` fixture and a `FakeAdapter` with `dropped_revisions = 3` → the collect stage end line contains `dropped_revisions=3`.

## Commands

```
uv run --no-project --python 3.12 --with pydantic --with pytest --with numpy --with pyyaml --with respx --with httpx --with feedparser --with anthropic --with scikit-learn --with typer python -m pytest -q
```

Currently 220 passing; all must still pass plus the new ones. No network in tests.

## Commit

One commit on `main`, message `fix: drop bioRxiv revisions of papers first posted outside the window; add wipe command`. **Do not push.** The coordinator pushes and then runs the wipe and the October re-backfill.

## Evidence to report

- pytest summary line (count passed).
- The new fixture file contents.
- `git show --stat HEAD`.
- Confirmation that `data/` is unchanged (`git status --porcelain data` empty).
