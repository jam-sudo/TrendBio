# TrendBio

## What this is

TrendBio tracks computational biology research, tools, and industry news.
It clusters related evidence into a daily ranked Top 5 with linked sources and
machine-generated syntheses for readers familiar with the field.

## How the pipeline runs

GitHub Actions runs the Python pipeline daily at 06:00 UTC. It collects,
deduplicates, enriches, clusters, ranks, and synthesizes evidence, then commits
successful output under `data/computational/`. Cloudflare Pages builds the Astro
site on pushes to `main`. Failed runs leave the last published data available.

Configure the `ANTHROPIC_API_KEY` Actions secret and optionally `NCBI_API_KEY`;
Actions supplies `GITHUB_TOKEN`. Keep keys out of committed files.
The daily workflow also accepts an optional `date` and a `dry_run` switch.
Use a dry run before the first real run to inspect usage and estimated cost.

The manual backfill workflow takes inclusive `from` and `to` dates in
`YYYY-MM-DD` format, with `resume` enabled by default. Run monthly chunks in
chronological order; each successful invocation commits its output once.
Daily and backfill runs share a concurrency group to prevent overlapping writes.
Their job limits are 30 and 350 minutes, respectively.

## Operator notes

Add Markdown at `notes/<slug>.md`, using the slug from the topic URL, and push
to `main`. The site rebuild displays it as the topic's Editor's note; no
pipeline run is needed. A note for an unknown slug produces a build warning.

## Costs (measured)

Pending: record token usage and estimated USD cost after the first live dry run.

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

The development server uses synthetic fixtures. To build against real output,
run from `site/`:

```sh
TRENDBIO_DATA_ROOT=../data TRENDBIO_NOTES_ROOT=../notes npm run build
```
