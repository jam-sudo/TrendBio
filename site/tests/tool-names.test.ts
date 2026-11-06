import { readFileSync, readdirSync } from "node:fs";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { chromium, type Browser, type Page } from "playwright";
import { extractToolName, selectToolNames, TOOL_NAME_STOPLIST } from "../src/lib/tool-names";
import { allTopics, loadDay, loadTaxonomy } from "../src/lib/data";
import { dailyRows } from "../src/lib/leaderboard";
import { rankPeriod } from "../src/lib/periods";
import type { Item } from "../src/lib/types";

const items = readdirSync("tests/fixtures/tool-names", { recursive: true, encoding: "utf8" })
  .filter(path => path.endsWith(".json"))
  .map(path => JSON.parse(readFileSync(`tests/fixtures/tool-names/${path}`, "utf8")) as Item);

describe("paper title names", () => {
  it.each([
    [" AlphaFold 2.0: structure prediction", "AlphaFold 2.0"], ["2b+: a method", "2b+"],
    ["ab: description", "ab"], ["A".repeat(25) + ": description", "A".repeat(25)],
    ["A".repeat(26) + ": description", null], ["a: description", null],
    ["Two Words: description", null], ["AlphaFold without a colon", null],
    ["AlphaFold:no space", null], ["-Alpha: description", null],
  ])("extracts %s", (title, expected) => expect(extractToolName(title)).toBe(expected));

  it("rejects every stoplisted word case-insensitively, including version suffixes", () => {
    for (const word of TOOL_NAME_STOPLIST) {
      expect(extractToolName(`${word.toUpperCase()}: description`)).toBeNull();
      expect(extractToolName(`${word} 2.0: description`)).toBeNull();
    }
  });

  it("deduplicates case-insensitively, prefers published papers, sorts and caps at three", () => {
    const cohort = items.filter(item => item.id.includes('02000') || item.id.includes('fixture-02'));
    const selected = selectToolNames(cohort, 1);
    expect(selected.map(({ name }) => name)).toEqual(["atlas", "BetaTool 2.0", "DeltaTool"]);
    expect(selected[0].url).toBe(cohort.find(item => item.type === "published")!.url);
    expect(selectToolNames(cohort.map(item => ({ ...item, type: "code" })), 1)).toEqual([]);
    expect(selectToolNames(cohort.map(item => ({ ...item, type: "industry" })), 1)).toEqual([]);
    expect(selectToolNames(cohort, 20)).toHaveLength(3);
    expect(selectToolNames(cohort, 21)).toEqual([]);
    expect(selectToolNames([
      { ...cohort[0], title: "Alpha: preprint", type: "preprint" },
      { ...cohort[0], title: "Zulu: published", type: "published" },
      { ...cohort[0], title: "Omega: published", type: "published" },
    ], 1).map(({ name }) => name)).toEqual(["Omega", "Zulu", "Alpha"]);
  });

  it("uses the exact daily history and the latest history inside a period", () => {
    const topics = structuredClone(allTopics("computational"));
    for (const topic of topics) topic.history.reverse();
    for (const row of rankPeriod(topics, "2026-10-26", "2026-10-31", loadTaxonomy("computational"))) {
      const latest = topics.find(topic => topic.slug === row.slug)!.history
        .filter(entry => entry.date >= "2026-10-26" && entry.date <= "2026-10-31")
        .sort((a, b) => a.date.localeCompare(b.date)).at(-1)!;
      expect(row.latest_item_ids).toEqual(latest.item_ids);
    }
    const day = structuredClone(loadDay("computational", "2026-11-01")!);
    day.date = "1900-01-01";
    expect(dailyRows(day).every(row => row.toolNames.length === 0)).toBe(true);
  });
});

describe("built tool names", () => {
  let browser: Browser, page: Page;
  beforeAll(async () => { browser = await chromium.launch(); page = await browser.newPage(); });
  afterAll(async () => { await browser?.close(); });

  it.each(["index.html", "day/2026-11-01/index.html", "week/2026-W44/index.html", "month/2026-11/index.html"])(
    "renders linked names without empty elements or nested anchors on %s", async path => {
      const html = readFileSync(`dist/${path}`, "utf8");
      // Check source too: HTML parsers silently repair nested anchors.
      let depth = 0;
      for (const [tag] of html.matchAll(/<\/?a\b[^>]*>/g)) {
        depth += tag.startsWith("</") ? -1 : 1;
        expect(depth).toBeGreaterThanOrEqual(0);
        expect(depth).toBeLessThanOrEqual(1);
      }
      expect(depth).toBe(0);
      await page.setContent(html);
      const rows = page.locator("[data-topic-cats]");
      expect(await rows.count()).toBe(40);
      expect(await page.locator("a a").count()).toBe(0);
      expect(await page.locator(".tool-names:empty").count()).toBe(0);
      for (const row of await rows.all()) {
        const rank = Number((await row.locator(".rank").textContent())!.replace(/\D/g, ""));
        expect(await row.locator(".tool-names a").count()).toBeLessThanOrEqual(rank <= 20 ? 3 : 0);
      }
      const first = rows.filter({ has: page.locator('a[href="/topic/single-cell-perturbations-c3d4/"]') });
      expect(await first.locator(".tool-names a").allTextContents()).toEqual(["atlas", "BetaTool 2.0", "DeltaTool"]);
      for (const link of await page.locator(".tool-names a").all()) {
        expect(await link.getAttribute("target")).toBe("_blank");
        expect(await link.getAttribute("rel")).toBe("noopener");
      }
      const unnamed = rows.filter({ has: page.locator('a[href="/topic/protein-design-binders-a1b2/"]') });
      expect(await unnamed.locator(".tool-names").count()).toBe(0);
      if (path === "index.html") {
        expect(await rows.nth(19).locator(".tool-names").textContent()).toBe("BoundaryTool");
        expect(await rows.nth(20).locator(".tool-names").count()).toBe(0);
      }
    },
  );
});
