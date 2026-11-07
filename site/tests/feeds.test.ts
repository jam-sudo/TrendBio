import { readFileSync } from "node:fs";
import { afterAll, beforeAll, expect, it } from "vitest";
import { chromium, type Browser, type Page } from "playwright";
import { atomFeed } from "../src/lib/feeds";
import { loadDays, loadTaxonomy } from "../src/lib/data";
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
    expect(feed.entries.map(entry => entry.id)).toEqual(expected.map(({ row, day }) => `tag:trendbio.dev,${day.date}:${row.slug}`));
    expect(feed.entries.map(entry => entry.link)).toEqual(expected.map(({ row }) => `https://trendbio.dev/topic/${row.slug}/`));
    expect(new Set(feed.entries.map(entry => entry.id)).size).toBe(expected.length);
  }
  expect(readFileSync("dist/feed.xml", "utf8")).toContain("Tools: atlas, BetaTool 2.0, DeltaTool.");
  expect(readFileSync("dist/sitemap.xml", "utf8")).not.toContain("/feed");
  expect(readFileSync("dist/index.html", "utf8")).toContain('type="application/atom+xml"');
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
