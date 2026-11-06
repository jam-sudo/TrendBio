# "Shared by researchers" list (TrendBio, `main`, /Users/jam/TrendBio)

The owner approved a display-only list of the papers researchers reacted to most on Bluesky. It sits below the Top 40 and never changes rankings or scores. Measurement (`ops/bluesky-probe/probe.py`, GitHub Actions run 42144497650): 196 high-volume accounts made 80% of swept posts; after excluding them, 13 of 450 relevant papers in a week reached engagement of at least 5, and 11 such papers were absent from every Top 40 row. Engagement is too sparse for scoring, but it surfaces single papers the cluster-based ranking cannot.

Read: `ops/bluesky-probe/probe.py`, `tests/test_bluesky_probe.py`, `.github/workflows/bluesky-probe.yml`, `.github/workflows/daily.yml`, `pipeline/run.py` (`run_day`, `_stage`, `_staging`, `Deps`), `pipeline/store.py`, `pipeline/models.py`, `pipeline/config.py`, `config/scoring.yaml`, `site/src/components/IndustryList.astro`, `CodeList.astro`, `DayTopics.astro`, `site/src/lib/data.ts`, `site/src/lib/types.ts`, `site/src/pages/about.astro`, `site/tests/industry.test.ts`, `site/tests/code.test.ts`, `site/tests/build.ts`.

## Pipeline
1. Move the reusable logic from the probe (session, search with backoff and budget, link extraction, id normalization, join to stored items, automated-account classification) into `pipeline/attention.py`, and have the probe import it so `tests/test_bluesky_probe.py` stays green.
2. Query form, verified live: `q="*"` with `domain=<host>`, `sort=latest`, `limit=100`. Hosts: `biorxiv.org`, `medrxiv.org`, `arxiv.org`, `doi.org`, `pubmed.ncbi.nlm.nih.gov`, `nature.com`.
3. Sweep each UTC day of the window as its own `since`/`until` slice. The probe's single 7-day sweep hit the cursor limit on 5 of 6 hosts, and with `sort=latest` that silently drops the oldest days. Record per-host truncation.
4. New stage `attention` in `run_day`, for daily runs only. It must not run in backfill, reprocess, repair, resynthesize or restatus paths, and it makes no LLM calls.
5. Config under `attention:` in `config/scoring.yaml` and `pipeline/config.py`: `automated_min_ids: 20`, `min_engagement: 5`, `store_top_n: 20`, `window_days: 7`, `max_search_calls: 800`.
6. Engagement = likes + reposts + quotes on posts by non-automated accounts. A paper qualifies when it is a stored item with `relevant: true`, type preprint or published, and engagement of at least `min_engagement`.
7. Write `data/computational/attention/<date>.json`: `date`, `window_start`, `partial` (bool), `search_calls`, `posts_swept`, `automated_accounts`, `automated_post_share`, and `papers`: up to `store_top_n` of `{item_id, engagement, authors}` sorted by engagement, then authors, then id. The repository is public: NEVER store or log handles, DIDs, post text or post URIs, nor the password or tokens.
8. **The stage must never hurt the daily run.** Missing credentials, login failure, HTTP errors, budget stop or any exception: log one warning without secrets, write no file for that day (or write it with `partial: true` when partial data exists), and leave `run.status`, notes, rankings and scores untouched. A failed Bluesky stage must not mark a day degraded.
9. `daily.yml`: pass `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` to the pipeline step. No other workflow gets them. Check that the `Commit data` step includes the new directory.

## Site
10. `site/src/components/SharedList.astro`, titled "Shared by researchers", rendered directly after "From code" on the home page and day pages, in the same style. Read `attention/<date>.json` for that day through the existing global index; a missing directory or file means no section, not an error. Show at most 8 papers. Each row: linked paper title, type (preprint or published), first-seen date, `N reactions` and `M people`, and, when the paper belongs to a ranked topic that day, a link to that topic labelled with its rank. Otherwise show nothing extra for rank.
11. One line under the heading: "Papers with the most reactions on Bluesky this week, excluding high-volume posting accounts."
12. About page: a short paragraph stating that this list never affects rankings, covers Bluesky only, excludes accounts linking 20 or more papers a week, and can include authors promoting their own work.
13. Add the attention pages to nothing else: no map, topic or period page changes.

## Tests
- Pipeline (no network): per-day slicing; truncation recorded per host; automated accounts excluded from engagement; threshold; relevant-only; stored file contains no handle, DID, post text or URI; missing credentials and HTTP 500 each leave `run.status` `ok` and do not raise; stage skipped in backfill and reprocess; no LLM call; probe tests still pass.
- Site: section renders with a fixture, at most 8 rows; rank link shown only when ranked; omitted with no file; About text present. Put site fixtures under `site/tests/fixtures` and copy them in `site/tests/build.ts`. Do NOT add files to `fixtures/data/` (doing so broke the pipeline fixture tests last time).

## Constraints
- Edit `pipeline/**`, `ops/bluesky-probe/**`, `config/scoring.yaml`, `.github/workflows/daily.yml`, `site/**`, `tests/**`, `README.md`. Do not edit `data/`. No new dependencies. No real network calls to Bluesky, no live LLM calls, no workflow dispatch.
- Run BOTH suites and report both: `uv run --no-project --python 3.12 --with pydantic --with pytest --with numpy --with pyyaml --with respx --with httpx --with feedparser --with anthropic --with scikit-learn --with typer --with umap-learn python -m pytest -q`, and `cd site && npm test && npm run build`. `TRENDBIO_DATA_ROOT=../data npm run build` must still finish in seconds.
- Commit on `main` as `feat: Shared by researchers list from Bluesky reactions; display only`. Do not push (coordinator pushes).

## Evidence
- Both test summaries; a screenshot of the section built from a fixture; `git log --oneline -2`.
