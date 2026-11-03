import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, inject, it } from "vitest";
import { allTopics, rankedTopics, loadItems, loadNote, loadTaxonomy, loadTopic } from "../src/lib/data";

const domain = "computational";
const slug = "protein-design-binders-a1b2";
const neverRankedSlug = "never-ranked-fixture-0000";
const topic = loadTopic(domain, slug)!;
const latest = topic.history.at(-1)!;
const items = loadItems(domain, latest.item_ids);
const readPage = (path: string) => readFileSync(`dist/${path}/index.html`, "utf8");
const section = (html: string, id: string) => html.match(new RegExp(`<section\\b[^>]*id="${id}"[^>]*>[\\s\\S]*?</section>`))?.[0] ?? "";
const headings = (html: string) => [...html.matchAll(/<h2\b[^>]*>(.*?)<\/h2>/g)].map((match) => match[1]);

describe("built topic pages", () => {
  it("renders the note HTML and the specified content order", () => {
    const html = readPage(`topic/${slug}`);
    expect(html).toContain(loadNote(slug)!.trim());
    const content = [
      'href="/day/2026-11-01/"', "#2 · Structural bio &amp; protein design", topic.headline!,
      'class="signal-badges"', "<svg", topic.synthesis!, "Editor's note", "Published papers",
      "Preprints", "Code &amp; tools", "Industry</h2>", "Related topics", "Topic history",
    ];
    const article = html.slice(html.indexOf("<article"));
    const positions = content.map((text) => article.indexOf(text));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
    const styles = [...html.matchAll(/<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"/g)]
      .map(([, href]) => readFileSync(`dist${href}`, "utf8")).join("\n");
    expect(styles).toContain("max-width:720px");
  });

  it("renders 56 dated sparkline bars including unranked days and highlights the latest day", () => {
    const html = readPage(`topic/${slug}`);
    const svg = html.match(/<svg\b[\s\S]*?<\/svg>/)![0];
    const dates = [...svg.matchAll(/data-date="([^"]+)"/g)].map((match) => match[1]);
    expect(dates).toEqual(topic.history.slice(-56).map((entry) => entry.date));
    expect(svg).toContain('preserveAspectRatio="none"');
    expect(html).toContain("Items per day, last 8 weeks");
    expect(html).toContain(`today: ${latest.count_7d}`);
    expect(svg).toContain('aria-label="7-day item counts from 2026-09-07 to 2026-11-01"');
    expect(svg.match(/class="today"/g)).toHaveLength(1);
    expect(svg).toMatch(/<rect[^>]*data-date="2026-11-01"[^>]*class="today"/);
  });

  it("groups evidence and links the published paper's preprint exactly once", () => {
    const html = readPage(`topic/${slug}`);
    expect(headings(html)).toEqual(["Editor's note", "Published papers", "Preprints", "Code &amp; tools", "Industry", "Related topics", "Topic history"]);
    const published = items.find((item) => item.type === "published")!;
    const preprint = items.find((item) => item.id === published.preprint_id)!;
    expect(html.split(`href="${preprint.url}"`)).toHaveLength(2);
    expect(section(html, "published")).toMatch(new RegExp(`href="${preprint.url}"[^>]*>preprint</a>`));
    expect(section(html, "preprint")).not.toContain(preprint.url);
    expect(section(html, "published")).toContain(topic.item_one_liners[published.id]);
    expect(section(html, "published")).toContain("Synthetic Methods Journal");
    expect(section(html, "published")).toContain("Example Researcher et al.");
    expect(section(html, "preprint")).toContain("arXiv");
    expect(section(html, "code")).toContain("GitHub");
    expect(section(html, "code")).toContain("+120 ★ this week");
    expect(section(html, "code")).toContain("MIT");
    expect(section(html, "industry")).toContain("Example Research Tools");
    for (const item of items.filter((item) => item.id !== preprint.id)) {
      const evidence = section(html, item.type);
      expect(evidence).toContain(`href="${item.url}"`);
      expect(evidence).toContain(item.published_at);
      expect(evidence).toContain(topic.item_one_liners[item.id] ?? item.summary);
    }
  });

  it("lists only ranked history dates newest first and resolves related labels", () => {
    const html = readPage(`topic/${slug}`);
    const history = section(html, "topic-history");
    const ranked = topic.history.filter((entry) => entry.rank !== null).reverse();
    expect([...history.matchAll(/href="\/day\/([^/]+)\/"/g)].map((match) => match[1]))
      .toEqual(ranked.map((entry) => entry.date));
    for (const entry of ranked) expect(history).toContain(`${entry.date} · #${entry.rank}`);
    const related = section(html, "related-topics");
    expect(related.match(/<a\b/g)).toHaveLength(2);
    for (const relatedSlug of topic.related.slice(0, 3)) {
      expect(related).toContain(loadTopic(domain, relatedSlug)!.label);
    }
    expect(related).not.toContain(`href="/topic/${neverRankedSlug}/"`);
    expect(related).toMatch(new RegExp(`<li[^>]*>${loadTopic(domain, neverRankedSlug)!.label}</li>`));
  });

  it("warns about orphan notes without failing the build", () => {
    expect(inject("buildOutput")).toContain("orphan note: nonexistent-topic-zzzz");
    expect(inject("buildOutput")).toContain("[build] Complete!");
  });

  it("lists exactly the five ranked topics with matching category filters", () => {
    const html = readPage("topics");
    const ranked = allTopics(domain).filter((entry) => entry.history.some((day) => day.rank !== null));
    expect(rankedTopics(domain)).toEqual(ranked);
    expect(rankedTopics("missing-domain")).toEqual([]);
    expect(html.match(/\bdata-topic-cats="/g)).toHaveLength(5);
    expect([...html.matchAll(/href="\/topic\/([^/]+)\/"/g)].map((match) => match[1]))
      .toEqual(ranked.map((entry) => entry.slug));
    for (const entry of ranked) {
      expect(html).toContain(`data-topic-cats="${[entry.category, ...entry.secondary_categories].join(" ")}"`);
      expect(html).toContain(entry.headline ?? entry.label);
      expect(html).toContain(`href="/topic/${entry.slug}/"`);
    }
    expect(html).toContain("data-category-chips");
    expect(html.match(/datetime="2026-11-01"/g)).toHaveLength(5);
    expect(html).not.toContain(neverRankedSlug);
    expect(html).not.toContain(loadTopic(domain, neverRankedSlug)!.label);
    expect(existsSync(`dist/topic/${neverRankedSlug}`)).toBe(false);
    for (const category of loadTaxonomy(domain)) {
      const chip = html.match(new RegExp(`<button[^>]*data-cat="${category.slug}"[^>]*>`))![0];
      expect(chip.includes("disabled")).toBe(!ranked.some((entry) =>
        [entry.category, ...entry.secondary_categories].includes(category.slug)));
    }
  });

  it("handles unranked latest entries, never-ranked topics, short histories and empty evidence", () => {
    const temporary = mkdtempSync(resolve(".topic-test-"));
    try {
      const data = join(temporary, "data");
      cpSync("../fixtures/data", data, { recursive: true });
      const changed = structuredClone(topic);
      const published = items.find((item) => item.type === "published")!;
      changed.history.push({ ...latest, date: "2026-11-02", rank: null,
        item_ids: [published.id, published.preprint_id!], count_7d: 1,
        signals: { published: 1, preprint: 0, code: 0, industry: 0, star_gain_7d: 0, rise_ratio: 1.49 } });
      changed.related = [];
      writeFileSync(join(data, domain, "topics", `${slug}.json`), JSON.stringify(changed));
      const other = rankedTopics(domain).find((entry) => entry.slug !== slug)!;
      other.history = other.history.slice(-2).map((entry, index) => ({ ...entry,
        rank: index === 0 ? 3 : null, item_ids: [] }));
      other.history.reverse();
      other.headline = other.synthesis = null;
      other.related = [];
      writeFileSync(join(data, domain, "topics", `${other.slug}.json`), JSON.stringify(other));
      const output = join(temporary, "dist");
      execFileSync(process.execPath, ["node_modules/astro/astro.js", "build", "--outDir", output], {
        env: { ...process.env, TRENDBIO_DATA_ROOT: data },
      });
      const html = readFileSync(join(output, `topic/${slug}/index.html`), "utf8");
      expect(headings(html)).toEqual(["Editor's note", "Published papers", "Topic history"]);
      expect(html).toContain("#2 ·");
      expect(html).toContain('href="/day/2026-11-01/"');
      expect(html).toContain("1 published");
      expect(html).not.toContain("vs 4-wk avg");
      expect(section(html, "topic-history")).not.toContain("2026-11-02");
      const short = readFileSync(join(output, `topic/${other.slug}/index.html`), "utf8");
      expect(short).toContain("#3 ·");
      expect(short).toContain(other.label);
      expect(short).not.toContain("<svg");
      expect(short).not.toContain("Editor's note");
      expect(headings(short)).toEqual(["Topic history"]);
      expect(section(short, "topic-history")).toContain("/day/2026-10-31/");
      expect(section(short, "topic-history")).not.toContain("/day/2026-11-01/");
      expect(existsSync(join(output, `topic/${neverRankedSlug}`))).toBe(false);
      const index = readFileSync(join(output, "topics/index.html"), "utf8");
      const links = [...index.matchAll(/href="\/topic\/([^/]+)\/"/g)].map((match) => match[1]);
      expect(links.at(-1)).toBe(other.slug);
      expect(links).toHaveLength(5);
      expect(links).not.toContain(neverRankedSlug);
    } finally {
      rmSync(temporary, { recursive: true, force: true });
    }
  });
});
