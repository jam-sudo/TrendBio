# TrendBio

## What this is

TrendBio tracks computational biology research, tools, and industry news.
It clusters related papers into a daily ranked Top 40 with attached code/industry evidence and
machine-generated syntheses for readers familiar with the field.

## How the pipeline runs

The manual [Bluesky attention probe](.github/workflows/bluesky-probe.yml) uses `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` to report aggregate attention for `days` (default 7), ending on the latest stored day, without changing rankings or data.

GitHub Actions runs the Python pipeline daily at 05:23 UTC with fallbacks at 08:41 and 12:17 UTC; a later slot is skipped when a run already succeeded that UTC day. It collects,
deduplicates, enriches, clusters, ranks, and synthesizes evidence, then commits
successful output under `data/computational/`. Failed runs leave the last published data available.
GitHub Actions builds and deploys the Astro site to Cloudflare Pages on every push to `main` via `.github/workflows/deploy.yml`.
The site is served at https://trendbio.dev (and https://trendbio.pages.dev).

RSS collects 22 feeds: 18 company/institute feeds and four keyword-filtered news feeds.
Company coverage includes AI-for-biology models, protein design, and bioinformatics
platforms; enrichment excludes corporate, community, HR, event, and general AI posts
without a computational-biology subject. RSS supplies only each feed’s available
entries, so daily collection builds coverage going forward rather than restoring history.

PubMed collects the computational-biology journals in `pubmed.journals` in full.
Journals in `pubmed.journals_keyword_filtered` require a title or abstract match to
`keywords`; no broad MeSH query is used. PubMed copies of bioRxiv and medRxiv
preprints are excluded. Enrichment excludes routine public-data analyses such as
hub-gene nomination and prognostic signatures unless they contribute a new method,
tool, model, dataset, benchmark or resource. Sync enrichment retries empty or invalid
output once, increasing its output allowance from 512 to 1,024 tokens without changing
the prompt or effort; empty-output warnings include the stop reason and output usage.
Exhausted enrichment failures retain relevance for papers only; code and industry
fallbacks remain stored with an `enrichment-fallback:` note but are not relevant.

Paper clusters use complete linkage at cosine distance 0.10, with at least three papers.
Each relevant code/industry item attaches to only its nearest paper centroid when cosine
similarity reaches `attach_min_similarity` (0.94; [calibration](tests/evidence/code-industry-2026-11-05.md)).
Attached IDs are stored separately in `attached_item_ids` (empty for older histories),
contributing evidence, diversity and code velocity without changing paper centroids,
counts, rise, volume or continuity. Unattached items do not rank. Home and day pages
also show up to eight relevant industry items first seen in their trailing seven days,
newest first, whether attached or not; the Industry chip is omitted when no topic uses it.
These changes apply to future runs; existing daily results are not rewritten.

The Top 40 reserves `category_floor` (default 1) topic per represented primary category,
then fills by score up to `max_per_category` (default 8) per category; sparse days can have fewer than 40.
The selected topics are ranked by score. The first `featured_n` (default 5) get full rows
and Opus synthesis; ranks 6–20 get compact rows and Sonnet synthesis, and ranks 21–40
get compact rows and Haiku synthesis. The first `display_open_n` (default 20) rows
are visible; “Show more” reveals the rest. `synthesis_tiers` sets the model boundaries.
Backfill and reprocessed history use `backfill_synthesis_model` (Haiku) for every tier;
over-ceiling runs always use Haiku.

Topic continuity requires a history entry within ±10 days (`continuity_max_gap_days`),
including when backfilling older months. A cluster continues a topic if its paper IDs
have Jaccard overlap ≥0.25 (`continuity_min_jaccard`) with the adjacent seven days of
that topic's history, or centroid cosine similarity ≥0.95 (`continuity_threshold`).
Matches are assigned by overlap first, then similarity, with at most one cluster per
topic per day. The centroid and categories track today's cluster; keyword slugs stay
stable. Empty history entries fill gaps of at most 10 days between appearances;
inactive topics stop accumulating history, and a later return starts a new topic.

GitHub discovery excludes forks and repos below `github.min_stars_for_discovery` (20 stars); explicit watchlist entries bypass these filters.
Discovered repos with matching normalized descriptions and variant names, or identical descriptions and fewer than 50 stars, collapse to the most-starred copy; collection logs report `collapsed=<n>`.

Configure the `ANTHROPIC_API_KEY` Actions secret and optionally `NCBI_API_KEY`;
Actions supplies `GITHUB_TOKEN`. Keep keys out of committed files.
The daily workflow also accepts an optional `date` and a `dry_run` switch.
Use a dry run before the first real run to inspect usage and estimated cost.

The manual backfill workflow takes inclusive `from` and `to` dates in
`YYYY-MM-DD` format, with `resume` enabled by default. Run monthly chunks;
each successful invocation commits its output once.
Historical star velocity is unavailable because GitHub restricted the stargazers endpoint, so backfilled days carry paper and industry signals only; daily runs accumulate star counts from launch (2026-11-02) onward.
Set optional `chain_until` (`YYYY-MM-01`) to automatically backfill previous months through that month, inclusive, after each successful run; failures stop the chain.
Daily and backfill processing steps have limits of 30 and 350 minutes, respectively.
The manual resynthesize workflow rewrites ranked-topic and day syntheses for inclusive `from`/`to` dates (`YYYY-MM-DD`) using `claude-haiku-5-5` (default) or `claude-opus-5-5` for the featured tier and always Haiku for ranks 6–40, shares the `pipeline` concurrency group, and commits changed data with a 120-minute processing limit.

`repair-synthesis --from YYYY-MM-DD --to YYYY-MM-DD [--model claude-haiku-5-5]` (also in Maintenance) fills missing topic and day syntheses without changing ranks, evidence, or map coordinates.

The manual maintenance workflow supports `restatus` (recompute stored run statuses
without collection or LLM calls) and `reprocess` (apply current PubMed scope and
rebuild clustering, ranking and synthesis from stored items). It shares the
`pipeline` concurrency group, has a 350-minute processing limit, and rebases before pushing
its committed output to `main`. `reprocess` requires whole months and automatically resumes
an interrupted run with the same range and options while its checkpoint remains
in the data directory. It retains items
and existing embeddings, clears days and topic history in range, then rebuilds days
chronologically. `--reenrich` replaces summaries, categories and relevance for every
item via Batches; venue exclusions still apply. The hosted workflow enables
reenrichment by default with `claude-haiku-5-5`; locally it is opt-in.
Use `--no-reenrich --only-missing-synthesis` to extend existing days: this retains
topic identities and existing headlines, summaries and syntheses while rerunning
clustering and ranking, and synthesizes only topics without a headline. No LLM
enrichment is performed. The workflow exposes `only_missing_synthesis` (default false):

For a full continuity rebuild, pass `--rebuild-topics`: it removes every topic's
history in the requested months, deletes topics left empty, and clears synthesis
only for topics whose entire history is inside the range before replaying days
chronologically. Items and embeddings remain cached. Combine with `--only-missing-synthesis` to synthesize new
topics once with the backfill model (Haiku), while keeping synthesis on
surviving topics with history outside the range. Rebuild the entire affected date
range to replace old mega-topics completely.

```sh
python -m pipeline restatus --domain computational --from 2026-10-01 --to 2026-10-31
python -m pipeline reprocess --domain computational --from 2026-10-01 --to 2026-10-31 --reenrich --model claude-haiku-5-5
python -m pipeline reprocess --domain computational --from 2026-01-01 --to 2026-10-31 --rebuild-topics --only-missing-synthesis
```

The four data-writing workflows (Daily pipeline, Backfill, Maintenance and
Resynthesize) keep the `pipeline` concurrency group and also poll the Actions API
after checkout, waiting for earlier-created queued or in-progress writers before
refreshing `main` and processing data. The wait defaults to 300 minutes with a
60-second poll interval; younger runs wait for older runs to avoid a mutual wait.
The 360-minute job limit includes waiting, setup and processing, so long waits
reduce the remaining processing time. If committing still hits a rebase conflict,
the workflow aborts the rebase and logs a single merge retry using `-X ours`, so
this run's fresher data wins conflicting hunks while non-conflicting upstream
changes are retained. This fallback is a last resort; the wait does not prevent
GitHub from replacing pending runs in the retained concurrency group.

## Operator notes

The recommended daily trigger is the [Cloudflare Worker in `ops/daily-trigger/`](ops/daily-trigger/),
which dispatches the Daily pipeline at 06:05 UTC after checking for an active run
or a success created today (UTC). Enable it with one GitHub token secret using
the linked setup instructions; keep GitHub's `schedule` as backup because its
runs can arrive hours late.

Add Markdown at `notes/<slug>.md`, using the slug from the topic URL, and push
to `main`. The site rebuild displays it as the topic's Editor's note; no
pipeline run is needed. A note for an unknown slug produces a build warning.

## Costs (measured)

Hosted dry run on 2026-11-02 (GitHub Actions `ubuntu-latest`, 7-day window, 1,196 new items, 164 topics):

| Stage | Result |
|---|---|
| Wall time | 16 min including setup (collect 4.7 min, enrich 3.4 min, embed 4.5 min, synthesize 56 s) |
| Haiku 5.5 (enrichment) | 1.96M input / 124k output tokens |
| Opus 5.5 (5 syntheses) | 17.5k input / 5.1k output tokens |
| Estimated cost | USD 0.43 for the run; a steady-state day (~170 new items) is lower, so roughly USD 10-15/month |
| Enrichment fallbacks | 10 of 1,196 (5 `refusal:bio`, 4 `empty_output`, 1 `validation`) |

Planning estimate for Top 40: 5 Opus + 15 Sonnet + 20 Haiku syntheses/day ≈ USD 0.50/day
(about USD 15/month), within the USD 50 monthly ceiling; actual usage depends on
evidence length. History stays on Haiku for cost control.

## Run locally

Use Python 3.12 and Node 22. Set `ANTHROPIC_API_KEY` in your environment for
live pipeline commands; optionally set `NCBI_API_KEY` and `GITHUB_TOKEN`.

```sh
pip install -e '.[dev]'
pytest -q
python -m pipeline run --dry-run
cd site
npm ci
npx playwright install --with-deps chromium
npm test
npm run dev
```

To re-run a backfilled month after a collection fix, wipe that whole month before backfilling it again:

```sh
python -m pipeline wipe --domain computational --from 2026-10-01 --to 2026-10-31 --data-root data
```

The development server uses synthetic fixtures. To build against real output,
run from `site/`:

```sh
TRENDBIO_DATA_ROOT=../data TRENDBIO_NOTES_ROOT=../notes npm run build
```

## Site sponsors

Edit `site/src/content/sponsors.json` and push to `main` to update sponsors.
The static build publishes the cards; there is no ad network or sponsor JavaScript.
Keep `slots` an even number (10 by default; 0 disables sponsorship), and set
`contact` to the email used by the Advertise card. Add entries like:

```json
{ "name": "Example Bio", "tagline": "Tools for computational biology", "url": "https://example.com", "logo": "🧪", "hue": 150 }
```

Taglines must be one line and at most 60 characters; links must be absolute HTTP(S)
URLs and hues must be numbers from 0 to 360. Use one emoji for `logo`, or put an
image (PNG, JPEG, WebP, GIF, AVIF, SVG; at most 20 KB) in `site/public/sponsors/`
and set `logo` to `/sponsors/filename.png`. Logos display at 28px. The build fails
with the entry and field when the JSON is invalid. Keep the number of sponsors
at or below `slots`; remaining capacity appears in the contact card.

At 1440px and wider, cards sit in sticky columns beside the main content; on
smaller screens they appear in a scrollable Sponsors row above the footer.
