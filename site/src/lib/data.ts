import { existsSync, readFileSync, readdirSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { marked } from "marked";
import { parse } from "yaml";
import type { Attention, SharedItem, CodeItem, Day, GitHubStarSample, Item, MapData, Topic } from "./types";

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

interface DataIndex {
  days: Day[];
  daysByDate: Map<string, Day>;
  topics: Topic[];
  topicsBySlug: Map<string, Topic>;
  rankedTopics: Topic[];
  itemPathById: Map<string, string>;
  industryItems?: Item[];
  codeItems?: Item[];
  attentionByDate: Map<string, Attention>;
  githubStars: Record<string, GitHubStarSample[]>;
  map: MapData | null;
  notes: Map<string, string | null>;
  orphanNotes: string[];
  stats: { builds: number; itemReads: number };
}

// Astro can evaluate server modules more than once; share immutable build inputs across them.
// shortcut: inputs are a process-lifetime snapshot; add invalidation if live data reloads are needed.
const shared = globalThis as typeof globalThis & {
  trendbioData?: {
    indexes: Map<string, DataIndex>;
    notes: Map<string, Map<string, string | null>>;
    taxonomies: Map<string, Category[]>;
    builds: Map<string, number>;
  };
};
const cache = shared.trendbioData ??= {
  indexes: new Map(), notes: new Map(), taxonomies: new Map(), builds: new Map(),
};
const notesKey = resolve(NOTES_ROOT);
const notes = cache.notes.get(notesKey) ?? new Map<string, string | null>();
cache.notes.set(notesKey, notes);

export function getDataIndex(domain: string): DataIndex {
  const key = JSON.stringify([resolve(DATA_ROOT, domain), notesKey]);
  const cached = cache.indexes.get(key);
  if (cached) return cached;
  const started = performance.now();
  const days = readRecords<Day>(join(DATA_ROOT, domain, "days"))
    .sort((a, b) => b.date.localeCompare(a.date));
  const topics = readRecords<Topic>(join(DATA_ROOT, domain, "topics"));
  const topicsBySlug = new Map(topics.map((topic) => [topic.slug, topic]));
  const ranked = topics.map((topic) => ({
    topic,
    lastRanked: topic.history.filter((entry) => entry.rank !== null).map((entry) => entry.date).sort().at(-1),
  })).filter((entry) => entry.lastRanked !== undefined)
    .sort((a, b) => b.lastRanked!.localeCompare(a.lastRanked!))
    .map(({ topic }) => topic);
  const itemDirectory = join(DATA_ROOT, domain, "items");
  const itemPathById = new Map<string, string>();
  if (existsSync(itemDirectory)) {
    for (const path of readdirSync(itemDirectory, { recursive: true, encoding: "utf8" }).sort()) {
      if (!path.endsWith(".json")) continue;
      const id = basename(path, ".json"), fullPath = join(itemDirectory, path);
      const previous = itemPathById.get(id);
      // Filename encoding is lossy: disambiguate collisions across shards by their stored IDs once.
      if (previous) {
        for (const candidate of [previous, fullPath]) {
          const item = readJson<Item>(candidate);
          if (item) itemPathById.set(item.id, candidate);
        }
      }
      itemPathById.set(id, fullPath);
    }
  }
  const orphanNotes = existsSync(NOTES_ROOT) ? readdirSync(NOTES_ROOT, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md"))
    .map((entry) => entry.name.slice(0, -3))
    .filter((slug) => !topicsBySlug.has(slug)).sort() : [];
  const builds = (cache.builds.get(key) ?? 0) + 1;
  cache.builds.set(key, builds);
  const githubStars = readJson<Record<string, GitHubStarSample[]>>(join(DATA_ROOT, domain, "github_stars.json")) ?? {};
  for (const history of Object.values(githubStars)) history.sort((a, b) => a.date.localeCompare(b.date));
  const index: DataIndex = {
    days, daysByDate: new Map(days.map((day) => [day.date, day])), topics, topicsBySlug,
    rankedTopics: ranked, itemPathById, map: readJson<MapData>(join(DATA_ROOT, domain, "map.json")),
    attentionByDate: new Map(readRecords<Attention>(join(DATA_ROOT, domain, "attention")).map(record => [record.date, record])),
    githubStars, notes, orphanNotes, stats: { builds, itemReads: 0 },
  };
  cache.indexes.set(key, index);
  console.info(`[data-index] ${domain} built #${builds} in ${(performance.now() - started).toFixed(0)}ms`);
  return index;
}

export function loadMap(domain: string): MapData | null {
  return getDataIndex(domain).map;
}

export function loadDays(domain: string): Day[] {
  return getDataIndex(domain).days;
}

export function loadDay(domain: string, date: string): Day | null {
  return getDataIndex(domain).daysByDate.get(date) ?? null;
}

export function latestDay(domain: string): Day | null {
  return loadDays(domain)[0] ?? null;
}

export function loadTopic(domain: string, slug: string): Topic | null {
  return getDataIndex(domain).topicsBySlug.get(slug) ?? null;
}

export function allTopics(domain: string): Topic[] {
  return getDataIndex(domain).topics;
}

export function rankedTopics(domain: string): Topic[] {
  return getDataIndex(domain).rankedTopics;
}

export function loadItems(domain: string, ids: string[]): Item[] {
  const index = getDataIndex(domain);
  return ids.map((id) => {
    // Match pipeline/jsonio.py's filename encoding; sorted paths retain the last shard's copy.
    const path = index.itemPathById.get(id) ?? index.itemPathById.get(id.replace(/[:/]/g, "_"));
    if (!path) return null;
    index.stats.itemReads++;
    const item = readJson<Item>(path);
    return item?.id === id ? item : null;
  }).filter((item): item is Item => item !== null);
}

export function loadNote(slug: string): string | null {
  if (!notes.has(slug)) {
    try {
      notes.set(slug, marked.parse(readFileSync(join(NOTES_ROOT, `${slug}.md`), "utf8"), { async: false }));
    } catch {
      notes.set(slug, null);
    }
  }
  const html = notes.get(slug)!;
  if (html === null) console.warn(`Could not load note: ${slug}`);
  return html;
}

export function orphanNotes(domain: string): string[] {
  return getDataIndex(domain).orphanNotes;
}

export function loadTaxonomy(domain: string): Category[] {
  const path = resolve("../config/taxonomy", `${domain}.yaml`);
  if (!cache.taxonomies.has(path)) cache.taxonomies.set(path, parse(readFileSync(path, "utf8")).categories);
  return cache.taxonomies.get(path)!;
}

export function industryItems(domain: string, day: string): Item[] {
  const index = getDataIndex(domain);
  if (!index.industryItems) {
    // Industry comes from RSS; read those files once, not every paper on every day page.
    index.industryItems = [...new Set(index.itemPathById.values())]
      .filter((path) => basename(path).startsWith("rss_"))
      .map((path) => { index.stats.itemReads++; return readJson<Item>(path); })
      .filter((item): item is Item => item !== null && item.type === "industry" && item.relevant !== false)
      .sort((a, b) => b.first_seen.localeCompare(a.first_seen) || a.id.localeCompare(b.id));
  }
  const start = new Date(`${day}T00:00:00Z`);
  start.setUTCDate(start.getUTCDate() - 6);
  const from = start.toISOString().slice(0, 10);
  return index.industryItems.filter((item) => item.first_seen >= from && item.first_seen <= day).slice(0, 8);
}

export function codeItems(domain: string, day: string): CodeItem[] {
  const index = getDataIndex(domain);
  if (!index.codeItems) {
    index.codeItems = [...new Set(index.itemPathById.values())]
      .filter((path) => basename(path).startsWith("github_"))
      .map((path) => { index.stats.itemReads++; return readJson<Item>(path); })
      .filter((item): item is Item => item !== null && item.type === "code" && item.relevant !== false);
  }
  const start = new Date(`${day}T00:00:00Z`);
  start.setUTCDate(start.getUTCDate() - 6);
  const from = start.toISOString().slice(0, 10);
  return index.codeItems.filter((item) => item.first_seen >= from && item.first_seen <= day)
    .map((item): CodeItem => {
      const history = index.githubStars[item.id.slice("github:".length)] ?? [];
      const latest = history.filter((sample) => sample.date <= day).at(-1);
      let gain: number | null = null;
      if (latest) {
        const earlier = new Date(`${latest.date}T00:00:00Z`);
        earlier.setUTCDate(earlier.getUTCDate() - 7);
        const baseline = history.find((sample) => sample.date === earlier.toISOString().slice(0, 10));
        if (baseline) gain = Math.max(latest.stars - baseline.stars, 0);
      }
      return { ...item, stars: latest?.stars ?? null, star_gain_7d: gain };
    })
    .sort((a, b) => (b.star_gain_7d ?? 0) - (a.star_gain_7d ?? 0)
      || (b.stars ?? 0) - (a.stars ?? 0) || a.id.localeCompare(b.id))
    .slice(0, 8);
}

export function sharedItems(domain: string, day: string): SharedItem[] {
  const index = getDataIndex(domain);
  const papers = index.attentionByDate.get(day)?.papers.slice(0, 8) ?? [];
  if (!papers.length) return [];
  const rankedByItem = new Map<string, { slug: string; rank: number }>();
  for (const row of [...(index.daysByDate.get(day)?.ranked ?? [])].sort((a, b) => a.rank - b.rank)) {
    const entry = index.topicsBySlug.get(row.slug)?.history.find(entry => entry.date === day);
    for (const id of [...(entry?.item_ids ?? []), ...(entry?.attached_item_ids ?? [])]) {
      if (!rankedByItem.has(id)) rankedByItem.set(id, { slug: row.slug, rank: row.rank });
    }
  }
  const items = new Map(loadItems(domain, papers.map(paper => paper.item_id)).map(item => [item.id, item]));
  return papers.flatMap(paper => {
    const item = items.get(paper.item_id);
    return item && item.relevant !== false && (item.type === "preprint" || item.type === "published")
      ? [{ ...item, engagement: paper.engagement, people: paper.authors, rankedTopic: rankedByItem.get(item.id) }] : [];
  });
}
