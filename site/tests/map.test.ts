import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { preview } from "astro";
import { chromium, type Browser } from "playwright";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { MapData } from "../src/lib/types";
import { loadMap, rankedTopics } from "../src/lib/data";

const map: MapData = JSON.parse(readFileSync('tests/fixtures/map.json', 'utf8'));
const html = () => readFileSync('dist/map/index.html', 'utf8');

it('embeds the fixture points, canvas, native slider and a fallback link per topic', () => {
  const content = html();
  expect(content).toContain('<canvas');
  expect(content).toMatch(/<input[^>]*type="range"/);
  const embedded = content.match(/<script[^>]*id="topic-map-data"[^>]*>([\s\S]*?)<\/script>/)![1];
  expect(JSON.parse(embedded)).toEqual(map);
  expect(map.points.map(p => p.slug).sort()).toEqual(rankedTopics('computational').map(p => p.slug).sort());
  expect(content).toContain('<noscript>');
  for (const p of map.points) expect(content).toContain(`href="/topic/${p.slug}/"`);
  const script = content.match(/<script[^>]*type="module"[^>]*>([\s\S]*?)<\/script>/)![1];
  expect(Buffer.byteLength(script)).toBeLessThanOrEqual(12_000);
  expect(loadMap('missing-domain')).toBeNull();
});

it('includes the Map navigation link on every HTML page', () => {
  for (const path of readdirSync('dist', { recursive: true, encoding: 'utf8' }).filter(p => p.endsWith('.html'))) {
    expect(readFileSync(join('dist', path), 'utf8'), path).toMatch(/<nav\b[\s\S]*href="\/map\/"[^>]*>Map<\/a>/);
  }
});

it('fetches maps over 600 KB and escapes embedded script terminators', () => {
  const temporary = mkdtempSync(join(tmpdir(), 'trendbio-map-'));
  try {
    const data = join(temporary, 'data'), output = join(temporary, 'dist');
    cpSync('../fixtures/data', data, { recursive: true });
    const hostile = structuredClone(map);
    hostile.points[0].headline = '</script><script>alert(1)</script>';
    for (const large of [false, true]) {
      if (large) hostile.points[0].label = 'x'.repeat(600_001);
      writeFileSync(join(data, 'computational/map.json'), JSON.stringify(hostile));
      execFileSync(process.execPath, ['node_modules/astro/astro.js', 'build', '--outDir', output], {
        env: { ...process.env, TRENDBIO_DATA_ROOT: data }, stdio: 'pipe',
      });
      const content = readFileSync(join(output, 'map/index.html'), 'utf8');
      expect(content).not.toContain('</script><script>alert(1)</script>');
      if (large) {
        expect(content).toContain('data-src="/map.json"');
        expect(content).not.toContain('x'.repeat(600_001));
        expect(JSON.parse(readFileSync(join(output, 'map.json'), 'utf8'))).toEqual(hostile);
      } else {
        expect(content).toContain('\\u003c/script>');
      }
    }
  } finally { rmSync(temporary, { recursive: true, force: true }); }
}, 30_000);

describe('interactive topic map', () => {
  let server: Awaited<ReturnType<typeof preview>>;
  let browser: Browser;
  beforeAll(async () => {
    browser = await chromium.launch({ headless: true });
    server = await preview({ server: { host: '127.0.0.1' }, logLevel: 'error' });
  });
  afterAll(async () => { await browser?.close(); await server?.stop(); });

  it('renders at device scale, filters by month and category, and opens a hovered topic', async () => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
    const page = await context.newPage();
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    try {
      await page.goto(`http://127.0.0.1:${server.port}/map/`);
      const canvas = page.locator('canvas');
      await page.waitForFunction(() => document.querySelector('canvas')!.width > 1000);
      const box = (await canvas.boundingBox())!;
      expect(await canvas.getAttribute('width')).toBe(String(Math.round(box.width * 2)));
      const image = () => canvas.evaluate(c => (c as HTMLCanvasElement).toDataURL());
      const all = await image();
      await page.locator('[data-cat="structural"]').click();
      expect(await image()).not.toBe(all);
      await page.locator('[data-cat="all"]').click();
      expect(await image()).toBe(all);
      await page.locator('#map-month').focus();
      await page.keyboard.press('Home');
      expect(await page.locator('#map-month-label').textContent()).toBe('2026-08');
      expect(await image()).not.toBe(all);
      await page.keyboard.press('End');
      expect(await page.locator('#map-month-label').textContent()).toBe('All time');
      expect(await image()).toBe(all);
      const p = map.points[0];
      await page.mouse.move(box.x + 24 + p.x * (box.width - 48), box.y + 24 + p.y * (box.height - 48));
      expect(await page.locator('.map-tooltip').isVisible()).toBe(true);
      expect(await page.locator('.map-tooltip').textContent()).toContain(p.headline);
      await page.mouse.click(box.x + 24 + p.x * (box.width - 48), box.y + 24 + p.y * (box.height - 48));
      await page.waitForURL(`**/topic/${p.slug}/`);
      expect(errors).toEqual([]);
    } finally { await context.close(); }
  });

  it('shows the topic list with JavaScript disabled and keeps the map within a mobile column', async () => {
    for (const javaScriptEnabled of [false, true]) {
      const context = await browser.newContext({ javaScriptEnabled, viewport: { width: 375, height: 812 } });
      const page = await context.newPage();
      try {
        await page.goto(`http://127.0.0.1:${server.port}/map/`);
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(375);
        const list = page.locator('.map-links');
        expect(await list.locator('a').count()).toBe(map.points.length);
        if (!javaScriptEnabled) {
          expect((await list.boundingBox())!.width).toBeGreaterThan(300);
          expect(await page.locator('canvas').isVisible()).toBe(false);
        } else {
          await list.locator('a').first().focus();
          expect((await list.boundingBox())!.width).toBeGreaterThan(300);
        }
      } finally { await context.close(); }
    }
  });
});
