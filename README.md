# TrendBio

## What this is

TrendBio tracks computational biology research, tools, and industry news.
It clusters related evidence into a daily ranked Top 40 with linked sources and
machine-generated syntheses for readers familiar with the field.

## How the pipeline runs

GitHub Actions runs the Python pipeline daily at 06:00 UTC. It collects,
deduplicates, enriches, clusters, ranks, and synthesizes evidence, then commits
successful output under `data/computational/`. Failed runs leave the last published data available.
GitHub Actions builds and deploys the Astro site to Cloudflare Pages on every push to `main` via `.github/workflows/deploy.yml`.
The site is served at https://trendbio.dev (and https://trendbio.pages.dev).

PubMed collects the computational-biology journals in `pubmed.journals` in full.
Journals in `pubmed.journals_keyword_filtered` require a title or abstract match to
`keywords`; no broad MeSH query is used. PubMed copies of bioRxiv and medRxiv
preprints are excluded. Enrichment excludes routine public-data analyses such as
hub-gene nomination and prognostic signatures unless they contribute a new method,
tool, model, dataset, benchmark or resource. Enrichment failures retain relevance.
The Top 40 reserves `category_floor` (default 1) topic per represented primary category,
then fills by score up to `max_per_category` (default 8) per category; sparse days can have fewer than 40.
The selected topics are ranked by score. The first `featured_n` (default 5) get full rows
and Opus synthesis; ranks 6–20 get compact rows and Sonnet synthesis, and ranks 21–40
get compact rows and Haiku synthesis. The first `display_open_n` (default 20) rows
are visible; “Show more” reveals the rest. `synthesis_tiers` sets the model boundaries.
Backfill and reprocessed history use `backfill_synthesis_model` (Haiku) for every tier;
over-ceiling runs always use Haiku.

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
Daily and backfill runs share a concurrency group to prevent overlapping writes.
Their job limits are 30 and 350 minutes, respectively.
The manual resynthesize workflow rewrites ranked-topic and day syntheses for inclusive `from`/`to` dates (`YYYY-MM-DD`) using `claude-haiku-5-5` (default) or `claude-opus-5-5` for the featured tier and always Haiku for ranks 6–40, shares the `pipeline` concurrency group, and commits changed data with a 120-minute job limit.

The manual maintenance workflow supports `restatus` (recompute stored run statuses
without collection or LLM calls) and `reprocess` (apply current PubMed scope and
rebuild clustering, ranking and synthesis from stored items). It shares the
`pipeline` concurrency group, has a 350-minute limit, and rebases before pushing
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

```sh
python -m pipeline restatus --domain computational --from 2026-10-01 --to 2026-10-31
python -m pipeline reprocess --domain computational --from 2026-10-01 --to 2026-10-31 --reenrich --model claude-haiku-5-5
```

## Operator notes

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
