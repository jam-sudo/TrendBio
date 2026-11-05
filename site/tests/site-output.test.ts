import { readFileSync, readdirSync, statSync } from "node:fs";
import { chromium, type Browser, type Page } from "playwright";
import { afterAll, beforeAll, expect, it } from "vitest";
import { getDataIndex } from "../src/lib/data";
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
    expect(metadata.card).toBe("summary");
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
  expect(parsed.entries).toHaveLength(7 + days.length + weeks.length + months.length + topicSlugs.size);
  const urls = new Map(parsed.entries.map(({ loc, date }) => [loc, date]));
  expect(urls.size).toBe(parsed.entries.length);
  for (const path of readdirSync("dist", { recursive: true, encoding: "utf8" }).filter(path => path.endsWith("index.html"))) {
    expect(urls.has(`https://trendbio.dev/${path.replace(/index\.html$/, "")}`), path).toBe(true);
  }
  for (const { date } of days) expect(urls.get(`https://trendbio.dev/day/${date}/`)).toBe(date);
  for (const topic of rankedTopics) expect(urls.get(`https://trendbio.dev/topic/${topic.slug}/`))
    .toBe(topic.history.filter(({ rank }) => rank !== null).map(({ date }) => date).sort().at(-1));
  for (const { date } of parsed.entries) expect(date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(read("robots.txt")).toContain("Sitemap: https://trendbio.dev/sitemap.xml");
});

it("preserves email_off immediately around all mailto anchors", () => {
  for (const path of ["index.html", "about/index.html"]) {
    const html = read(path);
    const protectedAnchors = html.match(/<!--email_off-->\s*<a\b[^>]*href="mailto:[^"]+"[^>]*>[\s\S]*?<\/a>\s*<!--\/email_off-->/g) ?? [];
    expect(protectedAnchors.length).toBeGreaterThan(0);
    expect(protectedAnchors).toHaveLength((html.match(/href="mailto:/g) ?? []).length);
  }
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
