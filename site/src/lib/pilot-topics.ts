import { readFileSync } from "node:fs";
import { parseFragment, type DefaultTreeAdapterTypes } from "parse5";
import cs from "../../../docs/expansion-measurements/2026-11-20/computer-science-ranking.json";
import placement from "../../../docs/expansion-measurements/2026-11-20/science-field-routing.json";
import { loadTaxonomy } from "./data";
import { fieldLabel, type Edition } from "./editions";

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

export function pilotRows(field: Edition, date: string) {
  const doc = parseFragment(readFileSync(`pilot-editions/${field}/${date}.html`, "utf8"));
  const list = [...elements(doc)].find(node => node.tagName === "ol" && attr(node, "class") === "rankings");
  return (list?.childNodes ?? []).flatMap(row => {
    if (!("tagName" in row) || row.tagName !== "li") return [];
    const nodes = [...elements(row)];
    if (nodes.some(n => attr(n, "data-editorial-withdrawal") !== undefined)) return [];
    const heading = nodes.find(n => n.tagName === "h3");
    const category = nodes.find(n => attr(n, "class") === "category");
    const id = attr(row, "id");
    if (!heading || !category || !id) throw Error(`Incomplete pilot topic in ${field}/${date}`);
    return [{ title: words(heading), category: words(category), content: words(row),
      url: `/pilots/${field}/${date}/#${id}`, date }];
  });
}

export function placementChecks(field: Edition, date: string) {
  return placement.cases.filter(check => check.edition === field && check.date === date);
}

export const csReview = cs;
export function csReviewRows() {
  const categories = new Map(loadTaxonomy("computer-information").map(c => [c.slug, c.label]));
  return cs.selected_topics.map(topic => ({
    title: topic.headline, category: categories.get(topic.category) ?? topic.category,
    content: [topic.headline, topic.reviewed_summary, ...topic.papers.map(p => p.title)].join(" "),
    url: `/computer-information/#review-${cs.edition}-${topic.rank}`, date: cs.edition,
  }));
}

export function pilotSearchRecord(field: Edition, row: ReturnType<typeof pilotRows>[number]) {
  const context = `${fieldLabel(field)} · Pilot · ${row.date}`;
  return { url: row.url, language: "en", content: `${row.content} ${context}`,
    filters: { field: [field], category: [row.category] }, meta: { title: row.title, field: context } };
}
