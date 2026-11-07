import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { preview } from 'astro';
import { chromium } from 'playwright';

process.chdir(fileURLToPath(new URL('../', import.meta.url)));
if (!existsSync('../data')) {
  console.log('SKIP real-data search: ../data is absent');
  process.exit(0);
}

const build = spawnSync('npm', ['run', 'build'], {
  env: { ...process.env, TRENDBIO_DATA_ROOT: '../data', TRENDBIO_NOTES_ROOT: '../notes' },
  stdio: 'inherit',
});
if (build.error) throw build.error;
assert.equal(build.status, 0, 'real-data build failed');

const queries = [
  ['qqzzxxnomatch', null], ['zzzzqqqq', null], ['xkcdvvv', null],
  ['PoolParty', 'poolparty'], ['poolparty', 'poolparty'],
  ['alphafold', 'alphafold'], ['AlphaFold3', 'alphafold3'],
  ['perturbation', 'perturbation'], ['perturbations', 'perturbation'],
  ['scRNA-seq', 'scrnaseq'], ['single-cell', 'singlecell'], ['scRNA.seq', 'scrnaseq'],
];
const server = await preview({ server: { host: '127.0.0.1', port: 4345 }, logLevel: 'error' });
let browser;
try {
  browser = await chromium.launch();
  const page = await browser.newPage();
  const rows = [];
  for (const [query, stem] of queries) {
    await page.goto(`http://127.0.0.1:${server.port}/search/?q=${encodeURIComponent(query)}`);
    await page.waitForFunction(() => /found\./.test(document.getElementById('search-status').textContent));
    const result = await page.evaluate(async query => {
      const pagefind = await import('/pagefind/pagefind.js');
      const { filterResults } = await import('/search-match.js');
      const raw = await pagefind.search(query);
      const filtered = await filterResults(query, raw.results);
      return { raw: raw.results.length, contents: filtered.map(result => result.content) };
    }, query);
    const count = result.contents.length;
    if (stem === null) {
      assert.equal(count, 0, query);
      assert.equal(await page.locator('#search-status').textContent(), 'No topics found. Try another term or category.');
    } else {
      assert.ok(count > 0, `${query}: no matches`);
      // Independent content assertion: the expected term/stem must start an indexed word.
      assert.ok(result.contents.some(content => content.toLowerCase().replace(/[-.]/g, '')
        .split(/[^\p{L}\p{N}]+/u).some(word => word.startsWith(stem))), `${query}: unrelated results`);
      assert.equal(await page.locator('#search-status').textContent(),
        `${count} ${count === 1 ? 'topic' : 'topics'} found. Showing ${Math.min(20, count)}.`);
    }
    assert.equal(await page.locator('#search-results li').count(), Math.min(20, count), query);
    rows.push({ query, raw: result.raw, filtered: count, content: stem === null ? 'empty' : `contains ${stem}` });
  }
  console.table(rows);
  console.log(`PASS real-data search: ${queries.length} queries (index: ../data)`);
} finally {
  await browser?.close();
  await server.stop();
}
