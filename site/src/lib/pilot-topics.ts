import { readFileSync } from "node:fs";
import { parseFragment, serializeOuter, type DefaultTreeAdapterTypes } from "parse5";
import cs from "../../../docs/expansion-measurements/2026-11-20/computer-science-ranking.json";
import placement from "../../../docs/expansion-measurements/2026-11-20/science-field-routing.json";
import { loadTaxonomy } from "./data";
import { fieldLabel, pilotDates, type Edition } from "./editions";
import type { LeaderboardTopic } from "./leaderboard";
import { readingParagraphs } from "./reading-paragraphs";

type Node = DefaultTreeAdapterTypes.Node;
type Element = DefaultTreeAdapterTypes.Element;
function* elements(node: Node): Generator<Element> {
  if ("tagName" in node) yield node;
  if ("childNodes" in node) for (const child of node.childNodes) yield* elements(child);
}
function words(node: Node): string {
  if ("value" in node) return node.value;
  return "childNodes" in node ? node.childNodes.map(words).join(" ").replace(/\s+/g, " ").trim() : "";
}
const attr = (node: Element, name: string) => node.attrs.find(a => a.name === name)?.value;

export const csReview = cs;
export const isReviewedSelection = (field: Edition, date: string) => field === "computer-information" && date === cs.edition;
export function pilotIssues(field: Edition) {
  const dates = pilotDates(field);
  return field === "computer-information" ? [...new Set([...dates, cs.edition])].sort().reverse() : dates;
}

function snapshot(field: Edition, date: string) {
  const doc = parseFragment(readFileSync(`pilot-editions/${field}/${date}.html`, "utf8"));
  const list = [...elements(doc)].find(node => node.tagName === "ol" && attr(node, "class") === "rankings");
  if (!list?.parentNode) throw Error(`Missing pilot rankings in ${field}/${date}`);
  return { list, section: list.parentNode };
}

export function pilotCoverage(field: Edition, date: string) {
  const { list, section } = snapshot(field, date);
  return section.childNodes.slice(0, section.childNodes.indexOf(list))
    .filter(node => "tagName" in node && !["h1", "h2"].includes(node.tagName))
    .map(node => serializeOuter(node)).join("\n");
}

interface PilotRow {
  slug: string; rank: number; title: string; summary: string; category: string; categorySlug: string;
  paperCount: number; content: string; date: string; url: string; correction?: boolean; withdrawn?: boolean;
}

export function pilotEntries(field: Edition, date: string): PilotRow[] {
  const taxonomy = loadTaxonomy(field);
  if (isReviewedSelection(field, date)) {
    return cs.selected_topics.map(topic => {
      const slug = `review-${date}-${topic.rank}`;
      return { slug, rank: topic.rank, title: topic.headline, summary: readingParagraphs(topic.reviewed_summary)[0],
        category: taxonomy.find(c => c.slug === topic.category)?.label ?? topic.category, categorySlug: topic.category,
        paperCount: topic.papers.length, content: [topic.headline, topic.reviewed_summary, ...topic.papers.map(p => p.title)].join(" "),
        url: `/pilots/${field}/${date}/papers/#${slug}`, date };
    });
  }
  const { list } = snapshot(field, date);
  return list.childNodes.flatMap(row => {
    if (!("tagName" in row) || row.tagName !== "li") return [];
    const nodes = [...elements(row)];
    const withdrawn = nodes.some(n => attr(n, "data-editorial-withdrawal") !== undefined);
    const heading = nodes.find(n => n.tagName === "h3");
    const category = nodes.find(n => attr(n, "class") === "category");
    const id = attr(row, "id");
    if (!heading || !category || !id) throw Error(`Incomplete pilot topic in ${field}/${date}`);
    const label = words(category);
    const categorySlug = taxonomy.find(c => c.label.toLowerCase() === label.toLowerCase())?.slug ?? label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    const summary = row.childNodes.find(n => "tagName" in n && n.tagName === "p" && n !== category);
    const paperCount = nodes.filter(n => n.tagName === "summary").map(n => /^(\d+) supporting papers?\b/i.exec(words(n)))
      .find(Boolean)?.[1];
    const rank = Number(attr(row, "value"));
    if (!Number.isInteger(rank) || rank < 1 || (!withdrawn && (!summary || !paperCount))) throw Error(`Missing rank, summary or paper count in ${field}/${date}/${id}`);
    return [{ slug: id, rank, title: words(heading), summary: summary ? words(summary) : "", category: label, categorySlug, paperCount: Number(paperCount ?? 0),
      correction: nodes.some(n => attr(n, "class") === "correction"), withdrawn, content: words(row),
      url: `/pilots/${field}/${date}/papers/#${id}`, date }];
  });
}

export function placementChecks(field: Edition, date: string) {
  return placement.cases.filter(check => check.edition === field && check.date === date);
}

export function pilotRows(field: Edition, date: string) {
  return pilotEntries(field, date).filter(row => !row.withdrawn);
}

export function pilotCards(field: Edition, date: string): LeaderboardTopic[] {
  return pilotRows(field, date).map(row => ({
    rank: row.rank, slug: row.slug, headline: row.title, summary: row.summary, category: row.categorySlug, categoryLabel: row.category,
    correction: row.correction, toolNames: [], secondary_categories: [],
    stats: [{ label: "papers", value: row.paperCount, spoken: `${row.paperCount} supporting papers` }],
    url: row.url,
  }));
}

export function csReviewRows() {
  return pilotRows("computer-information", cs.edition);
}

export function pilotSearchRecord(field: Edition, row: ReturnType<typeof pilotRows>[number]) {
  const context = `${fieldLabel(field)} · Pilot · ${row.date}`;
  return { url: row.url, language: "en", content: `${row.content} ${context}`,
    filters: { field: [field], category: [row.category] }, meta: { title: row.title, field: context } };
}
