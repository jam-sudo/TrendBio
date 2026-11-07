import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { chromium, type Browser, type Page } from "playwright";
import { atomFeed } from "../src/lib/feeds";
import { industryItems, loadDays, loadTaxonomy } from "../src/lib/data";
import sample from "./fixtures/feed.json";

let browser: Browser, page: Page;
beforeAll(async () => { browser = await chromium.launch(); page = await browser.newPage(); });
afterAll(async () => { await browser?.close(); });
const parse = (xml: string) => page.evaluate(xml => {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  return { error: doc.querySelector("parsererror")?.textContent,
    self: doc.querySelector('feed > link[rel="self"]')?.getAttribute("href"),
    updated: doc.querySelector("feed > updated")?.textContent,
    entries: [...doc.querySelectorAll("entry")].map(entry => ({
      id: entry.querySelector("id")?.textContent, title: entry.querySelector("title")?.textContent,
      summary: entry.querySelector("summary")?.textContent, updated: entry.querySelector("updated")?.textContent,
      link: entry.querySelector("link")?.getAttribute("href"),
      author: entry.querySelector("author name")?.textContent,
    })) };
}, xml);

it("builds parseable Atom feeds with stable IDs, category filtering and absolute links", async () => {
  const days = loadDays("computational").slice(0, 30);
  for (const category of [undefined, ...loadTaxonomy("computational")]) {
    const path = category ? `feed/${category.slug}.xml` : "feed.xml";
    const feed = await parse(readFileSync(`dist/${path}`, "utf8"));
    const expected = days.flatMap(day => day.ranked.filter(row => category ? row.category === category.slug : row.rank <= 5)
      .map(row => ({ row, day }))).slice(0, category ? 100 : 150);
    expect(feed.error).toBeUndefined();
    expect(feed.self).toBe(`https://trendbio.dev/${path}`);
    expect(feed.updated).toBe(days[0].run.finished);
    if (category?.slug === "industry") {
      const items = industryItems("computational", days[0].date, 30, 100);
      expect(items.length).toBeGreaterThan(0);
      expect(feed.entries).toEqual(items.map(item => ({
        id: `tag:trendbio.dev,${item.first_seen}:${item.id}`, title: item.title, link: item.url,
        summary: item.summary ?? "", author: item.org ?? "TrendBio", updated: `${item.first_seen}T00:00:00Z`,
      })));
      continue;
    }
    expect(feed.entries.map(entry => entry.id)).toEqual(expected.map(({ row, day }) => `tag:trendbio.dev,${day.date}:${row.slug}`));
    expect(feed.entries.map(entry => entry.link)).toEqual(expected.map(({ row }) => `https://trendbio.dev/topic/${row.slug}/`));
    expect(new Set(feed.entries.map(entry => entry.id)).size).toBe(expected.length);
  }
  expect(readFileSync("dist/feed.xml", "utf8")).toContain("Tools: atlas, BetaTool 2.0, DeltaTool.");
  expect(readFileSync("dist/sitemap.xml", "utf8")).not.toContain("/feed");
  expect(readFileSync("dist/index.html", "utf8")).toContain('type="application/atom+xml"');
});

it("uses relevant company posts from the inclusive last 30 days, newest first, capped at 100", async () => {
  const root = mkdtempSync(resolve(".industry-feed-test-"));
  const base = loadDays("computational")[0];
  const category = { slug: "industry", label: "Industry" };
  const item = { type: "industry", title: "Company & lab <news>", summary: "New tools & models <announced>",
    org: "A & B <Labs>", url: "https://example.org/post?a=1&b=2", published_at: "2020-01-01", relevant: true };
  try {
    const directory = join(root, "computational/items/2026/11");
    mkdirSync(directory, { recursive: true });
    const entries = [
      { id: "rss:boundary", first_seen: "2026-10-03" },
      { id: "rss:recent", first_seen: "2026-11-01" },
      { id: "rss:old", first_seen: "2026-10-02" },
      { id: "rss:future", first_seen: "2026-11-02" },
      { id: "rss:irrelevant", first_seen: "2026-11-01", relevant: false },
    ];
    for (const entry of entries) writeFileSync(join(directory, entry.id.replace(":", "_") + ".json"), JSON.stringify({ ...item, ...entry }));
    vi.stubEnv("TRENDBIO_DATA_ROOT", root);
    vi.resetModules();
    const { atomFeed: feed } = await import("../src/lib/feeds");
    const parsed = await parse(feed([base], new URL("https://trendbio.dev"), category));
    expect(parsed.error).toBeUndefined();
    expect(parsed.entries.map(entry => entry.id)).toEqual(["tag:trendbio.dev,2026-11-01:rss:recent", "tag:trendbio.dev,2026-10-03:rss:boundary"]);
    expect(parsed.entries[0]).toMatchObject({ title: item.title, summary: item.summary, author: item.org, link: item.url });
    expect((await parse(feed([], new URL("https://trendbio.dev"), category))).entries).toEqual([]);

    const cappedRoot = join(root, "capped");
    const cappedDirectory = join(cappedRoot, "computational/items/2026/11");
    mkdirSync(cappedDirectory, { recursive: true });
    for (let i = 0; i < 105; i++) writeFileSync(join(cappedDirectory, `rss_${i}.json`),
      JSON.stringify({ ...item, id: `rss:${i}`, first_seen: "2026-11-01" }));
    vi.stubEnv("TRENDBIO_DATA_ROOT", cappedRoot);
    vi.resetModules();
    const { atomFeed: cappedFeed } = await import("../src/lib/feeds");
    expect((await parse(cappedFeed([base], new URL("https://trendbio.dev"), category))).entries).toHaveLength(100);
  } finally {
    vi.unstubAllEnvs();
    vi.resetModules();
    rmSync(root, { recursive: true, force: true });
  }
});

it("caps at 30 stored days and 100 category entries, escapes XML and falls back to the date", async () => {
  const base = loadDays("computational")[0];
  const days = Array.from({ length: 40 }, (_, i) => ({ ...base, date: new Date(Date.UTC(2026, 9, i + 1)).toISOString().slice(0, 10),
    run: { ...base.run, finished: "" }, ranked: base.ranked.slice(0, 8).map(row => ({ ...row, ...sample })) }));
  const main = await parse(atomFeed(days, new URL("https://trendbio.dev")));
  const category = await parse(atomFeed(days, new URL("https://trendbio.dev"), { slug: sample.category, label: "A & B < C" }));
  expect(main.error).toBeUndefined();
  expect(category.error).toBeUndefined();
  expect(main.entries).toHaveLength(150);
  expect(category.entries).toHaveLength(100);
  expect(main.entries[0].title).toBe(sample.headline);
  expect(main.entries[0].summary).toBe(sample.summary);
  expect(main.entries[0].updated).toBe("2026-11-09T00:00:00Z");
  expect(main.entries.at(-1)?.id).toContain(",2026-10-11:");
  expect(category.entries.some(entry => entry.id?.endsWith(days[0].ranked[7].slug))).toBe(true);
});

it("sets the Atom MIME type in endpoints and in the static hosting headers", async () => {
  const context = { site: new URL("https://trendbio.dev"), props: { category: loadTaxonomy("computational")[0] } };
  for (const endpoint of [await import("../src/pages/feed.xml"), await import("../src/pages/feed/[category].xml")]) {
    const response = await endpoint.GET(context as Parameters<typeof endpoint.GET>[0]);
    expect(response.headers.get("Content-Type")).toBe("application/atom+xml; charset=utf-8");
  }
  expect(readFileSync("dist/_headers", "utf8")).toContain("/feed.xml\n  Content-Type: application/atom+xml; charset=utf-8\n/feed/*\n  Content-Type: application/atom+xml; charset=utf-8");
});
