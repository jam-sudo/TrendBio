import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { preview } from "astro";
import { chromium } from "playwright";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { loadSponsors } from "../src/lib/sponsors";

const sponsor = { name: "Example Bio", tagline: "Tools for computational biology", url: "https://example.com", logo: "🧪", hue: 150 };
const config = { slots: 10, contact: "jaemin6013@gmail.com", sponsors: [sponsor] };
const temporary = mkdtempSync(resolve(".sponsors-test-"));
const fixture = join(temporary, "sponsors.json");
function useFixture(data: unknown) {
  writeFileSync(fixture, JSON.stringify(data));
  vi.stubEnv("TRENDBIO_SPONSORS_FILE", fixture);
}
afterEach(() => vi.unstubAllEnvs());
afterAll(() => rmSync(temporary, { recursive: true, force: true }));

it("loads the shipped empty inventory", () => {
  expect(loadSponsors()).toEqual({ slots: 10, contact: "jaemin6013@gmail.com", sponsors: [] });
});

it.each([
  ["missing url", { ...sponsor, url: undefined }, /sponsors\[0\]\.url/],
  ["unsafe url", { ...sponsor, url: "javascript:alert(1)" }, /url/],
  ["long tagline", { ...sponsor, tagline: "a".repeat(61) }, /tagline/],
  ["multiline name", { ...sponsor, name: "One\nTwo" }, /name/],
  ["bad hue", { ...sponsor, hue: 361 }, /hue/],
  ["remote logo", { ...sponsor, logo: "https://example.com/logo.png" }, /logo/],
  ["traversal logo", { ...sponsor, logo: "/sponsors/../../logo.png" }, /logo/],
  ["missing logo", { ...sponsor, logo: "/sponsors/missing.png" }, /logo/],
  ["text logo", { ...sponsor, logo: "bio" }, /logo/],
])("rejects %s with a clear entry error", (_, entry, error) => {
  useFixture({ ...config, sponsors: [entry] });
  expect(() => loadSponsors()).toThrow(error);
});

it.each([
  { ...config, slots: 3 }, { ...config, slots: -2 }, { ...config, slots: 0 },
  { ...config, contact: "invalid" }, { ...config, sponsors: {} }, null,
])("rejects malformed inventory %#", data => {
  useFixture(data);
  expect(() => loadSponsors()).toThrow(/Invalid sponsors file/);
});

it("accepts a local image source and rejects files larger than 20 KB", () => {
  const directory = mkdtempSync(resolve("public/sponsors/test-"));
  const path = join(directory, "logo.svg");
  try {
    writeFileSync(path, '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28"><circle cx="14" cy="14" r="12"/></svg>');
    useFixture({ ...config, sponsors: [{ ...sponsor, logo: `/${path.split("/public/")[1]}` }] });
    expect(loadSponsors().sponsors[0].logo).toMatch(/logo.svg$/);
    writeFileSync(path, "x".repeat(20 * 1024 + 1));
    expect(() => loadSponsors()).toThrow(/20 KB/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

it("fails the build for an entry missing url", () => {
  useFixture({ ...config, sponsors: [{ ...sponsor, url: undefined }] });
  const result = spawnSync(process.execPath, ["node_modules/astro/astro.js", "build", "--outDir", join(temporary, "invalid")], { env: process.env, encoding: "utf8" });
  expect(result.status).not.toBe(0);
  expect(result.stdout + result.stderr).toMatch(/Invalid sponsors file.*sponsors\[0\]\.url/);
});

it("builds both columns and the empty advert before the footer on every page", () => {
  for (const path of ["index.html", "about/index.html", "archive/index.html"]) {
    const html = readFileSync(`dist/${path}`, "utf8");
    expect(html).toContain("sponsor-left");
    expect(html).toContain("sponsor-right");
    expect(html).toContain("sponsored-badge");
    expect(html).toContain("SPONSORED");
    expect(html).toContain("Advertise · 10/10 spots left");
    expect(html).toContain('href="mailto:jaemin6013@gmail.com?subject=TrendBio%20sponsorship"');
    expect(html.indexOf('class="sponsors-row"')).toBeLessThan(html.indexOf("<footer"));
  }
});

describe("sponsor rendering", () => {
  let browser: Awaited<ReturnType<typeof chromium.launch>>;
  let server: Awaited<ReturnType<typeof preview>>;
  let fixtureServer: Awaited<ReturnType<typeof preview>>;
  beforeAll(async () => {
    const output = join(temporary, "dist");
    writeFileSync(fixture, JSON.stringify({ ...config, sponsors: [sponsor, { ...sponsor, name: "Protein Lab", hue: 280, logo: "🧬" }] }));
    execFileSync(process.execPath, ["node_modules/astro/astro.js", "build", "--outDir", output], {
      env: { ...process.env, TRENDBIO_SPONSORS_FILE: fixture },
    });
    browser = await chromium.launch({ executablePath: chromium.executablePath() });
    server = await preview({ server: { host: "127.0.0.1", port: 4330 }, logLevel: "error" });
    fixtureServer = await preview({ outDir: output, server: { host: "127.0.0.1", port: 4331 }, logLevel: "error" });
  });
  afterAll(async () => {
    await browser?.close();
    await server?.stop();
    await fixtureServer?.stop();
  });

  it("aligns sticky columns at the hero and shows the footer row below 1440px", async () => {
    const page = await browser.newPage({ viewport: { width: 1512, height: 982 }, colorScheme: "dark", reducedMotion: "reduce" });
    try {
      await page.goto(`http://127.0.0.1:${server.port}/`);
      await page.evaluate(() => document.fonts.ready);
      expect(await page.locator(".sponsor-column:visible").count()).toBe(2);
      expect(await page.locator(".sponsors-row").isVisible()).toBe(false);
      const advert = (await page.locator(".sponsor-right .advertise-card").boundingBox())!;
      const hero = (await page.locator(".hero").boundingBox())!;
      expect(advert.y).toBe(hero.y);
      expect(advert.width).toBe(200);
      expect(advert.x - hero.x - hero.width).toBe(24);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(1512);
      mkdirSync(".playwright-shots", { recursive: true });
      await page.screenshot({ path: ".playwright-shots/sponsors-1512-dark.png" });
      await page.evaluate(() => window.scrollTo(0, 400));
      expect((await page.locator(".sponsor-right .advertise-card").boundingBox())!.y).toBe(32);
      await page.goto(`http://127.0.0.1:${server.port}/about/`);
      expect((await page.locator(".sponsor-right").boundingBox())!.y).toBe((await page.locator("main").boundingBox())!.y);
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.goto(`http://127.0.0.1:${server.port}/`);
      expect(await page.locator(".sponsor-column:visible").count()).toBe(0);
      expect(await page.locator(".sponsors-row .advertise-card:visible").count()).toBe(1);
      await page.locator(".sponsors-row").scrollIntoViewIfNeeded();
      await page.screenshot({ path: ".playwright-shots/sponsors-1280-dark.png" });
    } finally { await page.close(); }
  });

  it.each(["dark", "light"])("shows two sponsors and eight vacancies, with AA contrast in %s", async theme => {
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      await page.addInitScript(theme => localStorage.setItem("trendbio-theme", theme), theme);
      await page.goto(`http://127.0.0.1:${fixtureServer.port}/`);
      for (const width of [1512, 1280, 375]) {
        await page.setViewportSize({ width, height: 982 });
        expect(await page.locator("[data-sponsor]:visible").count()).toBe(2);
        expect(await page.locator(".advertise-card:visible").textContent()).toContain("8/10 spots left");
        for (const card of await page.locator("[data-sponsor]:visible").all()) {
          expect(await card.getAttribute("rel")).toBe("sponsored noopener");
          expect(await card.getAttribute("target")).toBe("_blank");
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
        expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()).violations).toEqual([]);
        if (width === 375) expect(await page.locator(".sponsor-scroll").evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
      }
    } finally { await context.close(); }
  });
});
