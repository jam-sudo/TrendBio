import { readFileSync, realpathSync, statSync } from "node:fs";
import { resolve, sep } from "node:path";

export interface Sponsor {
  name: string;
  tagline: string;
  url: string;
  logo: string;
  hue: number;
}

export function loadSponsors(): { slots: number; contact: string; sponsors: Sponsor[] } {
  const file = process.env.TRENDBIO_SPONSORS_FILE || resolve("src/content/sponsors.json");
  const check = (valid: unknown, message: string) => {
    if (!valid) throw new Error(message);
  };
  try {
    const data = JSON.parse(readFileSync(file, "utf8"));
    check(data && typeof data === "object" && !Array.isArray(data), "expected an object");
    check(Number.isSafeInteger(data.slots) && data.slots >= 0 && data.slots % 2 === 0, "slots must be a non-negative even integer");
    check(typeof data.contact === "string" && /^[^\s@?&#]+@[^\s@?&#]+\.[^\s@?&#]+$/.test(data.contact), "contact must be an email address");
    check(Array.isArray(data.sponsors) && data.sponsors.length <= data.slots, "sponsors must be an array with no more entries than slots");
    for (const [index, sponsor] of data.sponsors.entries()) {
      const label = `sponsors[${index}]`;
      check(sponsor && typeof sponsor === "object" && !Array.isArray(sponsor), `${label} must be an object`);
      for (const key of ["name", "tagline", "url", "logo"]) {
        check(typeof sponsor[key] === "string" && sponsor[key].trim() && !/[\r\n]/.test(sponsor[key]), `${label}.${key} must be a non-empty single-line string`);
      }
      check([...sponsor.tagline].length <= 60, `${label}.tagline must be at most 60 characters`);
      check(/^https?:\/\//.test(sponsor.url) && URL.canParse(sponsor.url), `${label}.url must be an absolute HTTP(S) URL`);
      check(Number.isFinite(sponsor.hue) && sponsor.hue >= 0 && sponsor.hue <= 360, `${label}.hue must be a number from 0 to 360`);
      if (sponsor.logo.startsWith("/sponsors/")) {
        check(/^\/sponsors\/(?:[\w-]+\/)*[\w.-]+\.(png|jpe?g|webp|gif|avif|svg)$/i.test(sponsor.logo), `${label}.logo must be a local image path under /sponsors/`);
        const root = realpathSync(resolve("public/sponsors"));
        let logo: string;
        try { logo = realpathSync(resolve("public", `.${sponsor.logo}`)); }
        catch { throw new Error(`${label}.logo file does not exist: ${sponsor.logo}`); }
        check(logo.startsWith(root + sep), `${label}.logo must stay under public/sponsors/`);
        const stat = statSync(logo);
        check(stat.isFile() && stat.size > 0 && stat.size <= 20 * 1024, `${label}.logo must be an image file no larger than 20 KB`);
      } else {
        check(/\p{Extended_Pictographic}|\p{Regional_Indicator}|\u20E3/u.test(sponsor.logo)
          && /^(?:\p{Extended_Pictographic}|\p{Regional_Indicator}|\p{Emoji_Modifier}|[\uFE0F\u200D\u{E0020}-\u{E007F}]|[0-9#*]\uFE0F?\u20E3)+$/u.test(sponsor.logo)
          && [...new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(sponsor.logo)].length === 1,
        `${label}.logo must be one emoji or a local image path under /sponsors/`);
      }
    }
    return data;
  } catch (error) {
    throw new Error(`Invalid sponsors file ${file}: ${error instanceof Error ? error.message : String(error)}`);
  }
}
