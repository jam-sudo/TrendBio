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
  const input = page.getByRole("combobox", { name: "Search topics" });
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
  const input = page.getByRole("combobox", { name: "Search topics" });
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

const combo = () => page.getByRole('combobox', { name: 'Search topics' });
const options = () => page.getByRole('option');
const dropdownReady = () => page.getByRole('link', { name: 'See all results' }).waitFor();

it('loads dependencies only on focus and shows six headline/category options', async () => {
  const requests: string[] = [];
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  await visit('/');
  await page.waitForLoadState('networkidle');
  expect(requests.filter(url => /pagefind|search-match/.test(url))).toEqual([]);
  await combo().focus();
  await expect.poll(() => requests.includes('/pagefind/pagefind.js')).toBe(true);
  await expect.poll(() => requests.some(url => /^\/_astro\/search-match\.[\w-]+\.js$/.test(url))).toBe(true);
  await combo().fill('r');
  await page.waitForTimeout(500);
  expect(await combo().getAttribute('aria-expanded')).toBe('false');
  await combo().fill('reproducible');
  await dropdownReady();
  expect(await options().count()).toBe(6);
  expect(await options().locator('small').allTextContents()).toHaveLength(6);
  expect(await combo().getAttribute('aria-expanded')).toBe('true');
  expect(await combo().getAttribute('aria-activedescendant')).toBeNull();
  expect(await page.locator('#header-search-status').textContent()).toBe('6 topics shown');
  expect(await page.getByRole('link', { name: 'See all results' }).getAttribute('href')).toBe('/search/?q=reproducible');
});

it('shows no topics for nonsense and lets See all results open the full search', async () => {
  await visit('/');
  await combo().fill('zzzxqnotaword98765');
  await dropdownReady();
  expect(await page.locator('#header-search-message').textContent()).toBe('No topics found');
  expect(await options().count()).toBe(0);
  await page.getByRole('link', { name: 'See all results' }).click();
  await page.waitForURL(url => url.pathname === '/search/' && url.search === '?q=zzzxqnotaword98765');
});

it.each(['keyboard', 'click'])('opens a dropdown topic with %s', async action => {
  await visit('/');
  await combo().fill('Binder');
  await dropdownReady();
  const href = await options().first().getAttribute('href');
  if (action === 'keyboard') {
    await combo().press('ArrowDown');
    expect(await combo().getAttribute('aria-activedescendant')).toBe(await options().first().getAttribute('id'));
    expect(await options().first().getAttribute('aria-selected')).toBe('true');
    await combo().press('ArrowUp');
    expect(await combo().getAttribute('aria-activedescendant')).toBe(await options().last().getAttribute('id'));
    await combo().press('ArrowDown');
    await combo().press('Enter');
  } else await options().first().click();
  await page.waitForURL(url => url.pathname === href);
});

it('submits Enter with an open panel and nothing highlighted', async () => {
  await visit('/');
  await combo().fill('Binder');
  await dropdownReady();
  await combo().press('Enter');
  await page.waitForURL(url => url.pathname === '/search/' && url.search === '?q=Binder');
});

it.each(['Escape', 'Tab', 'outside'])('closes on %s and keeps the text', async action => {
  await visit('/');
  await combo().fill('Binder');
  await dropdownReady();
  await combo().press('ArrowDown');
  if (action === 'outside') await page.locator('h1').click();
  else await combo().press(action);
  expect(await combo().getAttribute('aria-expanded')).toBe('false');
  expect(await combo().getAttribute('aria-activedescendant')).toBeNull();
  expect(await combo().inputValue()).toBe('Binder');
  expect(await page.locator('#header-search-panel').isVisible()).toBe(false);
  if (action === 'Tab') expect(await combo().evaluate(el => el === document.activeElement)).toBe(false);
});

it('silently hides a failed index and preserves Enter fallback', async () => {
  await page.route('**/pagefind/**', route => route.abort());
  await visit('/');
  await combo().fill('Binder');
  await page.waitForTimeout(700);
  expect(await page.locator('#header-search-panel').isVisible()).toBe(false);
  await combo().press('Enter');
  await page.waitForURL(url => url.pathname === '/search/' && url.search === '?q=Binder');
});

it('delays Searching and never lets an older response replace the latest query', async () => {
  await page.route('**/pagefind/pagefind.js', route => route.fulfill({
    contentType: 'text/javascript', body: `
      window.pendingSearches = {};
      export function search(query) {
        return new Promise(resolve => { window.pendingSearches[query] = () => resolve({ results: [{ data: async () => ({
          url: '/topic/' + query + '/', meta: {title: query}, filters: {category: ['Tools']}, content: query
        }) }] }); });
      }`,
  }));
  await visit('/');
  // Freeze elapsed time while imports and browser assertions use real time.
  await page.clock.pauseAt(new Date());
  await combo().focus();
  await expect.poll(() => page.evaluate(() => Boolean((window as any).pendingSearches))).toBe(true);
  await combo().fill('older');
  await page.clock.runFor(150);
  await expect.poll(() => page.evaluate(() => Boolean((window as any).pendingSearches?.older))).toBe(true);
  await page.clock.runFor(299);
  await expect.poll(() => page.locator('#header-search-panel').isVisible()).toBe(false);
  await page.clock.runFor(1);
  await expect.poll(() => page.locator('#header-search-message').textContent()).toBe('Searching…');
  await expect.poll(() => page.locator('#header-search-panel').isVisible()).toBe(true);
  await combo().fill('newer');
  expect(await combo().getAttribute('aria-expanded')).toBe('false');
  await page.clock.runFor(150);
  await expect.poll(() => page.evaluate(() => Boolean((window as any).pendingSearches?.newer))).toBe(true);
  await page.evaluate(() => (window as any).pendingSearches.newer());
  await dropdownReady();
  await expect.poll(() => options().allTextContents()).toEqual(['newerTools']);
  await page.evaluate(() => (window as any).pendingSearches.older());
  await page.clock.runFor(1000);
  await expect.poll(() => options().allTextContents()).toEqual(['newerTools']);
});

it.each(['dark', 'light'].flatMap(theme => [320, 390].map(width => ({ theme, width }))))(
  'has an accessible overlay without overflow in $theme at $width', async ({ theme, width }) => {
    await page.setViewportSize({ width, height: 600 });
    await page.addInitScript(theme => localStorage.setItem('trendbio-theme', theme), theme);
    await visit('/');
    const mainTop = await page.locator('main').evaluate(el => el.getBoundingClientRect().top + scrollY);
    await combo().fill('reproducible');
    await dropdownReady();
    await combo().press('ArrowDown');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    expect(await page.locator('main').evaluate(el => el.getBoundingClientRect().top + scrollY)).toBe(mainTop);
    const box = (await combo().boundingBox())!;
    const panel = (await page.locator('#header-search-panel').boundingBox())!;
    expect(box.y).toBeLessThan(96);
    expect(panel.width).toBe(box.width);
    expect(panel.y).toBeGreaterThan(box.y + box.height);
    expect(panel.y + panel.height).toBeLessThanOrEqual(600);
    expect(await page.locator('#header-search-panel').evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true);
    expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()).violations).toEqual([]);
  },
);

it.each(['dark', 'light'].flatMap(theme => [
  { width: 1280, height: 800 }, { width: 390, height: 844 },
].map(viewport => ({ theme, ...viewport }))))(
  'fits the home search overlay below the box at $width × $height in $theme', async ({ theme, width, height }) => {
    await page.setViewportSize({ width, height });
    await page.addInitScript(theme => localStorage.setItem('trendbio-theme', theme), theme);
    await visit('/');
    await page.evaluate(() => document.fonts.ready);
    const rowTop = await page.locator('[data-topic-cats]').first().evaluate(el => el.getBoundingClientRect().top + scrollY);
    await combo().fill('reproducible');
    await dropdownReady();
    const box = (await combo().boundingBox())!;
    const panel = (await page.locator('#header-search-panel').boundingBox())!;
    expect(panel.y).toBeCloseTo(box.y + box.height + 4, 1);
    expect(panel.y + panel.height).toBeLessThanOrEqual(height);
    expect(panel.x).toBe(box.x);
    expect(panel.width).toBe(box.width);
    expect(panel.height).toBeCloseTo(Math.min(420, height - box.y - box.height - 20), 0);
    expect(await page.locator('[data-topic-cats]').first().evaluate(el => el.getBoundingClientRect().top + scrollY)).toBe(rowTop);
    expect(await page.locator('#header-search-panel').evaluate(el => {
      const rect = el.getBoundingClientRect();
      return el.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.bottom - 5));
    })).toBe(true);
    expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()).violations).toEqual([]);
  },
);
