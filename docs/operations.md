# TrendBio operations

## Daily run and triggers

The recommended daily trigger is the [Cloudflare Worker in `ops/daily-trigger/`](../ops/daily-trigger/),
which dispatches the Daily pipeline at 06:05 UTC after checking for an active run
or a success created today (UTC). Enable it with one GitHub token secret using
the linked setup instructions; keep GitHub's `schedule` as backup because its
runs can arrive hours late.

GitHub Actions runs the computational biology, Physics and All Biology editions daily at 05:23 UTC with fallbacks at 08:41 and 12:17 UTC.
Each workflow uses its creation date in UTC for every field, including GitHub reruns. A manual dispatch can specify a different edition date. Collection, coverage checks and the data commit use that same date across midnight. Each scheduled fallback checks the stored edition for that field and retries missing editions and failed paper sources.
Each successful field commits under `data/<domain>/`. Failed runs leave the last published edition available.
GitHub Actions builds and deploys the Astro site to Cloudflare Pages on pushes to `main` and after Daily pipeline, Backfill, Resynthesize or Maintenance completes via `.github/workflows/deploy.yml`.
The site is served at https://trendbio.dev (and https://trendbio.pages.dev).

### Website and local preview

The site, Atom feeds and downloadable editions use English. Each public field has a daily Top 5 feed and a feed for each category. The footer links to the current field’s Top 5. The About page lists the category subscriptions. Cloudflare Pages redirects former `/ko/` links to the corresponding English paths. The website build uses Node 22. [CompBio feed](https://trendbio.dev/feed.xml) · [All Biology feed](https://trendbio.dev/biology/feed.xml) · [Physics feed](https://trendbio.dev/physics/feed.xml)

An editor can withdraw a ranking from a downloadable pilot when its studies do not support a common result. Record the edition date, topic slug, exact headlines, full list of paper IDs and an English reason in `notes/<domain>/withdrawals.json`. For a decision about the eligibility of the source papers themselves, record an English reason and a `source_versions` object mapping every paper ID to its reviewed version URL. That decision follows the same set into later editions only while every ID and version URL matches. The export checks the original ranking and citations, then shows the reason at the original rank.

```sh
cd site
npm ci
TRENDBIO_DATA_ROOT=../data TRENDBIO_NOTES_ROOT=../notes npm run build
npm run preview
```

Configure the `ANTHROPIC_API_KEY` Actions secret and optionally `NCBI_API_KEY`;
Actions supplies `GITHUB_TOKEN`. Keep keys out of committed files.
The daily workflow accepts a field, an optional `date` and a `dry_run` switch. The manual field workflow runs the science pilots listed in the [field directory](https://trendbio.dev/fields/). Selected reading copies appear on the public site after review. It has read-only repository access. Each artifact contains the dated rank, source records, review decisions and the model usage ledger. Signed-in readers of this public repository can download artifacts during the 14-day retention period. [GitHub artifact access](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts) Select `audit` with a previous run ID for a review without model calls. The expanded Physics pilot now queries 47 arXiv subjects. The workflow renders the requested date and checks each rank, headline, short summary and supporting paper link against the stored edition. Download the reading copy from the run summary, extract it and open `en.html` in a browser. Use `audit` to regenerate an existing issue without model charges. For missing summaries, `repair-summaries` defaults to Haiku. Select Sonnet to retry a dated summary that repeatedly fails validation. Store source-checked corrections beside the affected summary in `notes/<domain>/<date>/<topic-slug>.md`. The two public beta audits accumulate the first 14 live dates under `data/<domain>/audits/first-14.json`. [Field pilot workflow](../.github/workflows/field-pilot.yml)

The manual [field placement check](../.github/workflows/field-placement.yml) runs the production Computer Science classifier on the versioned arXiv papers in the review protocol. It verifies the source text and archive labels against the original trial before calling the model. The results artifact records the assignments, unavailable decisions and model cost by run.

Select `rank-28d` in the field pilot to screen, group, rank and summarize a 28-day publication window. Start with an empty store or restore the preceding 28-day issue. Each run saves its evidence window with the edition. The audit compares the same eligible records over four weeks and over the full period. The English reading copy shows both dates. The `rerank`, `replay` and `audit` actions retain the original window. For a local independent trial, run `python -m pipeline run --domain earth-environment --window-days 28 --date 2026-07-22 --data-root science-pilot`.

On the main branch, Computer Science and Mathematics ranking jobs run in sequence within each field and retain their classification and cohesion decisions in a separate 90-day artifact. Each job restores the newest available decision set by its creation time from this repository's manual field workflow. If older snapshots have diverged, it merges their receipts and preserves the earliest retained decision for each request. The resulting `lineage.json` lists the source runs. The normal source collection, topic history, scoring and ranking still use the selected parent store. An exact request can reuse a decision across parents. A change to the source text, effective hints or inclusion guidance triggers fresh classification. A provider refusal withholds the paper for that request. A temporary failure withholds it until classification succeeds. The dated `audits/screening-YYYY-MM-DD.json` file reports requests, reuse and unavailable papers. Historical `replay` uses the selected edition's stored inputs. An expired or missing decision set can require fresh model calls.

Use these commands from the repository root to reproduce the metadata and window comparisons. The window trial embeds titles and abstracts locally. The seven-day and 28-day results count candidate groups before editorial screening.

```sh
python -m pipeline survey --domain chemistry --to 2026-11-18
python -m pipeline trial-windows --domain astronomy --to 2026-11-18
python -m pipeline trial-windows --domain computer-information --to 2026-11-18
python -m pipeline trial-windows --domain engineering --to 2026-11-18
python -m pipeline trial-windows --domain agriculture-food-veterinary --to 2026-11-18
python -m pipeline trial-windows --domain medicine-health --to 2026-11-18
python -m pipeline audit-beta --domain biology --to 2026-11-19
```

Agricultural publisher records keep the publication date, DOI, original language and the language of the author-supplied abstract. The collector checks reuse terms as of the edition date. Three Czech journals also supply missing abstracts on article pages matched by DOI, ISSN and date. [Coverage and historical edition checks](expansion-measurements/2026-11-19/applied-pilots.json)

Medicine uses Europe PMC first-publication dates and checks the source article and its reuse terms in PMC or in licensed publisher deposits in Crossref. Medical notices link to the original record. Later integrity updates can exclude a paper from the next ranking while retaining its dated history. [Health source checks](expansion-measurements/2026-11-19/health-social-pilots.json)

The Computer Science pilot collects regular ECRTS systems papers from the publisher’s LIPIcs volume. For IHM 2026 it matches ACM’s main proceedings to the conference collection in HAL. It dates each work by online publication, checks both article and deposit licenses, and selects an author-supplied title and abstract in the same language. Versioned HAL deposits and the date source are linked in the English reader.

The on-demand expanded Physics workflow accepts `rank-announced` for a comparison against the standard submission-date edition. It reads every page of the Physics group’s daily arXiv mailings and retrieves version 1 by identifier for new and cross-listed works. The evidence window uses the mailing date. Each retained item also records the author’s original submission date. Only papers in the configured subjects proceed to the usual screening and ranking. The dated file stores each mailing’s counts, including replacements and days with no announcements. arXiv provides this daily archive for the past 90 days. Start this comparison in a fresh pilot store. Subsequent runs from its saved artifact retain the same date basis, and `replay` or `audit` can use the saved collection after the daily lists expire. [Daily mailings](https://arxiv.org/catchup) · [Versioned arXiv metadata](https://info.arxiv.org/help/api/user-manual.html#511-a-note-on-article-versions)

The pilots partition every candidate into specific shared research problems or phenomena. An exact source passage supports each assignment. Engineering and expanded Physics verify the reported result for each proposed member in a second review. In expanded Physics, a conference or review note together with an abstract describing a recap or companion work triggers an originality check. The note comes from the matching archived arXiv record. Its supporting passage still comes from the title or abstract. The dated topic stores the confirmed question, supporting passages and the ID of the review used for its English summary. A changed review refreshes the summary on replay. Groups meeting the configured minimum enter the shared ranking. The dated audit records smaller groups and review failures separately. To measure the cost of the next edition, use `rank` with the previous UTC day's pilot run ID. This restores the item cache and ledger before collecting the next day's papers. Use `rerank` to collect any additional source records and reassess the same date. Use `replay` to compare editorial changes on the latest saved edition with exactly its original source records, enrichment and collection statuses. Expanded Physics includes the atomic physics and atomic and molecular clusters subjects. Its control editions queried sixteen subjects and its expanded editions query eighteen. Dated editions store the arXiv subjects queried at collection. The expanded Physics reader shows each subject’s primary submissions, cross-listed papers and distinct papers cited by a rank in the stored window. An editorial replay uses the stored scope. Older editions label the available source list as current coverage. The expanded Physics trial also reads CC BY articles from Physical Review A and B through Crossref. It independently checks the physical question in each proposed group against every paper. Accepted groups keep the confirmed question with their dated history for the original summary and any later repair. The date-specific source list identifies which runs included journal articles. An editorial correction can specify its original English claim and supporting paper IDs in Markdown front matter using `claim` and `papers`. The edition shows the correction while the claim and evidence still match. A correction in `notes/<domain>/shared/` follows an exact claim and paper set across dates and topic slugs. A matching dated correction takes precedence. Chemistry follows the journals in its [source configuration](../config/sources/chemistry.yaml). An article needs a precise publication date and a current CC BY licence for the published version. For Analytical Sciences and Analytical and Bioanalytical Chemistry, a missing registry abstract can come from a PubMed record matching the DOI, title, ISSN and electronic publication date. The edition links the indexed abstract. A lookup outage marks collection as partial. Earth samples the journals in its [source configuration](../config/sources/earth-environment.yaml). The hydrology journal contributes research articles and technical notes after matching its XML publication date, DOI, ISSN and licence. For Frontiers in Conservation Science, publisher XML supplies the genre, final electronic publication date, DOI, ISSN and licence. Both the article type and the journal’s genre heading must identify an original contribution or brief research report. For PLOS Climate, PLOS Water, Nature Conservation and One Ecosystem, the publisher page must confirm the DOI, ISSN, date and article type. These journals contribute research articles, short communications and data papers under CC BY or CC0. The Earth edition lists the journals represented in that date’s collection and links confirmed DataCite datasets. The chemistry source survey counts ChemRxiv revisions and journal links separately. [Measured pilot coverage](science-expansion-plan.en.md)

The Mathematics and Statistics pilot combines 36 arXiv subjects with five journals listed by ISSN in its source configuration. The Crossref collector selects articles with a precise publication day, a usable abstract and an active CC BY license for the version of record. A dated edition lists the journals represented in that week's collection. [Configured journals](../config/sources/math.yaml) · [Intake and editorial checks](expansion-measurements/2026-11-20/math-journals-and-proofs.json)

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
Use `--no-reenrich --only-missing-synthesis` to extend existing days with their
stored evidence and topic identities. When replaying an older edition, the pipeline
reuses a headline and summary from that date or an earlier ranked edition whose
supporting items and reviewed findings still apply. A topic whose only copy comes
from a later edition needs a new synthesis for the earlier date. The newer
edition keeps its published copy. The workflow option is `only_missing_synthesis`
(default false).

For a full continuity rebuild, pass `--rebuild-topics`: it removes every topic's
history in the requested months, deletes topics left empty, and clears synthesis
only for topics whose entire history is inside the range before replaying days
chronologically. Items and embeddings remain cached. Combine with `--only-missing-synthesis` to synthesize new
topics with the backfill model (Haiku) and reuse dated copy when its evidence
still applies. Rebuild the entire affected date
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

The Public edition operations workflow reads the stored editions on `main` and the GitHub Actions job records after each daily workflow. To reproduce the full report, authenticate the GitHub CLI with Actions read access and run `python -m pipeline audit-operations --actions-repo jam-sudo/TrendBio --to 2026-11-20`. Supply `--from` to change the default 30-day window. Omit `--actions-repo` to inspect the local edition files offline. Each field and date has its publication status, source issues, elapsed time and recorded model cost. A missing edition can include dates before a field launched. [Workflow and JSON download](https://github.com/jam-sudo/TrendBio/actions/workflows/public-operations.yml)

A live edition starts on its edition date in UTC. Backfills and later reconstructions have their own labels. The saved edition clock measures the first regular run through its write stage. The workflow table adds up the duration of every live `Run pipeline` step, including retries. Setup, time between jobs and deployment fall outside that clock. Each job links to its source and records its pipeline and commit outcomes. The November 20 CompBio jobs took 12 minutes 22 seconds and 10 minutes 9 seconds. The retry recovered arXiv. [First attempt](https://github.com/jam-sudo/TrendBio/actions/runs/44685310579/job/136118123516) · [Retry](https://github.com/jam-sudo/TrendBio/actions/runs/44695057089/job/136149714149)

Model costs use the ledger’s token rates. The stored edition includes metered reruns saved for that date. An unsuccessful save can incur a further charge. The report adds a measured charge when the ledger comparison shows it is missing. A pending job makes its date provisional. If an amount still cannot be reconciled once the jobs finish, the date stays out of the projection. This affected the November 4 CompBio edition, where the first run reached the model and its commit failed. The 30-day estimate uses the latest 14 shared live dates with attributable costs, including degraded editions. The expansion plan records on-demand pilot costs separately. [Failed November 4 save](https://github.com/jam-sudo/TrendBio/actions/runs/41838755968/job/126685919118) · [November 20 service measurement](expansion-measurements/2026-11-20/public-operations.json)

Hosted dry run on 2026-11-02 (GitHub Actions `ubuntu-latest`, 7-day window, 1,196 new items, 164 topics):

| Stage | Result |
|---|---|
| Wall time | 16 min including setup (collect 4.7 min, enrich 3.4 min, embed 4.5 min, synthesize 56 s) |
| Haiku 5.5 (enrichment) | 1.96M input / 124k output tokens |
| Opus 5.5 (5 syntheses) | 17.5k input / 5.1k output tokens |
| Estimated cost | USD 0.43 for the run; a steady-state day (~170 new items) is lower, so roughly USD 10-15/month |
| Enrichment fallbacks | 10 of 1,196 (5 `refusal:bio`, 4 `empty_output`, 1 `validation`) |

The initial Top 40 planning estimate was about USD 0.50 per day for five Opus, 15 Sonnet and 20 Haiku syntheses. Actual usage depends on evidence length. Each field switches model tiers at USD 55 in monthly model usage. The service-wide monthly budget will be chosen from pilot measurements.

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

## Publishing a dated science pilot

Build the site with the downloaded pilot store as `TRENDBIO_DATA_ROOT` and the reviewed notes as `TRENDBIO_NOTES_ROOT`. From `site/`, run the existing English reading-copy check with its optional fourth argument to retain the reviewed article on the site.

```sh
node scripts/pilot-preview.mjs dist "$TRENDBIO_DATA_ROOT/$field/days/$date.json" "$preview_dir" "pilot-editions/$field/$date.html"
```

The check compares the original ranks and ordered paper links and applies editorial withdrawals before writing either copy. Commit the dated article after review. The field overview and sitemap discover it on the next build. The dated article keeps its original source scope when the field later expands.
