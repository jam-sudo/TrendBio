# TrendBio — Design

Date: 2026-11-02
Status: approved by owner (brainstorm), pending builder check
Builder: Codex workers (model "Astra") dispatched via the `orchestration` skill. Claude plans; Codex builds.

## 1. Intent

TrendBio is an English-language website that automatically tracks and synthesizes what is moving in computational biology / bioinformatics: new research (preprints and published papers), code and tool releases, and industry announcements. It answers one question for a reader who already knows the field: **"What moved in computational biology today, and why does it matter?"**

The owner's observation: there is no place that combines the latest research, tools and industry news into a trend-level view. bioRxiv is a feed, not a synthesis. Newsletters are human-paced and narrow. TrendBio fills that gap with an automated daily pipeline and a minimal, clean site.

The owner is one person and will not write content. The pipeline must run unattended. The owner may occasionally add a short note to a topic.

## 2. Goals, non-goals, anti-goals

### Goals (v1)
- Every day, publish a ranked **Top 5 topics** for computational biology with, for each topic, a headline, a short "why this is trending" synthesis, the signals behind the ranking, and the underlying evidence (published papers, preprints, code, industry items).
- Let a reader filter the day's topics by **category** (omics subfields and method areas, see §5).
- Keep a browsable **archive** of past days and of each topic's history.
- Run at near-zero operating cost: free hosting, free scheduler, LLM spend capped around **USD 50/month**.
- Be structured so that new **domains** (wet-lab biology, pharma, genomics-clinical, …) can be added later as sibling sections without rewriting the pipeline or the site.

### Non-goals (v1)
- No user accounts, personalization, comments, voting or any visitor-generated content.
- No full-text site search.
- No social-media signals (X/Bluesky). Deferred to a later version.
- No email newsletter. (A third-party subscription form may be embedded later; nothing to build now.)
- No admin UI. Operator notes are files in the repo.
- No custom domain at launch. Use the host's default URL; a domain can be attached later.
- No languages other than English.

### Anti-goals (what would make it a failure even if it "works")
- **A feed dressed as trends.** If the Top 5 is just "the five most recent / most tweeted papers", the site has failed. Topics must be clusters of related activity with a reason for rising.
- **Beginner tone.** No "What is a genome?" explanations. Assume a reader with graduate-level familiarity.
- **Visual clutter.** The design must stay minimal: white background, dark text, one accent colour, generous whitespace. Decorative elements beyond the hero animation are out.
- **Silent failure.** A day where the pipeline breaks must be visible to the owner (failed CI run), and the site must keep showing the last good day rather than an empty page.
- **Hallucinated evidence.** Every claim in a topic synthesis must be traceable to listed items. The LLM never invents papers, numbers or affiliations; it writes only from the items it is given.

## 3. Audience

Computational biologists, bioinformaticians, ML-for-biology researchers and engineers, and bio-industry people who follow the technical side. They read bioRxiv, follow GitHub, and know the vocabulary. They want density and speed, not explanation.

## 4. The product

### 4.1 Landing page ("Today")

Chosen layout (mockup "B" in the brainstorm):

1. **Nav**: wordmark "TrendBio" left; links right: Today, Topics, Archive, About.
2. **Compact hero**, about one third of the viewport: left, a headline ("What moved in computational biology today") and one line of subtext stating the sources and the update time; right, a **minimal motion graphic** of a DNA double helix or protein backbone (see §4.5). The hero must never push the Top 5 below the fold on a laptop screen.
3. **Category chips** in a single row: "All" plus the categories in §5. Clicking a chip filters the cards in place (client-side, no page reload). A chip with zero matching topics that day is shown disabled.
4. **Top 5 topic cards** in a two-column grid. The #1 card spans both columns. Each card shows:
   - rank and category label (e.g. "#1 · Protein design")
   - headline (one sentence, ≤ 90 characters)
   - one-line summary (≤ 160 characters) — on the #1 card only
   - **signal line**, e.g. `7 preprints · 2 published · 2 tools · 1 industry · ↑ 4× vs 4-wk avg`
   - clicking the card opens the topic page.
5. **Footer**: short "how this works" line linking to About; last pipeline run time.

### 4.2 Topic page

Single-column (mockup "1" in the brainstorm), max width ~680px.

1. Breadcrumb back to the day it appeared on.
2. Rank-and-category label, then the **headline**.
3. **Signal badges**: counts per evidence type and the rise ratio.
4. **Sparkline**: this topic's item count per day over the last 8 weeks, with today highlighted. Hidden if the topic is fewer than 3 days old.
5. **Synthesis**: an LLM-written paragraph (80–160 words) explaining what the activity is and why it is rising now. Written only from the listed items; every concrete claim must correspond to an item below.
6. **Editor's note** (optional): the owner's comment, rendered in a visually distinct callout. Shown only when a note file exists for this topic (see §6.6).
7. **Evidence sections**, in this order, each omitted when empty:
   - **Published papers** — journal articles. Title, journal, date, first author + "et al.", one-line summary, link (DOI). If the paper has a known preprint, show a small "preprint" link next to it.
   - **Preprints** — bioRxiv / arXiv. Title, server badge, date, first author + "et al.", one-line summary, link. If a preprint has since been published, it is moved to Published papers and not duplicated here.
   - **Code & tools** — GitHub repos / releases. Name, stars gained this week, license, one-line summary, link.
   - **Industry** — company blog posts, press releases, funding, product launches. Title, source, date, one-line summary, link.
8. **Related topics**: up to 3 other topics with the closest embedding centroids, as links.
9. **Topic history**: list of dates this topic ranked in the Top 5, with rank.

### 4.3 Archive

- `/archive` — list of days, newest first, each showing the date and its five headlines.
- `/day/YYYY-MM-DD` — that day's landing page (same layout as Today, without the hero).
- `/topics` — all topics ever ranked, sorted by most recent appearance, with category filter.
- `/topic/<slug>` — topic page.
- `/about` — plain page: what the site is, sources, how ranking works (one paragraph each), disclaimer that summaries are machine-generated, contact.

### 4.4 Domain structure (for later expansion)

Everything above is scoped to one **domain**: `computational`. URLs in v1 are unprefixed. The data layout and config are keyed by domain from day one so that a second domain (e.g. `wetlab`) can be added by adding a config file and a data folder, after which the site gains a domain switcher in the nav and domain-prefixed URLs. Building the switcher is out of scope for v1; keeping the data keyed by domain is in scope.

### 4.5 Visual design

- **Tone**: minimal, editorial, quiet. Think a well-typeset journal front page, not a dashboard.
- **Palette**: white background (`#ffffff`), near-black text (`#111`), one accent for category labels, sparkline highlight and links (a blue around `#4f7cff`; builder may pick a close alternative), light grey borders (`#e5e5e5`). Light theme only in v1; use CSS variables so dark mode can be added later.
- **Type**: a single sans-serif family (Inter or system stack). Tight letter-spacing on headlines. No more than three type sizes on a page.
- **Hero animation**: a looping, slow (≥ 6 s period), low-contrast motion graphic of a DNA double helix or protein backbone. Vector-based (SVG + CSS or a lightweight canvas), no video, no heavy 3D library; total hero JS ≤ 30 KB. Respects `prefers-reduced-motion` by showing a static frame. Must be the only animated element on the page.
- **Responsive**: works on a phone; chips scroll horizontally; cards stack to one column.
- **Accessibility**: semantic HTML, keyboard-navigable chips and cards, WCAG AA contrast, animation disabled under reduced-motion.

## 5. Categories (v1 taxonomy for the `computational` domain)

Each item and each topic gets exactly one **primary** category and optionally secondary ones. Chips filter on primary or secondary.

| Slug | Label | Covers |
|---|---|---|
| `genomics` | Genomics | genome assembly, variant calling, pangenomes, population genetics, GWAS methods |
| `transcriptomics` | Transcriptomics | bulk RNA-seq methods, isoform analysis, spatial transcriptomics |
| `proteomics` | Proteomics | mass-spec informatics, PTM analysis, protein quantification |
| `metabolomics` | Metabolomics | metabolite ID, flux analysis, lipidomics |
| `epigenomics` | Epigenomics | methylation, chromatin accessibility, 3D genome, histone marks |
| `single-cell` | Single-cell | scRNA/scATAC methods, integration, trajectory, perturbation models, cell atlases |
| `structural` | Structural bio & protein design | structure prediction, protein design, docking, molecular dynamics |
| `systems` | Systems biology | networks, modelling, gene regulation, multi-omics integration |
| `ml-ai` | ML / AI methods | foundation models, representation learning, benchmarks, where the contribution is the method rather than the biology |
| `tools-infra` | Tools & infrastructure | workflow managers, file formats, databases, cloud/HPC, visualization |
| `industry` | Industry | company announcements, funding, product launches, partnerships |

The taxonomy lives in a config file so it can be edited without code changes. Categories are assigned by the LLM at ingestion (see §6.3) from the item's title and abstract, constrained to this list.

## 6. The pipeline

Runs once a day, unattended, as a scheduled GitHub Actions workflow. Language: **Python 3.12**. Output: JSON files committed to the repo, consumed by the static site build.

### 6.1 Stages

```
collect → normalize & dedupe → enrich (summary, category, embedding)
→ cluster into topics → link topics across days → score & rank
→ synthesize top 5 → write JSON → commit → build site → deploy
```

Each stage is a separate module with a CLI entry point so it can be run and tested alone. The whole run must finish in under 30 minutes on a standard GitHub Actions runner.

### 6.2 Sources (v1)

All source definitions (API endpoints, categories, journal lists, repo lists, RSS URLs, keyword filters) live in `config/sources/<domain>.yaml`, never in code.

| Source | What | How | Notes |
|---|---|---|---|
| bioRxiv | preprints | official API, by date and category | categories: Bioinformatics, Genomics, Systems Biology, Synthetic Biology, Biophysics, Molecular Biology (keyword-filtered), Cell Biology (keyword-filtered). Also pull the published-DOI field to link preprint → paper. |
| arXiv | preprints | API query | `q-bio.*` all; `cs.LG`, `cs.AI`, `stat.ML` filtered by a bio keyword list in config. |
| PubMed | published papers | E-utilities, date-bounded | two queries: (a) journal list in config (Bioinformatics, Genome Biology, Nature Methods, Nature Biotechnology, Nucleic Acids Research, Cell Systems, PLOS Comp Bio, Genome Research, Briefings in Bioinformatics, BMC Bioinformatics, Nature Computational Science, Nature Machine Intelligence, Cell Genomics, Molecular Systems Biology, GigaScience, eLife — editable); (b) a MeSH/keyword query for computational biology in other journals. Match to preprints by DOI, then by normalized title. |
| GitHub | code & tools | REST search + repo endpoints | track repos by topic tags (`bioinformatics`, `computational-biology`, `genomics`, `single-cell`, `protein-design`, …) and a curated watchlist in config. Record daily star count; a repo becomes an **item** when its 7-day star gain crosses a threshold (default 100) or it publishes a release. |
| Industry | announcements | RSS/Atom feeds listed in config | company blogs (e.g. Isomorphic Labs, Recursion, insitro, Arc Institute, CZI, Broad, EMBL-EBI, NVIDIA BioNeMo, Google DeepMind science, Microsoft Research health) and trade news (GEN, STAT+ RSS, Endpoints, FierceBiotech) filtered by the bio-computational keyword list. |

Every collected record becomes an **item** with: stable id, source, type (`published` / `preprint` / `code` / `industry`), title, url, DOI if any, published date, first-seen date, authors or org, raw abstract or description, and raw source metadata.

Dedupe rules: same DOI → same item; preprint and its published version → one item of type `published` with `preprint_url` kept; same normalized title within 30 days across sources → same item.

### 6.3 Enrichment

For each **new** item (not previously enriched), one LLM call plus one local embedding:

- **One-line summary** (≤ 160 chars) and **primary + secondary categories** from the taxonomy, produced in one LLM call with structured output. Model: **`claude-haiku-5-5`** (bulk extraction role). Requests are submitted via the **Message Batches API** (50% price) since latency does not matter.
- **Category classification is zero-shot by the LLM; no trained classifier.** The call receives the taxonomy (slug, label, "covers" text from §5), the item's title and abstract, and **source hints** as priors: bioRxiv category, arXiv primary category, journal name, GitHub topic tags. A config file maps common hints to likely categories (e.g. bioRxiv `Genomics` → `genomics`; arXiv `q-bio.BM` → `structural`; journal `Nature Methods` → `tools-infra` or `ml-ai`). The model returns exactly one `primary` and 0–2 `secondary` slugs; the structured-output schema restricts values to the taxonomy, so no post-hoc validation is needed. Cost at ~300 items/day: about USD 2/month. The owner reviewed the alternative (a classifier trained on embeddings) and chose zero-shot for simplicity.
- **Embedding** of title + abstract, computed locally in the Actions runner with a sentence-transformers model suited to scientific text (default `allenai/specter2_base`; builder may choose a comparable open model). No paid embedding API in v1.

Enrichment results are cached by item id so items are never re-processed.

### 6.4 Topics: clustering and continuity

- **Window**: items first seen in the last **7 days**.
- **Clustering**: agglomerative clustering on embeddings with a cosine distance threshold (config, default 0.35), minimum cluster size 3 items. Items that do not cluster are kept as items but produce no topic.
- **Continuity**: each cluster is compared to existing topics by centroid cosine similarity. If the best match is above a threshold (config, default 0.80), the cluster **continues** that topic (same slug, history extended). Otherwise a new topic is created with a new slug derived from its headline. This is what makes sparklines and "topic history" possible.
- Each topic's primary category is the majority primary category of its items.

### 6.5 Scoring and ranking

For each topic on a given day:

```
score = w1 · rise + w2 · diversity + w3 · code_velocity + w4 · volume
```

- `rise`: today's 7-day item count divided by the topic's mean weekly count over the preceding 4 weeks (floored at 1 to avoid division by zero). This is the main "trending" term.
- `diversity`: number of distinct evidence types present among {published, preprint, code, industry}, scaled to 0–1. A topic with papers and code and a company announcement ranks above one with only preprints.
- `code_velocity`: log of total 7-day star gain across the topic's code items, scaled.
- `volume`: log of total items, scaled (small weight; prevents tiny clusters from winning on rise alone).

Default weights `w1=0.45, w2=0.25, w3=0.15, w4=0.15`, in config. Top 5 by score are the day's topics. A topic that ranked yesterday gets a small penalty (config, default −5%) so the list rotates unless it genuinely keeps rising.

Every topic's component scores are stored so the About page's "how ranking works" can be honest and so weights can be tuned later against the archive.

### 6.6 Synthesis

For each of the Top 5, one LLM call produces, as structured output: `headline` (≤ 90 chars), `summary` (≤ 160 chars), `synthesis` (80–160 words), and, for any item whose enrichment one-liner reads poorly in the topic's context, a replacement `one_liner` (≤ 160 chars). Input: the topic's items (title, source, date, abstract or description, enrichment summary), its category, its signal counts, and yesterday's synthesis if the topic continued. Model: **`claude-opus-5-5`** with adaptive thinking (the default; do not set `budget_tokens`). The prompt forbids introducing facts not present in the items and asks for a tone suitable for expert readers.

**Operator notes**: a markdown file at `notes/<topic-slug>.md` is rendered as the Editor's note on that topic's page. Adding or editing a note and pushing to `main` triggers a site rebuild (no pipeline run). Nothing else is needed.

### 6.7 Data layout (git as the database)

```
data/
  computational/
    items/YYYY/MM/<item-id>.json      # one file per item; immutable after enrichment
    topics/<topic-slug>.json          # centroid, history [{date, rank, item_ids, scores}], current synthesis
    days/YYYY-MM-DD.json              # ranked top-5 slugs + scores + run metadata
    github_stars.json                 # repo → [{date, stars}] rolling 60 days
    embeddings.npy + embeddings.index.json   # float16 matrix + id→row map (LFS if > 50 MB)
notes/<topic-slug>.md
config/
  sources/computational.yaml
  taxonomy/computational.yaml
  scoring.yaml
```

The pipeline commits its output with a message like `data: 2026-11-02 run`. Expected growth is a few MB a month; if the repo exceeds ~1 GB or the build exceeds 10 minutes, migrate the store (SQLite or Cloudflare D1) — a known, later step.

### 6.8 Failure behaviour

- Any source failing (API down, rate limit) is logged and skipped; the run continues with the other sources. A run with **all** paper sources failing aborts without committing.
- If the LLM step fails for a topic, that topic is published with the headline derived from the enrichment summaries and no synthesis paragraph, and the run is marked `degraded` in the day file (shown as a small notice on the page).
- If the run fails entirely, nothing is committed and the site keeps yesterday's data. GitHub Actions emails the owner on failure (default behaviour).
- Idempotent: re-running the same day overwrites that day's outputs and never duplicates items.

### 6.9 Costs (estimate, to be verified by the builder with a dry run)

- Enrichment: ~300 new items/day × ~2k tokens in, ~150 out on Haiku 5.5 via Batches → about USD 2/month.
- Synthesis: 5 topics/day × ~25k tokens in, ~1.5k out on Opus 5.5 → roughly USD 15–20/month.
- Embeddings, hosting, scheduler, build: USD 0.
- Hard stop: the pipeline reads a monthly spend ceiling from config (default USD 50) and estimates spend from token usage returned by the API; when the estimate exceeds the ceiling it switches synthesis to Haiku 5.5 for the rest of the month and flags `degraded`.

### 6.10 Backfill (12 months before launch)

The site must not launch empty. Before the first scheduled run, a one-time **backfill** populates the archive with the preceding **12 months**, day by day, so that `/archive`, topic histories and sparklines are full on day one.

- **Mechanism**: the same pipeline, invoked with a date range (`--from 2025-11-01 --to 2026-11-01`). Days are processed **in chronological order** so topic continuity, sparklines and the yesterday-penalty behave exactly as they will going forward. Collection for the whole range happens first (one pass per source, date-bounded), then enrichment in a few large batches, then the per-day cluster/score/synthesize loop. The backfill must be resumable (it checkpoints after each stage and each day) and runnable either on the owner's machine or as a manually dispatched Actions job split into monthly chunks (Actions jobs are capped at 6 hours).
- **Source coverage in the backfill** differs by source and the day pages must not pretend otherwise:
  - bioRxiv, arXiv, PubMed: full coverage; all support date-range queries. Backfilling also improves preprint→published linking.
  - GitHub: no historical star counts from the API. Reconstruct daily star history from **stargazer timestamps** (`Accept: application/vnd.github.star+json`) for watchlist repos and topic-tagged repos with **< 40k stars**; skip larger repos. Releases are fully backfillable.
  - Industry RSS: feeds keep only recent entries; backfill is best-effort (whatever the feed returns) and otherwise skipped.
  - Consequence: historical days rank mostly on `rise`, `diversity` among paper types, and `volume`. Day files record `backfilled: true`, and the day page shows a one-line notice that code and industry signals are partial for that day.
- **Expected volume**: ~100k items. Local embedding of 100k items takes on the order of an hour on CPU; acceptable.
- **Cost (one-time, outside the monthly ceiling; builder verifies with a one-month dry run first)**:
  - Enrichment of ~100k items on Haiku 5.5 via Batches: ~USD 15.
  - Synthesis of ~1,825 topics (365 days × 5): on **`claude-opus-5-5` via Batches ~USD 120**; on `claude-haiku-5-5` ~USD 6.
  - **Owner to decide** which model synthesizes backfilled topics (see §14). Default if undecided: Opus via Batches, because historical topic pages are permanent and will be read.
- Backfill output is committed in monthly commits to keep diffs reviewable.

## 7. Site build and hosting

- **Framework**: Astro (static output). Pages are generated at build time from `data/`. Category filtering on the landing page is a small amount of client-side JS; everything else is zero-JS HTML.
- **Hosting**: Cloudflare Pages, connected to the GitHub repo, auto-deploying on every push to `main`. Free tier.
- **Scheduler**: GitHub Actions `schedule` cron, daily at 06:00 UTC, plus `workflow_dispatch` for manual runs. The workflow runs the Python pipeline, commits `data/`, and pushes; the push triggers the Pages build.
- **Secrets**: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN` (default), optional `NCBI_API_KEY` for higher PubMed rate limits. Stored as GitHub Actions secrets. Never in the repo.
- **Later**: Astro's Cloudflare adapter lets individual pages become server-rendered when search or accounts are needed, without a rewrite.

## 8. Repository layout

```
trendbio/
  pipeline/            # Python package; one module per stage; `python -m pipeline.run --domain computational --date YYYY-MM-DD`
  site/                # Astro project
  config/              # sources, taxonomy, scoring
  data/                # pipeline output (committed)
  notes/               # operator notes
  tests/               # pipeline unit tests with recorded fixtures; no network in tests
  .github/workflows/
    daily.yml          # scheduled pipeline run
  docs/superpowers/specs/  # this document and successors
```

## 9. Testing and verification

- Pipeline stages are unit-tested against recorded API fixtures (no live network in CI tests). Dedupe, clustering continuity and scoring each have tests with hand-built cases, including: preprint later published; same title from two sources; a cluster that should continue an existing topic vs. one that should start a new one; the "yesterday penalty".
- An end-to-end **dry run** mode fetches live data for one day, runs everything, and writes to a temp directory without committing, printing token usage and estimated cost. The builder runs this once before the first scheduled run and records the cost in the README.
- Site build is checked in CI on every PR (`astro build` must succeed against the committed data).
- Visual check: landing page and topic page screenshots at phone and laptop widths, reviewed by the owner before the first public deploy.

## 10. Decisions already made (owner's)

- Automated pipeline, no human writing. Owner may add notes.
- Daily cadence; Top 5 per day.
- Landing layout "B" (compact hero + card grid + category chips); topic page layout "1" (single column).
- Hero carries a DNA/protein motion graphic; overall tone minimal and clean.
- Evidence includes **published papers**, not only preprints.
- Category taxonomy as in §5.
- Trend signals: paper clustering, code velocity, source diversity, industry announcements. Social deferred.
- English only. Expert audience. Computational domain first, expandable.
- 12-month backfill before launch so the site is not empty.
- Category classification: LLM zero-shot (Haiku) with source hints, no trained classifier. Owner weighed a trained classifier and chose zero-shot at ~USD 2/month.

## 11. Decisions made by the planner (Claude) — owner may override

- Static site, Astro, Cloudflare Pages, GitHub Actions scheduler, git-as-database. Rationale: content changes once a day, zero cost, trivial to migrate individual pages to server rendering later.
- Python for the pipeline.
- LLM: `claude-haiku-5-5` for per-item enrichment via Batches; `claude-opus-5-5` for the five daily syntheses. Local open-source embeddings.
- USD 50/month LLM ceiling with automatic degradation.
- Scoring formula and default weights in §6.5.
- 7-day topic window; agglomerative clustering; continuity by centroid similarity.
- Operator notes as markdown files in the repo.
- Light theme only; one accent colour.

## 12. Left to the builder

- Exact Astro project structure, component split, CSS approach.
- Choice and implementation of the helix/backbone animation within the constraints in §4.5.
- Exact clustering library (scikit-learn is fine) and thresholds after inspecting a dry run; the defaults above are starting points.
- Exact prompts for enrichment and synthesis, subject to the constraints in §6.3 and §6.6 and the anti-goal on hallucinated evidence.
- Initial contents of the GitHub watchlist, journal list and RSS list beyond the examples given.
- Slug generation scheme and collision handling.
- How the day file records `degraded` and how the page shows it.
- Fixture recording approach for tests.

## 13. Open questions resolved during brainstorm

- *Is static enough?* Yes for v1; the list of things it cannot do (accounts, search, comments, real-time, newsletter) was reviewed and none are in v1.
- *Social signals?* Deferred; API cost and access issues.
- *Hosting?* None pre-existing; planner chose Cloudflare Pages.
- *Category classifier?* Trained-classifier option considered; owner chose LLM zero-shot given the ~USD 2/month cost (§6.3).

## 14. Open for the owner

- Which model synthesizes the ~1,825 **backfilled** topics: `claude-opus-5-5` via Batches (~USD 120 one-time) or `claude-haiku-5-5` (~USD 6). Default: Opus.
