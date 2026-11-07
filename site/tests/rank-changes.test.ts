import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { preview } from "astro";
import AxeBuilder from "@axe-core/playwright";
import { chromium, type Browser } from "playwright";
import { afterAll, beforeAll, expect, it } from "vitest";
import { rankChanges } from "../src/lib/rank-changes";
import { loadDays, allTopics } from "../src/lib/data";
import fixtures from "./fixtures/rank-changes.json";

const base = loadDays("computational")[0];
const days = fixtures.map(fixture => ({ ...base, date: fixture.date, ranked: Object.entries(fixture.rows)
  .map(([slug, rank]) => ({ ...base.ranked[0], slug, rank: rank!, headline: `Rank marker: ${slug}` })) }));
const topics = days.at(-1)!.ranked.map(row => ({ ...allTopics("computational")[0], slug: row.slug, related: [],
  history: days.flatMap(day => {
    const rank = day.ranked.find(entry => entry.slug === row.slug)?.rank;
    return rank === undefined ? [] : [{ ...allTopics("computational")[0].history[0], date: day.date, rank, item_ids: [] }];
  }) }));
let browser: Browser, server: Awaited<ReturnType<typeof preview>>, root: string;
beforeAll(async () => {
  root = mkdtempSync(resolve(".rank-test-"));
  for (const [kind, entries] of [["days", days], ["topics", topics]] as const) {
    mkdirSync(join(root, "data/computational", kind), { recursive: true });
    for (const entry of entries) writeFileSync(join(root, "data/computational", kind, `${"date" in entry ? entry.date : entry.slug}.json`), JSON.stringify(entry));
  }
  execFileSync(process.execPath, ["node_modules/astro/astro.js", "build", "--outDir", join(root, "dist")], {
    env: { ...process.env, TRENDBIO_DATA_ROOT: join(root, "data") }, stdio: "pipe",
  });
  server = await preview({ outDir: join(root, "dist"), server: { host: "127.0.0.1", port: 4332 }, logLevel: "error" });
  browser = await chromium.launch();
});
afterAll(async () => { await browser?.close(); await server?.stop(); if (root) rmSync(root, { recursive: true, force: true }); });

it("compares the previous stored day, distinguishes first-ever from returning and omits unchanged/first-day markers", () => {
  const changes = rankChanges(days[2], days, topics);
  expect([...changes].map(([slug, change]) => [slug, change.label])).toEqual([
    ["new", "New"], ["up", "▲3"], ["down", "▼2"], ["back", "Back"],
  ]);
  expect(changes.get("up")?.description).toBe("Up 3 places since the previous day");
  expect(rankChanges(days[0], days, topics).size).toBe(0);
  const withHistory = structuredClone(topics);
  withHistory[0].history.unshift({ ...withHistory[0].history[0], date: "2026-09-01", rank: 40 });
  expect(rankChanges(days[2], days, withHistory).get("new")?.label).toBe("Back");
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
          const row = page.locator("article[data-topic-cats]").filter({ has: page.locator(`a[href="/topic/${slug}/"]`) });
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
