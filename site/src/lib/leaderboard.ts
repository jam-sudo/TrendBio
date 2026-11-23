import { loadItems, loadTopic } from "./data";
import { selectToolNames, type ToolName } from "./tool-names";
import type { Day, Signals } from "./types";
import { periodHeadline, type PeriodRanked } from "./periods";
import { growthContext } from "./scoring";

export interface Stat { label: string; value: string | number; spoken?: string; context?: string }
export interface LeaderboardTopic {
  rank: number;
  slug: string;
  headline: string;
  evidenceDate?: string;
  summary?: string;
  category: string;
  secondary_categories: string[];
  stats: Stat[];
  autoLabel?: boolean;
  fallbackSummary?: boolean;
  toolNames: ToolName[];
}

export function signalStats(signals: Signals, context: string): Stat[] {
  const counts: Stat[] = [
    { label: "preprints", value: signals.preprint, spoken: `${signals.preprint} preprint${signals.preprint === 1 ? "" : "s"}` },
    { label: "published", value: signals.published, spoken: `${signals.published} published` },
    { label: "code", value: signals.code, spoken: `${signals.code} tool${signals.code === 1 ? "" : "s"}` },
    { label: "industry", value: signals.industry, spoken: `${signals.industry} industry` },
  ].filter(({ value }) => value > 0);
  if (signals.rise_ratio >= 1.5) counts.push({ label: "Rise", value: `↑ ${signals.rise_ratio.toFixed(1)}×`, context, spoken: `↑ ${signals.rise_ratio.toFixed(1)}× ${context}` });
  return counts;
}

export function dailyRows(day: Day | null, dated = false): LeaderboardTopic[] {
  if (!day) return [];
  return day.ranked.map(row => {
    const topic = loadTopic("computational", row.slug);
    const history = topic?.history ?? [];
    const ids = history.find(entry => entry.date === day.date)?.item_ids ?? [];
    return { ...row, evidenceDate: dated ? day.date : undefined,
      fallbackSummary: day.run.notes.includes(`synthesis-fallback:${row.slug}`),
      toolNames: selectToolNames(row.rank <= 20 ? loadItems("computational", ids) : [], row.rank),
      secondary_categories: topic?.secondary_categories ?? [],
      stats: signalStats(row.signals, growthContext(row.signals, day.date, history, day.run.window_days)),
    };
  });
}

export function periodRows(topics: PeriodRanked[]): LeaderboardTopic[] {
  return topics.map(topic => {
    const history = loadTopic("computational", topic.slug)?.history ?? [];
    const peak = history.find(entry => entry.date === topic.rise_date);
    return { ...topic,
      headline: periodHeadline(topic),
      autoLabel: !topic.headline,
      toolNames: selectToolNames(topic.rank <= 20 ? loadItems("computational", topic.latest_item_ids) : [], topic.rank),
      stats: [
        { label: "days ranked", value: topic.days_ranked },
        { label: "best rank", value: topic.best_rank === null ? "—" : `#${topic.best_rank}` },
        { label: "items", value: topic.items },
        { label: "Peak rise", value: `${topic.rise.toFixed(1)}×`, context: peak && growthContext(peak.signals, peak.date, history) },
      ],
    };
  });
}
