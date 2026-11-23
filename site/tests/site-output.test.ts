import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium, type Browser, type Page } from "playwright";
import { afterAll, beforeAll, expect, it } from "vitest";
import { getDataIndex } from "../src/lib/data";
import { editions, fieldLabel, pilotDates, publicEditions } from "../src/lib/editions";
import { loadPeriods } from "../src/lib/period-data";
import { truncateDescription } from "../src/lib/metadata";

const read = (path: string) => readFileSync(`dist/${path}`, "utf8");
const { days, rankedTopics } = getDataIndex("computational");
let browser: Browser, page: Page;
beforeAll(async () => { browser = await chromium.launch(); page = await browser.newPage(); });
afterAll(async () => { await browser?.close(); });

it("truncates descriptions at a word boundary, including exact limits and long words", () => {
  expect(truncateDescription("  short\n description  ")).toBe("short description");
  expect(truncateDescription("a".repeat(160))).toHaveLength(160);
  expect(truncateDescription("word ".repeat(40))).toBe("word ".repeat(32).trimEnd() + "…");
  expect(truncateDescription("x".repeat(170))).toBe("x".repeat(159) + "…");
});

it("builds a 404 page with the main landmark and recovery links, plus the favicon", async () => {
  await page.setContent(read("404.html"));
  expect(await page.title()).toBe("Page not found");
  expect(await page.locator("main#main h1").textContent()).toBe("Page not found");
  for (const [label, href] of [["Today", "/"], ["Archive", "/archive/"], ["Map", "/map/"]]) {
    expect(await page.locator("main").getByRole("link", { name: label, exact: true }).getAttribute("href")).toBe(href);
  }
  expect(read("index.html")).toContain('<link rel="icon" type="image/svg+xml" href="/favicon.svg">');
  expect(statSync("dist/favicon.svg").size).toBeLessThan(2048);
  expect(read("favicon.svg")).toContain('viewBox="0 0 16 16"');
});

it("publishes the selected materials papers and recovered biology originals at their review locations", async () => {
  await page.setContent(read("collections/materials/index.html"));
  const groups = page.locator("main section[id]");
  expect(await groups.count()).toBe(2);
  const papers = await groups.locator("li a").evaluateAll(links => links.map(link => link.getAttribute("href")));
  expect(new Set(papers).size).toBe(7);
  expect(papers.every(url => /^https:\/\/(doi\.org|arxiv\.org)\//.test(url!))).toBe(true);
  await page.setContent(read("collections/energy/index.html"));
  expect(await page.locator("#electrode-processing li a").count()).toBe(4);
  expect(await page.locator("#grid-dispatch li a").count()).toBe(5);
  await page.setContent(read("biology/index.html"));
  expect(await page.locator("#coverage-review li a").count()).toBe(6);
});

it("displays the stored scoring components and synthesis flags in rank order", async () => {
  const day = days.find(issue => issue.ranked.length)!;
  await page.setContent(read(`day/${day.date}/index.html`));
  const rows = page.locator(".rank-signals tbody tr");
  const top = day.ranked.filter(row => row.rank <= 10);
  expect(await rows.count()).toBe(top.length);
  for (const [i, topic] of top.entries()) {
    const { rise, diversity, code_velocity, volume, total } = topic.scores;
    expect(await rows.nth(i).locator("td").allTextContents()).toEqual([
      ...[rise, diversity, code_velocity, volume, total].map(value => value.toFixed(2)),
      day.run.notes.includes(`synthesis-fallback:${topic.slug}`) ? "Yes" : "—",
    ]);
  }
});

it("gives every page canonical, description and preview metadata", async () => {
  const paths = readdirSync("dist", { recursive: true, encoding: "utf8" }).filter(path => path.endsWith(".html"));
  for (const path of paths) {
    const metadata = await page.evaluate(html => {
      const doc = new DOMParser().parseFromString(html, "text/html");
      const content = (selector: string) => doc.querySelector(selector)?.getAttribute("content");
      return { lang: doc.documentElement.lang, languageLinks: doc.querySelectorAll("[hreflang], [data-language]").length, title: doc.title, description: content('meta[name="description"]'),
        canonical: doc.querySelector('link[rel="canonical"]')?.getAttribute("href"),
        ogTitle: content('meta[property="og:title"]'), ogDescription: content('meta[property="og:description"]'),
        ogUrl: content('meta[property="og:url"]'), ogType: content('meta[property="og:type"]'),
        image: content('meta[property="og:image"]'), width: content('meta[property="og:image:width"]'),
        height: content('meta[property="og:image:height"]'), alt: content('meta[property="og:image:alt"]'),
        site: content('meta[property="og:site_name"]'), card: content('meta[name="twitter:card"]'),
        themes: [...doc.querySelectorAll('meta[name="theme-color"]')].map(el => [el.getAttribute("media"), el.getAttribute("content")]) };
    }, read(path));
    expect(metadata.lang, path).toBe("en");
    expect(metadata.languageLinks, path).toBe(0);
    expect(metadata.description, path).toBeTruthy();
    expect(metadata.description!.length, path).toBeLessThanOrEqual(160);
    expect(metadata.canonical).toBe(`https://trendbio.dev/${path.replace(/index\.html$/, "")}`);
    expect(metadata.ogTitle).toBe(metadata.title);
    expect(metadata.ogDescription).toBe(metadata.description);
    expect(metadata.ogUrl).toBe(metadata.canonical);
    expect(metadata.ogType).toBe("website");
    expect(metadata.site).toBe("TrendBio");
    expect(metadata.card).toBe("summary_large_image");
    const field = editions.find(f => path.startsWith(f + "/") || path.startsWith("pilots/" + f + "/"));
    const card = path.startsWith("collections/") ? path.split("/")[1] : field;
    const image = card ? `/og/${card}.png` : "/og.png";
    expect(metadata.image).toBe("https://trendbio.dev" + image);
    expect(existsSync("dist" + image)).toBe(true);
    expect(metadata.width).toBe("1200");
    expect(metadata.height).toBe("630");
    expect(metadata.alt).toBe(field ? `TrendBio — ${fieldLabel(field)}` : card === "energy" ? "TrendBio — Energy Storage & Power Grids" : card ? "TrendBio — Materials Science" : "TrendBio — What moved in computational biology");
    expect(metadata.themes).toEqual([["(prefers-color-scheme: dark)", "oklch(14.5% 0 0)"], ["(prefers-color-scheme: light)", "#fafafa"]]);
  }
  expect(read("index.html")).toContain(truncateDescription(`Today's leading computational biology topic: ${days[0].ranked[0].headline}.`));
  expect(read(`day/${days[0].date}/index.html`)).toContain(truncateDescription(`Top ${days[0].ranked.length} computational-biology topics on ${days[0].date}: ${days[0].ranked[0].headline}`));
});

it("builds valid XML covering the index and every public HTML route with lastmod dates", async () => {
  const parsed = await page.evaluate(xml => {
    const doc = new DOMParser().parseFromString(xml, "application/xml");
    return { error: doc.querySelector("parsererror")?.textContent,
      entries: [...doc.querySelectorAll("url")].map(el => ({ loc: el.querySelector("loc")?.textContent, date: el.querySelector("lastmod")?.textContent })) };
  }, read("sitemap.xml"));
  expect(parsed.error).toBeUndefined();
  const { weeks, months } = loadPeriods();
  const topicSlugs = new Set([...rankedTopics.map(topic => topic.slug), ...[...weeks, ...months].flatMap(period => period.topics.map(topic => topic.slug))]);
  const fieldPages = editions.reduce((n, field) => n + 1 + getDataIndex(field).days.length, 0);
  const fieldTopics = new Map<string, string>();
  for (const field of publicEditions) {
    for (const day of getDataIndex(field).days) {
      for (const row of day.ranked) {
        const url = `https://trendbio.dev/${field}/topic/${row.slug}/`;
        if (!fieldTopics.has(url)) fieldTopics.set(url, day.date);
      }
    }
  }
  expect(parsed.entries).toHaveLength(10 + editions.flatMap(pilotDates).length + fieldPages + days.length + weeks.length + months.length + topicSlugs.size + fieldTopics.size);
  const urls = new Map(parsed.entries.map(({ loc, date }) => [loc, date]));
  for (const [url, date] of fieldTopics) expect(urls.get(url)).toBe(date);
  expect(urls.size).toBe(parsed.entries.length);
  for (const path of readdirSync("dist", { recursive: true, encoding: "utf8" }).filter(path => path.endsWith("index.html"))) {
    expect(urls.has(`https://trendbio.dev/${path.replace(/index\.html$/, "")}`), path).toBe(path !== "search/index.html");
  }
  for (const { date } of days) expect(urls.get(`https://trendbio.dev/day/${date}/`)).toBe(date);
  for (const topic of rankedTopics) expect(urls.get(`https://trendbio.dev/topic/${topic.slug}/`))
    .toBe(topic.history.filter(({ rank }) => rank !== null).map(({ date }) => date).sort().at(-1));
  for (const { date } of parsed.entries) expect(date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(read("robots.txt")).toContain("Sitemap: https://trendbio.dev/sitemap.xml");
});

it("renders native open and closed summary labels and adjacent existing days", async () => {
  const latest = read(`day/${days[0].date}/index.html`);
  expect(latest).toMatch(/<summary[^>]*><span class="closed-label"[^>]*>Show 20 more<\/span><span class="open-label"[^>]*>Show less<\/span><\/summary>/);
  for (const [index, day] of days.entries()) {
    await page.setContent(read(`day/${day.date}/index.html`));
    const nav = page.getByRole("navigation", { name: "Day navigation", exact: true });
    for (const [rel, target] of [["prev", days[index + 1]], ["next", days[index - 1]]] as const) {
      const link = nav.locator(`a[rel="${rel}"]`);
      expect(await link.count()).toBe(target ? 1 : 0);
      if (target) expect(await link.getAttribute("href")).toBe(`/day/${target.date}/`);
    }
  }
  await page.setContent(read("archive/index.html"));
  expect(await page.locator(`#heading-${days[0].date.slice(0, 7)}`).textContent()).toBe("November 2026 in progress");
});

it("ships one PNG link preview at 1200×630 under 200 KB", () => {
  const png = readFileSync("dist/og.png");
  expect(png.subarray(1, 4).toString()).toBe("PNG");
  expect(png.readUInt32BE(16)).toBe(1200);
  expect(png.readUInt32BE(20)).toBe(630);
  expect(png.length).toBeLessThan(200_000);
  expect(png.equals(readFileSync("public/og.png"))).toBe(true);
});

it("explains cookie-free page-view analytics on About", () => {
  expect(read("about/index.html")).toContain("The site uses Cloudflare Web Analytics, which sets no cookies, to count page views.");
});

it("links the Physics edition, its dated ranking and its own supporting papers", async () => {
  await page.setContent(read("index.html"));
  expect(await page.getByRole("navigation").getByText("Physics", { exact: true }).getAttribute("href")).toBe("/physics/");
  for (const path of ["physics/index.html", "physics/day/2026-11-01/index.html"]) {
    await page.setContent(read(path));
    const main = page.locator("main");
    expect(await page.getByRole("heading", { level: 1 }).textContent()).toBe(path === "physics/index.html" ? "What moved in physics today?" : "Physics");
    expect(await page.locator(".hero").count()).toBe(path === "physics/index.html" ? 1 : 0);
    expect(await main.locator('[data-arxiv-scope="current"]').textContent()).toContain("Current coverage");
    expect(await main.locator("ol h3").textContent()).toBe("Optical cavities reveal sources of readout noise");
    expect(await main.locator("ol h3 a").getAttribute("href")).toBe("/physics/topic/cavity-readout-fixture/");
    expect(await main.locator('a[href^="https://example.org/physics/"]').count()).toBe(3);
    const archiveLink = path === "physics/index.html" ? "/physics/day/2026-11-01/" : "/physics/#editions";
    expect(await main.locator(`a[href="${archiveLink}"]`).count()).toBe(1);
  }
});

it("opens the English pilot offline at the selected topic with its cited evidence", async () => {
  const folder = mkdtempSync(join(tmpdir(), "trendbio-pilot-preview-"));
  const offline = await browser.newPage();
  try {
    execFileSync(process.execPath, ["scripts/pilot-preview.mjs", "dist", "../fixtures/data/physics/days/2026-11-01.json", folder]);
    expect(readdirSync(folder)).toEqual(["en.html"]);
    const article = join(folder, "checked", "sample.html");
    execFileSync(process.execPath, ["scripts/pilot-preview.mjs", "dist", "../fixtures/data/physics/days/2026-11-01.json", folder, article]);
    const fragment = readFileSync(article, "utf8");
    expect(fragment).toContain('class="rankings"');
    expect(fragment).toContain("Editorial correction");
    expect(fragment).not.toContain("<html");
    expect(fragment).not.toContain("data-astro-cid-");
    const row = getDataIndex("physics").days[0].ranked[0];
    await offline.context().setOffline(true);
    await offline.goto(pathToFileURL(join(folder, "en.html")).href + "#" + row.slug);
    expect(await offline.locator("html").getAttribute("lang")).toBe("en");
    expect(await offline.locator(":target").getAttribute("value")).toBe("1");
    expect(await offline.locator("main .rankings h3").textContent()).toBe(row.headline);
    const note = offline.getByRole("note");
    expect(await note.locator("strong").textContent()).toBe("Editorial correction");
    expect(await note.locator("a").first().getAttribute("href")).toBe("https://example.org/calibration");
    expect(await note.locator("a").last().textContent()).toBe("arXiv:2611.19130");
    await offline.getByText("3 supporting papers", { exact: true }).click();
    expect(await offline.locator('main details a[href^="https://example.org/physics/"]').count()).toBe(3);
  } finally {
    await offline.close();
    rmSync(folder, { recursive: true, force: true });
  }
});

it("publishes an English archive with permanent redirects for former Korean links", () => {
  expect(readdirSync("dist")).not.toContain("ko");
  expect(read("sitemap.xml")).not.toContain("trendbio.dev/ko/");
  expect(read("_redirects").trim().split("\n")).toEqual(["/ko / 301", "/ko/* https://trendbio.dev/:splat 301"]);
});

it("withdraws pilot ranks by a dated claim or the complete set of reviewed source versions", async () => {
  const folder = mkdtempSync(join(tmpdir(), "trendbio-withdrawal-"));
  try {
    const registry = join(folder, "physics");
    mkdirSync(registry);
    const dayFile = "../fixtures/data/physics/days/2026-11-01.json";
    const day = JSON.parse(readFileSync(dayFile, "utf8"));
    const { headline, slug } = day.ranked[0];
    const papers = [3, 1, 2].map(n => `arxiv:optics-fixture-${n}`);
    const reason = "The studies measure different properties (<noise> and loss).";
    const dated = (claim: string, ids: string[]) => ({ date: day.date, slug, headlines: [claim], papers: ids });
    const render = async (decision: Record<string, unknown>) => {
      writeFileSync(join(registry, "withdrawals.json"), JSON.stringify([{ ...decision, reason }]));
      execFileSync(process.execPath, ["scripts/pilot-preview.mjs", "dist", dayFile, folder],
        { env: { ...process.env, TRENDBIO_NOTES_ROOT: folder } });
      await page.setContent(readFileSync(join(folder, "en.html"), "utf8"));
      return page.locator("ol.rankings > li").first();
    };
    const withdrawn = await render(dated(headline, papers));
    expect(await withdrawn.getAttribute("value")).toBe("1");
    expect(await withdrawn.getByRole("note").textContent()).toBe(reason);
    expect(await withdrawn.locator("details, a").count()).toBe(0);
    expect(await (await render(dated("A revised headline", papers))).locator("h3").textContent()).toBe(headline);
    expect(await (await render(dated(headline, [...papers.slice(1), "another-paper"]))).locator("details").count()).toBe(1);
    const versions = Object.fromEntries([3, 1, 2].map(n => [`arxiv:optics-fixture-${n}`, `https://example.org/physics/cavity-${n}`]));
    expect(await (await render({ source_versions: versions })).getByRole("note").textContent()).toBe(reason);
    expect(await (await render({ source_versions: { ...versions, [papers[0]]: versions[papers[0]] + "v2" } })).locator("h3").textContent()).toBe(headline);
    expect(await (await render({ source_versions: { ...versions, extra: "https://example.org/extra" } })).locator("details").count()).toBe(1);
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
});

it("links each science field and its dated pilots while omitting retired fields", async () => {
  await page.setContent(read("fields/index.html"));
  expect(await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Computer Science" }).getAttribute("href")).toBe("/computer-information/");
  const directory = page.locator("main");
  const links = await directory.locator("dl a").evaluateAll(nodes => nodes.map(a => a.getAttribute("href")));
  expect(new Set(links)).toEqual(new Set(["/", ...editions.map(field => `/${field}/`)]));
  expect(await directory.getByRole("link", { name: "Computer Science", exact: true }).getAttribute("href")).toBe("/computer-information/");
  expect(await directory.getByRole("list", { name: "Physics editions" }).getByRole("link").count()).toBe(2);
  expect(await directory.getByRole("list", { name: "All Biology editions" }).getByRole("link", { name: "CompBio" }).getAttribute("href")).toBe("/");
  for (const field of ["social-sciences", "humanities-arts"]) {
    expect(existsSync(`dist/${field}/index.html`)).toBe(false);
    expect(read("sitemap.xml")).not.toContain(`/${field}/`);
  }
  for (const field of editions.filter(field => !publicEditions.includes(field))) {
    await page.setContent(read(`${field}/index.html`));
    const href = await page.locator("main section[aria-label='Dated pilot editions'] a[href^='/pilots/']").first().getAttribute("href");
    expect(href).toMatch(new RegExp(`^/pilots/${field}/\\d{4}-\\d{2}-\\d{2}/$`));
    const sample = read(href!.slice(1) + "index.html");
    expect(sample).toContain('lang="en"');
    expect(sample).toContain('class="rankings"');
    expect(sample).toContain(`href="/${field}/"`);
  }
});

it("retains original ranks and paper versions in the reviewed Computer Science selection", async () => {
  await page.setContent(read("computer-information/index.html"));
  const review = page.locator("#ranking-review-2026-11-18");
  expect(await review.locator("h3").first().isVisible()).toBe(true);
  const topics = review.locator("ol > li");
  expect(await topics.evaluateAll(nodes => nodes.map(li => Number(li.getAttribute("value"))))).toEqual([9, 35, 38]);
  const papers = await topics.locator("a").evaluateAll(nodes => nodes.map(a => a.getAttribute("href") ?? ""));
  expect(new Set(papers).size).toBe(10);
  expect(papers.every(url => /^https:\/\/arxiv\.org\/abs\/\d{4}\.\d+v\d+$/.test(url))).toBe(true);
});

it("keeps the Biology beta and CompBio as distinct editions", async () => {
  for (const [path, current] of [["biology/index.html", "Biology"], ["index.html", "CompBio"]]) {
    await page.setContent(read(path));
    const switcher = page.getByRole("group", { name: "Science field" });
    expect(await switcher.locator("[aria-current]").textContent()).toBe(current);
    expect(await switcher.getByRole("link", { name: "Biology", exact: true }).getAttribute("href")).toBe("/biology/");
    expect(await switcher.getByText("CompBio").getAttribute("href")).toBe("/");
  }
});

it("shows the sources collected for a Computing edition even when no group ranks", async () => {
  await page.setContent(read("computer-information/day/2026-11-11/index.html"));
  const main = page.getByRole("main");
  expect(await main.locator("[data-edition-venues] span").textContent()).toBe("Proceedings of the 37th Conference on l'Interaction Humain-Machine, arXiv");
  expect(await main.getByRole("link", { name: "IHM proceedings" }).getAttribute("href")).toBe("https://doi.org/10.1145/3845948");
  expect(await main.getByRole("link", { name: "HAL", exact: true }).getAttribute("href")).toBe("https://hal.science/IHM-2026");
  expect(await main.locator("ol.rankings li").count()).toBe(0);
});

it("lists the journals represented in a dated Agriculture pilot and links its regional publisher", async () => {
  await page.setContent(read("agriculture-food-veterinary/day/2026-09-30/index.html"));
  const coverage = page.locator("main .coverage");
  expect(await coverage.count()).toBe(1);
  expect(await coverage.locator("span").textContent()).toBe("Agrociencia Uruguay, Agronomy");
  expect(await coverage.getByRole("link", { name: "Agrociencia Uruguay" }).getAttribute("href"))
    .toBe("https://agrocienciauruguay.uy/index.php/agrociencia/");
});

it("links a dated mathematics edition to the arXiv subjects queried at the time", async () => {
  await page.setContent(read("math/day/2026-11-01/index.html"));
  expect(await page.getByRole("group", { name: "Science field" }).locator("[aria-current]").textContent()).toBe("Math & Stats");
  expect(await page.getByRole("group", { name: "Biology edition" }).count()).toBe(0);
  const main = page.getByRole("main");
  expect(await main.locator('[data-arxiv-scope="edition"] a').evaluateAll(links => links.map(a => a.getAttribute("href"))))
    .toEqual(["https://arxiv.org/list/math.NA/recent"]);
  expect(await main.locator('a[href^="https://example.org/math/"]').count()).toBe(3);
  expect(await main.locator(".coverage").count()).toBe(1);
  expect(await page.locator("footer").textContent()).toContain("Auto-curated from arXiv.");
  expect(await main.getByRole("heading", { name: "Quadrature error bounds depend on smoothness" }).count()).toBe(1);
});

it("credits the Earth pilot papers and links their datasets as supporting material", async () => {
  await page.setContent(read("earth-environment/day/2026-11-01/index.html"));
  expect(await page.locator("[data-window-days=\"28\"]").textContent()).toBe("Evidence window of 28 days from 2026-10-05 through 2026-11-01 (UTC).");
  const main = page.getByRole("main");
  expect(await main.locator(".coverage").textContent()).toBe("Journals represented in this edition’s collection include Ocean Science.");
  expect(await main.locator("summary").first().textContent()).toBe("3 supporting papers");
  await main.locator("summary").first().click();
  expect(await main.locator('a[href^="https://example.org/earth/"]').count()).toBe(3);
  expect(await main.getByRole("link", { name: "CC BY" }).count()).toBe(2);
  expect(await main.getByRole("link", { name: "CC0" }).getAttribute("href")).toBe("https://creativecommons.org/publicdomain/zero/1.0/");
  expect(await main.locator('a[href="https://doi.org/10.5555/example-data"]').count()).toBe(1);
  expect(await main.getByRole("link", { name: "Preprint version" }).getAttribute("href")).toBe("https://doi.org/10.5555/example-preprint");
  expect(await main.getByRole("link", { name: "Publisher correction history" }).getAttribute("href")).toBe("https://crossmark.crossref.org/dialog/?doi=10.5555%2Fexample-earth-1");
  expect(await main.getByRole("link", { name: "Linked correction" }).getAttribute("href")).toBe("https://doi.org/10.5555/example-erratum");
});
