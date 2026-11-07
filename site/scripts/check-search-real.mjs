import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { preview } from 'astro';
import { chromium } from 'playwright';
import { filterResults } from '../src/lib/search-match.js';

process.chdir(fileURLToPath(new URL('../', import.meta.url)));
if (!existsSync('../data')) {
  console.log('SKIP real-data search: ../data is absent');
  process.exit(0);
}

const buildStarted = performance.now();
const build = spawnSync('npm', ['run', 'build'], {
  env: { ...process.env, TRENDBIO_DATA_ROOT: '../data', TRENDBIO_NOTES_ROOT: '../notes' },
  stdio: 'inherit',
});
if (build.error) throw build.error;
assert.equal(build.status, 0, 'real-data build failed');
const buildSeconds = (performance.now() - buildStarted) / 1000;
assert.ok(buildSeconds < 60, `real-data build took ${buildSeconds}s`);
console.log(`Real-data build: ${buildSeconds.toFixed(2)}s`);

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
    const raw = await page.evaluate(async query => {
      const pagefind = await import('/pagefind/pagefind.js');
      const raw = await pagefind.search(query);
      return { total: raw.results.length, data: await Promise.all(raw.results.slice(0, 50).map(result => result.data())) };
    }, query);
    const filtered = await filterResults(query, raw.data.map(data => ({ data: async () => data })));
    const result = { raw: raw.total, contents: filtered.map(result => result.content) };
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
  const html = readFileSync('dist/index.html', 'utf8');
  assert.equal(existsSync('dist/search-match.js'), false);
  assert.doesNotMatch(html, /\/pagefind\/|search-match/);
  const scriptPath = html.match(/<script type="module" src="([^"]+)"/)[1];
  const script = readFileSync(`dist${scriptPath}`, 'utf8');
  assert.ok(script.includes('header-search-query'));
  const scriptBytes = Buffer.byteLength(script);
  assert.ok(scriptBytes < 4000, `header script: ${scriptBytes} bytes`);
  const context = await browser.newContext();
  const home = await context.newPage();
  const requests = [];
  home.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (/pagefind|search-match/.test(path)) requests.push(path);
  });
  await home.goto(`http://127.0.0.1:${server.port}/`);
  await home.waitForLoadState('networkidle');
  assert.deepEqual(requests, [], 'untouched header loaded search dependencies');
  const untouched = [...requests];
  const dropdown = [];
  let firstQuery;
  for (const query of ['PoolParty', 'alphafold', 'qqzzxxnomatch']) {
    await home.getByRole('combobox').fill(query);
    await home.getByRole('link', { name: 'See all results' }).waitFor();
    const links = await home.getByRole('option').evaluateAll(options => options.map(option => ({
      title: option.textContent, url: option.getAttribute('href'),
    })));
    if (!firstQuery) firstQuery = [...requests];
    if (query === 'qqzzxxnomatch') {
      assert.equal(links.length, 0);
      assert.equal(await home.locator('#header-search-message').textContent(), 'No topics found');
    } else {
      assert.ok(links.length > 0 && links.length <= 6, query);
      const candidates = await home.evaluate(async query => {
        const pagefind = await import('/pagefind/pagefind.js');
        return Promise.all((await pagefind.search(query)).results.slice(0, 50).map(result => result.data()));
      }, query);
      const expected = (await filterResults(query, candidates.map(data => ({ data: async () => data })))).slice(0, 6).map(result => result.url);
      assert.deepEqual(links.map(link => link.url), expected, query);
    }
    dropdown.push({ query, links });
  }
  await context.close();
  mkdirSync('.playwright-shots', { recursive: true });
  const screenshots = [];
  for (const [width, theme] of [[1280, 'dark'], [1280, 'light'], [390, 'dark']]) {
    const shotContext = await browser.newContext({ viewport: { width, height: 900 } });
    await shotContext.addInitScript(theme => localStorage.setItem('trendbio-theme', theme), theme);
    const shot = await shotContext.newPage();
    await shot.goto(`http://127.0.0.1:${server.port}/`);
    await shot.getByRole('combobox').fill('alphafold');
    await shot.getByRole('link', { name: 'See all results' }).waitFor();
    await shot.evaluate(() => document.fonts.ready);
    assert.equal(await shot.evaluate(() => document.documentElement.scrollWidth), width);
    const path = `.playwright-shots/instant-search-real-${width}-${theme}.png`;
    await shot.screenshot({ path });
    screenshots.push(path);
    await shotContext.close();
  }
  const evidence = { scriptBytes, buildSeconds, untouched, firstQuery, dropdown, screenshots };
  writeFileSync('.playwright-shots/instant-search-evidence.json', JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence, null, 2));
  console.table(rows);
  console.log(`PASS real-data search: ${queries.length} queries (index: ../data)`);
} finally {
  await browser?.close();
  await server.stop();
}
