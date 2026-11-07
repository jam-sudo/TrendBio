import { createHash } from "node:crypto";
import { loadItems } from "./data";
import type { Item, Topic } from "./types";

export function topicEvidence(topic: Topic): Item[] {
  const latest = [...topic.history].sort((a, b) => b.date.localeCompare(a.date))[0];
  return loadItems("computational", [...(latest?.item_ids ?? []), ...(latest?.attached_item_ids ?? [])]);
}

export const hasPapers = (items: Item[]) => items.some(item => item.type === "published" || item.type === "preprint");

export function escapeBibtex(value: string): string {
  return value.replace(/\\|[{}%&#_$~^]/g, char => ({
    "\\": "\\textbackslash{}", "{": "\\{", "}": "\\}", "%": "\\%", "&": "\\&", "#": "\\#",
    "_": "\\_", "$": "\\$", "~": "\\textasciitilde{}", "^": "\\textasciicircum{}",
  })[char]!).replace(/\s+/g, " ").trim();
}

export function bibtex(items: Item[]): string {
  const seen = new Set<string>(), keys = new Set<string>();
  return items.filter(item => item.type === "published" || item.type === "preprint").filter(item => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  }).map(item => {
    const author = item.authors[0] ?? "anonymous";
    const surname = (author.includes(",") ? author.split(",")[0] : author.trim().split(/\s+/).at(-1)!)
      .normalize("NFKD").replace(/[^a-zA-Z]/g, "").toLowerCase() || "anonymous";
    const year = item.published_at.slice(0, 4);
    const shortId = createHash("sha256").update(item.id).digest("hex").slice(0, 8);
    const base = `${surname}${year}${shortId}`;
    let key = base, suffix = 2;
    while (keys.has(key)) key = `${base}${suffix++}`;
    keys.add(key);
    const fields = { title: item.title, author: item.authors.join(" and "), year,
      journal: typeof item.metadata.journal === "string" ? item.metadata.journal : null,
      doi: item.doi, url: item.url };
    return `@${item.type === "published" ? "article" : "misc"}{${key},\n${Object.entries(fields)
      .filter(([, value]) => value).map(([field, value]) => `  ${field} = {${escapeBibtex(value!)}},`).join("\n")}\n}`;
  }).join("\n\n") + (seen.size ? "\n" : "");
}
