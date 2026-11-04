import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, inject, it, vi } from "vitest";
import { allTopics, getDataIndex, loadDays, loadItems, loadNote, loadTaxonomy } from "../src/lib/data";
import { loadPeriods } from "../src/lib/period-data";
import { allMonths, allWeeks, indexHistories, rankPeriod } from "../src/lib/periods";

vi.mock("node:fs", async (importOriginal) => {
  const fs = await importOriginal<typeof import("node:fs")>();
  return { ...fs, readFileSync: vi.fn(fs.readFileSync), readdirSync: vi.fn(fs.readdirSync),
    globSync: vi.fn(() => { throw new Error("Item lookup must not glob"); }),
  };
});

const domain = "computational";

describe("build data index", () => {
  it("constructs one index for the entire fixture site build", () => {
    // The shared global setup builds all fixture routes in a separate Astro process.
    const output = inject("buildOutput");
    expect(output).toContain("[build] Complete!");
    expect(output.match(/\[data-index\] computational built #\d+/g))
      .toEqual(["[data-index] computational built #1"]);
  });

  it("reuses the index, notes and period rankings across module evaluation", async () => {
    const index = getDataIndex(domain);
    const periods = loadPeriods();
    const note = loadNote("protein-design-binders-a1b2");
    vi.resetModules();
    const reloaded = await import("../src/lib/data");
    expect(reloaded.getDataIndex(domain)).toBe(index);
    expect(index.stats.builds).toBe(1);
    expect(vi.mocked(readFileSync).mock.calls.filter(([path]) => String(path).includes("/items/")))
      .toHaveLength(0);
    expect(vi.mocked(readdirSync).mock.calls.filter(([path]) => String(path).endsWith("/items")))
      .toHaveLength(1);
    expect(reloaded.allTopics(domain)).toBe(index.topics);
    expect(reloaded.loadDays(domain)).toBe(index.days);
    expect(reloaded.loadTopic(domain, index.topics[0].slug)).toBe(index.topics[0]);
    expect(reloaded.loadNote("protein-design-binders-a1b2")).toBe(note);
    expect(index.notes.get("protein-design-binders-a1b2")).toBe(note);
    expect((await import("../src/lib/period-data")).loadPeriods()).toBe(periods);
  });

  it("reads only requested item files across shards, preserving order and duplicates", () => {
    const index = getDataIndex(domain);
    const before = index.stats.itemReads;
    vi.mocked(readFileSync).mockClear();
    vi.mocked(readdirSync).mockClear();
    const ids = ["pubmed:fixture-01-05", "biorxiv:10.1101/2026.08.24.010001", "pubmed:fixture-01-05"];
    expect(loadItems(domain, [...ids, "missing-id"]).map(({ id }) => id)).toEqual(ids);
    expect(index.stats.itemReads - before).toBe(ids.length);
    expect(loadItems(domain, [])).toEqual([]);
    expect(index.stats.itemReads - before).toBe(ids.length);
    expect(readFileSync).toHaveBeenCalledTimes(ids.length);
    expect(readdirSync).not.toHaveBeenCalled();
  });

  it("keeps distinct IDs with colliding filenames and the last copy of a repeated ID", async () => {
    const root = mkdtempSync(resolve(".build-perf-"));
    try {
      const ids = ["github:a_b/c", "github:a/b_c", "github:a_b/c"];
      for (const [i, id] of ids.entries()) {
        const directory = join(root, domain, "items", "2026", `0${i + 1}`);
        mkdirSync(directory, { recursive: true });
        writeFileSync(join(directory, "github_a_b_c.json"), JSON.stringify({ id, title: `version-${i}` }));
      }
      vi.stubEnv("TRENDBIO_DATA_ROOT", root);
      vi.resetModules();
      const data = await import("../src/lib/data");
      expect(data.loadItems(domain, ids.slice(0, 2)).map(({ id, title }) => ({ id, title }))).toEqual([
        { id: ids[0], title: "version-2" }, { id: ids[1], title: "version-1" },
      ]);
    } finally {
      vi.unstubAllEnvs();
      vi.resetModules();
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("memoises periods by dataset and boundaries without mixing different topic sets", async () => {
    const days = loadDays(domain);
    const topics = allTopics(domain);
    const taxonomy = loadTaxonomy(domain);
    const histories = indexHistories(topics);
    const start = "2026-10-26", end = "2026-11-01";
    const ranked = rankPeriod(histories, start, end, taxonomy);
    const reloaded = await import("../src/lib/periods");
    expect(reloaded.allWeeks(days)).toBe(allWeeks(days));
    expect(reloaded.allMonths(days)).toBe(allMonths(days));
    expect(reloaded.indexHistories(topics)).toBe(histories);
    expect(reloaded.rankPeriod(topics, start, end, taxonomy)).toBe(ranked);
    expect(rankPeriod([], start, end, taxonomy)).toEqual([]);
    expect(rankPeriod(topics, "1900-01-01", "1900-01-07", taxonomy)).toEqual([]);
  });
});
