import {
  readFileSync,
  writeFileSync,
  readdirSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  renameSync,
  rmSync,
} from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { homedir, tmpdir } from 'node:os';
import { gzipSync, gunzipSync } from 'node:zlib';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parse, serialize } from 'parse5';
import { truncateDescription } from '../src/lib/metadata.ts';

const home = fileURLToPath(new URL('..', import.meta.url));
const ui = JSON.parse(readFileSync(join(home, 'i18n/ko.json'), 'utf8'));
const reviewed = JSON.parse(readFileSync(join(home, 'i18n/ko-reviewed.json'), 'utf8'));
const cacheFile = process.env.TRENDBIO_KO_CACHE || join(homedir(), '.cache/trendbio/ko-delta.json.gz');
const readCatalog = (path) => (existsSync(path) ? JSON.parse(gunzipSync(readFileSync(path))) : {});
const delta = readCatalog(cacheFile);
const cache = { ...delta, ...readCatalog(join(home, 'i18n/ko.catalog.json.gz')) };
const needed = new Set();
const fixed = new Set([
  'TrendBio',
  'English',
  '한국어',
  'GitHub',
  'PubMed',
  'bioRxiv',
  'arXiv',
  'CC BY',
  'ET',
  'UTC',
  'BibTeX',
]);
const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const longMonths = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];
const monthDate =
  /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), (\d{4})(?:, (\d{2}:\d{2}) (E[SD]T))?$/;

function korean(text) {
  const s = text.trim().replace(/\s+/gu, ' ');
  if (Object.hasOwn(ui, s)) return ui[s];
  if (Object.hasOwn(reviewed, s)) return reviewed[s];
  if (!s || fixed.has(s) || /^(?:https?:\/\/|mailto:|\/|10\.\d{4,9}\/|arXiv:\d)/i.test(s)) return s;
  let v = monthDate.exec(s);
  if (v)
    return (
      v[3] + '년 ' + (months.indexOf(v[1]) + 1) + '월 ' + v[2] + '일' + (v[4] ? ' ' + v[4] + ' ' + v[5] : '')
    );
  if ((v = /^([A-Za-z]+) (\d{4})$/.exec(s))) {
    const month = Math.max(months.indexOf(v[1]), longMonths.indexOf(v[1]));
    if (month >= 0) return v[2] + '년 ' + (month + 1) + '월';
  }
  if ((v = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)))
    return v[1] + '년 ' + Number(v[2]) + '월 ' + Number(v[3]) + '일';
  if ((v = /^(\d{4}-\d{2}-\d{2}): (.+)$/.exec(s))) return korean(v[1]) + ' · ' + korean(v[2]);
  if ((v = /^Week (\d+), (\d{4}) · ([A-Z][a-z]{2}) (\d+) – ([A-Z][a-z]{2}) (\d+)$/.exec(s))) {
    return (
      v[2] +
      '년 ' +
      v[1] +
      '주차 · ' +
      (months.indexOf(v[3]) + 1) +
      '월 ' +
      v[4] +
      '일 ~ ' +
      (months.indexOf(v[5]) + 1) +
      '월 ' +
      v[6] +
      '일'
    );
  }
  if (!/[A-Za-z]/.test(s)) return s;
  if ((v = /^(.+) — (.+), last ranked (\d{4}-\d{2}-\d{2})$/.exec(s)))
    return korean(v[1]) + ' — ' + korean(v[2]) + ' · 마지막 순위 진입 ' + korean(v[3]);
  if ((v = /^(.+) — TrendBio$/.exec(s))) return korean(v[1]) + ' — TrendBio';
  if (s.startsWith('TrendBio — ')) return 'TrendBio — ' + korean(s.slice('TrendBio — '.length));
  if ((v = /^(.+) Tools: (.+)$/.exec(s))) return korean(v[1]) + ' 도구 ' + v[2];
  if ((v = /^(#\d+ · )(.+)/.exec(s))) return v[1] + korean(v[2]);
  if ((v = /^Rank (\d+)$/.exec(s))) return v[1] + '위';
  if ((v = /^Top (\d+)$/.exec(s))) return '상위 ' + v[1] + '개';
  if ((v = /^Show (\d+) more$/.exec(s))) return v[1] + '개 더 보기';
  if ((v = /^today: (\d+)$/i.exec(s))) return '오늘 ' + v[1] + '건';
  if ((v = /^(Up|Down) (\d+) places? since the previous day$/.exec(s)))
    return '전날보다 ' + v[2] + '계단 ' + (v[1] === 'Up' ? '상승' : '하락');
  if ((v = /^(\d+) supporting papers?$/.exec(s))) return '근거 논문 ' + v[1] + '편';
  if ((v = /^([\d,]+) (people|reactions|stars)$/.exec(s)))
    return (
      { people: '참여자 ', reactions: '반응 ', stars: '별 ' }[v[2]] +
      v[1] +
      { people: '명', reactions: '개', stars: '개' }[v[2]]
    );
  if ((v = /^\+([\d,]+) (?:in 7d|★ this week)$/.exec(s))) return '최근 7일간 별 +' + v[1] + '개';
  if ((v = /^Papers added since (.+)$/.exec(s))) return korean(v[1]) + ' 이후 추가된 논문';
  if ((v = /^(.+) editions by date$/.exec(s))) return korean(v[1]) + ' 날짜별 순위';
  if (/^Browse [a-z-]+ editions$/.test(s)) return '날짜별 순위 보기';
  if ((v = /^(.+) · (\d{4}-\d{2}-\d{2})$/.exec(s))) return korean(v[1]) + ' · ' + korean(v[2]);
  if ((v = /^(\d+) (preprints?|published|items|topics)$/.exec(s)))
    return (
      {
        preprint: '프리프린트',
        preprints: '프리프린트',
        published: '출판 논문',
        items: '자료',
        topics: '주제',
      }[v[2]] +
      ' ' +
      v[1] +
      (['preprint', 'preprints', 'published'].includes(v[2]) ? '편' : '개')
    );
  if (s.includes(' · ') && /^(?:\d+ (?:preprints?|published|tools?|industry)\b|days ranked:|Biology ·|Physics ·)/.test(s))
    return s.split(' · ').map(korean).join(' · ');
  if ((v = /^↑ ([\d.]+)× vs 4-wk avg$/.exec(s))) return '최근 4주 평균의 ' + v[1] + '배';
  if ((v = /^(\d+) tools?$/.exec(s))) return '도구 ' + v[1] + '개';
  if ((v = /^(\d+) industry$/.exec(s))) return '산업계 소식 ' + v[1] + '건';
  if ((v = /^days ranked: (\d+)$/.exec(s))) return '순위 진입 ' + v[1] + '일';
  if ((v = /^best rank: #(\d+)$/.exec(s))) return '최고 ' + v[1] + '위';
  if (s === 'best rank: —') return '최고 순위 없음';
  if ((v = /^items: (\d+)$/.exec(s))) return '자료 ' + v[1] + '건';
  if ((v = /^Rise: ([\d.]+)×$/.exec(s))) return '증가율 ' + v[1] + '배';
  if (/^[\w.+#/-]+$/.test(s) || /^[A-Z0-9 &+._/-]+$/.test(s) || /^\S+@\S+\.\S+$/.test(s)) return s;
  if (Object.hasOwn(cache, s)) return cache[s];
  needed.add(s);
  return s;
}
function translateText(value) {
  if (!value.trim()) return value;
  return value.replace(/^(\s*)([\s\S]*?)(\s*)$/u, (_, before, main, after) => before + korean(main) + after);
}

const attr = (node, key) => node.attrs?.find((a) => a.name === key);
const value = (node, key) => attr(node, key)?.value;
function set(node, key, val) {
  const a = attr(node, key);
  if (a) a.value = val;
  else node.attrs.push({ name: key, value: val });
}
function localUrl(path) {
  const prefix = 'https://trendbio.dev';
  if (path.startsWith(prefix + '/')) return prefix + localUrl(path.slice(prefix.length));
  if (!path.startsWith('/') || path.startsWith('//') || /^\/ko(?:\/|$)/.test(path)) return path;
  const clean = path.split(/[?#]/, 1)[0];
  if (
    clean === '/map.json' ||
    clean === '/404.html' ||
    /^\/feed(?:\/[^/]+)?\.xml$/.test(clean) ||
    !/\.[a-z0-9]+$/i.test(clean)
  )
    return '/ko' + path;
  return path;
}
function mapData(data) {
  for (const point of data?.points ?? []) {
    if (point.headline) point.headline = korean(point.headline);
    if (point.label) point.label = korean(point.label);
  }
  return data;
}
const accessible = new Set([
  'aria-label',
  'aria-valuetext',
  'title',
  'placeholder',
  'alt',
  'data-loading',
  'data-empty',
  'data-count',
]);
function visit(n) {
  const tag = n.tagName;
  if (n.nodeName === '#text') {
    n.value = translateText(n.value);
    return;
  }
  if (tag === 'html') set(n, 'lang', 'ko');
  if (tag === 'a' && value(n, 'data-language')) {
    n.attrs = n.attrs.filter((a) => a.name !== 'aria-current');
    if (value(n, 'data-language') === 'ko') set(n, 'aria-current', 'true');
    return;
  }
  if (tag === 'a' && value(n, 'href')) {
    const href = value(n, 'href');
    set(n, 'href', localUrl(href));
    if (href.startsWith('/feed') && n.childNodes?.[0]?.value === href) n.childNodes[0].value = localUrl(href);
  }
  if (tag === 'form' && value(n, 'action')) set(n, 'action', localUrl(value(n, 'action')));
  if (tag === 'link' && value(n, 'rel') === 'canonical') set(n, 'href', localUrl(value(n, 'href')));
  if (tag === 'link' && value(n, 'type') === 'application/atom+xml')
    set(n, 'href', localUrl(value(n, 'href')));
  if (tag === 'meta') {
    const key = value(n, 'property') || value(n, 'name');
    if (['og:title', 'og:image:alt'].includes(key)) set(n, 'content', korean(value(n, 'content') || ''));
    if (['og:description', 'description'].includes(key))
      set(n, 'content', truncateDescription(korean(value(n, 'content') || '')));
    if (key === 'og:url') set(n, 'content', localUrl(value(n, 'content')));
    if (key === 'og:locale') set(n, 'content', 'ko_KR');
    if (key === 'og:locale:alternate') set(n, 'content', 'en_US');
  }
  for (const a of n.attrs || []) if (accessible.has(a.name)) a.value = korean(a.value);
  if (tag === 'option' && value(n, 'value')) set(n, 'value', korean(value(n, 'value')));
  const filter = value(n, 'data-pagefind-filter');
  if (filter?.startsWith('category:')) set(n, 'data-pagefind-filter', 'category:' + korean(filter.slice(9)));
  if (value(n, 'data-colors')) {
    const colors = JSON.parse(value(n, 'data-colors'));
    for (const v of Object.values(colors)) v.label = korean(v.label);
    set(n, 'data-colors', JSON.stringify(colors));
  }
  if (value(n, 'id') === 'topic-map-data') {
    if (value(n, 'data-src')) set(n, 'data-src', localUrl(value(n, 'data-src')));
    else if (n.childNodes?.[0]?.value)
      n.childNodes[0].value = JSON.stringify(mapData(JSON.parse(n.childNodes[0].value))).replace(
        /</g,
        '\\u003c',
      );
  }
  if (['script', 'style', 'svg', 'code', 'pre', 'kbd'].includes(tag) || value(n, 'translate') === 'no')
    return;
  for (const child of n.childNodes || []) visit(child);
  if (n.content) visit(n.content);
}
function htmlFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((f) =>
    f.isDirectory()
      ? f.name === 'ko' || f.name.startsWith('_') || f.name === 'pagefind'
        ? []
        : htmlFiles(join(dir, f.name))
      : f.name.endsWith('.html')
        ? [join(dir, f.name)]
        : [],
  );
}
const entities = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
function localizedFeed(xml) {
  const escape = (text) =>
    text.replace(/[&<>"']/g, (c) => '&' + Object.keys(entities).find((k) => entities[k] === c) + ';');
  return xml
    .replace('<feed xmlns=', '<feed xml:lang="ko" xmlns=')
    .replace(/<(title|summary)([^>]*)>([^<]*)<\/\1>/g, (_, tag, attributes, content) => {
      const plain = content.replace(/&(amp|lt|gt|quot|apos);/g, (_, key) => entities[key]);
      return '<' + tag + attributes + '>' + escape(korean(plain)) + '</' + tag + '>';
    })
    .replace(/href="(https:\/\/trendbio\.dev\/[^"]*)"/g, (_, path) => 'href="' + localUrl(path) + '"')
    .replace(/<id>(https:\/\/trendbio\.dev\/[^<]*)<\/id>/g, (_, path) => '<id>' + localUrl(path) + '</id>');
}
function transform(body, file) {
  if (file.endsWith('.xml')) return localizedFeed(body);
  if (file.endsWith('.json')) return JSON.stringify(mapData(JSON.parse(body)));
  const doc = parse(body);
  visit(doc);
  return serialize(doc);
}

function translateMissing() {
  if (!needed.size) return;
  const temp = mkdtempSync(join(tmpdir(), 'trendbio-ko-'));
  try {
    const input = join(temp, 'missing.json'),
      output = join(temp, 'translated.json');
    writeFileSync(input, JSON.stringify([...needed]));
    const job = spawnSync(
      process.env.TRENDBIO_TRANSLATION_PYTHON || 'python3',
      [join(home, 'scripts/translate-ko.py'), input, output],
      { stdio: 'inherit' },
    );
    if (job.error || job.status !== 0)
      throw new Error(
        'Korean translation did not finish. See docs/operations.md for the local translator setup.',
      );
    const translated = JSON.parse(readFileSync(output, 'utf8'));
    for (const s of needed) {
      if (typeof translated[s] !== 'string' || !translated[s].trim())
        throw new Error('Missing Korean translation');
      cache[s] = delta[s] = translated[s];
    }
    mkdirSync(dirname(cacheFile), { recursive: true });
    const cacheTemp = cacheFile + '.' + process.pid + '.tmp';
    writeFileSync(cacheTemp, gzipSync(JSON.stringify(delta), { level: 9 }));
    renameSync(cacheTemp, cacheFile);
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
  needed.clear();
}

export function localizePreview(body, file) {
  const translated = transform(body, file);
  if (!needed.size) return translated;
  translateMissing();
  return transform(body, file);
}

function build(root) {
  const pages = htmlFiles(root);
  const feedDir = join(root, 'feed');
  const feeds = existsSync(feedDir)
    ? readdirSync(feedDir)
        .filter((f) => f.endsWith('.xml'))
        .map((f) => join(feedDir, f))
    : [];
  const files = [...pages, join(root, 'map.json'), join(root, 'feed.xml'), ...feeds].filter(existsSync);
  for (const file of files) transform(readFileSync(file, 'utf8'), file);
  translateMissing();
  for (const file of files) {
    const path = join(root, 'ko', relative(root, file));
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, transform(readFileSync(file, 'utf8'), file));
  }
  if (needed.size) throw new Error('Untranslated text appeared during rendering');
  console.log('Built ' + pages.length + ' Korean pages.');
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  build(resolve(process.argv[2] || join(home, 'dist')));
}
