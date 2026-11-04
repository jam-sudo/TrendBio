# Site build performance

Measured on 2026-11-04 on the local macOS arm64 laptop, Node v26.7.0. The baseline was commit `85e6d00e5` (`feat(site): sponsor slots beside the hero`). Both real-data builds used `/usr/bin/time -p npm run build` from `site/`, with the default `../data` and `../notes`; builds ran sequentially.

| Build | Wall time | Astro build time | HTML pages |
| --- | ---: | ---: | ---: |
| Before | 555.47 s | 554.84 s | 689 |
| After | 1.87 s | 1.31 s | 689 |
| After, synthetic 3,000-topic expansion | 4.30 s | 3.91 s | 3,437 |

The real dataset contained 262 topic records, 45,817 item files, and 365 days. Its output contained 252 topic pages, 365 day pages, 53 week pages, 12 month pages, and seven other HTML pages. SHA-256 comparison of every emitted file found **705 identical files, zero changed, zero added, and zero removed**. Real topic rendering dropped from 2.16–2.35 seconds per page to 0–2 milliseconds. Wall time improved about 297 times.

The synthetic measurement retained every original record and added 2,748 ranked topic copies, cycling through real topic histories and evidence IDs. It reused the real item/day/map stores and rendered 3,000 topic pages plus the same 437 other pages. This checks page-count scaling, not a separately rebuilt dataset with a different item distribution. Its command was `TRENDBIO_DATA_ROOT=.build-perf-scale/data /usr/bin/time -p npm run build -- --outDir .build-perf-scale/dist`; temporary stress inputs and outputs were removed afterward.

## Implementation

`data.ts` now holds a lazy global cache keyed by absolute data root, domain, and notes root. It loads days, topics, rankings and map data once, walks item filenames once, resolves topic/day lookups through maps, and caches taxonomy, note HTML (including missing notes), and orphan-note results. Item lookup follows the pipeline's filename encoding and reads only requested files. Ambiguous filenames across month shards are resolved by stored ID during indexing, retaining distinct IDs and the last shard's copy of a repeated ID.

`periods.ts` shares memoized week/month lists, history indexes and rankings across module evaluations; rankings are keyed by history dataset, boundaries and taxonomy. `period-data.ts` likewise reuses the assembled periods. The existing topic route already passed topic objects through props; its related-topic loader now uses the cached slug map, so page/component changes were unnecessary.

The real-data build logged exactly one index construction: `[data-index] computational built #1 in 232ms`. The stress build also constructed it once, in 659ms.

## Validation

- `npm test`: **11 test files passed; 93 tests passed**, in 11.33 seconds. All original 88 tests remain unchanged.
- Five new tests in `tests/build-perf.test.ts` cover the fixture build's single index construction, reuse across module evaluation, one item-directory walk without reading item bodies at startup, bounded item reads with no glob/rescan, colliding filenames and repeated IDs, and period-cache isolation.
- `node node_modules/typescript/bin/tsc --noEmit`: passed.
- `git diff --check`: passed.

GitHub Actions and its configured Node 22 runtime were not measured locally; no push or workflow run was performed. Caches intentionally snapshot inputs for the process lifetime: restart the dev/build process after changing data, notes or taxonomy. Live cache invalidation is outside this change.
