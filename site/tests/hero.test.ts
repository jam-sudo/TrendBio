import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { runInNewContext } from "node:vm";
import { beforeAll, describe, expect, it } from "vitest";
import { latestDay, loadTaxonomy, loadTopic } from "../src/lib/data";

let html: string;
let scripts: RegExpMatchArray[];

beforeAll(() => {
  html = readFileSync("dist/index.html", "utf8");
  scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
}, 30_000);

describe("built landing hero", () => {
  it("contains a decorative SVG inside the hero and no video", () => {
    const hero = html.match(/<section\b[^>]*class="hero"[^>]*>([\s\S]*?)<\/section>/)?.[1];
    expect(hero).toContain("<svg");
    expect(hero).toContain('aria-hidden="true"');
    expect(html).not.toContain("<video");
  });

  it("keeps the eight-second animation behind the reduced-motion preference", () => {
    expect(html).toContain("prefers-reduced-motion: no-preference");
    expect(html).toMatch(/animation:[^;}]*8s/);
  });

  it("keeps all page JavaScript within 30 KB and the inline filter within 2 KB", () => {
    const bytes = scripts.reduce((total, [, attributes, body]) => {
      const src = attributes.match(/\bsrc="([^"]+)"/)?.[1];
      return total + Buffer.byteLength(body) + (src ? statSync(join("dist", src.split(/[?#]/)[0])).size : 0);
    }, 0);
    expect(bytes).toBeLessThanOrEqual(30_000);
    const filter = scripts.find(([, , body]) => body.includes("data-topic-cats"))?.[2];
    expect(filter).toBeDefined();
    expect(Buffer.byteLength(filter!)).toBeLessThanOrEqual(2_000);
  });

  it("disables every zero-count category and renders the latest ranked headlines", () => {
    const day = latestDay("computational")!;
    expect(day.date).toBe("2026-11-01");
    for (const category of loadTaxonomy("computational")) {
      const chip = html.match(new RegExp(`<button\\b[^>]*data-cat="${category.slug}"[^>]*>`))?.[0];
      expect(chip).toBeDefined();
      expect(chip).not.toContain('role="tab"');
      expect(chip).toContain('aria-pressed="false"');
      expect(/\bdisabled\b/.test(chip!)).toBe(!day.ranked.some((topic) =>
        topic.category === category.slug ||
        loadTopic("computational", topic.slug)?.secondary_categories.includes(category.slug),
      ));
    }
    for (const topic of day.ranked) {
      const secondary = loadTopic("computational", topic.slug)?.secondary_categories ?? [];
      expect(html).toContain(`data-topic-cats="${[topic.category, ...secondary].join(" ")}"`);
      expect(html).toContain(topic.headline);
    }
  });

  it("filters whole category slugs, accepts secondary categories, and restores All", () => {
    let focused = "";
    const buttons = ["all", "genomics", "proteomics"].map((cat) => ({
      dataset: { cat }, disabled: cat === "proteomics", attributes: {} as Record<string, string>,
      setAttribute(name: string, value: string) { this.attributes[name] = value; },
      closest() { return this; },
      focus() { focused = cat; },
      click() { listeners.click({ target: this }); },
    }));
    const cards = ["genomics ml-ai", "epigenomics", "single-cell"].map((topicCats) => ({
      dataset: { topicCats }, hidden: false,
    }));
    const listeners: Record<string, (event: object) => void> = {};
    const row = {
      querySelectorAll: () => buttons,
      addEventListener: (event: string, listener: (event: object) => void) => { listeners[event] = listener; },
    };
    const script = scripts.find(([, , body]) => body.includes("data-topic-cats"))?.[2];
    expect(script).toBeDefined();
    runInNewContext(script!, {
      document: {
        querySelectorAll: (selector: string) => selector === "[data-topic-cats]" ? cards : [row],
      },
    });
    listeners.click({ target: buttons[1] });
    expect(cards.map((card) => card.hidden)).toEqual([false, true, true]);
    expect(buttons.map((button) => button.attributes["aria-pressed"])).toEqual(["false", "true", "false"]);
    listeners.click({ target: buttons[2] });
    expect(cards.map((card) => card.hidden)).toEqual([false, true, true]);
    listeners.click({ target: buttons[0] });
    expect(cards.every((card) => !card.hidden)).toBe(true);
    const press = (key: string, target: typeof buttons[number]) => {
      let prevented = false;
      listeners.keydown({ key, target, preventDefault() { prevented = true; } });
      return prevented;
    };
    expect(press("ArrowRight", buttons[0])).toBe(true);
    expect(focused).toBe("genomics");
    expect(cards.map((card) => card.hidden)).toEqual([false, true, true]);
    press("ArrowRight", buttons[1]);
    expect(focused).toBe("all");
    press("ArrowLeft", buttons[0]);
    expect(focused).toBe("genomics");
    press("Home", buttons[1]);
    expect(focused).toBe("all");
    press("End", buttons[0]);
    expect(focused).toBe("genomics");
    expect(press("Tab", buttons[1])).toBe(false);
  });
});
