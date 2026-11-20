import assert from 'node:assert/strict';
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { parse, serializeOuter } from 'parse5';

const [dist, dayFile, out] = process.argv.slice(2);
const read = path => JSON.parse(readFileSync(path, 'utf8'));
const { domain, date, ranked } = read(dayFile);
const store = dirname(dirname(dayFile));

function* elements(node) {
  if (node.tagName) yield node;
  for (const child of node.childNodes ?? []) yield* elements(child);
}
const attr = (node, key) => node.attrs.find(a => a.name === key)?.value;
const children = (node, tag) => node.childNodes.filter(child => child.tagName === tag);
const text = node => node.nodeName === '#text' ? node.value : (node.childNodes ?? []).map(text).join('');

const document = parse(readFileSync(join(dist, domain, 'day', date, 'index.html'), 'utf8'));
const nodes = [...elements(document)];
assert.equal(attr(nodes.find(n => n.tagName === 'html'), 'lang'), 'en');
const main = nodes.find(n => n.tagName === 'main');
const contents = [...elements(main)];
assert.equal(attr(contents.find(n => n.tagName === 'time'), 'datetime'), date);
const list = contents.find(n => n.tagName === 'ol' && attr(n, 'class') === 'rankings');
const rows = list ? children(list, 'li') : [];
assert.deepEqual(rows.map(n => [attr(n, 'id'), Number(attr(n, 'value'))]), ranked.map(r => [r.slug, r.rank]));

if (ranked.length) {
  const urls = new Map();
  const items = join(store, 'items');
  for (const file of readdirSync(items, { recursive: true })) {
    if (!file.endsWith('.json')) continue;
    const item = read(join(items, file));
    urls.set(item.id, item.url);
  }
  for (const [index, row] of rows.entries()) {
    const { slug, headline, summary } = ranked[index];
    assert.equal(text(children(row, 'h3')[0]), headline);
    assert.equal(text(children(row, 'p')[1]), summary);
    const topic = read(join(store, 'topics', slug + '.json'));
    const history = topic.history.find(entry => entry.date === date);
    const sources = [...elements(row)].find(n => n.tagName === 'ul');
    const links = children(sources, 'li').map(li => attr(children(li, 'a')[0], 'href'));
    assert.deepEqual(links, history.item_ids.map(id => urls.get(id)), 'Supporting papers for ' + slug);
  }
} else {
  assert.match(text(main), /No topic cleared the ranking threshold/);
}

// The download contains one date and retains its external research links.
const archive = contents.find(n => n.tagName === 'p' && attr(n, 'class') === 'archive');
archive.parentNode.childNodes = archive.parentNode.childNodes.filter(n => n !== archive);
for (const a of elements(main)) {
  if (a.tagName === 'a') assert.match(attr(a, 'href'), /^https?:\/\//);
}
const title = nodes.find(n => n.tagName === 'title');
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
${serializeOuter(title)}
<style>
:root { color-scheme: light dark; font: 1rem/1.65 system-ui, sans-serif }
body { max-width: 72ch; margin: 1.5rem auto; padding: 0 1rem; overflow-wrap: anywhere }
h1, h2, h3 { line-height: 1.3 } li:target { outline: 2px solid; outline-offset: .25rem }
ol.rankings > li { padding: .6rem 0; border-top: 1px solid GrayText } summary { cursor: pointer }
.correction { border-inline-start: 3px solid; padding-inline-start: .75rem; margin: 1rem 0 }
</style></head><body>${serializeOuter(main)}</body></html>\n`;
mkdirSync(out, { recursive: true });
writeFileSync(join(out, 'en.html'), html);
console.log(`Verified the English edition for ${date} with ${ranked.length} ranked topics.`);
