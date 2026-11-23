import { allTopics, loadDays, loadItems } from "./data";
import type { Day, Topic } from "./types";

export interface RankChange { label: string; description: string }
export interface TopicMovement { rank?: RankChange; entered: boolean; addedPaperIds: Set<string> }

function compareEditions(day: Day, days: Day[], topics: Topic[]) {
  const older = days.filter(entry => entry.date < day.date).sort((a, b) => b.date.localeCompare(a.date));
  const previous = older[0];
  if (!previous) return null;
  const top40 = (rank: number | null) => rank !== null && rank >= 1 && rank <= 40;
  const previousRanks = new Map(previous.ranked.filter(row => top40(row.rank)).map(row => [row.slug, row.rank]));
  const seen = new Set(older.flatMap(entry => entry.ranked.filter(row => top40(row.rank)).map(row => row.slug)));
  const histories = new Map(topics.map(topic => [topic.slug, topic.history]));
  const rows = new Map<string, TopicMovement>();
  let entered = 0;
  for (const row of day.ranked.filter(row => top40(row.rank))) {
    const prior = previousRanks.get(row.slug);
    const history = histories.get(row.slug) ?? [];
    let rank: RankChange | undefined;
    if (prior === undefined) {
      rank = seen.has(row.slug) || history.some(entry => entry.date < day.date && top40(entry.rank))
        ? { label: "Back", description: "Back in the Top 40 after a previous appearance" }
        : { label: "New", description: "First recorded appearance in the Top 40" };
    } else if (prior !== row.rank) {
      const distance = Math.abs(prior - row.rank);
      rank = { label: `${prior > row.rank ? "▲" : "▼"}${distance}`,
        description: `${prior > row.rank ? "Up" : "Down"} ${distance} ${distance === 1 ? "place" : "places"} since the previous edition` };
    }
    const joined = row.rank <= 10 && (prior === undefined || prior > 10);
    if (joined) entered++;
    const before = history.find(entry => entry.date === previous.date);
    const after = history.find(entry => entry.date === day.date);
    const previousIds = new Set(before?.item_ids);
    const additions = before && after ? [...new Set(after.item_ids)].filter(id => !previousIds.has(id)) : [];
    const addedPaperIds = new Set(loadItems(day.domain, additions)
      .filter(item => item.type === "published" || item.type === "preprint").map(item => item.id));
    rows.set(row.slug, { rank, entered: joined, addedPaperIds });
  }
  return { previousDate: previous.date, entered, rows };
}

const comparisons = new WeakMap<Day, ReturnType<typeof compareEditions>>();
export function editionChanges(day: Day, days?: Day[], topics?: Topic[]) {
  if (days || topics) return compareEditions(day, days ?? loadDays(day.domain), topics ?? allTopics(day.domain));
  if (!comparisons.has(day)) comparisons.set(day, compareEditions(day, loadDays(day.domain), allTopics(day.domain)));
  return comparisons.get(day) ?? null;
}
