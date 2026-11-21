// Run from site with a local preview of the production build. One JSON line per HTML page.
import { readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { chromium } from 'playwright';

const [origin, directory, mode] = process.argv.slice(2);
if (!origin || !directory || !['layout', 'text', 'dark', 'light'].includes(mode)) {
  throw Error('Usage: node scripts/audit-accessibility.mjs PREVIEW_URL BUILD_DIRECTORY layout|text|dark|light');
}
const paths = readdirSync(directory, { recursive: true, encoding: 'utf8' })
  .filter(path => path.endsWith('.html')).map(path => path === 'index.html' ? '/' : '/' + path.replace(/\/index\.html$/, '/'));
if (!paths.includes('/') || !paths.includes('/404.html')) throw Error('Incomplete HTML inventory');
const tags = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22a', 'wcag22aa'];
const browser = await chromium.launch();
const mobile = mode !== 'dark';
const context = await browser.newContext({ viewport: { width: mode === 'text' ? 640 : mobile ? 320 : 1280, height: 900 },
  reducedMotion: 'reduce', colorScheme: mode === 'dark' ? 'dark' : 'light' });
if (['light','dark'].includes(mode)) await context.addInitScript({ path: createRequire(import.meta.url).resolve('axe-core/axe.min.js') });
const spacing = '* { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important } p { margin-bottom: 2em !important }';
let failures = 0;
try {
  const work = paths.values();
  async function inspect(page, path) {
    const issues = [];
    const response = await page.goto(new URL(path, origin).href, { waitUntil: 'load' });
    if (response.status() !== 200 && !(path === '/404.html' && response.status() === 404)) throw Error('HTTP ' + response.status());
    await page.evaluate(() => document.fonts.ready);
    if (mode === 'layout') {
      await page.keyboard.press('Tab');
      const first = await page.evaluate(() => document.activeElement.getAttribute('href'));
      if (first !== '#main') issues.push(['first-tab', first]);
      else {
        await page.keyboard.press('Enter');
        if (!await page.evaluate(() => document.activeElement?.id === 'main')) issues.push(['skip-focus']);
      }
    }
    if (mobile) await page.locator('main details').evaluateAll(nodes => nodes.forEach(el => el.open = true));
    if (mode === 'text') {
      const width = await page.evaluate(() => {
        document.documentElement.style.fontSize = '200%';
        return document.documentElement.scrollWidth;
      });
      if (width > 641) issues.push(['text-resize-overflow',width]);
      return {path,issues};
    }
    if (mode === 'layout') {
      const basics = await page.evaluate(() => {
        const ids = Array.from(document.querySelectorAll('[id]'), el => el.id);
        const h = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(el=>Number(el.tagName[1]));
        return { landmark: document.querySelectorAll('main').length, title: !!document.title.trim(),
          language: document.documentElement.lang, h1: h.filter(x=>x===1).length,
          headingJumps: h.some((x,i) => i && x > h[i-1]+1), duplicates: ids.filter((id,i)=>ids.indexOf(id)!==i).slice(0,4) };
      });
      if (basics.landmark !== 1 || basics.h1 !== 1 || !basics.title || !basics.language || basics.headingJumps || basics.duplicates.length) issues.push(['structure',basics]);
      for (const spaced of [false, true]) {
        if (spaced) await page.addStyleTag({content:spacing});
        const overflow = await page.evaluate(() => {
          if (document.documentElement.scrollWidth <= innerWidth + 1) return null;
          return { width:document.documentElement.scrollWidth, examples:[...document.querySelectorAll('main *, header *, footer *')].filter(el=>{
            const rect = el.getBoundingClientRect();
            return rect.width && rect.right>innerWidth+1 && !(el instanceof SVGElement) && !el.closest('.sr-only');
          }).slice(0,6).map(e=>[e.tagName,e.className?.toString().slice(0,70)]) };
        });
        if (overflow) issues.push([spaced?'spaced-overflow':'overflow',overflow]);
      }
      return {path,issues};
    }
    const result = await page.evaluate(async tags => {
      const { violations, incomplete } = await window.axe.run(document, {
        runOnly: {type:'tag',values:tags}, resultTypes:['violations','incomplete'],
        reporter:'v2', iframes:false,
      });
      // Inspect the flat CSS colors of text and icons axe could not compare.
      const painter = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
      const pixel = () => [...painter.getImageData(0, 0, 1, 1).data];
      const luminance = rgb => rgb.slice(0, 3).map(value => value / 255)
        .map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
        .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
      let lowestContrast = null;
      const review = [];
      for (const node of incomplete.find(rule => rule.id === 'color-contrast')?.nodes ?? []) {
        const el = document.querySelector(node.target[0]);
        if (!el) { review.push(node.target); continue; }
        const layers = [];
        for (let ancestor = el; ancestor; ancestor = ancestor.parentElement) layers.unshift(getComputedStyle(ancestor));
        if (layers.some(s => s.backgroundImage !== 'none' || Number(s.opacity) < 1)) {
          review.push(node.target); continue;
        }
        painter.clearRect(0, 0, 1, 1);
        for (const layer of layers) {
          painter.fillStyle = layer.backgroundColor;
          painter.fillRect(0, 0, 1, 1);
        }
        const background = pixel();
        if (background[3] !== 255) { review.push(node.target); continue; }
        const style = layers.at(-1);
        painter.fillStyle = style.color;
        painter.fillRect(0, 0, 1, 1);
        const values = [luminance(background), luminance(pixel())].sort((a,b) => a-b);
        const ratio = (values[1] + .05) / (values[0] + .05);
        lowestContrast = Math.min(lowestContrast ?? Infinity, ratio);
        const large = parseFloat(style.fontSize) >= 24 || (parseFloat(style.fontSize) >= 18.67 && Number(style.fontWeight) >= 700);
        if (ratio < (large ? 3 : 4.5)) review.push(node.target);
      }
      return {
        violations: violations.map(v => ({id:v.id, impact:v.impact, count:v.nodes.length, target:v.nodes.slice(0,3).map(n=>n.target)})),
        incomplete: incomplete.map(v => v.id), lowestContrast, review,
      };
    },tags);
    return {path, ...result};
  }
  await Promise.all(Array.from({length:8},async()=>{
    const page=await context.newPage();
    for (const path of work) {
      try {
        const result=await inspect(page,path);
        if (result.issues?.length || result.violations?.length || result.review?.length) failures++;
        console.log(JSON.stringify(result));
      } catch (error) { failures++; console.log(JSON.stringify({path,error:String(error)})); }
    }
    await page.close();
  }));
} finally { await browser.close(); }
console.error(`${mode}: ${paths.length} pages, ${failures} with findings or errors`);
process.exitCode = failures ? 1 : 0;
