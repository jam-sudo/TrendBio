// Run from site/: node scripts/og.mjs (uses the committed site helix geometry).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright';

const geometry = JSON.parse(readFileSync(new URL('../src/components/helix-paths.json', import.meta.url), 'utf8'));
const font = weight => readFileSync(new URL(`../node_modules/@fontsource/inconsolata/files/inconsolata-latin-${weight}-normal.woff2`, import.meta.url)).toString('base64');
const helix = [false, true].map(front => [
  ...geometry.rungs.flatMap(rung => rung.segments.filter(segment => segment.front === front).map(segment =>
    `<line x1="${segment.x1}" y1="${segment.y1}" x2="${segment.x2}" y2="${segment.y2}" stroke="#a1a1a1" stroke-width="5" stroke-opacity="${segment.opacity}"/>`)),
  ...geometry.backbones.flatMap(backbone => backbone.segments.filter(segment => segment.front === front).map(segment =>
    `<path d="${segment.d}" stroke="#fafafa" stroke-width="9" stroke-opacity="${front ? 1 : .35}"/>`)),
].join('')).join('');
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
  await page.setContent(`<!doctype html><html lang="en"><meta charset="utf-8"><title>TrendBio preview</title>
<style>
${[400, 700].map(weight => `@font-face { font-family: Inconsolata; font-weight: ${weight}; src: url(data:font/woff2;base64,${font(weight)}); }`).join('\n')}
* { box-sizing: border-box; } body { margin: 0; width: 1200px; height: 630px; background: #111; color: #fafafa; font-family: Inconsolata, monospace; display: grid; place-content: center; text-align: center; }
h1 { display: flex; align-items: center; justify-content: center; gap: 30px; font-size: 112px; line-height: 1; margin: 0 0 36px; letter-spacing: -3px; }
svg { width: 120px; height: 100px; } p { margin: 0; font-size: 34px; color: #a1a1a1; }
</style><body><main><h1><svg viewBox="0 0 ${geometry.pitch} 120" fill="none" stroke-linecap="round" aria-hidden="true">${helix}</svg>TrendBio</h1><p>What moved in computational biology</p></main></body></html>`);
  await page.evaluate(() => document.fonts.ready);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 1200);
  const png = await page.screenshot({ path: new URL('../public/og.png', import.meta.url).pathname });
  assert.equal(png.readUInt32BE(16), 1200);
  assert.equal(png.readUInt32BE(20), 630);
  assert(png.length < 200_000, `Preview is too large: ${png.length} bytes`);
  console.log(`og.png: 1200×630, ${png.length} bytes`);
} finally { await browser.close(); }
