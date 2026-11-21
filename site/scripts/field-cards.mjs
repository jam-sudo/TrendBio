// Run against a local preview after changing a field's hero.
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

const origin = process.argv[2];
if (!origin) throw Error("Pass the URL of the local site preview.");
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, colorScheme: "dark", reducedMotion: "reduce" });
  await page.goto(new URL("/fields/", origin).href);
  const paths = await page.locator("main dl a, main a[href^='/collections/']").evaluateAll(links =>
    links.map(link => link.pathname).filter(path => path !== "/"));
  await mkdir("public/og", { recursive: true });
  for (const path of new Set(paths)) {
    await page.goto(new URL(path, origin).href);
    const field = await page.locator(".hero svg").getAttribute("data-field");
    if (!field) throw Error(`Missing field art on ${path}`);
    await page.evaluate(() => {
      const hero = document.querySelector(".hero");
      const brand = document.createElement("div");
      brand.textContent = "TrendBio";
      hero.prepend(brand);
      document.body.replaceChildren(hero);
    });
    await page.addStyleTag({ content: `
      body { margin:0; display:grid; place-items:center; min-height:630px; }
      .hero { width:1060px; margin:0; display:grid; justify-items:center; gap:18px; }
      .hero > div:first-child { font-size:32px; color:var(--muted); }
      .hero h1 { font-size:64px; max-width:980px; line-height:1.05; }
      .hero p { display:none; }
      .hero .hero-art { width:530px; margin:0; }
    ` });
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: `public/og/${field}.png` });
  }
} finally { await browser.close(); }
