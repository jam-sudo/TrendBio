import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { categoryIcon, categoryIdentity } from "../src/lib/categories";
import { loadTaxonomy } from "../src/lib/data";

describe("drawn category icons", () => {
  it("gives every taxonomy slug its own compact SVG drawing", () => {
    const slugs = loadTaxonomy("computational").map(({ slug }) => slug);
    expect(Object.keys(categoryIdentity).sort()).toEqual(slugs.sort());
    expect(new Set(slugs.map(categoryIcon)).size).toBe(slugs.length);
    for (const slug of [...slugs, "unknown"]) {
      const icon = categoryIcon(slug);
      expect(icon).toMatch(/<(?:path|circle|polyline)\b/);
      expect(icon).not.toContain("<svg");
      const paths = [...icon.matchAll(/\b(?:d|points)="([^"]*)"/g)].map(([, data]) => data).join("");
      expect(Buffer.byteLength(paths)).toBeLessThanOrEqual(600);
    }
    expect(categoryIcon("unknown")).not.toBe(categoryIcon("genomics"));
  });

  it("uses only medal emoji in the landing page's visible text", () => {
    const html = readFileSync("dist/index.html", "utf8");
    const text = html.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/g, "")
      .replace(/<[^>]+>/g, "");
    const emoji = text.match(/[\u{1F300}-\u{1FAFF}]/gu) ?? [];
    expect(emoji.filter((glyph) => !["🥇", "🥈", "🥉"].includes(glyph))).toEqual([]);
    expect(emoji).toEqual(["🥇", "🥈", "🥉"]);
  });

  it("renders decorative icons at both sizes while retaining labels and the note emoji", () => {
    const home = readFileSync("dist/index.html", "utf8");
    const icons = [...home.matchAll(/<svg\b[^>]*class="category-icon\b[^>]*>/g)].map(([svg]) => svg);
    expect(icons).toHaveLength(loadTaxonomy("computational").length + 5);
    for (const svg of icons) {
      expect(svg).toContain('viewBox="0 0 24 24"');
      expect(svg).toContain('aria-hidden="true"');
      expect(svg).toContain('focusable="false"');
      expect(svg).toContain('stroke-width="1.75"');
      expect(svg).toContain('stroke="currentColor"');
    }
    expect(icons.filter((svg) => svg.includes('width="16"'))).toHaveLength(11);
    expect(icons.filter((svg) => svg.includes('width="36"'))).toHaveLength(5);
    const topic = readFileSync("dist/topic/protein-design-binders-a1b2/index.html", "utf8");
    expect(topic).toContain("#2 · Structural bio &amp; protein design");
    expect(topic).toContain("📝");
  });
});
