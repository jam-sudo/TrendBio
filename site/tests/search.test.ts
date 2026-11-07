import { readFileSync, readdirSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { preview } from "astro";
import { chromium, type Browser, type Page } from "playwright";
import { afterAll, afterEach, beforeAll, beforeEach, expect, it } from "vitest";

let browser: Browser, page: Page, server: Awaited<ReturnType<typeof preview>>;
beforeAll(async () => {
  browser = await chromium.launch();
  server = await preview({ server: { host: "127.0.0.1", port: 4333 }, logLevel: "error" });
});
beforeEach(async () => { page = await (await browser.newContext()).newPage(); });
afterEach(async () => { await page?.context().close(); });
afterAll(async () => { await browser?.close(); await server?.stop(); });
const visit = (path: string) => page.goto(`http://127.0.0.1:${server.port}${path}`);
const finished = () => page.waitForFunction(() => /found\./.test(document.getElementById("search-status")!.textContent!));

it.each(["Binder", "  Binder  "])("submits the home search and trims %j on the search page", async query => {
  await visit("/");
  const input = page.getByRole("searchbox", { name: "Search topics" });
  await input.fill(query);
  await input.press("Enter");
  await page.waitForURL(url => url.pathname === "/search/" && url.search === "?q=Binder");
  await finished();
  expect(await page.getByRole("searchbox").inputValue()).toBe("Binder");
  expect(await page.locator('#search-results a[href="/topic/protein-design-binders-a1b2/"]').textContent()).toBe("Binder design gains shared evaluation tools");
  expect(await page.locator("header form").count()).toBe(0);
  expect(await page.getByRole("search").count()).toBe(1);
});

it.each(["", "   "])("submits an empty home query %j to the focused empty prompt", async query => {
  await visit("/");
  const input = page.getByRole("searchbox", { name: "Search topics" });
  await input.fill(query);
  await input.press("Enter");
  await page.waitForURL(url => url.pathname === "/search/" && !url.search);
  await expect.poll(() => page.getByRole("status").textContent()).toContain("Enter a term");
  expect(await page.getByRole("searchbox").inputValue()).toBe("");
  expect(await page.getByRole("searchbox").evaluate(el => el === document.activeElement)).toBe(true);
});

it("searches a fixture headline and displays its category and excerpt", async () => {
  await visit("/search/");
  await expect.poll(() => page.getByRole("searchbox").evaluate(el => el === document.activeElement)).toBe(true);
  expect(await page.locator("#search-help").textContent()).toContain("paper titles and tool names");
  await page.getByRole("searchbox", { name: "Search topics" }).fill("Binder");
  await finished();
  const result = page.locator('#search-results li').filter({ hasText: "Binder design gains shared evaluation tools" });
  expect(await result.locator("a").getAttribute("href")).toBe("/topic/protein-design-binders-a1b2/");
  expect(await result.locator(".category").textContent()).toBe("Structural bio & protein design");
  expect(await result.locator(".excerpt").textContent()).toBeTruthy();
});

it("prefills and runs URL queries, and shows an empty state for nonsense", async () => {
  await visit("/search/?q=Binder");
  await finished();
  expect(await page.getByRole("searchbox").inputValue()).toBe("Binder");
  expect(await page.locator("#search-results a").count()).toBeGreaterThan(0);
  await page.getByRole("searchbox").fill("zzzxqnotaword98765");
  await expect.poll(() => page.getByRole("status").textContent()).toBe("No topics found. Try another term or category.");
  expect(await page.locator("#search-results li").count()).toBe(0);
  await page.getByRole("searchbox").fill("");
  await expect.poll(() => page.getByRole("status").textContent()).toContain("Enter a term");
  expect(new URL(page.url()).searchParams.has("q")).toBe(false);
});

it("narrows results by category and loads further results on demand", async () => {
  await visit("/search/?q=reproducible");
  await finished();
  expect(await page.locator("#search-results li").count()).toBe(20);
  await page.getByRole("button", { name: "Show more results" }).click();
  await expect.poll(() => page.locator("#search-results li").count()).toBeGreaterThan(20);
  await page.getByLabel("Category", { exact: true }).selectOption({ label: "Structural bio & protein design" });
  await expect.poll(() => page.locator("#search-results .category").allTextContents()).toEqual(Array(4).fill("Structural bio & protein design"));
});

it.each(["dark", "light"].flatMap(theme => [320, 390].map(width => ({ theme, width }))))(
  "keeps search results accessible without overflow in $theme at $width", async ({ theme, width }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(theme => localStorage.setItem("trendbio-theme", theme), theme);
    await visit("/search/?q=Binder");
    await finished();
    await page.evaluate(() => document.fonts.ready);
    expect(await page.getByRole("search").count()).toBe(1);
    expect(await page.getByRole("searchbox").count()).toBe(1);
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()).violations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  },
);

it("loads no Pagefind files on home or before a search and explains the JavaScript requirement", async () => {
  const requested: string[] = [];
  page.on("request", request => { if (request.url().includes("/pagefind/")) requested.push(request.url()); });
  await visit("/");
  await page.waitForLoadState("networkidle");
  expect(await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Search", exact: true }).count()).toBe(0);
  expect(requested).toEqual([]);
  await visit("/search/");
  await page.waitForLoadState("networkidle");
  expect(requested).toEqual([]);
  const noJS = await browser.newContext({ javaScriptEnabled: false });
  try {
    const staticPage = await noJS.newPage();
    await staticPage.goto(`http://127.0.0.1:${server.port}/`);
    const input = staticPage.getByRole("searchbox", { name: "Search topics" });
    await input.fill("Binder");
    await input.press("Enter");
    await staticPage.waitForURL(`http://127.0.0.1:${server.port}/search/?q=Binder`);
    await staticPage.locator("noscript p").waitFor({ state: "visible" });
    expect(await staticPage.locator("noscript p").textContent()).toContain("Search needs JavaScript.");
  } finally { await noJS.close(); }
});

it("indexes only topic pages and keeps search out of the sitemap with noindex", () => {
  for (const path of readdirSync("dist", { recursive: true, encoding: "utf8" }).filter(path => path.endsWith(".html"))) {
    expect(readFileSync(`dist/${path}`, "utf8").includes("data-pagefind-body"), path).toBe(path.startsWith("topic/"));
  }
  expect(readFileSync("dist/search/index.html", "utf8")).toContain('name="robots" content="noindex"');
  expect(readFileSync("dist/sitemap.xml", "utf8")).not.toContain("/search/");
});

it("reports a failed index load without leaving a searching state", async () => {
  await page.route("**/pagefind/**", route => route.abort());
  await visit("/search/?q=Binder");
  await expect.poll(() => page.getByRole("status").textContent()).toBe("Search could not load. Please try again.");
});
