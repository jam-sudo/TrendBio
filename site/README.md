# TrendBio site

Use Node 22. Run `npm ci`, `npx playwright install chromium`, and `npm test`.
The tests build the fixture data and serve `dist/` locally through Astro preview
for headless Chromium and axe checks. If Chromium is missing, the suite attempts
installation and skips browser checks with a warning only if installation fails;
launch errors and accessibility failures fail the suite. On Linux, install
Chromium's system libraries with `npx playwright install --with-deps chromium`.

Build the same 13 fixture pages with:

```sh
TRENDBIO_DATA_ROOT=../fixtures/data TRENDBIO_NOTES_ROOT=../fixtures/notes npm run build
```

## Known audit findings

On 2026-11-02, `npm audit fix` (without `--force`) left **5 vulnerabilities:
1 low, 3 high, 1 critical**, all in Astro 5.18.2 or its dependency tree.
`npm audit` still exits 1; its proposed fix is a breaking upgrade to Astro 7.4.5.

The critical advisory is [GHSA-26w7-cxv4-gfx2](https://github.com/advisories/GHSA-26w7-cxv4-gfx2),
remote code execution through AVIF image optimization. This project uses Astro
only to build static HTML, CSS and JavaScript, has no server adapter, image
optimization calls or image inputs, and deploys only `dist/`. Astro, sharp,
esbuild and Zod are not deployed server runtimes. The remaining findings include
Astro rendering/server advisories, sharp image-decoder vulnerabilities
(`GHSA-f88m-g3jw-g9cj`, `GHSA-rgj7-g3m4-5g8c`, `GHSA-wq5f-xc86-pv6w`),
esbuild's Windows development-server file read (`GHSA-g7r4-m6w7-qqqr`), and
Zod's oversized-collection memory exhaustion (`GHSA-mrhx-c7xc-m3w5`, also
reported through zod-to-ts).

The dependency findings remain unresolved; a breaking framework upgrade is
outside this accessibility pass. Reassess before adding image processing,
server rendering or accepting untrusted build inputs. Do not expose the local
development/preview server as production hosting.
