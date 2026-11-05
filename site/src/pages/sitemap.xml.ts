import type { APIRoute } from "astro";
import { loadPeriods, topicPages } from "../lib/period-data";

export const GET: APIRoute = ({ site }) => {
  const { days, weeks, months } = loadPeriods();
  const today = new Date().toISOString().slice(0, 10);
  const entries = [
    ...["/", "/topics/", "/map/", "/archive/", "/about/", "/week/", "/month/"].map(path => ({ path, date: today })),
    ...days.map(({ date }) => ({ path: `/day/${date}/`, date })),
    ...([["week", weeks], ["month", months]] as const).flatMap(([kind, periods]) =>
      periods.map(period => ({ path: `/${kind}/${period.id}/`,
        date: days.find(({ date }) => date >= period.start && date <= period.end)!.date }))),
    ...topicPages().map(topic => {
      const ranked = topic.history.filter(({ rank }) => rank !== null);
      return { path: `/topic/${topic.slug}/`,
        date: (ranked.length ? ranked : topic.history).map(({ date }) => date).sort().at(-1)! };
    }),
  ];
  const escape = (text: string) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return new Response(`<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${entries.map(({ path, date }) =>
    `<url><loc>${escape(new URL(path, site).href)}</loc><lastmod>${date}</lastmod></url>`).join("")}</urlset>`,
  { headers: { "Content-Type": "application/xml" } });
};
