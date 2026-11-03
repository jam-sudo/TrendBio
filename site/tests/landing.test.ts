import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { latestDay, loadDays } from "../src/lib/data";

const readPage = (path: string) => readFileSync(`dist/${path}`, "utf8");
const cards = (html: string) => [...html.matchAll(/<a\b[^>]*data-topic-cats="[^"]*"[^>]*>[\s\S]*?<\/a>/g)].map(([card]) => card);

describe("built landing, day and archive pages", () => {
  it("links five leaderboard rows and gives rank one a larger summary", () => {
    const html = readPage("index.html");
    const rendered = cards(html);
    const day = latestDay("computational")!;
    expect(rendered).toHaveLength(5);
    expect(html.match(/\bdata-topic-cats="/g)).toHaveLength(5);
    expect(rendered[0]).toMatch(/class="[^"]*\bfeatured\b/);
    expect(html).toContain('class="topic-list"');
    day.ranked.forEach((topic, index) => {
      expect(rendered[index]).toContain(`href="/topic/${topic.slug}/"`);
      expect(rendered[index]).toContain(topic.headline);
      expect(rendered[index]).toContain(topic.summary);
    });
  });

  it("renders the dated page without a hero and with the backfill notice", () => {
    const html = readPage("day/2026-10-30/index.html");
    expect(html).toMatch(/<h1[^>]*>[\s\S]*?2026-10-30[\s\S]*?<\/h1>/);
    expect(html).toContain("Code and industry signals are partial for backfilled days.");
    expect(html).not.toContain('class="hero"');
    expect(cards(html)).toHaveLength(5);
    expect(html).toContain("1 preprint · 1 published · 1 tool · 1 industry · ↑ 4.3× vs 4-wk avg");
    expect(html).toContain("4 preprints");
  });

  it("renders a quiet day without cards and preserves its backfill notice", () => {
    const html = readPage("day/2026-10-29/index.html");
    expect(html).toContain("Quiet day: no topic cleared the bar.");
    expect(html).toContain("Code and industry signals are partial for backfilled days.");
    expect(cards(html)).toHaveLength(0);
    expect(html).not.toContain("Some sources or summaries were unavailable for this run.");
  });

  it("renders monthly calendars with only the top topic and links to each full day", () => {
    const html = readPage("archive/index.html");
    const sections = [...html.matchAll(/<section\b[^>]*class="archive-month"[^>]*>[\s\S]*?<\/section>/g)].map(([section]) => section);
    expect(sections).toHaveLength(2);
    expect(sections[0]).toContain("November 2026");
    expect(sections[1]).toContain("October 2026");
    expect(html).toContain('href="#month-2026-11"');
    expect(html).toContain('href="#month-2026-10"');
    const cells = [...html.matchAll(/<a\b[^>]*href="\/day\/(\d{4}-\d{2}-\d{2})\/"[^>]*>[\s\S]*?<\/a>/g)];
    expect(cells.map(([, date]) => date)).toEqual(["2026-11-01", "2026-10-29", "2026-10-30", "2026-10-31"]);
    for (const day of loadDays("computational")) {
      const cell = cells.find(([, date]) => date === day.date)![0];
      const top = day.ranked.find(({ rank }) => rank === 1);
      expect(cell).toContain(`aria-label="${day.date}: ${top?.headline ?? "quiet"}"`);
      expect(cell).toContain(top?.headline ?? "quiet");
      if (top) expect(cell).toMatch(/<svg[^>]*width="16"/);
      for (const topic of day.ranked.filter(({ rank }) => rank !== 1)) expect(cell).not.toContain(topic.headline);
    }
    expect(cells.find(([, date]) => date === "2026-10-30")![0]).toContain("BACKFILLED");
    expect(html).not.toContain('href="/day/2026-10-28/"');
    expect(html).toContain('datetime="2026-10-28"');
    expect(html).not.toContain('href="/topic/');
    expect(html).not.toContain("<table");
    expect(readPage("index.html")).toMatch(/href="\/archive\/"[^>]*>View all/);
  });

  it("renders degraded notices and signal count/rise boundaries on both landing and day pages", () => {
    const temporary = mkdtempSync(resolve(".landing-test-"));
    try {
      const data = join(temporary, "data");
      cpSync("../fixtures/data/computational/days", join(data, "computational/days"), { recursive: true });
      cpSync("../fixtures/data/computational/topics", join(data, "computational/topics"), { recursive: true });
      const day = latestDay("computational")!;
      day.run.status = "degraded";
      day.run.backfilled = true;
      day.ranked.find(({ rank }) => rank === 2)!.headline = "Unique November rank-two headline";
      day.ranked[0].signals = { preprint: 7, published: 2, code: 2, industry: 1, rise_ratio: 4, star_gain_7d: 0 };
      day.ranked[1].signals = { preprint: 1, published: 0, code: 1, industry: 0, rise_ratio: 1.49, star_gain_7d: 0 };
      day.ranked[2].signals = { preprint: 0, published: 0, code: 0, industry: 0, rise_ratio: 1.5, star_gain_7d: 0 };
      day.ranked[3].signals = { preprint: 0, published: 0, code: 0, industry: 0, rise_ratio: 0, star_gain_7d: 0 };
      writeFileSync(join(data, `computational/days/${day.date}.json`), JSON.stringify(day));
      const partial = loadDays("computational").find(({ date }) => date === "2026-10-31")!;
      partial.run.status = "degraded";
      partial.run.backfilled = false;
      writeFileSync(join(data, `computational/days/${partial.date}.json`), JSON.stringify(partial));
      const output = join(temporary, "dist");
      execFileSync(process.execPath, ["node_modules/astro/astro.js", "build", "--outDir", output], {
        env: { ...process.env, TRENDBIO_DATA_ROOT: data },
      });
      const archive = readFileSync(join(output, "archive/index.html"), "utf8");
      const cell = archive.match(new RegExp(`<a\\b[^>]*href="/day/${day.date}/"[^>]*>[\\s\\S]*?</a>`))![0];
      expect(cell).toContain(day.ranked.find(({ rank }) => rank === 1)!.headline);
      expect(archive).not.toContain("Unique November rank-two headline");
      expect(cell).not.toContain("PARTIAL");
      expect(archive.match(/<a\b[^>]*href="\/day\/2026-10-31\/"[^>]*>[\s\S]*?<\/a>/)![0]).toContain("PARTIAL");
      expect(cell).toContain("BACKFILLED");
      for (const page of ["index.html", `day/${day.date}/index.html`]) {
        const html = readFileSync(join(output, page), "utf8");
        expect(html).toContain("Some sources or summaries were unavailable for this run.");
        expect(html).toContain("Code and industry signals are partial for backfilled days.");
        const rendered = cards(html);
        expect(rendered[0]).toContain("7 preprints · 2 published · 2 tools · 1 industry · ↑ 4.0× vs 4-wk avg");
        expect(rendered[1]).toContain("1 preprint · 1 tool");
        expect(rendered[1]).not.toMatch(/↑|0 published|0 industry/);
        expect(rendered[2]).toContain("↑ 1.5× vs 4-wk avg");
        expect(rendered[2]).not.toMatch(/0 preprints|0 published|0 tools|0 industry/);
        expect(rendered[3]).not.toContain('class="signal-line"');
      }
    } finally {
      rmSync(temporary, { recursive: true, force: true });
    }
  });
});
