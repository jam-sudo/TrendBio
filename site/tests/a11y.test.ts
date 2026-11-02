import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { preview } from "astro";
import { chromium, type Browser, type Page } from "playwright";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

it("keeps the only animation rule behind the no-preference motion query", () => {
  const sources = readdirSync("src", { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => ({ path: join(entry.parentPath, entry.name), text: readFileSync(join(entry.parentPath, entry.name), "utf8") }));
  const declarations = /\banimation(?:-[\w-]+)?\s*:[^;}]+/g;
  const animated = sources.filter(({ text }) => /\banimation(?:-[\w-]+)?\s*:/.test(text));
  expect(animated).toHaveLength(1);
  expect(["src/styles/global.css", "src/components/Helix.astro"]).toContain(animated[0].path);
  const rule = animated[0].text.match(/@media\s*\(prefers-reduced-motion:\s*no-preference\)\s*\{\s*[^{}]+\{([^{}]+)\}/);
  expect(rule).not.toBeNull();
  expect(animated[0].text.match(declarations)).toEqual(rule![1].match(declarations));
  expect(rule![1].match(/\banimation\s*:/g)).toHaveLength(1);
});

describe("built site accessibility and responsive layout", () => {
  let server: Awaited<ReturnType<typeof preview>> | undefined;
  let browser: Browser | undefined;
  let page: Page;
  let unavailable: string | undefined;

  beforeAll(async () => {
    if (!existsSync(chromium.executablePath())) {
      try {
        execFileSync(process.execPath, ["node_modules/playwright/cli.js", "install", "chromium"], {
          timeout: 60_000, stdio: "pipe",
        });
      } catch (error) {
        unavailable = `Skipping browser checks: Chromium could not be installed; run npx playwright install chromium. ${String(error)}`;
        console.warn(unavailable);
        return;
      }
    }
    browser = await chromium.launch({ headless: true, executablePath: chromium.executablePath() });
    server = await preview({ server: { host: "127.0.0.1" }, logLevel: "error" });
  }, 90_000);

  beforeEach(async (context) => {
    if (unavailable) context.skip(unavailable);
    const browserContext = await browser!.newContext({ viewport: { width: 1280, height: 900 } });
    page = await browserContext.newPage();
  });

  afterEach(async () => { await page?.context().close(); });
  afterAll(async () => {
    await browser?.close();
    await server?.stop();
  });

  it.each(["/", "/topic/protein-design-binders-a1b2/", "/topics/", "/archive/"])(
    "%s has zero WCAG A/AA violations and accessible landmarks", async (path) => {
      const response = await page.goto(`http://127.0.0.1:${server!.port}${path}`);
      expect(response?.status()).toBe(200);
      const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
      console.log(`axe ${path}: ${violations.length} wcag2a/wcag2aa violations`);
      expect(violations).toEqual([]);
      for (const selector of ["header", "header nav[aria-label]", "main#main", "footer", "h1"]) {
        expect(await page.locator(selector).count(), selector).toBe(1);
      }
      await page.keyboard.press("Tab");
      expect(await page.locator("a[href='#main']").evaluate((link) => link === document.activeElement)).toBe(true);
      expect(await page.locator("a[href='#main']").evaluate((link) => getComputedStyle(link).outlineStyle)).toBe("solid");
      await page.keyboard.press("Enter");
      expect(new URL(page.url()).hash).toBe("#main");
      if (path === "/") expect(await page.locator(".helix").getAttribute("aria-hidden")).toBe("true");
      if (path.startsWith("/topic/")) expect(await page.locator(".sparkline").getAttribute("aria-label")).toBeTruthy();
    }, 30_000,
  );

  it("stacks cards and scrolls a single unwrapped chip row at 375px", async () => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`http://127.0.0.1:${server!.port}/`);
    const cards = page.locator("[data-topic-cats]");
    const first = (await cards.nth(0).boundingBox())!;
    const second = (await cards.nth(1).boundingBox())!;
    expect(first.width).toBeGreaterThan(300);
    expect(second.y).toBeGreaterThan(first.y + first.height);
    const chips = await page.locator("[data-category-chips]").evaluate((row) => ({
      scrollWidth: row.scrollWidth, clientWidth: row.clientWidth,
      overflow: getComputedStyle(row).overflowX, wrap: getComputedStyle(row).flexWrap,
      tops: [...row.children].map((chip) => chip.getBoundingClientRect().top),
    }));
    expect(chips.scrollWidth).toBeGreaterThan(chips.clientWidth);
    expect(chips.overflow).toBe("auto");
    expect(chips.wrap).toBe("nowrap");
    expect(new Set(chips.tops).size).toBe(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(375);
  });

  it("spans both columns with the first card at 1280px", async () => {
    await page.goto(`http://127.0.0.1:${server!.port}/`);
    const cards = page.locator("[data-topic-cats]");
    const first = (await cards.nth(0).boundingBox())!;
    const second = (await cards.nth(1).boundingBox())!;
    expect(first.width).toBeGreaterThan(1.5 * second.width);
  });

  it("updates chip pressed states and filters cards from the keyboard", async () => {
    await page.goto(`http://127.0.0.1:${server!.port}/`);
    const all = page.locator('[data-cat="all"]');
    await all.focus();
    await page.keyboard.press("ArrowRight");
    const selected = page.locator('[data-cat][aria-pressed="true"]');
    expect(await selected.count()).toBe(1);
    const category = await selected.getAttribute("data-cat");
    expect(category).not.toBe("all");
    expect(await all.getAttribute("aria-pressed")).toBe("false");
    expect(await selected.evaluate((chip) => chip === document.activeElement)).toBe(true);
    const visible = page.locator("[data-topic-cats]:visible");
    expect(await visible.count()).toBeGreaterThan(0);
    for (const card of await visible.all()) expect((await card.getAttribute("data-topic-cats"))!.split(/\s+/)).toContain(category);
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()).violations).toEqual([]);
    await page.keyboard.press("Home");
    expect(await all.getAttribute("aria-pressed")).toBe("true");
    expect(await visible.count()).toBe(5);
  }, 30_000);
});
