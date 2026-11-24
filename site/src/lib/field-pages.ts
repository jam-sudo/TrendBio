import { loadDays } from "./data";
import { isDaily, type Edition } from "./editions";
import { loadPeriods, type RankedPeriod } from "./period-data";
import { pilotIssues } from "./pilot-topics";
import type { Day } from "./types";

interface FieldPage {
  path: string;
  view: "landing" | "day" | "papers" | "topics" | "map" | "archive" | "week" | "month";
  date?: string;
  day?: Day;
  period?: RankedPeriod;
}

export function fieldPages(field: Edition): FieldPage[] {
  const days = loadDays(field);
  const latest = days[0];
  const pages: FieldPage[] = [{ path: "", view: "landing", day: latest, date: [latest?.date, pilotIssues(field)[0]].filter(Boolean).sort().at(-1) }];
  for (const day of days) {
    pages.push({ path: `day/${day.date}`, view: "day", date: day.date, day },
      { path: `day/${day.date}/papers`, view: "papers", date: day.date, day });
  }
  if (isDaily(field)) {
    for (const view of ["topics", "map", "archive", "week", "month"] as const) pages.push({ path: view, view, date: latest?.date });
    const data = loadPeriods(field);
    for (const [view, periods] of [["week", data.weeks], ["month", data.months]] as const) {
      for (const period of periods) pages.push({ path: `${view}/${period.id}`, view, period,
        date: days.find(day => day.date >= period.start && day.date <= period.end)?.date });
    }
  }
  return pages;
}
