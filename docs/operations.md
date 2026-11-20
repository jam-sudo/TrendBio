# TrendBio operations

## Daily run and triggers

The recommended daily trigger is the [Cloudflare Worker in `ops/daily-trigger/`](../ops/daily-trigger/),
which dispatches the Daily pipeline at 06:05 UTC after checking for an active run
or a success created today (UTC). Enable it with one GitHub token secret using
the linked setup instructions; keep GitHub's `schedule` as backup because its
runs can arrive hours late.

GitHub Actions runs the computational biology, Physics and All Biology editions daily at 05:23 UTC with fallbacks at 08:41 and 12:17 UTC.
Each fallback checks the stored edition for that field. Missing editions and failed paper sources are retried.
Each successful field commits under `data/<domain>/`. Failed runs leave the last published edition available.
GitHub Actions builds and deploys the Astro site to Cloudflare Pages on pushes to `main` and after Daily pipeline, Backfill, Resynthesize or Maintenance completes via `.github/workflows/deploy.yml`.
The site is served at https://trendbio.dev (and https://trendbio.pages.dev).

### English and Korean editions

The existing paths serve English. Add `/ko` before the path to read the same edition, date or topic in Korean. The language links preserve the search query and section. Both languages use the same stored rankings, evidence and paper links. Search indexes the two languages separately. [English](https://trendbio.dev/) · [한국어](https://trendbio.dev/ko/)

The static build uses reviewed interface labels in `site/i18n/ko.json`, editorial corrections in `ko-reviewed.json` and the compressed archive of translations in the same directory. For new text it runs Helsinki-NLP OPUS-MT locally on the build runner. Deployment caches the model and new translations under `~/.cache/trendbio/`. The translator has no paid API dependency. [Model and attribution](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-ko)

For a local preview of both editions, use Python 3.12 and the project's Node 22 version. From the repository root run the following commands.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r site/scripts/translation-requirements.txt
cd site
npm ci
TRENDBIO_DATA_ROOT=../data TRENDBIO_NOTES_ROOT=../notes npm run build
npm run preview
```

The first build that encounters new text downloads and verifies the original model. A failed translation stops the build before publication.

Configure the `ANTHROPIC_API_KEY` Actions secret and optionally `NCBI_API_KEY`;
Actions supplies `GITHUB_TOKEN`. Keep keys out of committed files.
The daily workflow accepts a field, an optional `date` and a `dry_run` switch. An independent manual workflow runs pilot editions outside the public website in Math & Stats, Earth observations, Chemistry, stellar and galactic astronomy, Computing & Information, Engineering, Agriculture/Food/Veterinary Science, Medicine & Health, Economics & Psychology, and Humanities & Arts. It has read-only repository access. Each artifact contains the dated rank, source records, review decisions and the model usage ledger. Signed-in readers of this public repository can download artifacts during the 14-day retention period. [GitHub artifact access](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts) Select `audit` with a previous run ID for a review without model calls. The same workflow includes a broader Physics trial across 16 arXiv archives. Its English and Korean reading copies, like those of every pilot, render from one dated result. Download the second artifact linked in the workflow summary, extract the ZIP and open `ko.html` or `en.html` in a browser. The copies work from disk, switch languages at the same topic and retain the original research links. The build checks each rank against the stored edition and compares the ordered evidence links. Auditing an existing run can generate a reading copy without model charges. A source-checked correction in `notes/<domain>/<date>/<topic-slug>.md` appears beside the affected summary in both languages. Include its reviewed Korean text in the translation catalogue. The two public beta audits accumulate the first 14 live dates under `data/<domain>/audits/first-14.json`. [Field pilot workflow](../.github/workflows/field-pilot.yml)

Use these commands from the repository root to reproduce the metadata and window comparisons. The window trial embeds titles and abstracts locally. The seven-day and 28-day results count candidate groups before editorial screening.

```sh
python -m pipeline survey --domain chemistry --to 2026-11-18
python -m pipeline trial-windows --domain humanities-arts --to 2026-11-18
python -m pipeline trial-windows --domain astronomy --to 2026-11-18
python -m pipeline trial-windows --domain computer-information --to 2026-11-18
python -m pipeline trial-windows --domain engineering --to 2026-11-18
python -m pipeline trial-windows --domain agriculture-food-veterinary --to 2026-11-18
python -m pipeline trial-windows --domain medicine-health --to 2026-11-18
python -m pipeline trial-windows --domain social-sciences --to 2026-11-18
python -m pipeline audit-beta --domain biology --to 2026-11-19
```

Agricultural publisher records keep the publication date, DOI, original language and the language of the author-supplied abstract. The collector checks reuse terms as of the edition date. Three Czech journals also supply missing abstracts on article pages matched by DOI, ISSN and date. [Coverage and historical edition checks](expansion-measurements/2026-11-19/applied-pilots.json)

Medicine uses Europe PMC first-publication dates and checks the source article and its reuse terms in PMC or in licensed publisher deposits in Crossref. Medical notices link to the original record. Later integrity updates can exclude a paper from the next ranking while retaining its dated history. Economics and Psychology combines arXiv and eight journals with the World Bank Policy Research Working Papers collection. Its records retain the report number, version links and individual reuse terms. [Independent source checks and pilot artifacts](expansion-measurements/2026-11-19/health-social-pilots.json)

Humanities and Arts combines licensed journal records with OpenEdition author and publisher metadata and Thoth book descriptions. The pilot matches editions by DOI or ISBN, title and date. A later catalogue upload or a new translation can describe an older work. A temporary failure in a book-date lookup marks the source partial and keeps verified works available. The trial command requires a complete lookup before reporting window sizes. Both language editions retain original titles when needed and distinguish catalogue rights from book or article rights. [Book and journal coverage](expansion-measurements/2026-11-19/humanities-pilot.json)

The pilots partition every candidate into specific shared research problems or phenomena. An exact source passage supports each assignment. Groups meeting the configured minimum enter the shared ranking. The dated audit records smaller groups and review failures separately. To measure the cost of the next edition, use `rank` with the previous UTC day's pilot run ID. This restores the item cache and ledger before collecting the next day's papers. Use `rerank` to reassess the same edition. The expanded Physics trial also reads CC BY articles from Physical Review A and B through Crossref. The date-specific source list identifies which runs included journal articles. An editorial correction can specify its original English claim and supporting paper IDs in Markdown front matter using `claim` and `papers`. Both language versions show that correction while the claim and evidence still match. Earth and Chemistry each sample five journals and admit records with an exact date, an abstract and a current CC BY version-of-record licence. Earth also links confirmed DataCite datasets. The chemistry source survey counts ChemRxiv revisions and journal links separately. [Measured pilot coverage](science-expansion-plan.ko.md)

## Sources

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

GitHub discovery excludes forks and repos below `github.min_stars_for_discovery` (20 stars); explicit watchlist entries bypass these filters.
Discovered repos with matching normalized descriptions and variant names, or identical descriptions and fewer than 50 stars, collapse to the most-starred copy; collection logs report `collapsed=<n>`.

## Clustering, attachment and continuity

Paper clusters use SPECTER2 (`allenai/specter2_base`) embeddings and complete linkage at cosine distance 0.10, with at least three papers.
Each relevant code/industry item attaches to only its nearest paper centroid when cosine
similarity reaches `attach_min_similarity` (0.94; [calibration](../tests/evidence/code-industry-2026-11-05.md)).
Attached IDs are stored separately in `attached_item_ids` (empty for older histories),
contributing evidence, diversity and code velocity without changing paper centroids,
counts, rise, volume or continuity. Unattached items do not rank. Home and day pages
also show up to eight relevant industry items first seen in their trailing seven days,
newest first, whether attached or not; the Industry chip is omitted when no topic uses it.
These changes apply to future runs; existing daily results are not rewritten.

Topic continuity requires a history entry within ±10 days (`continuity_max_gap_days`),
including when backfilling older months. A cluster continues a topic if its paper IDs
have Jaccard overlap ≥0.25 (`continuity_min_jaccard`) with the adjacent seven days of
that topic's history, or centroid cosine similarity ≥0.95 (`continuity_threshold`).
Matches are assigned by overlap first, then similarity, with at most one cluster per
topic per day. The centroid and categories track today's cluster; keyword slugs stay
stable. Empty history entries fill gaps of at most 10 days between appearances;
inactive topics stop accumulating history, and a later return starts a new topic.

## Selection, tiers and synthesis

The Top 40 reserves `category_floor` (default 1) topic per represented primary category,
then fills by score up to `max_per_category` (default 8) per category; sparse days can have fewer than 40.
The selected topics are ranked by score. The first `featured_n` (default 5) get full rows
and Opus synthesis; ranks 6–20 get compact rows and Sonnet synthesis, and ranks 21–40
get compact rows and Haiku synthesis. The first `display_open_n` (default 20) rows
are visible; “Show more” reveals the rest. `synthesis_tiers` sets the model boundaries.
Backfill and reprocessed history use `backfill_synthesis_model` (Haiku) for every tier;
over-ceiling runs always use Haiku.

## Shared by researchers (Bluesky)

The manual [Bluesky attention probe](../.github/workflows/bluesky-probe.yml) uses `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` to report aggregate attention for `days` (default 7), ending on the latest stored day, without changing rankings or data.

“Shared by researchers” is a display-only list below “From code” on home and day
pages; it never changes rankings or scores and makes no LLM calls. Daily runs with
`BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` sweep six paper hosts on Bluesky in UTC
day slices over seven days, excluding accounts linking 20 or more distinct paper
IDs in that window. Relevant stored papers need at least five likes + reposts +
quotes; the pipeline stores the top 20 and the site shows up to eight, including
papers outside the Top 40. Authors may be promoting their own work. Settings live
under `attention` in `config/scoring.yaml` (800 search calls maximum by default).
Only aggregate counts, paper IDs and per-host coverage go into
`data/computational/attention/<date>.json`; social identities, post content and
credentials are never written. Missing credentials or failures leave daily status
unchanged, with no file or `partial: true` when results exist. Partial sweeps may
miss high-volume accounts. Backfills, reprocessing, repairs and dry runs skip this
optional stage; missing attention data simply hides the section.

## Degraded days and repair

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

## Workflows and concurrency

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

## Editor's notes

Add Markdown at `notes/<slug>.md`, using the slug from the topic URL, and push
to `main`. The site rebuild displays it as the topic's Editor's note; no
pipeline run is needed. A note for an unknown slug produces a build warning.

The development server uses synthetic fixtures. To build against real output,
run from `site/`:

```sh
TRENDBIO_DATA_ROOT=../data TRENDBIO_NOTES_ROOT=../notes npm run build
```

## Sponsors

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

## Measured costs

Hosted dry run on 2026-11-02 (GitHub Actions `ubuntu-latest`, 7-day window, 1,196 new items, 164 topics):

| Stage | Result |
|---|---|
| Wall time | 16 min including setup (collect 4.7 min, enrich 3.4 min, embed 4.5 min, synthesize 56 s) |
| Haiku 5.5 (enrichment) | 1.96M input / 124k output tokens |
| Opus 5.5 (5 syntheses) | 17.5k input / 5.1k output tokens |
| Estimated cost | USD 0.43 for the run; a steady-state day (~170 new items) is lower, so roughly USD 10-15/month |
| Enrichment fallbacks | 10 of 1,196 (5 `refusal:bio`, 4 `empty_output`, 1 `validation`) |

Planning estimate for Top 40: 5 Opus + 15 Sonnet + 20 Haiku syntheses/day ≈ USD 0.50/day
(about USD 15/month), within the USD 55 monthly ceiling; actual usage depends on
evidence length. History stays on Haiku for cost control.

## Backfill and wipe

The manual backfill workflow takes inclusive `from` and `to` dates in
`YYYY-MM-DD` format, with `resume` enabled by default. Run monthly chunks;
each successful invocation commits its output once.
Historical star velocity is unavailable because GitHub restricted the stargazers endpoint, so backfilled days lack historical star velocity but can still include GitHub releases; daily runs accumulate star counts from launch (2026-11-02) onward.
Set optional `chain_until` (`YYYY-MM-01`) to automatically backfill previous months through that month, inclusive, after each successful run; failures stop the chain.
Daily and backfill processing steps have limits of 30 and 350 minutes, respectively.
The manual resynthesize workflow rewrites ranked-topic and day syntheses for inclusive `from`/`to` dates (`YYYY-MM-DD`) using `claude-haiku-5-5` (default) or `claude-opus-5-5` for the featured tier and always Haiku for ranks 6–40, shares the `pipeline` concurrency group, and commits changed data with a 120-minute processing limit.

To re-run a backfilled month after a collection fix, wipe that whole month before backfilling it again:

```sh
python -m pipeline wipe --domain computational --from 2026-10-01 --to 2026-10-31 --data-root data
```
