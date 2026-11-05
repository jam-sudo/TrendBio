import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { expect, it, vi } from "vitest";

it("limits industry to eight relevant items first seen within the inclusive week, newest first", async () => {
  const root = mkdtempSync(resolve(".industry-test-"));
  try {
    const directory = join(root, "computational/items/2026/11");
    mkdirSync(directory, { recursive: true });
    const items = [
      ...Array.from({ length: 10 }, (_, i) => ({ id: `rss:${i}`, first_seen: `2026-11-0${1 + i % 5}`, relevant: true })),
      { id: "rss:future", first_seen: "2026-11-06", relevant: true },
      { id: "rss:old", first_seen: "2026-10-29", relevant: true },
      { id: "rss:irrelevant", first_seen: "2026-11-05", relevant: false },
    ];
    for (const item of items) writeFileSync(join(directory, item.id.replace(":", "_") + ".json"),
      JSON.stringify({ ...item, type: "industry", published_at: "2020-01-01" }));
    vi.stubEnv("TRENDBIO_DATA_ROOT", root);
    vi.resetModules();
    const { industryItems, getDataIndex } = await import("../src/lib/data");
    expect(industryItems("computational", "2026-11-05").map(item => item.id))
      .toEqual(["rss:4", "rss:9", "rss:3", "rss:8", "rss:2", "rss:7", "rss:1", "rss:6"]);
    const reads = getDataIndex("computational").stats.itemReads;
    expect(industryItems("computational", "2026-11-11").map(item => item.id)).toEqual(["rss:future", "rss:4", "rss:9"]);
    expect(industryItems("computational", "2026-11-13")).toEqual([]);
    expect(getDataIndex("computational").stats.itemReads).toBe(reads);
  } finally {
    vi.unstubAllEnvs();
    vi.resetModules();
    rmSync(root, { recursive: true, force: true });
  }
});
