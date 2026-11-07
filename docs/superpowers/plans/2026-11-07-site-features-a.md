# Site features batch A: RSS, rank changes, link preview image, BibTeX, analytics note (TrendBio, `main`, work inside `site/`)

The owner approved these. No pipeline, LLM or ranking changes; nothing is written to `data/`.

Read: `site/src/layouts/Base.astro`, `site/src/lib/data.ts`, `site/src/lib/types.ts`, `site/src/lib/leaderboard.ts`, `site/src/lib/categories.ts`, `site/src/lib/tool-names.ts`, `site/src/components/TopicCard.astro`, `DayTopics.astro`, `EvidenceList.astro`, `site/src/pages/topic/[slug].astro`, `site/src/pages/sitemap.xml.ts`, `site/src/pages/about.astro`, `site/tests/*`, `site/tests/build.ts`.

## 1. RSS (Atom) feeds
- `/feed.xml`: ranks 1-5 of each of the latest 30 stored days, newest first.
- `/feed/<category-id>.xml` for each taxonomy category: that category's ranked rows (any rank) of the latest 30 days, at most 100 entries.
- Each entry: stable id `tag:trendbio.dev,<date>:<slug>`, title = headline, link = absolute topic URL, updated = the day's `run.finished` or the date, summary = row summary plus tool names when present. Escape XML correctly. Feed-level title, self link and updated.
- Served as `application/atom+xml` through Astro endpoints (no new dependency). Add `<link rel="alternate" type="application/atom+xml">` for `/feed.xml` in `Base.astro`, a footer link "RSS", and an About sentence listing the feed URLs. Exclude feeds from the sitemap.

## 2. Rank change markers
On home and day pages only, for every Top 40 row, compare with the previous stored day's Top 40 by slug:
- First time this topic has ever been ranked: label `New`.
- Absent from the previous day's Top 40 but ranked before: label `Back`.
- Present in both: `▲3` or `▼2`. Show nothing when unchanged.
- The first stored day shows nothing.
Keep it quiet: small muted text beside the rank or in the row's meta line, clearly separate from the existing rise badge (`↑ 2.4×`). Include screen-reader text such as "Up 3 places since the previous day". Do not use colour alone. Must fit compact rows at 320, 390 and 1280 wide without clipping.

## 3. Link preview image
One static image, `site/public/og.png`, 1200x630, under 200 KB: the TrendBio wordmark with the site's helix on the dark background, plus the line "What moved in computational biology". Generate it once from an HTML page with Playwright, commit the PNG, and keep the generator script under `site/scripts/`. In `Base.astro` add absolute `og:image`, `og:image:width`, `og:image:height`, `og:image:alt`, and change `twitter:card` to `summary_large_image`. No per-page images.

## 4. BibTeX export
For each ranked topic build `/topic/<slug>/citations.bib` from the papers in its evidence list (preprints and published): type `@article` or `@misc` for preprints, key `<firstauthorlastname><year><shortid>` kept ASCII and unique within the file, fields title, author (from stored authors, ` and `-joined), year, journal when stored, doi, url. Escape BibTeX specials. Topics with no papers produce no file. On the topic page add one link, "Export citations (BibTeX)", with a `download` attribute, shown only when the file exists. Exclude these from the sitemap.

## 5. Analytics note
Cloudflare Web Analytics is being enabled on the zone by the coordinator; no code is needed. Add one About sentence: the site uses Cloudflare Web Analytics, which sets no cookies, to count page views.

## Tests
Fixture-based, under `site/tests/`: feeds parse as XML, have stable ids, correct entry counts and category filtering, escape `&` and `<`; a `New`, `Back`, `▲`, `▼` and unchanged row each render correctly, and the first day shows none; `og:image` absolute and the file is 1200x630 and under 200 KB; BibTeX escapes specials, keys unique, no link when no papers; layout check at 320 and 390 wide has no overflow or clipping; axe stays clean in both themes. Put fixtures in `site/tests/fixtures`. Do NOT add files to `fixtures/data/`.

## Constraints
- Edit only inside `site/` and one README line. No new dependencies except what `site/scripts/` already can use (Playwright is present). Do not touch `data/`, `pipeline/`, workflows.
- Real-data build `TRENDBIO_DATA_ROOT=../data npm run build` must stay under 20 seconds; report before and after, plus total file count in `dist/`, which must stay under 15,000.
- Run BOTH suites and report both: `uv run --no-project --python 3.12 --with pydantic --with pytest --with numpy --with pyyaml --with respx --with httpx --with feedparser --with anthropic --with scikit-learn --with typer --with umap-learn python -m pytest -q`, and `cd site && npm test && npm run build`.
- One commit per numbered feature on `main`, messages starting `feat(site):`. Do not push (coordinator pushes). Do not dispatch workflows.

## Evidence
- Both test summaries; build times; file count; feed URLs and entry counts on real data; screenshots of rank markers at 390 and 1280 and of `og.png`; `git log --oneline -6`.
