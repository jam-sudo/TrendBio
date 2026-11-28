import { createHash } from "node:crypto";
import { loadItems } from "./data";
import { topicAppearances, type Field } from "./editions";
import type { Item, Topic, TopicDay } from "./types";

export function topicSnapshot(topic: Topic, field: Field = "computational") {
  const history = [...topic.history].sort((a, b) => b.date.localeCompare(a.date));
  const appearances = topicAppearances(field).get(topic.slug) ?? [];
  const byDate = new Map(history.map(entry => [entry.date, entry]));
  const synthesized = topic.synthesized_on ? byDate.get(topic.synthesized_on) : undefined;
  const issue = appearances[0];
  const entry = issue ? byDate.get(issue.day.date) : synthesized ?? history.find(entry => entry.rank !== null)
    ?? history.find(entry => entry.item_ids.length) ?? history[0];
  const hasSynthesis = !!entry && entry === synthesized;
  const row = issue?.row;
  const singleSource = issue?.day.run.notes.includes(`synthesis-fallback:${topic.slug}`);
  return {
    field, entry, history, issue, singleSource, category: row?.category ?? entry?.category ?? "uncategorized",
    headline: row?.headline || (hasSynthesis && topic.headline) || topic.label,
    summary: row?.summary ?? (hasSynthesis ? topic.summary : null),
    synthesis: singleSource ? null : row?.synthesis ?? (hasSynthesis ? topic.synthesis : null),
    oneLiners: hasSynthesis && !singleSource ? topic.item_one_liners : {},
  };
}

const evidenceIds = (entry?: TopicDay) => [...new Set([...(entry?.item_ids ?? []), ...(entry?.attached_item_ids ?? [])])];
export const isPaper = (item: Item) => item.type === "published" || item.type === "preprint";
export const hasPapers = (items: Item[]) => items.some(isPaper);

export function topicEvidence(topic: Topic, snapshot = topicSnapshot(topic)): Item[] {
  return loadItems(snapshot.field, evidenceIds(snapshot.entry));
}

export function datedPapers(field: Field, entry?: TopicDay): Item[] {
  return loadItems(field, evidenceIds(entry)).filter(isPaper);
}

export function laterPapers({ entry, history }: ReturnType<typeof topicSnapshot>) {
  if (!entry) return [];
  const seen = new Set(evidenceIds(entry));
  const later = [];
  for (const day of history.filter(day => day.date > entry.date).reverse()) {
    const ids = evidenceIds(day).filter(id => !seen.has(id));
    ids.forEach(id => seen.add(id));
    const papers = loadItems("computational", ids).filter(isPaper);
    if (papers.length) later.push({ date: day.date, papers });
  }
  return later.reverse();
}

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
