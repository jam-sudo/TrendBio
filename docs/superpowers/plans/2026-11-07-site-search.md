# Site search with Pagefind (TrendBio, `main`, work inside `site/`)

Start only after batch A has landed. The owner approved search. Static site: use Pagefind (new dev dependency approved for this task only), which builds a chunked index after `astro build` and loads it lazily in the browser.

Read: `site/package.json`, `site/src/layouts/Base.astro`, `site/src/pages/topic/[slug].astro`, `site/src/pages/about.astro`, `.github/workflows/deploy.yml`, `.github/workflows/ci.yml`, `site/tests/*`.

## Change
1. `npm run build` runs `astro build && pagefind --site dist`. Confirm `deploy.yml` uses that script, and adjust the workflow only if it does not.
2. Index topic pages only: `data-pagefind-body` on the topic page's main content so headline, summary, synthesis, paper titles and tool names are searchable. Filter by category with `data-pagefind-filter`. Do not index day, week, month, map or about pages.
3. New page `/search/`: one labelled search input, results listing headline, category and a short excerpt, linked to the topic. Support `/search/?q=term`. Style with existing tokens, no Pagefind default theme. Empty state explains what is searched. Without JavaScript the page says that search needs JavaScript.
4. Add "Search" to the main navigation. Load Pagefind only on `/search/`; other pages must ship no extra JavaScript for this.
5. Exclude `/search/` from the sitemap and mark it `noindex`.

## Tests
Build-based Playwright test on the fixture site: a search for a known fixture headline word returns that topic; a nonsense query shows the empty state; `?q=` prefills and runs; category filter narrows results; axe clean in both themes; no horizontal overflow at 320 and 390; the home page requests no pagefind file.

## Constraints
- Edit inside `site/`, and `.github/workflows/*` only if the build script is not used. One new dev dependency: `pagefind`. Do not touch `data/` or `pipeline/`.
- Real-data build must stay under 60 seconds; report before and after, the index size, and the total file count in `dist/`, which must stay under 18,000 (Cloudflare Pages allows 20,000).
- Run BOTH suites and report both: the standard uv pytest command from the README, and `cd site && npm test && npm run build`.
- Commit on `main` as `feat(site): topic search`. Do not push (coordinator pushes). Do not dispatch workflows.

## Evidence
- Test summaries; build time; index size; file count; a screenshot of real results for "perturbation"; `git log --oneline -2`.
