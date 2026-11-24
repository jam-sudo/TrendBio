import type { Topic } from "./types";
import { allTopics, loadDays, loadTaxonomy, rankedTopics } from "./data";
import { allMonths, allWeeks, indexHistories, rankPeriod, type Period, type PeriodRanked } from "./periods";
import type { Field } from "./editions";

export interface RankedPeriod extends Period { topics: PeriodRanked[] }
const shared = globalThis as typeof globalThis & {
  trendbioRankedPeriods?: WeakMap<Topic[], ReturnType<typeof buildPeriods>>;
};
const cache = shared.trendbioRankedPeriods ??= new WeakMap();

function buildPeriods(field: Field) {
  const days = loadDays(field);
  const topics = allTopics(field);
  const index = indexHistories(topics, days);
  const taxonomy = loadTaxonomy(field);
  const rank = (period: Period): RankedPeriod => ({ ...period, topics: rankPeriod(index, period.start, period.end, taxonomy) });
  const weeks = allWeeks(days).map(rank), months = allMonths(days).map(rank);
  const supplemental = new Map<string, Map<string, PeriodRanked>>();
  for (const period of [...weeks, ...months]) {
    for (const topic of period.topics) {
      if (topic.headline || !topic.evidenceDate) continue;
      const rows = supplemental.get(topic.evidenceDate) ?? new Map<string, PeriodRanked>();
      rows.set(topic.slug, topic);
      supplemental.set(topic.evidenceDate, rows);
    }
  }
  const paperDays = days.filter(day => day.ranked.length || supplemental.has(day.date));
  return { days, topics, weeks, months, supplemental, paperDays };
}

// All period routes share one loaded dataset and one history index; each entry is aggregated once per period kind.
export function loadPeriods(field: Field = "computational") {
  const topics = allTopics(field);
  let cached = cache.get(topics);
  if (!cached) {
    cached = buildPeriods(field);
    cache.set(topics, cached);
  }
  return cached;
}

export function topicPages(): Topic[] {
  const data = loadPeriods();
  const selected = new Set([...data.weeks, ...data.months].flatMap(({ topics }) => topics.map(({ slug }) => slug)));
  return [...rankedTopics("computational"), ...data.topics.filter((topic) =>
    selected.has(topic.slug) && !topic.history.some(({ rank }) => rank !== null))];
}
