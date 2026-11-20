import { loadDays } from "./data";
import type { Day, RankedTopic } from "./types";

export const editionInfo = {
  physics: { label: "Physics", source: "arXiv", stage: "" },
  biology: { label: "Biology", source: "bioRxiv and PubMed", stage: "Beta" },
  math: { label: "Math & Stats", source: "arXiv and mathematics and statistics journals via Crossref", stage: "Pilot" },
  "earth-environment": { label: "Earth & Environment", source: "Earth and environmental journals via Crossref", stage: "Pilot" },
  chemistry: { label: "Chemistry", source: "Chemistry journals via Crossref", stage: "Pilot" },
  astronomy: { label: "Stellar & Galactic Astronomy", source: "arXiv", stage: "Pilot" },
  "physics-expanded": { label: "Expanded Physics", source: "arXiv and two physics journals via Crossref", stage: "Pilot" },
  "computer-information": { label: "Computing & Information", source: "arXiv, DROPS and Crossref", stage: "Pilot" },
  engineering: { label: "Engineering", source: "arXiv and five engineering journals via Crossref", stage: "Pilot" },
  "agriculture-food-veterinary": { label: "Agriculture, Food & Veterinary Science", source: "Crossref and journal publishers", stage: "Pilot" },
  "medicine-health": { label: "Medicine & Health", source: "Europe PMC and Crossref", stage: "Pilot" },
  "social-sciences": { label: "Social Sciences", source: "arXiv, the World Bank and research journals", stage: "Pilot" },
  "humanities-arts": { label: "Humanities & Arts", source: "Thoth, OpenEdition and Crossref", stage: "Pilot" },
} as const;
export type Edition = keyof typeof editionInfo;
const configured = Object.keys(editionInfo) as Edition[];
export const publicEditions = configured.filter(field => editionInfo[field].stage !== "Pilot");
export const editions = configured.filter(field =>
  editionInfo[field].stage !== "Pilot" || loadDays(field).length > 0);

export type Field = Edition | "computational";
export function fieldLabel(field: Field): string {
  if (field === "computational") return "CompBio";
  return field === "biology" ? "All Biology" : editionInfo[field].label;
}

export function datedTopic(field: Field, date: string, slug: string): string {
  const prefix = field === "computational" ? "" : `/${field}`;
  return `${prefix}/day/${date}/#${encodeURIComponent(slug)}`;
}

const byIssue = new WeakMap<Day[], Map<string, { day: Day; row: RankedTopic }[]>>();
export function topicAppearances(field: Edition) {
  const days = loadDays(field);
  let topics = byIssue.get(days);
  if (!topics) {
    topics = new Map();
    for (const day of days) {
      for (const row of day.ranked) {
        const appearances = topics.get(row.slug) ?? [];
        appearances.push({ day, row });
        topics.set(row.slug, appearances);
      }
    }
    byIssue.set(days, topics);
  }
  return topics;
}
