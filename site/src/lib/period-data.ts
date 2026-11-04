import type { Topic } from "./types";
import { allTopics, loadDays, loadTaxonomy } from "./data";
import { allMonths, allWeeks, indexHistories, rankPeriod, type Period, type PeriodRanked } from "./periods";

export interface RankedPeriod extends Period { topics: PeriodRanked[] }
const shared = globalThis as typeof globalThis & {
  trendbioRankedPeriods?: WeakMap<Topic[], ReturnType<typeof buildPeriods>>;
};
const cache = shared.trendbioRankedPeriods ??= new WeakMap();

function buildPeriods() {
  const days = loadDays("computational");
  const topics = allTopics("computational");
  const index = indexHistories(topics);
  const taxonomy = loadTaxonomy("computational");
  const rank = (period: Period): RankedPeriod => ({ ...period, topics: rankPeriod(index, period.start, period.end, taxonomy) });
  return { days, topics, weeks: allWeeks(days).map(rank), months: allMonths(days).map(rank) };
}

// All period routes share one loaded dataset and one history index; each entry is aggregated once per period kind.
export function loadPeriods() {
  const topics = allTopics("computational");
  let cached = cache.get(topics);
  if (!cached) {
    cached = buildPeriods();
    cache.set(topics, cached);
  }
  return cached;
}
