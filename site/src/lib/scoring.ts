import { readFileSync } from "node:fs";
import { parse } from "yaml";
import type { Signals, TopicDay } from "./types";

export const scoring = parse(readFileSync("../config/scoring.yaml", "utf8"));

const baselineText = {
  field_median: "vs field median",
  four_week_mean: "vs 4-wk avg",
  prior_window_mean: "vs prior-window avg",
};

export function growthContext(signals: Signals, date: string, history: TopicDay[], windowDays = 7): string {
  if (signals.rise_baseline) return baselineText[signals.rise_baseline];
  // Legacy editions predate the stored baseline. Reconstruct the rule used for that issue.
  if (!history.some(entry => entry.date === date)) return "vs baseline";
  const asOf = Date.parse(date);
  if (windowDays === 7) {
    const cutoff = asOf - 14 * 86_400_000;
    return history.some(entry => Date.parse(entry.date) <= cutoff) ? baselineText.four_week_mean : baselineText.field_median;
  }
  const prior = new Set(Array.from({ length: 4 }, (_, i) =>
    new Date(asOf - (i + 1) * windowDays * 86_400_000).toISOString().slice(0, 10)));
  return history.filter(entry => prior.has(entry.date) && entry.item_ids.length).length >= 2
    ? baselineText.prior_window_mean : baselineText.field_median;
}
