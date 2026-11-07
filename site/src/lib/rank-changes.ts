import type { Day, Topic } from "./types";

export interface RankChange { label: string; description: string }

export function rankChanges(day: Day, days: Day[], topics: Topic[]): Map<string, RankChange> {
  const changes = new Map<string, RankChange>();
  const older = days.filter(entry => entry.date < day.date).sort((a, b) => b.date.localeCompare(a.date));
  if (!older.length) return changes;
  const top40 = (rank: number | null) => rank !== null && rank >= 1 && rank <= 40;
  const previous = new Map(older[0].ranked.filter(row => top40(row.rank)).map(row => [row.slug, row.rank]));
  const seen = new Set(older.flatMap(entry => entry.ranked.filter(row => top40(row.rank)).map(row => row.slug)));
  for (const topic of topics) {
    if (topic.history.some(entry => entry.date < day.date && top40(entry.rank))) seen.add(topic.slug);
  }
  for (const row of day.ranked.filter(row => top40(row.rank))) {
    const prior = previous.get(row.slug);
    if (prior === undefined) {
      changes.set(row.slug, seen.has(row.slug)
        ? { label: "Back", description: "Back in the Top 40 after a previous appearance" }
        : { label: "New", description: "New to the Top 40: first ranked appearance" });
    } else if (prior !== row.rank) {
      const distance = Math.abs(prior - row.rank);
      changes.set(row.slug, { label: `${prior > row.rank ? "▲" : "▼"}${distance}`,
        description: `${prior > row.rank ? "Up" : "Down"} ${distance} ${distance === 1 ? "place" : "places"} since the previous day` });
    }
  }
  return changes;
}
