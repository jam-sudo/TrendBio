import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { expect, it, vi } from "vitest";
import { codeItems } from "../src/lib/data";

const section = (path: string) => readFileSync(`dist/${path}`, "utf8")
  .match(/<section\b[^>]*aria-labelledby="from-code-heading"[^>]*>[\s\S]*?<\/section>/)![0];
const rows = (html: string) => [...html.matchAll(/<li\b[^>]*>[\s\S]*?<\/li>/g)].map(([row]) => row);
const repo = "trendbio-fixtures/protein-design-binders-a1b2";

it("renders eight fixture repositories after industry, ordered by gain then total stars", () => {
  for (const path of ["index.html", "day/2026-11-01/index.html"]) {
    const html = readFileSync(`dist/${path}`, "utf8");
    expect(html.indexOf('id="from-code-heading"')).toBeGreaterThan(html.indexOf('id="from-industry-heading"'));
    const rendered = rows(section(path));
    expect(rendered).toHaveLength(8);
    const names = rendered.map(row => row.match(/<a\b[^>]*>([^<]+)<\/a>/)![1]);
    expect(names.slice(0, 4)).toEqual([repo, "trendbio-fixtures/workflow-validation-0020",
      "trendbio-fixtures/enzyme-design-0018", "trendbio-fixtures/chromatin-accessibility-0008"]);
    const item = codeItems("computational", "2026-11-01")[0];
    expect(rendered[0]).toContain(`href="${item.url}"`);
    expect(rendered[0]).toContain('datetime="2026-10-28"');
    expect(rendered[0]).toContain(item.summary!);
    expect(rendered[0]).toContain("110 stars");
    expect(rendered[0]).toContain("+100 in 7d");
    expect(rendered[1]).toContain("1,050 stars");
  }
});

it("hides gains without an exact comparison sample and stars without any historical sample", () => {
  const rendered = rows(section("index.html"));
  expect(rendered[3]).toContain("2,000 stars");
  expect(rendered[3]).not.toContain("in 7d");
  expect(rendered[4]).not.toMatch(/stars|in 7d/);
});

it("uses only samples known by an old day, including its own seven-day comparison", () => {
  const row = rows(section("day/2026-10-29/index.html")).find(row => row.includes(repo))!;
  expect(row).toContain("20 stars");
  expect(row).toContain("+10 in 7d");
  expect(row).not.toMatch(/110 stars|99,999 stars|\+100 in 7d/);
});

it("filters the inclusive first-seen week and relevance, clamps losses, and caches source files", async () => {
  const root = mkdtempSync(resolve(".code-test-"));
  try {
    const directory = join(root, "computational/items/2026/11");
    mkdirSync(directory, { recursive: true });
    const items = [
      { id: "github:test/start", first_seen: "2026-10-30", relevant: true },
      { id: "github:test/end", first_seen: "2026-11-05", relevant: true },
      { id: "github:test/future", first_seen: "2026-11-06", relevant: true },
      { id: "github:test/old", first_seen: "2026-10-29", relevant: true },
      { id: "github:test/irrelevant", first_seen: "2026-11-05", relevant: false },
      { id: "github:test/wrong-type", first_seen: "2026-11-05", relevant: true, type: "industry" },
    ];
    for (const item of items) writeFileSync(join(directory, item.id.replace(/[:/]/g, "_") + ".json"),
      JSON.stringify({ type: "code", published_at: "2020-01-01", ...item }));
    const starsPath = join(root, "computational/github_stars.json");
    writeFileSync(starsPath, JSON.stringify({ "test/start": [
      { date: "2026-11-06", stars: 1000 },
      { date: "2026-10-28", stars: 30 },
      { date: "2026-11-04", stars: 20 },
    ], "test/end": [{ date: "2026-11-06", stars: 500 }] }));
    vi.stubEnv("TRENDBIO_DATA_ROOT", root);
    vi.resetModules();
    const data = await import("../src/lib/data");
    expect(data.codeItems("computational", "2026-11-05").map(({ id, stars, star_gain_7d }) => ({ id, stars, star_gain_7d })))
      .toEqual([{ id: "github:test/start", stars: 20, star_gain_7d: 0 },
        { id: "github:test/end", stars: null, star_gain_7d: null }]);
    const reads = data.getDataIndex("computational").stats.itemReads;
    rmSync(starsPath);
    rmSync(directory, { recursive: true });
    vi.resetModules();
    const reloaded = await import("../src/lib/data");
    expect(reloaded.codeItems("computational", "2026-11-05")[0].stars).toBe(20);
    expect(reloaded.codeItems("computational", "2026-11-12").map(item => item.id)).toEqual(["github:test/future"]);
    expect(reloaded.codeItems("computational", "2026-11-13")).toEqual([]);
    expect(reloaded.getDataIndex("computational").stats.itemReads).toBe(reads);
    expect(reloaded.getDataIndex("missing-domain").githubStars).toEqual({});
  } finally {
    vi.unstubAllEnvs();
    vi.resetModules();
    rmSync(root, { recursive: true, force: true });
  }
});
