# Tool names on Top 20 rows, and the last cut headline (TrendBio, `main`, /Users/jam/TrendBio)

The owner approved trying tool names under Top 20 headlines. Headlines stay as they are; this is display only. No LLM, no ranking change, no change to `data/`. Measured on real data: 88% of ranks 1-5 and 73% of ranks 6-20 have at least one paper titled "Name: description"; median 2 names per row.

Read: `site/src/lib/data.ts` (global index, item lookup), `site/src/lib/types.ts`, `site/src/lib/periods.ts`, `site/src/components/DayTopics.astro`, `TopicCard.astro`, `SharedList.astro`, `site/src/styles/global.css`, `site/src/pages/about.astro`, `site/tests/*`, `tests/test_run.py` (repair tests), `pipeline/run.py` (`synthesis_repair_targets`).

## A. Tool names (site only)
1. **Extraction**, at build time from stored item titles. For a row, use the `item_ids` of the topic's history entry for that day (papers only: type preprint or published). A title yields a name when it starts with a token of 2 to 25 characters that begins with a letter or digit and has no internal spaces, optionally followed by a version such as ` 2.0`, followed by optional spaces and a colon then a space. Regex to start from: `^\s*([A-Za-z0-9][\w.\-+]{1,24}(?:\s\d[\d.]*)?)\s*[::]\s`.
2. **Stoplist** in one exported constant, case-insensitive. Start with: Background, Objective, Purpose, Review, Introduction, Correction, Erratum, Commentary, Editorial, Perspective, Benchmarking, Benchmark, Evaluating, Harnessing, Deep, Machine, Single-cell, Spatial, Integrating, Towards, Toward, Comparing, Beyond, Decoding, Mapping, Unlocking, Leveraging, Multi-omics, Multiomics, Protein, Cancer, Genomics, Transcriptomics, Proteomics, Metabolomics, Epigenomics, Update, Editorial, Letter, Protocol, Methods. Then run the extraction on real `../data`, list the 80 most frequent names and a random 100, read them, extend the stoplist with obvious non-names, and estimate precision on the sample by hand. Put the lists and the estimate in `tests/evidence/tool-names-2026-11-06.md`.
3. **Selection:** ranks 1-20 only, at most 3 names per row, published papers first, then alphabetical; deduplicate case-insensitively. Rows with no name render exactly as they do now, with no empty space. Ranks 21-40 show none.
4. **Display:** one quiet line directly under the headline in both the featured rows and the compact rows, using existing muted tokens and small monospace text. No new colours, no emoji, no ALL CAPS. It may wrap on phones.
5. **Links:** each name links to its paper's URL in a new tab with `rel="noopener"`. Rows are currently whole-card anchors, and nested anchors are invalid HTML. Restructure to a stretched-link pattern (the card's main link covers the card through a pseudo-element; name links sit above it) so a click anywhere else on the card still opens the topic, keyboard order is sensible, and focus rings still show. If this cannot be done cleanly without breaking existing a11y or landing tests, render the names as plain text instead and say so in the evidence.
6. **Scope:** home and day pages. Include week and month pages only if they share the row component and a period row can use the topic's most recent history entry inside the period without new data; otherwise skip them and say so.
7. **About page:** one sentence saying the names are copied from paper titles and do not affect ranking.
8. **Performance:** do not read item files per row repeatedly; cache in the existing global index. `TRENDBIO_DATA_ROOT=../data npm run build` must stay under 10 seconds. Report the time before and after.

Tests in `site/tests/`: extraction cases (name with version, stoplisted word, spaces rejected, no colon); at most 3 and published first; rank 21 shows none; a row with no names has no empty element; built HTML has no anchor nested in an anchor; axe stays clean in both themes. Use fixtures under `site/tests/fixtures` and copy them in `site/tests/build.ts`. Do NOT add files to `fixtures/data/`.

Screenshots from the real-data build: `/` at 1280 and 390 wide, dark and light, into `site/.playwright-shots/`. Look at them.

## B. Last cut headline
`data/computational/days/2026-11-06.json` rank 19 ends in "…" at 112 characters. `repair-synthesis` only targets the old 91 and 161 length signature. Since the overrun retry now exists in the synthesis path, widen `synthesis_repair_targets` to target any row or topic headline or summary ending in "…", still skipping rows that carry a `synthesis-fallback:` note and show the item fallback. Update `test_repair_skips_new_limit_truncation` to the new rule, and keep a test that a repaired row is no longer a target. Report the `--dry-run` count on real `data/` for 2026-11-01..2026-11-06 (expected: a handful of jobs).

## Constraints
- Edit `site/**`, `pipeline/run.py`, `pipeline/__main__.py` if needed, `tests/**`, `README.md` (one line). Do not edit `data/`, workflows or prompts. No live LLM calls, no workflow dispatch, no new dependencies.
- Run BOTH suites and report both: `uv run --no-project --python 3.12 --with pydantic --with pytest --with numpy --with pyyaml --with respx --with httpx --with feedparser --with anthropic --with scikit-learn --with typer --with umap-learn python -m pytest -q`, and `cd site && npm test && npm run build`.
- Two commits on `main`: `feat(site): tool names under Top 20 headlines` and `fix: repair-synthesis targets any cut headline or summary`. Do not push (coordinator pushes).

## Evidence
- Both test summaries; build times; the evidence file path and precision estimate; whether names are links or plain text; which pages show them; screenshot paths; the dry count; `git log --oneline -3`.
