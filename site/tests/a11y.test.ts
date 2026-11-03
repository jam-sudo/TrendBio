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

  it.each(["dark", "light"].flatMap(theme => ["/", "/topic/protein-design-binders-a1b2/", "/topics/", "/archive/"].map(path => ({ theme, path }))))(
    "$path in $theme has zero WCAG A/AA violations and accessible landmarks", async ({ theme, path }) => {
      await page.addInitScript(theme => localStorage.setItem("trendbio-theme", theme), theme);
      const response = await page.goto(`http://127.0.0.1:${server!.port}${path}`);
      expect(response?.status()).toBe(200);
      const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
      console.log(`axe ${theme} ${path}: ${violations.length} wcag2a/wcag2aa violations`);
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

  it("switches themes from the keyboard and remembers the choice across pages", async () => {
    await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
    await page.goto(`http://127.0.0.1:${server!.port}/`);
    const toggle = page.locator("#theme-toggle");
    expect(await page.locator("html").getAttribute("data-theme")).toBe("dark");
    expect(await toggle.getAttribute("aria-label")).toBe("Switch to light theme");
    expect(await toggle.getAttribute("aria-pressed")).toBe("false");
    expect(await page.locator(".helix-flow").evaluate(el => getComputedStyle(el).animationName)).toBe("none");
    await toggle.focus();
    await page.keyboard.press("Enter");
    expect(await page.locator("html").getAttribute("data-theme")).toBe("light");
    expect(await toggle.getAttribute("aria-label")).toBe("Switch to dark theme");
    expect(await toggle.getAttribute("aria-pressed")).toBe("true");
    expect(await page.evaluate(() => localStorage.getItem("trendbio-theme"))).toBe("light");
    await page.locator('.nav-links a[href="/topics"]').click();
    expect(await page.locator("html").getAttribute("data-theme")).toBe("light");
    await page.locator("#theme-toggle").focus();
    await page.keyboard.press("Space");
    expect(await page.locator("html").getAttribute("data-theme")).toBe("dark");
  });

  it("fills the topic column with the sparkline at both viewport sizes", async () => {
    for (const width of [1280, 375]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`http://127.0.0.1:${server!.port}/topic/protein-design-binders-a1b2/`);
      const column = (await page.locator("article.prose").boundingBox())!;
      const chart = (await page.locator(".sparkline").boundingBox())!;
      expect(chart.x).toBe(column.x);
      expect(chart.width).toBe(column.width);
      const bars = page.locator(".sparkline rect");
      const first = (await bars.first().boundingBox())!, last = (await bars.last().boundingBox())!;
      expect(first.x).toBeCloseTo(chart.x, 1);
      expect(last.x + last.width).toBeCloseTo(chart.x + chart.width, 1);
    }
  });

  it("stacks cards and scrolls a single unwrapped chip row at 375px", async () => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`http://127.0.0.1:${server!.port}/`);
    const nav = await page.locator(".nav-links").boundingBox();
    expect(nav!.height).toBeLessThan(40);
    const title = (await page.locator("#hero-title").boundingBox())!;
    const art = (await page.locator(".hero-art").boundingBox())!;
    expect(art.y).toBeGreaterThan(title.y + title.height);
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

  it("aligns calendar weekdays and keeps mobile cells compact", async () => {
    await page.goto(`http://127.0.0.1:${server!.port}/archive/`);
    const october = page.locator("#month-2026-10");
    const november = page.locator("#month-2026-11");
    const thursday = (await october.locator(".weekday").nth(3).boundingBox())!;
    const octoberFirst = (await october.locator('.missing:has(time[datetime="2026-10-01"])').boundingBox())!;
    expect(octoberFirst.x).toBe(thursday.x);
    const sunday = (await november.locator(".weekday").nth(6).boundingBox())!;
    const novemberFirst = page.locator('a[href="/day/2026-11-01/"]');
    expect((await novemberFirst.boundingBox())!.x).toBe(sunday.x);
    expect(await novemberFirst.locator(".headline").evaluate(el => getComputedStyle(el).webkitLineClamp)).toBe("2");
    for (const month of [october, november]) {
      const heights = await month.locator(".calendar-day").evaluateAll(cells => cells.map(cell => cell.getBoundingClientRect().height));
      expect(new Set(heights).size).toBe(1);
      expect(heights[0]).toBeGreaterThanOrEqual(112);
    }
    const partial = october.locator('a[href="/day/2026-10-29/"]');
    const partialBox = (await partial.boundingBox())!;
    const badge = (await partial.locator(".day-badge").boundingBox())!;
    const dayNumber = (await partial.locator("time").boundingBox())!;
    expect(badge.x).toBe(dayNumber.x);
    expect(partialBox.y + partialBox.height - badge.y - badge.height).toBeCloseTo(11, 0);
    const number = (await novemberFirst.locator("time").boundingBox())!;
    const icon = (await novemberFirst.locator("svg").boundingBox())!;
    expect(icon.x).toBeGreaterThan(number.x + number.width);
    expect(icon.y).toBeLessThan(number.y + number.height);
    await novemberFirst.focus();
    expect(await novemberFirst.evaluate(el => getComputedStyle(el).outlineStyle)).toBe("solid");
    await page.setViewportSize({ width: 375, height: 812 });
    expect(await page.locator(".headline:visible, .day-badge:visible, .quiet:visible").count()).toBe(0);
    expect(await page.locator(".mobile-note:visible").count()).toBe(2);
    expect(await novemberFirst.locator("svg:visible").count()).toBe(1);
    expect((await novemberFirst.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect(await page.locator(".month-nav").evaluate(el => getComputedStyle(el).overflowX)).toBe("auto");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(375);
    await novemberFirst.click();
    expect(new URL(page.url()).pathname).toBe("/day/2026-11-01/");
  });

  it("uses equal-width leaderboard rows at 1280px", async () => {
    await page.goto(`http://127.0.0.1:${server!.port}/`);
    const cards = page.locator("[data-topic-cats]");
    const first = (await cards.nth(0).boundingBox())!;
    const second = (await cards.nth(1).boundingBox())!;
    expect(first.width).toBe(second.width);
    expect(second.y).toBeGreaterThan(first.y + first.height);
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
