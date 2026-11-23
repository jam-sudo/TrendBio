import { scoring } from "./scoring";
import type { Category } from "./data";
import type { Day, RankedTopic, Topic, TopicDay } from "./types";

const { top_n, max_per_category, category_floor } = scoring;

const DAY = 86_400_000;
const dateString = (date: Date) => date.toISOString().slice(0, 10);

export function isoWeekOf(date: string) {
  const start = new Date(`${date}T00:00:00Z`);
  start.setUTCDate(start.getUTCDate() - (start.getUTCDay() + 6) % 7);
  const thursday = new Date(+start + 3 * DAY);
  const year = thursday.getUTCFullYear();
  const week = Math.ceil(((+thursday - Date.UTC(year, 0, 1)) / DAY + 1) / 7);
  return { year, week, start: dateString(start), end: dateString(new Date(+start + 6 * DAY)) };
}

export function monthOf(date: string) {
  const first = new Date(`${date.slice(0, 7)}-01T00:00:00Z`);
  const year = first.getUTCFullYear(), month = first.getUTCMonth() + 1;
  return { year, month, start: dateString(first), end: dateString(new Date(Date.UTC(year, month, 0))) };
}

export interface Period {
  id: string;
  start: string;
  end: string;
  label: string;
  soFar: boolean;
}

const shortDate = (date: string) => new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
  month: "short", day: "numeric", timeZone: "UTC",
});

const shared = globalThis as typeof globalThis & {
  trendbioPeriods?: {
    weeks: WeakMap<Pick<Day, "date">[], Period[]>;
    months: WeakMap<Pick<Day, "date">[], Period[]>;
    histories: WeakMap<Topic[], HistoryIndex>;
    rankings: WeakMap<HistoryIndex, Map<string, PeriodRanked[]>>;
  };
};
const cache = shared.trendbioPeriods ??= {
  weeks: new WeakMap(), months: new WeakMap(), histories: new WeakMap(), rankings: new WeakMap(),
};

export function allWeeks(days: Pick<Day, "date">[]): Period[] {
  const cached = cache.weeks.get(days);
  if (cached) return cached;
  const latest = days.map(({ date }) => date).sort().at(-1);
  const weeks = [...new Set(days.map(({ date }) => isoWeekOf(date).start))].sort().reverse().map((date) => {
    const { year, week, start, end } = isoWeekOf(date);
    return { id: `${year}-W${String(week).padStart(2, "0")}`, start, end,
      label: `Week ${week}, ${year} · ${shortDate(start)} – ${shortDate(end)}`, soFar: start <= latest! && latest! < end };
  });
  cache.weeks.set(days, weeks);
  return weeks;
}

export function allMonths(days: Pick<Day, "date">[]): Period[] {
  const cached = cache.months.get(days);
  if (cached) return cached;
  const latest = days.map(({ date }) => date).sort().at(-1);
  const months = [...new Set(days.map(({ date }) => date.slice(0, 7)))].sort().reverse().map((id) => {
    const { start, end } = monthOf(`${id}-01`);
    return { id, start, end, label: new Date(`${start}T00:00:00Z`).toLocaleDateString("en-US", {
      month: "long", year: "numeric", timeZone: "UTC",
    }), soFar: start <= latest! && latest! < end };
  });
  cache.months.set(days, months);
  return months;
}

export interface PeriodRanked {
  slug: string;
  headline: string | null;
  evidenceDate?: string;
  label: string;
  category: string;
  secondary_categories: string[];
  latest_item_ids: string[];
  period_score: number;
  days_ranked: number;
  best_rank: number | null;
  items: number;
  rise: number;
  rise_date: string;
  rank: number;
}

export function periodHeadline(topic: Pick<PeriodRanked, "headline" | "label">) {
  return topic.headline || topic.label.replace(/\b\p{L}/gu, letter => letter.toUpperCase());
}

export type HistoryIndex = Map<string, { topic: Topic; entry: TopicDay; hasIssue: boolean; published?: RankedTopic }[]>;

export function indexHistories(topics: Topic[], days?: Day[]): HistoryIndex {
  const cached = !days && cache.histories.get(topics);
  if (cached) return cached;
  const editions = new Map(days?.map(day => [day.date, new Map(day.ranked.map(row => [row.slug, row]))]));
  const index: HistoryIndex = new Map();
  for (const topic of topics) {
    for (const entry of topic.history) {
      const entries = index.get(entry.date) ?? [];
      const issue = editions.get(entry.date);
      entries.push({ topic, entry, hasIssue: !!issue, published: issue?.get(topic.slug) });
      index.set(entry.date, entries);
    }
  }
  if (!days) cache.histories.set(topics, index);
  return index;
}

export function rankPeriod(topics: Topic[] | HistoryIndex, start: string, end: string, taxonomy: Category[]): PeriodRanked[] {
  const index = Array.isArray(topics) ? indexHistories(topics) : topics;
  const key = JSON.stringify([start, end, taxonomy.map(({ slug }) => slug)]);
  const rankings = cache.rankings.get(index) ?? new Map<string, PeriodRanked[]>();
  cache.rankings.set(index, rankings);
  const cached = rankings.get(key);
  if (cached) return cached;
  const totals = new Map<string, PeriodRanked & { itemIds: Set<string> }>();
  for (let date = new Date(`${start}T00:00:00Z`); dateString(date) <= end; date.setUTCDate(date.getUTCDate() + 1)) {
    for (const { topic, entry, hasIssue, published } of index.get(dateString(date)) ?? []) {
      let total = totals.get(topic.slug);
      if (!total) {
        // The original keyword label is part of the immutable slug. Synthesis can rewrite topic.label.
        const label = topic.slug.replace(/-[0-9a-f]{4}$/, "").replaceAll("-", " ");
        total = { slug: topic.slug, headline: null, label, category: topic.category,
          secondary_categories: topic.secondary_categories, period_score: 0, days_ranked: 0,
          best_rank: null, items: 0, rise: 0, rise_date: entry.date, rank: 0, latest_item_ids: [], itemIds: new Set() };
        totals.set(topic.slug, total);
      }
      if (published?.headline) {
        total.headline = published.headline;
        total.evidenceDate = entry.date;
        total.latest_item_ids = entry.item_ids;
      } else if (!total.headline && hasIssue && entry.item_ids.length) {
        total.evidenceDate = entry.date;
        total.latest_item_ids = entry.item_ids;
      } else if (!total.evidenceDate) {
        total.latest_item_ids = entry.item_ids;
      }
      total.period_score += entry.scores.total;
      if (entry.rank !== null) {
        total.days_ranked++;
        total.best_rank = Math.min(total.best_rank ?? Infinity, entry.rank);
      }
      for (const id of entry.item_ids) total.itemIds.add(id);
      total.items = total.itemIds.size;
      if (entry.signals.rise_ratio >= total.rise) {
        total.rise = entry.signals.rise_ratio;
        total.rise_date = entry.date;
      }
    }
  }
  const sorted = [...totals.values()].sort((a, b) => b.period_score - a.period_score ||
    b.days_ranked - a.days_ranked || b.items - a.items || a.slug.localeCompare(b.slug));
  const counts = new Map(taxonomy.map(({ slug }) => [slug, 0]));
  const selected = new Set<string>();
  // Reserve each represented category before filling remaining places, as in the daily ranking.
  for (const topic of sorted) {
    if (selected.size < top_n && (counts.get(topic.category) ?? 0) < Math.min(category_floor, max_per_category)) {
      selected.add(topic.slug);
      counts.set(topic.category, (counts.get(topic.category) ?? 0) + 1);
    }
  }
  for (const topic of sorted) {
    if (selected.size < top_n && !selected.has(topic.slug) && (counts.get(topic.category) ?? 0) < max_per_category) {
      selected.add(topic.slug);
      counts.set(topic.category, (counts.get(topic.category) ?? 0) + 1);
    }
  }
  const ranked = sorted.filter(({ slug }) => selected.has(slug)).map(({ itemIds, ...topic }, index) => ({ ...topic, rank: index + 1 }));
  rankings.set(key, ranked);
  return ranked;
}
