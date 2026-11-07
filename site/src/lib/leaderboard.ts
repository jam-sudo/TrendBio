import { allTopics, loadDays, loadItems, loadTopic } from "./data";
import { rankChanges, type RankChange } from "./rank-changes";
import { selectToolNames, type ToolName } from "./tool-names";
import type { Day, Signals } from "./types";
import type { PeriodRanked } from "./periods";

export interface Stat { label: string; value: string | number; spoken?: string; context?: string }
export interface LeaderboardTopic {
  rank: number;
  rankChange?: RankChange;
  slug: string;
  headline: string;
  summary?: string;
  category: string;
  secondary_categories: string[];
  stats: Stat[];
  autoLabel?: boolean;
  toolNames: ToolName[];
}

export function signalStats(signals: Signals): Stat[] {
  const counts: Stat[] = [
    { label: "preprints", value: signals.preprint, spoken: `${signals.preprint} preprint${signals.preprint === 1 ? "" : "s"}` },
    { label: "published", value: signals.published, spoken: `${signals.published} published` },
    { label: "code", value: signals.code, spoken: `${signals.code} tool${signals.code === 1 ? "" : "s"}` },
    { label: "industry", value: signals.industry, spoken: `${signals.industry} industry` },
  ].filter(({ value }) => value > 0);
  if (signals.rise_ratio >= 1.5) counts.push({ label: "Rise", value: `↑ ${signals.rise_ratio.toFixed(1)}×`, context: "vs 4-wk avg", spoken: `↑ ${signals.rise_ratio.toFixed(1)}× vs 4-wk avg` });
  return counts;
}

export function dailyRows(day: Day | null): LeaderboardTopic[] {
  const changes = day ? rankChanges(day, loadDays(day.domain), allTopics(day.domain)) : new Map();
  return (day?.ranked ?? []).map((topic) => ({ ...topic,
    rankChange: changes.get(topic.slug),
    toolNames: selectToolNames(topic.rank <= 20 ? loadItems("computational",
      loadTopic("computational", topic.slug)?.history.find(entry => entry.date === day!.date)?.item_ids ?? []) : [], topic.rank),
    secondary_categories: loadTopic("computational", topic.slug)?.secondary_categories ?? [], stats: signalStats(topic.signals),
  }));
}

export function periodRows(topics: PeriodRanked[]): LeaderboardTopic[] {
  return topics.map((topic) => ({ ...topic,
    headline: topic.headline || topic.label.replace(/\b\p{L}/gu, (letter) => letter.toUpperCase()),
    autoLabel: !topic.headline,
    toolNames: selectToolNames(topic.rank <= 20 ? loadItems("computational", topic.latest_item_ids) : [], topic.rank),
    stats: [
      { label: "days ranked", value: topic.days_ranked },
      { label: "best rank", value: topic.best_rank === null ? "—" : `#${topic.best_rank}` },
      { label: "items", value: topic.items },
      { label: "Rise", value: `${topic.rise.toFixed(1)}×` },
    ],
  }));
}
