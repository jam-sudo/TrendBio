import { describe, expect, it, vi } from "vitest";
import { allTopics, latestDay, loadCorrection, loadDay, loadDays, loadItems, loadNote, loadTaxonomy, loadTopic } from "../src/lib/data";

describe("fixture data", () => {
  it("keeps a correction with its claim and original evidence across reranking", () => {
    const note = (claim: string, ids: string[]) => loadCorrection("physics", "2026-11-01", "cavity-readout-fixture", [claim], ids);
    const claim = "Three fixture papers examine light losses and readout noise.";
    const ids = [3, 1, 2].map(n => `arxiv:optics-fixture-${n}`);
    expect(note(claim, ids)).toContain("Calibration record");
    expect(note("The calibration is up to date.", ids)).toBeNull();
    expect(note(claim, ids.slice(1))).toBeNull();
    expect(note(claim, [...ids, "arxiv:fourth"])).toBeNull();
  });

  it("shows a shared field correction on a new date and topic only for the same claim and papers", () => {
    const claim = "The original calibration applies to this measurement.";
    const ids = [3, 2, 1].map(n => `arxiv:optics-fixture-${n}`);
    const next = (field: string, text: string, papers: string[]) => loadCorrection(field, "2026-11-02", "new-topic", [text], papers);
    expect(next("physics", claim, ids)).toContain("used the updated calibration");
    expect(next("physics", claim, ids.slice(1))).toBeNull();
    expect(next("physics", "A different claim.", ids)).toBeNull();
    expect(next("math", claim, ids)).toBeNull();
  });

  it("loads the latest day", () => {
    expect(latestDay("computational")?.date).toBe("2026-11-01");
  });

  it("loads a topic with its history", () => {
    expect(loadTopic("computational", "protein-design-binders-a1b2")?.history.length)
      .toBeGreaterThanOrEqual(10);
  });

  it("loads days in descending order and handles missing records", () => {
    expect(loadDays("computational").map((day) => day.date))
      .toEqual(["2026-11-01", "2026-10-31", "2026-10-30", "2026-10-29"]);
    expect(loadDay("computational", "2026-10-30")?.run.backfilled).toBe(true);
    expect(loadDay("computational", "1900-01-01")).toBeNull();
    expect(loadTopic("computational", "not-a-slug")).toBeNull();
    expect(latestDay("missing-domain")).toBeNull();
    expect(allTopics("computational")).toHaveLength(41);
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
