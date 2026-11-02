# Task 4: degraded-run threshold for enrichment fallbacks

Date: 2026-11-02. Approved by trendbio-03 and trendbio-e4. Land after Tasks 1–3 (can be done alongside Task 2; they touch different files).

## Problem

`run_day` marks a day `degraded` when any `-fallback:` note exists. Hosted dry run #3 had 10 enrichment fallbacks of 1,196 items (5 bioRxiv refusals), and every backfilled October day carries dozens of `enrichment-fallback:` notes, so every day shows the "Some sources or summaries were unavailable" notice. A notice that always shows means nothing. The predecessor project's rule: a step is degraded only when its errors exceed a floor AND a share of the work.

## Rule

A day is `degraded` when any of these holds:

1. Enrichment fallbacks: `count > cfg.degraded_fallback_min` **and** `count > cfg.degraded_fallback_rate * attempted`, where `count` is the number of distinct `enrichment-fallback:` notes and `attempted` is the number of items in the day's 7-day window (`store.items_between(start, day)`, before the relevance filter from Task 3).
2. Any `synthesis-fallback:` note (unconditional; five topics, each matters).
3. Any paper source (`biorxiv`, `arxiv`, `pubmed`) `failed` (unconditional, existing).
4. `github` `failed` on a non-backfill day (existing).
5. Budget over ceiling (existing).

## Changes

### `pipeline/config.py` and `config/scoring.yaml`

`Scoring` gains `degraded_fallback_min: int = 3` and `degraded_fallback_rate: float = 0.2`; add both to `config/scoring.yaml`.

### `pipeline/run.py`

Extract a pure helper and use it in the `write` stage:

```python
def is_degraded(notes: list[str], source_status: dict[str, str], *, backfill: bool,
                over_ceiling: bool, attempted: int, cfg: Scoring) -> bool
```

`attempted` in `run_day` is `len(store.items_between(start, day))` computed in the embed stage before any filtering (store it in a local).

### `pipeline/__main__.py`

`resynthesize` recomputes `degraded` inline with the old rule. Replace that block with `is_degraded(...)`, with `attempted = len(staged.items_between(day - timedelta(days=deps.cfg.window_days - 1), day))`.

### Site

No change. `DayTopics.astro` already renders the notice from `run.status`.

## Files the worker may edit

- `pipeline/config.py`, `config/scoring.yaml`, `pipeline/run.py`, `pipeline/__main__.py`
- `tests/test_config.py`, `tests/test_run.py`

Do not edit `data/`, `site/`, other pipeline modules.

## Tests (write first)

`tests/test_config.py`:

- extend `test_scoring_defaults` with `degraded_fallback_min == 3` and `degraded_fallback_rate == 0.2`.

`tests/test_run.py` (unit tests on `is_degraded` with `load_scoring()`, plus one integration test through `run_day`):

- `test_few_enrichment_fallbacks_do_not_degrade`: 3 fallback notes, attempted 10, all sources ok → `False` (3 is not > 3).
- `test_fallbacks_above_floor_but_below_rate_do_not_degrade`: 4 of 100 → `False`.
- `test_many_enrichment_fallbacks_degrade`: 5 of 10 → `True`.
- `test_synthesis_fallback_always_degrades`: one `synthesis-fallback:` note, attempted 1,000 → `True`.
- `test_paper_source_failure_always_degrades`: no notes, `pubmed: failed` → `True`.
- `test_duplicate_fallback_notes_count_once`: the same `enrichment-fallback:x` note twice, min 3 → counts as 1.
- Update the existing `test_degraded_when_fallback_note_present` to assert the new behaviour: with the `ctx` fixture (few items), a single enrichment fallback leaves the day `ok`, while a synthesis fallback makes it `degraded`. Keep `test_partial_paper_failure_marks_day_degraded` and `test_only_daily_github_collection_failure_degrades_day` unchanged.
- `test_cli_resynthesize_uses_threshold_rule`: a stored day with status `degraded` due only to two enrichment fallbacks becomes `ok` after `resynthesize` (extend `test_cli_resynthesize_honors_model`'s setup).

## Commands

```
uv run --no-project --python 3.12 --with pydantic --with pytest --with numpy --with pyyaml --with respx --with httpx --with feedparser --with anthropic --with scikit-learn --with typer python -m pytest -q
```

## Commit

One commit on `main`: `fix: degrade a day on enrichment fallbacks only above a floor and a rate`. **Do not push.**

## Evidence to report

- pytest summary line.
- `git show --stat HEAD`; `git status --porcelain data` empty.
