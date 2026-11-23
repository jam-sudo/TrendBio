import { existsSync, readdirSync, readFileSync } from "node:fs";
import { parse } from "yaml";
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
  "computer-information": { label: "Computer Science", source: "arXiv, DROPS and Crossref", stage: "Pilot" },
  engineering: { label: "Engineering", source: "arXiv and engineering journals via Crossref", stage: "Pilot" },
  "agriculture-food-veterinary": { label: "Agriculture, Food & Veterinary Science", source: "Crossref and journal publishers", stage: "Pilot" },
  "medicine-health": { label: "Medicine & Health", source: "Europe PMC and Crossref", stage: "Pilot" },
} as const;
export type Edition = keyof typeof editionInfo;
export type Field = Edition | "computational";
export const scienceGroups: Record<string, Partial<Record<Field, { scope: string; parent?: Field }>>> =
  parse(readFileSync("../config/science-fields.yaml", "utf8"));
const configured = Object.values(scienceGroups).flatMap(fields =>
  (Object.keys(fields) as Field[]).filter((field): field is Edition => field !== "computational"));
export const publicEditions = configured.filter(field => editionInfo[field].stage !== "Pilot");
export const editions = configured;
export function pilotDates(field: Edition): string[] {
  const dir = `pilot-editions/${field}`;
  return existsSync(dir) ? readdirSync(dir).filter(name => /^\d{4}-\d{2}-\d{2}\.html$/.test(name))
    .map(name => name.slice(0, -5)).sort().reverse() : [];
}

export function fieldLabel(field: Field): string {
  if (field === "computational") return "CompBio";
  return field === "biology" ? "All Biology" : editionInfo[field].label;
}

export function datedTopic(field: Field, date: string, slug: string): string {
  const prefix = field === "computational" ? "" : `/${field}`;
  return `${prefix}/day/${date}/#${encodeURIComponent(slug)}`;
}

export function datedEvidence(field: Field, date: string, slug: string): string {
  return field === "computational" ? `/day/${date}/papers/#${encodeURIComponent(slug)}` : datedTopic(field, date, slug);
}

const byIssue = new WeakMap<Day[], Map<string, { day: Day; row: RankedTopic }[]>>();
export function topicAppearances(field: Field) {
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
