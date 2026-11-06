import { cpSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { expect, it, vi } from "vitest";

const section = (html: string) => html.match(/<section\b[^>]*aria-labelledby="shared-heading"[^>]*>[\s\S]*?<\/section>/)?.[0];

it("renders at most eight papers after code on home and day pages, linking only ranked topics", () => {
  for (const path of ["index.html", "day/2026-11-01/index.html"]) {
    const html = readFileSync(`dist/${path}`, "utf8");
    const shared = section(html)!;
    expect(shared).toContain("Shared by researchers");
    expect(shared).toContain("Papers with the most reactions on Bluesky this week, excluding high-volume posting accounts.");
    expect(html.indexOf('id="shared-heading"')).toBeGreaterThan(html.indexOf('id="from-code-heading"'));
    const rows = [...shared.matchAll(/<li\b[^>]*>[\s\S]*?<\/li>/g)].map(([row]) => row);
    expect(rows).toHaveLength(8);
    expect(rows[0]).toMatch(/href="\/topic\/single-cell-perturbations-c3d4\/"[^>]*>#1<\/a>/);
    expect(rows[0]).toContain("52 reactions");
    expect(rows[0]).toContain("6 people");
    expect(rows[0]).toContain("preprint");
    expect(rows[0]).toContain('datetime="2026-10-26"');
    expect(rows[1]).toMatch(/href="\/topic\/protein-design-binders-a1b2\/"[^>]*>#2<\/a>/);
    expect(rows[1]).toContain("published");
    expect(rows[2]).toContain('href="https://example.org/papers/0"');
    expect(rows[2]).toContain("Mapping cell states across human tissues");
    for (const row of rows.slice(2)) expect(row).not.toContain('/topic/');
  }
});

it("omits the section when the day has no attention file and on period or topic pages", () => {
  for (const path of ["day/2026-10-31/index.html", "week/index.html", "month/index.html",
    "topic/single-cell-perturbations-c3d4/index.html", "map/index.html"]) {
    expect(section(readFileSync(`dist/${path}`, "utf8"))).toBeUndefined();
  }
});

it("documents the list's scope and limitations", () => {
  const html = readFileSync("dist/about/index.html", "utf8");
  for (const text of ["covers Bluesky only", "never affects rankings or scores", "20 or more papers a week",
    "authors promoting their own work"]) expect(html).toContain(text);
});

it("loads attention once through the global index and handles a missing directory", async () => {
  const root = mkdtempSync(resolve(".shared-test-"));
  try {
    cpSync("../fixtures/data", root, { recursive: true });
    cpSync("tests/fixtures/shared", join(root, "computational"), { recursive: true });
    vi.stubEnv("TRENDBIO_DATA_ROOT", root);
    vi.resetModules();
    const data = await import("../src/lib/data");
    const papers = data.sharedItems("computational", "2026-11-01");
    expect(papers).toHaveLength(8);
    expect(papers[0].rankedTopic).toEqual({ slug: "single-cell-perturbations-c3d4", rank: 1 });
    expect(papers[2].rankedTopic).toBeUndefined();
    rmSync(join(root, "computational/attention"), { recursive: true });
    vi.resetModules();
    const reloaded = await import("../src/lib/data");
    expect(reloaded.sharedItems("computational", "2026-11-01")).toEqual(papers);
    expect(reloaded.sharedItems("computational", "2026-10-31")).toEqual([]);
    expect(reloaded.sharedItems("missing-domain", "2026-11-01")).toEqual([]);
    expect(reloaded.getDataIndex("computational").stats.builds).toBe(1);
  } finally {
    vi.unstubAllEnvs();
    vi.resetModules();
    rmSync(root, { recursive: true, force: true });
  }
});
