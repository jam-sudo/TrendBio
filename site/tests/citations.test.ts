import { existsSync, readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { bibtex, escapeBibtex, hasPapers, topicEvidence } from "../src/lib/citations";
import { topicPages } from "../src/lib/period-data";
import type { Item } from "../src/lib/types";
import fixtures from "./fixtures/citations.json";

it("escapes BibTeX specials, preserves authors and generates unique ASCII keys", () => {
  const items = fixtures as Item[];
  const result = bibtex([...items, items[0]]);
  expect(escapeBibtex(items[0].title)).toBe(String.raw`RNA \& DNA: \{100\%\} \#1\_\$ \textbackslash{} \textasciitilde{} \textasciicircum{} <models>`);
  expect(result).toContain(`title = {${escapeBibtex(items[0].title)}}`);
  expect(result).toContain("author = {Zoë García and Smith, Anne}");
  expect(result).toContain("journal = {Methods \\& Tools}");
  expect(result).toContain("doi = {10.1234/a\\_b}");
  expect(result).toContain("url = {https://example.org/?a=1\\&b=2}");
  expect(result).toContain("year = {2026}");
  const keys = [...result.matchAll(/@(article|misc)\{([^,]+),/g)];
  expect(keys.map(match => match[1])).toEqual(["article", "misc", "misc"]);
  expect(keys.map(match => match[2])).toEqual([expect.stringMatching(/^garcia2026[a-f0-9]{8}$/),
    expect.stringMatching(/^garcia2026[a-f0-9]{8}$/), expect.stringMatching(/^anonymous2025[a-f0-9]{8}$/)]);
  expect(new Set(keys.map(match => match[2])).size).toBe(3);
  expect(bibtex(items)).toBe(result);
  expect(bibtex([{ ...items[0], type: "code" }])).toBe("");
  expect(hasPapers([{ ...items[0], type: "industry" }])).toBe(false);
});

it("exports exactly the topic evidence papers and links only to existing files", () => {
  for (const topic of topicPages()) {
    const path = `dist/topic/${topic.slug}`;
    const items = topicEvidence(topic);
    const html = readFileSync(`${path}/index.html`, "utf8");
    expect(existsSync(`${path}/citations.bib`)).toBe(hasPapers(items));
    if (hasPapers(items)) {
      const output = readFileSync(`${path}/citations.bib`, "utf8");
      // The build overlays tool-title fixtures; check counts and identifiers independently of titles.
      expect([...output.matchAll(/^@/gm)]).toHaveLength(new Set(items.filter(item => ["preprint", "published"].includes(item.type)).map(item => item.id)).size);
      expect(html).toMatch(new RegExp(`href="/topic/${topic.slug}/citations.bib" download[^>]*>Export citations \\(BibTeX\\)</a>`));
    } else expect(html).not.toContain("Export citations (BibTeX)");
  }
  expect(readFileSync("dist/sitemap.xml", "utf8")).not.toContain("citations.bib");
});
