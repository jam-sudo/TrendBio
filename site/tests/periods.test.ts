import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { allTopics, loadDays, loadTaxonomy } from "../src/lib/data";
import { allMonths, allWeeks, indexHistories, isoWeekOf, monthOf, rankPeriod } from "../src/lib/periods";
import { loadPeriods } from "../src/lib/period-data";
import { periodRows } from "../src/lib/leaderboard";

const topics = allTopics("computational");
const taxonomy = loadTaxonomy("computational");
const page = (path: string) => readFileSync(`dist/${path}/index.html`, "utf8");

describe("period boundaries and selection", () => {
  it("handles ISO weeks, year boundaries, leap months and sparse stored days", () => {
    expect(isoWeekOf("2026-11-01")).toEqual({ year: 2026, week: 44, start: "2026-10-26", end: "2026-11-01" });
    expect(isoWeekOf("2027-01-01")).toEqual({ year: 2026, week: 53, start: "2026-12-28", end: "2027-01-03" });
    expect(isoWeekOf("2024-12-30")).toEqual({ year: 2025, week: 1, start: "2024-12-30", end: "2025-01-05" });
    expect(monthOf("2026-11-01")).toEqual({ year: 2026, month: 11, start: "2026-11-01", end: "2026-11-30" });
    expect(monthOf("2024-02-12").end).toBe("2024-02-29");
    expect(allWeeks(loadDays("computational")).map(({ id, soFar }) => ({ id, soFar })))
      .toEqual([{ id: "2026-W44", soFar: false }]);
    expect(allMonths(loadDays("computational")).map(({ id, soFar }) => ({ id, soFar })))
      .toEqual([{ id: "2026-11", soFar: true }, { id: "2026-10", soFar: false }]);
    expect(allWeeks([{ date: "2026-10-01" }, { date: "2026-11-03" }]).map(({ id }) => id)).toEqual(["2026-W45", "2026-W40"]);
    expect(allMonths([{ date: "2026-08-01" }, { date: "2026-11-03" }]).map(({ id }) => id)).toEqual(["2026-11", "2026-08"]);
    expect(allWeeks([])).toEqual([]);
    expect(allMonths([])).toEqual([]);
  });

  it("sums scores including unranked days, unions items, and reports rank and rise", () => {
    const ranked = rankPeriod(topics, "2026-10-26", "2026-11-01", taxonomy);
    const winner = ranked[0];
    const entries = topics.find(({ slug }) => slug === winner.slug)!.history.filter(({ date }) => date >= "2026-10-26" && date <= "2026-11-01");
    expect(winner.slug).toBe("protein-design-binders-a1b2");
    expect(winner.days_ranked).toBe(3);
    expect(winner.best_rank).toBe(1);
    expect(winner.period_score).toBeCloseTo(entries.reduce((sum, entry) => sum + entry.scores.total, 0));
    expect(winner.items).toBe(new Set(entries.flatMap(({ item_ids }) => item_ids)).size);
    expect(winner.rise).toBe(Math.max(...entries.map(({ signals }) => signals.rise_ratio)));
    expect(rankPeriod(topics, "2020-01-01", "2020-01-07", taxonomy)).toEqual([]);
  });

  it("reserves each category, caps at eight, takes forty and uses stable tie breaks", () => {
    const base = topics[0], entry = base.history[0];
    const candidates = Array.from({ length: 60 }, (_, i) => ({ ...base, slug: `topic-${String(i).padStart(2, "0")}`,
      category: `category-${Math.floor(i / 12)}`, history: [{ ...entry, date: "2026-10-26", rank: null,
        scores: { ...entry.scores, total: 100 - i }, item_ids: ["shared"] }],
    }));
    const ranked = rankPeriod(candidates, "2026-10-26", "2026-11-01", taxonomy);
    expect(ranked).toHaveLength(40);
    for (let category = 0; category < 5; category++) {
      const count = ranked.filter((topic) => topic.category === `category-${category}`).length;
      expect(count).toBeGreaterThanOrEqual(1);
      expect(count).toBeLessThanOrEqual(8);
    }
    expect(ranked.map(({ rank }) => rank)).toEqual(Array.from({ length: 40 }, (_, i) => i + 1));
    const tied = candidates.slice(0, 4).map((topic, i) => ({ ...topic, history: [{ ...topic.history[0],
      rank: i === 0 ? null : 2, scores: { ...entry.scores, total: 10 }, item_ids: i > 1 ? ["a", "b"] : ["a"],
    }] }));
    expect(rankPeriod(tied.reverse(), "2026-10-26", "2026-11-01", taxonomy).map(({ slug }) => slug))
      .toEqual(["topic-02", "topic-03", "topic-01", "topic-00"]);
  });

  it("title-cases an auto label and marks it for muted rendering", () => {
    const topic = { ...topics[0], headline: null, label: "protein design binders" };
    const rows = periodRows(rankPeriod([topic], "2026-10-26", "2026-11-01", taxonomy));
    expect(rows[0].headline).toBe("Protein Design Binders");
    expect(rows[0].autoLabel).toBe(true);
  });

  it("indexes histories once and ranks a year of periods without traversing histories again", () => {
    const copies = structuredClone(topics);
    const reads = copies.map((topic) => {
      const history = topic.history;
      const get = vi.fn(() => history);
      Object.defineProperty(topic, "history", { get });
      return get;
    });
    const index = indexHistories(copies);
    for (const read of reads) expect(read).toHaveBeenCalledTimes(1);
    const days = Array.from({ length: 365 }, (_, offset) => ({ date: new Date(Date.UTC(2026, 0, offset + 1)).toISOString().slice(0, 10) }));
    for (const { start, end } of [...allWeeks(days), ...allMonths(days)]) rankPeriod(index, start, end, taxonomy);
    for (const read of reads) expect(read).toHaveBeenCalledTimes(1);
    expect(loadPeriods()).toBe(loadPeriods());
  });
});

describe("built period pages", () => {
  it.each(["week/2026-W44", "month/2026-10"])("renders %s with shared cards, stats and navigation", (path) => {
    const html = page(path);
    expect(html).toContain('aria-label="Ranking period"');
    expect(html).toMatch(new RegExp(`href="/${path.startsWith("week") ? "week/2026-W44" : "month/2026-11"}/" aria-current="page"`));
    const rows = html.match(/\bdata-topic-cats="/g) ?? [];
    expect(rows.length).toBeGreaterThan(5);
    expect(rows.length).toBeLessThanOrEqual(40);
    const details = html.match(/<details\b[^>]*data-more-topics[^>]*>[\s\S]*?<\/details>/)![0];
    expect(details.match(/\bdata-topic-cats="/g)).toHaveLength(rows.length - 20);
    expect(html.replace(details, "").match(/\bdata-topic-cats="/g)).toHaveLength(20);
    expect(details).toContain(`Show ${rows.length - 20} more`);
    if (path.startsWith("week")) expect(rows).toHaveLength(40);
    for (const label of ["days ranked", "best rank", "items", "Rise"]) expect(details).toContain(label);
    for (const [, slug] of html.matchAll(/href="\/topic\/([^/]+)\/"/g)) expect(() => page(`topic/${slug}`)).not.toThrow();
    expect(html).toContain("data-category-chips");
  });

  it("links current periods from daily pages and month headings from the archive", () => {
    for (const html of [readFileSync("dist/index.html", "utf8"), page("day/2026-10-30")]) {
      expect(html).toMatch(/href="\/" aria-current="page"/);
      expect(html).toContain('href="/week/2026-W44/"');
      expect(html).toContain('href="/month/2026-11/"');
    }
    expect(page("archive")).toMatch(/<h2[^>]*id="heading-2026-10"[^>]*>\s*<a[^>]*href="\/month\/2026-10\/"/);
    expect(page("month/2026-11")).toContain("so far");
    expect(page("month/2026-10")).not.toContain("so far");
    expect(page("month/2026-11")).toMatch(/href="\/month\/2026-10\/" rel="prev"/);
    expect(page("month/2026-10")).toMatch(/href="\/month\/2026-11\/" rel="next"/);
    expect(page("week")).toContain(topics.find(({ slug }) => slug === "protein-design-binders-a1b2")!.headline!);
    const monthIndex = page("month");
    expect(monthIndex.indexOf("November 2026")).toBeLessThan(monthIndex.indexOf("October 2026"));
  });
});
