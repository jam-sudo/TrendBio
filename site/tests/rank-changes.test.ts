import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { preview } from "astro";
import AxeBuilder from "@axe-core/playwright";
import { chromium, type Browser } from "playwright";
import { afterAll, beforeAll, expect, it } from "vitest";
import { editionChanges } from "../src/lib/rank-changes";
import { loadDays, allTopics, loadItems } from "../src/lib/data";
import fixtures from "./fixtures/rank-changes.json";

const base = loadDays("computational")[0];
const days = fixtures.map(fixture => ({ ...base, date: fixture.date, ranked: Object.entries(fixture.rows)
  .map(([slug, rank]) => ({ ...base.ranked[0], slug, rank: rank!, headline: `Rank marker: ${slug}` })) }));
const [retained, added] = loadItems("computational", ["arxiv:fixture-02-02", "arxiv:fixture-01-08"]);
const topics = days.at(-1)!.ranked.map(row => ({ ...allTopics("computational")[0], slug: row.slug, related: [],
  history: days.flatMap(day => {
    const rank = day.ranked.find(entry => entry.slug === row.slug)?.rank;
    const ids = row.slug === "up" ? (day === days[2] ? [retained.id, added.id] : [retained.id]) : [];
    return rank === undefined ? [] : [{ ...allTopics("computational")[0].history[0], date: day.date, rank, item_ids: ids }];
  }) }));
let browser: Browser, server: Awaited<ReturnType<typeof preview>>, root: string;
beforeAll(async () => {
  root = mkdtempSync(resolve(".rank-test-"));
  const itemsDir = join(root, "data/computational/items");
  mkdirSync(itemsDir, { recursive: true });
  for (const item of [retained, added]) writeFileSync(join(itemsDir, item.id.replaceAll(":", "_") + ".json"), JSON.stringify(item));
  for (const [kind, entries] of [["days", days], ["topics", topics]] as const) {
    mkdirSync(join(root, "data/computational", kind), { recursive: true });
    for (const entry of entries) writeFileSync(join(root, "data/computational", kind, `${"date" in entry ? entry.date : entry.slug}.json`), JSON.stringify(entry));
  }
  execFileSync(process.execPath, ["node_modules/.bin/astro", "build", "--outDir", join(root, "dist")], {
    env: { ...process.env, TRENDBIO_DATA_ROOT: join(root, "data") }, stdio: "pipe",
  });
  server = await preview({ outDir: join(root, "dist"), server: { host: "127.0.0.1", port: 4332 }, logLevel: "error" });
  browser = await chromium.launch();
});
afterAll(async () => { await browser?.close(); await server?.stop(); if (root) rmSync(root, { recursive: true, force: true }); });

it("compares the previous stored day, distinguishes first-ever from returning and omits unchanged/first-day markers", () => {
  const { rows, previousDate, entered } = editionChanges(days[2], days, topics)!;
  const changes = [...rows].flatMap(([slug, row]) => row.rank ? [[slug, row.rank.label]] : []);
  expect(previousDate).toBe("2026-10-03");
  expect(entered).toBe(2);
  expect(changes).toEqual([
    ["new", "New"], ["up", "▲3"], ["down", "▼2"], ["back", "Back"],
  ]);
  expect(rows.get("up")?.rank?.description).toBe("Up 3 places since the previous edition");
  expect(editionChanges(days[0], days, topics)).toBeNull();
  const withHistory = structuredClone(topics);
  withHistory[0].history.unshift({ ...withHistory[0].history[0], date: "2026-09-01", rank: 40 });
  expect(editionChanges(days[2], days, withHistory)?.rows.get("new")?.rank?.label).toBe("Back");
});

it("recognizes a top-ten crossing and counts distinct newly supporting papers even when another leaves", () => {
  const editedDays = structuredClone(days);
  editedDays[1].ranked.find(row => row.slug === "up")!.rank = 11;
  const editedTopics = structuredClone(topics);
  const history = editedTopics.find(topic => topic.slug === "up")!.history;
  history.find(entry => entry.date === days[1].date)!.item_ids = ["arxiv:fixture-02-02"];
  history.find(entry => entry.date === days[2].date)!.item_ids = ["arxiv:fixture-01-08", "arxiv:fixture-01-08", "missing"];
  const changes = editionChanges(days[2], editedDays, editedTopics)!;
  expect(changes.entered).toBe(3);
  expect(changes.rows.get("up")).toMatchObject({ entered: true, addedPaperIds: new Set(["arxiv:fixture-01-08"]), rank: { label: "▲5" } });
  expect(changes.rows.get("new")?.addedPaperIds.size).toBe(0);
});

it("opens the papers behind an addition badge and places the new paper first with its comparison date", async () => {
  const page = await browser.newPage();
  try {
    await page.goto(`http://127.0.0.1:${server.port}/`);
    await page.locator("#up").getByRole("link", { name: "+1 supporting paper", exact: true }).click();
    expect(new URL(page.url()).pathname).toBe("/day/2026-10-06/papers/");
    const lists = page.locator("section:target details > ul");
    expect(await lists.first().getAttribute("aria-label")).toBe("Added since 2026-10-03");
    expect(await lists.first().locator("li a").getAttribute("href")).toBe(added.url);
    expect(await lists.nth(1).locator("li a").getAttribute("href")).toBe(retained.url);
    await page.goto(`http://127.0.0.1:${server.port}/day/2026-10-01/papers/#up`);
    expect(await page.locator(':target ul[aria-label^="Added since"]').count()).toBe(0);
  } finally { await page.close(); }
});

it.each(["dark", "light"])("renders each marker without clipping at 320, 390 and 1280px with clean axe in %s", async theme => {
  const context = await browser.newContext();
  const page = await context.newPage();
  try {
    await page.addInitScript(theme => localStorage.setItem("trendbio-theme", theme), theme);
    for (const width of [320, 390, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      for (const path of ["/", "/day/2026-10-06/"]) {
        await page.goto(`http://127.0.0.1:${server.port}${path}`);
        for (const [slug, label] of [["new", "New"], ["back", "Back"], ["up", "▲3"], ["down", "▼2"], ["same", ""]]) {
          const row = page.locator(`article[data-topic-cats][id="${slug}"]`);
          const marker = row.locator(".rank-change");
          expect(await marker.count()).toBe(label ? 1 : 0);
          if (label) {
            expect(await marker.locator('[aria-hidden="true"]').textContent()).toBe(label);
            expect(await marker.locator(".sr-only").textContent()).toBeTruthy();
          }
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
        expect(await page.locator(".rank-change, .compact-meta, .row-meta").evaluateAll(elements => elements
          .filter(el => el.clientWidth > 0 && (el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight)).map(el => el.className))).toEqual([]);
        expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()).violations).toEqual([]);
        if (path === "/" && theme === "dark" && width !== 320) {
          mkdirSync(".playwright-shots", { recursive: true });
          await page.screenshot({ path: `.playwright-shots/rank-markers-${width}.png`, fullPage: true });
        }
      }
    }
    for (const path of ["day/2026-10-01/index.html", "week/index.html", "topics/index.html"]) {
      expect(readFileSync(join(root, "dist", path), "utf8")).not.toContain('class="rank-change"');
    }
  } finally { await context.close(); }
});
