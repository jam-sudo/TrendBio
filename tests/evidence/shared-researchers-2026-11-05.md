# Shared by researchers — validation, 2026-11-05

The display-only list appears immediately after “From code” on home and day pages.
It shows up to eight stored relevant papers, with reactions, distinct posting people,
first-seen dates, types and links to their ranked topic when one exists that day.
About explains the Bluesky-only coverage, high-volume exclusion and self-promotion.
No map, topic or period rendering changed.

The daily attention stage runs after the normal data transaction commits. Missing
credentials, login/search errors, unexpected exceptions and write failures cannot
roll back the day or change its status, notes, scores, rankings or LLM usage. Partial
aggregates are retained when available. Backfill, reprocess, repair, resynthesis,
restatus and dry-run paths do not collect attention. The existing daily workflow's
`git add data` includes `data/computational/attention/`; only the daily workflow was
changed to pass the two Bluesky secrets (the pre-existing standalone probe workflow
was left unchanged).

Search uses `q=*`, `domain=<host>`, `sort=latest`, `limit=100`, a shared budget and
one UTC day per slice. Output contains numeric aggregates, stored paper IDs and
per-host `partial` / `truncated_days` coverage; social identities and posts stay
in memory. The probe imports the extracted implementation and its tests pass.

## Checks

- Required Python suite: **517 passed, 90 warnings in 82.43 seconds**. Warnings are
  UMAP's existing `n_jobs`/`random_state` warning. Coverage includes UTC slices,
  per-host truncation, budgets, automation filtering, eligibility, threshold and
  ordering, privacy, failure isolation, skipped modes and unchanged LLM usage.
- `cd site && npm test`: **15 test files, 114 tests passed in 12.62 seconds**,
  including browser accessibility checks and the new list's fixture coverage.
- `cd site && npm run build`: **1,070 pages in 2.37 seconds**.
- `cd site && TRENDBIO_DATA_ROOT=../data npm run build`: **1,070 pages in 1.85 seconds**.
- `git diff --check` passed. No changes under `data/` or `fixtures/data/`.
- [Fixture section screenshot](shared-researchers-2026-11-05.png), captured with
  Playwright at a 1,280-pixel viewport and visually checked; two ranked papers and
  six unranked papers are visible. Fixtures live only under `site/tests/fixtures`.

Python command:

```sh
uv run --no-project --python 3.12 --with pydantic --with pytest --with numpy --with pyyaml --with respx --with httpx --with feedparser --with anthropic --with scikit-learn --with typer --with umap-learn python -m pytest -q
```

No real Bluesky calls, live LLM calls, workflow dispatches, new dependencies or
pushes. Live coverage was not remeasured; a partial sweep can miss high-volume
accounts, and the list can include authors promoting their own work.
