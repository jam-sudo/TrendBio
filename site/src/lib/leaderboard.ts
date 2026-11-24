import { loadCorrection, loadItems, loadTopic } from "./data";
import { selectToolNames, type ToolName } from "./tool-names";
import type { Day, Signals } from "./types";
import { periodHeadline, type PeriodRanked } from "./periods";
import { growthContext } from "./scoring";
import type { Field } from "./editions";

export interface Stat { label: string; value: string | number; spoken?: string; context?: string }
export interface LeaderboardTopic {
  rank: number;
  slug: string;
  headline: string;
  evidenceDate?: string;
  url?: string;
  correction?: boolean;
  summary?: string;
  category: string;
  categoryLabel?: string;
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
    const topic = loadTopic(day.domain, row.slug);
    const history = topic?.history ?? [];
    const ids = history.find(entry => entry.date === day.date)?.item_ids ?? [];
    const synthesis = row.synthesis ?? (topic?.synthesized_on === day.date ? topic.synthesis : "");
    return { ...row, evidenceDate: dated ? day.date : undefined,
      correction: day.domain !== "computational" && !!loadCorrection(day.domain, day.date, row.slug, [row.headline, row.summary, synthesis ?? ""], ids),
      fallbackSummary: day.run.notes.includes(`synthesis-fallback:${row.slug}`),
      toolNames: selectToolNames(day.domain === "computational" && row.rank <= 20 ? loadItems(day.domain, ids) : [], row.rank),
      secondary_categories: topic?.secondary_categories ?? [],
      stats: signalStats(row.signals, growthContext(row.signals, day.date, history, day.run.window_days)),
    };
  });
}

export function periodRows(topics: PeriodRanked[], field: Field = "computational"): LeaderboardTopic[] {
  return topics.map(topic => {
    const history = loadTopic(field, topic.slug)?.history ?? [];
    const peak = history.find(entry => entry.date === topic.rise_date);
    return { ...topic,
      headline: periodHeadline(topic),
      autoLabel: !topic.headline,
      toolNames: selectToolNames(field === "computational" && topic.rank <= 20 ? loadItems(field, topic.latest_item_ids) : [], topic.rank),
      stats: [
        { label: "days ranked", value: topic.days_ranked },
        { label: "best rank", value: topic.best_rank === null ? "—" : `#${topic.best_rank}` },
        { label: "items", value: topic.items },
        { label: "Peak rise", value: `${topic.rise.toFixed(1)}×`, context: peak && growthContext(peak.signals, peak.date, history) },
      ],
    };
  });
}
