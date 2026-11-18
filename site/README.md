# TrendBio site

Use Node 22.23.4 or newer in the Node 22 series. Run `npm ci`, `npx playwright install chromium`, and `npm test`.
The tests build the fixture data and serve `dist/` locally through Astro preview
for headless Chromium and axe checks. If Chromium is missing, the suite attempts
installation and skips browser checks with a warning only if installation fails;
launch errors and accessibility failures fail the suite. On Linux, install
Chromium's system libraries with `npx playwright install --with-deps chromium`.

Build the fixture pages with:

```sh
TRENDBIO_DATA_ROOT=../fixtures/data TRENDBIO_NOTES_ROOT=../fixtures/notes npm run build
```

## Known audit findings

On 2026-11-18, the Astro 7.4.12 upgrade cleared the critical Astro advisory.
The remaining npm audit entries trace to [picomatch](https://github.com/advisories/GHSA-fc5q-39xc-vjpf).
Version 4.0.7 is affected and there is no patched npm release as of this date.
The site uses build-time glob patterns and deploys static files. Dependabot monitors the lockfile.

Weekly and monthly pages share a cached date index built from topic histories once per build.
The period tests verify that ranking a year of periods never reads those histories again.
Periods are listed only when they contain a stored day; “so far” means the latest stored
day is before that period’s end, so fixture builds are independent of the wall clock.
