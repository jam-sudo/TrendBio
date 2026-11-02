import { describe, expect, it, vi } from "vitest";
import { allTopics, latestDay, loadDay, loadDays, loadItems, loadNote, loadTaxonomy, loadTopic } from "../src/lib/data";

describe("fixture data", () => {
  it("loads the latest day", () => {
    expect(latestDay("computational")?.date).toBe("2026-11-01");
  });

  it("loads a topic with its history", () => {
    expect(loadTopic("computational", "protein-design-binders-a1b2")?.history.length)
      .toBeGreaterThanOrEqual(10);
  });

  it("loads days in descending order and handles missing records", () => {
    expect(loadDays("computational").map((day) => day.date))
      .toEqual(["2026-11-01", "2026-10-31", "2026-10-30"]);
    expect(loadDay("computational", "2026-10-30")?.run.backfilled).toBe(true);
    expect(loadDay("computational", "1900-01-01")).toBeNull();
    expect(loadTopic("computational", "not-a-slug")).toBeNull();
    expect(latestDay("missing-domain")).toBeNull();
    expect(allTopics("computational")).toHaveLength(5);
  });

  it("loads requested items across month shards in requested order", () => {
    const ids = ["pubmed:fixture-01-05", "biorxiv:10.1101/2026.08.24.010001"];
    expect(loadItems("computational", [...ids, "missing-id"]).map((item) => item.id))
      .toEqual(ids);
    expect(loadItems("computational", [])).toEqual([]);
  });

  it("reads categories from the taxonomy config", () => {
    const categories = loadTaxonomy("computational");
    expect(categories).toHaveLength(11);
    expect(categories[0]).toMatchObject({ slug: "genomics", label: "Genomics" });
  });

  it("renders an existing note and warns without throwing for a missing note", () => {
    expect(loadNote("nonexistent-topic-zzzz")).toContain("<p>");
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      expect(loadNote("not-a-slug")).toBeNull();
      expect(warning).toHaveBeenCalledWith(expect.stringContaining("not-a-slug"));
    } finally {
      warning.mockRestore();
    }
  });
});
