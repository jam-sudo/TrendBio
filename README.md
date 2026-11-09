<p align="center">
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="docs/readme/mark-light.svg">
    <img src="docs/readme/mark-dark.svg" width="56" alt="">
  </picture>
</p>

<h1 align="center">TrendBio</h1>

<p align="center">
  What is moving in computational biology, ranked every day.<br>
  Papers, code and industry — clustered, scored and summarised by a pipeline, not a newsroom.
</p>

<p align="center">
  <a href="https://trendbio.dev"><strong>trendbio.dev</strong></a>
</p>

<p align="center">
  <a href="https://github.com/jam-sudo/TrendBio/actions/workflows/daily.yml"><img src="https://github.com/jam-sudo/TrendBio/actions/workflows/daily.yml/badge.svg" alt="Daily pipeline"></a>
  <a href="https://github.com/jam-sudo/TrendBio/actions/workflows/deploy.yml"><img src="https://github.com/jam-sudo/TrendBio/actions/workflows/deploy.yml/badge.svg" alt="Deploy"></a>
  <a href="https://github.com/jam-sudo/TrendBio/actions/workflows/ci.yml"><img src="https://github.com/jam-sudo/TrendBio/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
</p>

<picture>
  <source media="(prefers-color-scheme: light)" srcset="docs/readme/home-light.png">
  <img src="docs/readme/home-dark.png" alt="The TrendBio home page: a centred helix, a search box, and the day's ranked research topics.">
</picture>

Every day TrendBio reads the new preprints, papers, repositories and company posts in computational biology, groups them into research topics, ranks the Top 40, and writes a short synthesis for each one. The result is one page a day for readers who already know the field. History runs back to 1 November 2025.

## How a day is made

```
      bioRxiv · arXiv · PubMed          GitHub              22 RSS feeds
       preprints and papers        repos and releases    company and news posts
                 │                        │                        │
                 └────────────────────────┼────────────────────────┘
                                          ▼
   collect ─▶ dedupe ─▶ enrich ─▶ embed ─▶ cluster ─▶ score ─▶  select ─▶ synthesize
                        Haiku     SPECTER2 complete   rise      Top 40    Opus 1–5
                                           linkage    diversity 1 per     Sonnet 6–20
                                           d ≤ 0.10   velocity  category  Haiku 21–40
                                                      volume    floor
                                          │
                                          ▼
             commit data/computational/  ─▶  Astro build  ─▶  Cloudflare Pages
```

| Stage | What happens |
|---|---|
| Collect | bioRxiv (7 categories), arXiv (`q-bio.*`, plus keyword-filtered `cs.LG`, `cs.AI`, `stat.ML`), PubMed (21 journals in full, 16 keyword-filtered), GitHub (20 watched repositories plus 8 topic searches), 22 RSS feeds (18 company, 4 news) |
| Dedupe | Preprint versions collapse; PubMed copies of bioRxiv and medRxiv preprints are dropped; preprints link to their published versions when known |
| Enrich | Claude Haiku judges relevance and writes a one-line summary; number claims are grounded against the title and abstract |
| Embed and cluster | SPECTER2 (`allenai/specter2_base`) embeddings; complete-linkage clustering at cosine distance 0.10; a topic needs at least 3 papers |
| Attach | A code or industry item joins its nearest topic only when cosine similarity reaches 0.94; it adds evidence, never paper counts |
| Score | rise 45 % · diversity 25 % · code velocity 15 % · volume 15 %, with a 5 % penalty for ranking yesterday |
| Select | One topic reserved per represented category, then by score, at most 8 per category, Top 40 |
| Synthesize | Claude Opus for ranks 1–5, Sonnet for 6–20, Haiku for 21–40; backfilled history uses Haiku |

Topics persist across days when a cluster shares enough papers with the adjacent seven days of a topic's history (Jaccard ≥ 0.25) or sits close enough to its centroid (similarity ≥ 0.95), with a history entry within 10 days in either direction. A topic keeps its page, its history and its rank changes.

## The site

[Today](https://trendbio.dev) · [Topics](https://trendbio.dev/topics) · [Map](https://trendbio.dev/map/) · [Archive](https://trendbio.dev/archive) · [About](https://trendbio.dev/about)

- Full rows for the Top 5, compact rows to 20, "Show more" to 40; rows carry rank changes, and the Top 20 show tool names extracted from paper titles.
- Every topic links its evidence, offers BibTeX for its papers, and keeps a day-by-day history.
- Weekly and monthly rankings, a topic map, and a year of archive pages.
- Three side lists: From code (GitHub repositories and star gains), From industry (company announcements), and Shared by researchers (papers getting attention on Bluesky; display only, never affects ranking).
- Instant search as you type (Pagefind, built at deploy time), Atom feeds for the daily Top 5 and per category, a dark and a light theme, times in US Eastern.
- Astro 5, static files on Cloudflare Pages, Cloudflare Web Analytics without cookies.

## Schedule and cost

A [Cloudflare Worker](ops/daily-trigger/) dispatches the Daily pipeline at 06:05 UTC; GitHub's own schedule stays as a late-arriving backup that skips when a run created that UTC day already succeeded. A run takes about ten minutes and commits its output to `data/computational/`; the site rebuilds after every push to `main` and after every pipeline run.

Planned LLM spend is about USD 0.50 a day under a USD 55 monthly ceiling; once the month's spend passes the ceiling, new syntheses fall back to Haiku and the day is marked degraded. Only aggregate counts, paper IDs and per-host coverage from Bluesky are stored; no identities, post text or credentials ever are.

## Run it yourself

Python 3.12 and Node 22. Set `ANTHROPIC_API_KEY` for live pipeline commands; `NCBI_API_KEY` and `GITHUB_TOKEN` are optional but raise rate limits.

```sh
pip install -e '.[dev]'
pytest -q
python -m pipeline run --dry-run

cd site
npm ci
npx playwright install --with-deps chromium
npm test
npm run dev                                       # synthetic fixtures
TRENDBIO_DATA_ROOT=../data npm run build          # the real year of data
```

## Repository map

```
config/     sources, scoring weights, category taxonomy
pipeline/   collect → dedupe → enrich → embed → cluster → score → synthesize
data/       the database: one JSON file per day, topic and item, committed by the pipeline
site/       the Astro site, rebuilt from data/ after every push and pipeline run
notes/      optional editor's notes, one Markdown file per topic slug
ops/        the Cloudflare trigger Worker and the Bluesky probe
tests/      pipeline tests and calibration evidence
docs/       design spec, implementation plans, operations guide
```

## Documentation

- [Design spec](docs/superpowers/specs/2026-11-02-trendbio-design.md) — the product decisions and why
- [Operations](docs/operations.md) — sources, thresholds, workflows, degraded days, sponsors, measured costs
- [Implementation plans](docs/superpowers/plans/) — one file per shipped change

Headlines, summaries and syntheses are machine-generated and can be wrong; follow the evidence links before relying on a claim. Contact: jaemin6013@gmail.com
