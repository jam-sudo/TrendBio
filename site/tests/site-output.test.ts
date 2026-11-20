import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium, type Browser, type Page } from "playwright";
import { afterAll, beforeAll, expect, it } from "vitest";
import { getDataIndex } from "../src/lib/data";
import { editions } from "../src/lib/editions";
import { loadPeriods } from "../src/lib/period-data";
import { truncateDescription } from "../src/lib/metadata";

const read = (path: string) => readFileSync(`dist/${path}`, "utf8");
const { days, rankedTopics } = getDataIndex("computational");
let browser: Browser, page: Page;
beforeAll(async () => { browser = await chromium.launch(); page = await browser.newPage(); });
afterAll(async () => { await browser?.close(); });

it("truncates descriptions at a word boundary, including exact limits and long words", () => {
  expect(truncateDescription("  short\n description  ")).toBe("short description");
  expect(truncateDescription("a".repeat(160))).toHaveLength(160);
  expect(truncateDescription("word ".repeat(40))).toBe("word ".repeat(32).trimEnd() + "…");
  expect(truncateDescription("x".repeat(170))).toBe("x".repeat(159) + "…");
});

it("builds a 404 page with the main landmark and recovery links, plus the favicon", async () => {
  await page.setContent(read("404.html"));
  expect(await page.title()).toBe("Page not found");
  expect(await page.locator("main#main h1").textContent()).toBe("Page not found");
  for (const [label, href] of [["Today", "/"], ["Archive", "/archive/"], ["Map", "/map/"]]) {
    expect(await page.locator("main").getByRole("link", { name: label, exact: true }).getAttribute("href")).toBe(href);
  }
  expect(read("index.html")).toContain('<link rel="icon" type="image/svg+xml" href="/favicon.svg">');
  expect(statSync("dist/favicon.svg").size).toBeLessThan(2048);
  expect(read("favicon.svg")).toContain('viewBox="0 0 16 16"');
});

it("gives every page canonical, description and preview metadata", async () => {
  const paths = readdirSync("dist", { recursive: true, encoding: "utf8" }).filter(path => path.endsWith(".html"));
  for (const path of paths) {
    const metadata = await page.evaluate(html => {
      const doc = new DOMParser().parseFromString(html, "text/html");
      const content = (selector: string) => doc.querySelector(selector)?.getAttribute("content");
      return { title: doc.title, description: content('meta[name="description"]'),
        canonical: doc.querySelector('link[rel="canonical"]')?.getAttribute("href"),
        ogTitle: content('meta[property="og:title"]'), ogDescription: content('meta[property="og:description"]'),
        ogUrl: content('meta[property="og:url"]'), ogType: content('meta[property="og:type"]'),
        image: content('meta[property="og:image"]'), width: content('meta[property="og:image:width"]'),
        height: content('meta[property="og:image:height"]'), alt: content('meta[property="og:image:alt"]'),
        site: content('meta[property="og:site_name"]'), card: content('meta[name="twitter:card"]'),
        themes: [...doc.querySelectorAll('meta[name="theme-color"]')].map(el => [el.getAttribute("media"), el.getAttribute("content")]) };
    }, read(path));
    expect(metadata.description, path).toBeTruthy();
    expect(metadata.description!.length, path).toBeLessThanOrEqual(160);
    expect(metadata.canonical).toBe(`https://trendbio.dev/${path.replace(/index\.html$/, "")}`);
    expect(metadata.ogTitle).toBe(metadata.title);
    expect(metadata.ogDescription).toBe(metadata.description);
    expect(metadata.ogUrl).toBe(metadata.canonical);
    expect(metadata.ogType).toBe("website");
    expect(metadata.site).toBe("TrendBio");
    expect(metadata.card).toBe("summary_large_image");
    expect(metadata.image).toBe("https://trendbio.dev/og.png");
    expect(metadata.width).toBe("1200");
    expect(metadata.height).toBe("630");
    expect(metadata.alt).toBe(path.startsWith("ko/") ? "TrendBio — 계산생물학 연구 동향" : "TrendBio — What moved in computational biology");
    expect(metadata.themes).toEqual([["(prefers-color-scheme: dark)", "oklch(14.5% 0 0)"], ["(prefers-color-scheme: light)", "#fafafa"]]);
  }
  expect(read("index.html")).toContain(truncateDescription(`Today's leading computational biology topic: ${days[0].ranked[0].headline}.`));
  expect(read(`day/${days[0].date}/index.html`)).toContain(truncateDescription(`Top ${days[0].ranked.length} computational-biology topics on ${days[0].date}: ${days[0].ranked[0].headline}`));
});

it("builds valid XML covering the index and every public HTML route with lastmod dates", async () => {
  const parsed = await page.evaluate(xml => {
    const doc = new DOMParser().parseFromString(xml, "application/xml");
    return { error: doc.querySelector("parsererror")?.textContent,
      entries: [...doc.querySelectorAll("url")].map(el => ({ loc: el.querySelector("loc")?.textContent, date: el.querySelector("lastmod")?.textContent })) };
  }, read("sitemap.xml"));
  expect(parsed.error).toBeUndefined();
  const { weeks, months } = loadPeriods();
  const topicSlugs = new Set([...rankedTopics.map(topic => topic.slug), ...[...weeks, ...months].flatMap(period => period.topics.map(topic => topic.slug))]);
  const fieldPages = editions.reduce((n, field) => n + 1 + getDataIndex(field).days.length, 0);
  expect(parsed.entries).toHaveLength(2 * (7 + fieldPages + days.length + weeks.length + months.length + topicSlugs.size));
  const urls = new Map(parsed.entries.map(({ loc, date }) => [loc, date]));
  expect(urls.size).toBe(parsed.entries.length);
  for (const path of readdirSync("dist", { recursive: true, encoding: "utf8" }).filter(path => path.endsWith("index.html"))) {
    expect(urls.has(`https://trendbio.dev/${path.replace(/index\.html$/, "")}`), path).toBe(!/^(ko\/)?search\/index\.html$/.test(path));
  }
  for (const { date } of days) expect(urls.get(`https://trendbio.dev/day/${date}/`)).toBe(date);
  for (const topic of rankedTopics) expect(urls.get(`https://trendbio.dev/topic/${topic.slug}/`))
    .toBe(topic.history.filter(({ rank }) => rank !== null).map(({ date }) => date).sort().at(-1));
  for (const { date } of parsed.entries) expect(date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(read("robots.txt")).toContain("Sitemap: https://trendbio.dev/sitemap.xml");
});

it("renders native open and closed summary labels and adjacent existing days", async () => {
  const latest = read(`day/${days[0].date}/index.html`);
  expect(latest).toMatch(/<summary[^>]*><span class="closed-label"[^>]*>Show 20 more<\/span><span class="open-label"[^>]*>Show less<\/span><\/summary>/);
  for (const [index, day] of days.entries()) {
    await page.setContent(read(`day/${day.date}/index.html`));
    const nav = page.getByRole("navigation", { name: "Day navigation", exact: true });
    for (const [rel, target] of [["prev", days[index + 1]], ["next", days[index - 1]]] as const) {
      const link = nav.locator(`a[rel="${rel}"]`);
      expect(await link.count()).toBe(target ? 1 : 0);
      if (target) expect(await link.getAttribute("href")).toBe(`/day/${target.date}/`);
    }
  }
  await page.setContent(read("archive/index.html"));
  expect(await page.locator(`#heading-${days[0].date.slice(0, 7)}`).textContent()).toBe("November 2026 in progress");
});

it("ships one PNG link preview at 1200×630 under 200 KB", () => {
  const png = readFileSync("dist/og.png");
  expect(png.subarray(1, 4).toString()).toBe("PNG");
  expect(png.readUInt32BE(16)).toBe(1200);
  expect(png.readUInt32BE(20)).toBe(630);
  expect(png.length).toBeLessThan(200_000);
  expect(png.equals(readFileSync("public/og.png"))).toBe(true);
});

it("explains cookie-free page-view analytics on About", () => {
  expect(read("about/index.html")).toContain("The site uses Cloudflare Web Analytics, which sets no cookies, to count page views.");
});

it("links the Physics edition, its dated ranking and its own supporting papers", async () => {
  await page.setContent(read("index.html"));
  expect(await page.getByRole("navigation").getByText("Physics", { exact: true }).getAttribute("href")).toBe("/physics/");
  for (const path of ["physics/index.html", "physics/day/2026-11-01/index.html"]) {
    await page.setContent(read(path));
    const main = page.locator("main");
    expect(await main.locator("h1").textContent()).toBe("Physics");
    expect(await main.locator("ol h3").textContent()).toBe("Optical cavities reveal sources of readout noise");
    expect(await main.locator('a[href^="https://example.org/physics/"]').count()).toBe(3);
    const archiveLink = path === "physics/index.html" ? "/physics/day/2026-11-01/" : "/physics/#editions";
    expect(await main.locator(`a[href="${archiveLink}"]`).count()).toBe(1);
  }
});

it("opens the downloaded English and Korean pilot files offline at the same ranked topic", async () => {
  const folder = mkdtempSync(join(tmpdir(), "trendbio-pilot-preview-"));
  const offline = await browser.newPage();
  try {
    execFileSync(process.execPath, ["scripts/pilot-preview.mjs", "dist", "../fixtures/data/physics/days/2026-11-01.json", folder]);
    const slug = getDataIndex("physics").days[0].ranked[0].slug;
    await offline.goto(pathToFileURL(join(folder, "en.html")).href + "#" + slug);
    await offline.getByRole("link", { name: "한국어" }).click();
    expect(offline.url()).toBe(pathToFileURL(join(folder, "ko.html")).href + "#" + slug);
    expect(await offline.locator("html").getAttribute("lang")).toBe("ko");
    expect(await offline.locator(":target").getAttribute("value")).toBe("1");
    expect(await offline.locator("main .rankings h3").textContent()).toMatch(/[가-힣]/);
    await offline.locator("main details summary").click();
    expect(await offline.locator('main details a[href^="https://example.org/physics/"]').count()).toBe(3);
    await offline.getByRole("link", { name: "English" }).click();
    expect(offline.url()).toBe(pathToFileURL(join(folder, "en.html")).href + "#" + slug);
  } finally {
    await offline.close();
    rmSync(folder, { recursive: true, force: true });
  }
});

it("pairs the same dated rankings in Korean and English and retains the evidence links", async () => {
  const path = "/physics/day/2026-11-01/";
  let englishPapers: string[] = [];
  for (const [lang, prefix, heading] of [["en", "", "Physics"], ["ko", "/ko", "물리학"]]) {
    await page.setContent(read(`${prefix}${path}index.html`.slice(1)));
    expect(await page.locator("html").getAttribute("lang")).toBe(lang);
    expect(await page.locator("main h1").textContent()).toBe(heading);
    expect(await page.locator("[data-language][aria-current]").getAttribute("data-language")).toBe(lang);
    for (const [code, target] of [["en", path], ["ko", "/ko" + path]]) {
      expect(await page.locator(`a[data-language=${code}]`).getAttribute("href")).toBe(target);
      expect(await page.locator(`link[hreflang=${code}]`).getAttribute("href")).toBe("https://trendbio.dev" + target);
    }
    const rows = page.locator("ol.rankings > li");
    expect(await rows.count()).toBe(1);
    const papers = await rows.locator('a[href^="https://example.org/physics/"]').evaluateAll(links => links.map(link => link.getAttribute("href")!));
    if (lang === "en") { englishPapers = papers; continue; }
    expect(papers).toEqual(englishPapers);
    expect(await rows.locator("h3").textContent()).toMatch(/[가-힣]/);
    expect(await rows.locator("p").first().textContent()).toMatch(/[가-힣]/);
    expect(await rows.locator("summary").textContent()).toBe("근거 논문 3편");
    expect(await page.locator('main a[href="/ko/physics/#editions"]').count()).toBe(1);
  }
});

it("reads the counts and the four-week comparison in Korean", async () => {
  await page.setContent(read("ko/day/2026-10-30/index.html"));
  const daily = await page.locator(".signal-line .sr-only").first().textContent();
  expect(daily).toContain("프리프린트 1편");
  expect(daily).toContain("최근 4주 평균의 4.3배");
  await page.setContent(read("ko/week/2026-W44/index.html"));
  expect(await page.locator(".signal-line .sr-only").first().textContent()).toMatch(/순위 진입 \d+일 · 최고 \d+위 · 자료 \d+건 · 증가율 [\d.]+배/);
});

it("preserves original book titles and distinguishes catalogue and text rights in both languages", async () => {
  const route = "/humanities-arts/day/2026-11-01/";
  let englishLinks: string[] = [];
  for (const [prefix, count, metadata, rights] of [
    ["", "3 supporting works", "Catalogue metadata (CC0)", "License for the work"],
    ["/ko", "근거 문헌 3건", "서지 정보 이용 조건(CC0)", "저작물 이용 조건"],
  ]) {
    await page.setContent(read((prefix + route).slice(1) + "index.html"));
    const picker = page.locator(".pilot-fields");
    await picker.locator("summary").click();
    expect(await picker.locator('a[aria-current="true"]').getAttribute("href")).toBe(prefix + "/humanities-arts/");
    const list = page.locator("ol.rankings");
    expect(await list.locator("summary").textContent()).toBe(count);
    expect(await list.getByText("Liederhandschriften").textContent()).toBe("Liederhandschriften");
    expect(await list.locator("cite").textContent()).toBe("Chansons en manuscrit");
    const book = list.locator("details ul > li").first();
    expect(await book.getByRole("link", { name: metadata, includeHidden: true }).getAttribute("href")).toBe("https://creativecommons.org/publicdomain/zero/1.0/");
    expect(await book.getByRole("link", { name: rights, includeHidden: true }).getAttribute("href")).toBe("https://creativecommons.org/licenses/by-nc/4.0/");
    const links = await list.locator("a").evaluateAll(elements => elements.map(a => a.href));
    if (prefix) expect(links).toEqual(englishLinks);
    else englishLinks = links;
  }
});

it("publishes a Korean topic map and a distinct valid Korean Atom feed", async () => {
  const map = JSON.parse(read("map.json"));
  const koMap = JSON.parse(read("ko/map.json"));
  expect(koMap.points.map((point: { slug: string }) => point.slug)).toEqual(map.points.map((point: { slug: string }) => point.slug));
  expect(koMap.points.some((point: { headline: string }) => /[가-힣]/.test(point.headline))).toBe(true);
  await page.setContent(read("ko/map/index.html"));
  const point = koMap.points[0];
  const label = await page.locator(`.map-links a[href="/ko/topic/${point.slug}/"]`).textContent();
  expect(label).toContain(point.headline + " — ");
  expect(label).toMatch(/마지막 순위 진입 \d{4}년 \d+월 \d+일$/);
  const feed = await page.evaluate(xml => {
    const doc = new DOMParser().parseFromString(xml, "application/xml");
    return { valid: !doc.querySelector("parsererror"), lang: doc.documentElement.getAttribute("xml:lang"),
      title: doc.querySelector("entry title")?.textContent, link: doc.querySelector("entry link")?.getAttribute("href") };
  }, read("ko/feed.xml"));
  expect(feed).toMatchObject({ valid: true, lang: "ko" });
  expect(feed.title).toMatch(/[가-힣]/);
  expect(feed.link).toMatch(/^https:\/\/trendbio\.dev\/ko\//);
});

it("keeps the Biology beta and CompBio as distinct editions", async () => {
  for (const [path, current] of [["biology/index.html", "All Biology (beta)"], ["index.html", "CompBio"]]) {
    await page.setContent(read(path));
    const switcher = page.getByRole("group", { name: "Biology edition" });
    expect(await switcher.locator("[aria-current]").textContent()).toBe(current);
    expect(await switcher.getByText("All Biology (beta)").getAttribute("href")).toBe("/biology/");
    expect(await switcher.getByText("CompBio").getAttribute("href")).toBe("/");
  }
});

it("links the mathematics pilot to its three arXiv subjects and its own dated evidence", async () => {
  await page.setContent(read("math/day/2026-11-01/index.html"));
  expect(await page.getByRole("group", { name: "Science field" }).locator("[aria-current]").textContent()).toBe("Math & Stats");
  expect(await page.getByRole("group", { name: "Biology edition" }).count()).toBe(0);
  const main = page.getByRole("main");
  expect(await main.locator(".coverage a").evaluateAll(links => links.map(a => a.getAttribute("href")))).toEqual(
    ["math.NT", "math.NA", "stat.ME"].map(code => `https://arxiv.org/list/${code}/recent`));
  expect(await main.locator('a[href^="https://example.org/math/"]').count()).toBe(3);
  expect(await main.getByRole("heading", { name: "Quadrature error bounds depend on smoothness" }).count()).toBe(1);
});

it("credits the Earth pilot papers and links their datasets as supporting material", async () => {
  await page.setContent(read("earth-environment/day/2026-11-01/index.html"));
  const main = page.getByRole("main");
  expect(await main.locator(".coverage").textContent()).toContain("Ocean Science");
  expect(await main.locator("summary").first().textContent()).toBe("3 supporting papers");
  await main.locator("summary").first().click();
  expect(await main.locator('a[href^="https://example.org/earth/"]').count()).toBe(3);
  expect(await main.getByRole("link", { name: "CC BY" }).count()).toBe(3);
  expect(await main.locator('a[href="https://doi.org/10.5555/example-data"]').count()).toBe(1);
});
