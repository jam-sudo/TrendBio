import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { parse, serializeOuter } from 'parse5';

const [dist, dayFile, out] = process.argv.slice(2);
const { domain, date, ranked } = JSON.parse(readFileSync(dayFile, 'utf8'));
const route = `${domain}/day/${date}`;

function* elements(node) {
  if (node.tagName) yield node;
  for (const child of node.childNodes ?? []) yield* elements(child);
}
const attr = (node, key) => node.attrs.find(a => a.name === key)?.value;
let englishEvidence;
const pages = new Map();

for (const lang of ['en', 'ko']) {
  const prefix = lang === 'ko' ? 'ko' : '';
  const document = parse(readFileSync(join(dist, prefix, route, 'index.html'), 'utf8'));
  const nodes = [...elements(document)];
  assert.equal(attr(nodes.find(n => n.tagName === 'html'), 'lang'), lang);
  const main = nodes.find(n => n.tagName === 'main');
  const contents = [...elements(main)];
  assert.equal(attr(contents.find(n => n.tagName === 'time'), 'datetime'), date);
  const list = contents.find(n => n.tagName === 'ol' && attr(n, 'class') === 'rankings');
  const rows = list.childNodes.filter(n => n.tagName === 'li');
  assert.deepEqual(rows.map(n => [attr(n, 'id'), Number(attr(n, 'value'))]), ranked.map(r => [r.slug, r.rank]));
  const evidence = rows.map(row => [...elements(row)].filter(n => n.tagName === 'a').map(a => attr(a, 'href')));
  if (lang === 'en') englishEvidence = evidence;
  else {
    assert.deepEqual(evidence, englishEvidence);
    for (const [i, row] of rows.entries()) {
      if (/\b[a-z]{2,}\s+[a-z]{2,}\b/.test(ranked[i].summary)) {
        const summary = row.childNodes.filter(n => n.tagName === 'p')[1];
        assert.match(serializeOuter(summary), /[가-힣]/u, `Missing Korean summary at rank ${ranked[i].rank}`);
      }
    }
  }

  // The download contains one date. Its language switch and evidence links must work from disk.
  const archive = contents.find(n => n.tagName === 'p' && attr(n, 'class') === 'archive');
  archive.parentNode.childNodes = archive.parentNode.childNodes.filter(n => n !== archive);
  const languages = nodes.find(n => attr(n, 'class') === 'language-links');
  const switches = [...elements(languages)].filter(n => n.tagName === 'a');
  assert.deepEqual(switches.map(a => attr(a, 'data-language')).sort(), ['en', 'ko']);
  for (const a of switches) a.attrs.find(v => v.name === 'href').value = attr(a, 'data-language') + '.html';
  for (const a of elements(main)) {
    if (a.tagName === 'a') assert.match(attr(a, 'href'), /^https?:\/\//);
  }
  const title = nodes.find(n => n.tagName === 'title');
  pages.set(lang, `<!doctype html><html lang="${lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
${serializeOuter(title)}
<style>
:root { color-scheme: light dark; font: 1rem/1.65 system-ui, sans-serif }
body { max-width: 72ch; margin: 1.5rem auto; padding: 0 1rem; overflow-wrap: anywhere }
header a { margin-inline-end: .75rem } [aria-current] { font-weight: bold }
h1, h2, h3 { line-height: 1.3 } li:target { outline: 2px solid; outline-offset: .25rem }
ol.rankings > li { padding: .6rem 0; border-top: 1px solid GrayText } summary { cursor: pointer }
.correction { border-inline-start: 3px solid; padding-inline-start: .75rem; margin: 1rem 0 }
</style></head><body><header>${serializeOuter(languages)}</header>${serializeOuter(main)}
<script>for (const a of document.querySelectorAll('[data-language]')) a.addEventListener('click', () => { a.hash = location.hash; });</script>
</body></html>\n`);
}
mkdirSync(out, { recursive: true });
for (const [lang, html] of pages) writeFileSync(join(out, lang + '.html'), html);
console.log(`Verified ${date} in English and Korean with ${ranked.length} ranked topics.`);
