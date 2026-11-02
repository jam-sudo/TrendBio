import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { marked } from "marked";
import { parse } from "yaml";
import type { Day, Item, Topic } from "./types";

export const DATA_ROOT = process.env.TRENDBIO_DATA_ROOT ?? "../data";
export const NOTES_ROOT = process.env.TRENDBIO_NOTES_ROOT ?? "../notes";

export interface Category {
  slug: string;
  label: string;
  covers: string;
}

function readJson<T>(path: string): T | null {
  return existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : null;
}

function readRecords<T>(directory: string): T[] {
  if (!existsSync(directory)) return [];
  return readdirSync(directory, { recursive: true, encoding: "utf8" })
    .filter((path) => path.endsWith(".json"))
    .sort()
    .map((path) => readJson<T>(join(directory, path)))
    .filter((record): record is T => record !== null);
}

export function loadDays(domain: string): Day[] {
  return readRecords<Day>(join(DATA_ROOT, domain, "days"))
    .sort((a, b) => b.date.localeCompare(a.date));
}

export function loadDay(domain: string, date: string): Day | null {
  return readJson<Day>(join(DATA_ROOT, domain, "days", `${date}.json`));
}

export function latestDay(domain: string): Day | null {
  return loadDays(domain)[0] ?? null;
}

export function loadTopic(domain: string, slug: string): Topic | null {
  return readJson<Topic>(join(DATA_ROOT, domain, "topics", `${slug}.json`));
}

export function allTopics(domain: string): Topic[] {
  return readRecords<Topic>(join(DATA_ROOT, domain, "topics"));
}

export function loadItems(domain: string, ids: string[]): Item[] {
  // shortcut: scans the item store per call; index by ID when archive builds become slow.
  const items = new Map(
    readRecords<Item>(join(DATA_ROOT, domain, "items")).map((item) => [item.id, item]),
  );
  return ids.map((id) => items.get(id)).filter((item): item is Item => item !== undefined);
}

export function loadNote(slug: string): string | null {
  try {
    return marked.parse(readFileSync(join(NOTES_ROOT, `${slug}.md`), "utf8"), { async: false });
  } catch {
    console.warn(`Could not load note: ${slug}`);
    return null;
  }
}

export function loadTaxonomy(domain: string): Category[] {
  return parse(readFileSync(join("../config/taxonomy", `${domain}.yaml`), "utf8")).categories;
}
