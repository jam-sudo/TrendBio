import { loadItems, loadTopic } from "./data";
import { selectToolNames } from "./tool-names";
import type { Day } from "./types";

export const escapeXml = (text: string) => text.replace(/[&<>"']/g, char =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[char]!);

export function atomFeed(days: Day[], site: URL, category?: { slug: string; label: string }): string {
  const recent = [...days].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 30);
  const updated = (day?: Day) => day?.run.finished || `${day?.date ?? "1970-01-01"}T00:00:00Z`;
  const self = new URL(category ? `/feed/${category.slug}.xml` : "/feed.xml", site).href;
  const rows = recent.flatMap(day => [...day.ranked].sort((a, b) => a.rank - b.rank)
    .filter(row => category ? row.category === category.slug : row.rank >= 1 && row.rank <= 5)
    .map(row => ({ day, row }))).slice(0, category ? 100 : 150);
  return `<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>${escapeXml(category ? `TrendBio — ${category.label}` : "TrendBio — Top 5")}</title>
<id>${escapeXml(self)}</id><link rel="self" href="${escapeXml(self)}"/><link href="${escapeXml(site.href)}"/>
<updated>${escapeXml(updated(recent[0]))}</updated><author><name>TrendBio</name></author>
${rows.map(({ day, row }) => {
    const entry = loadTopic(day.domain, row.slug)?.history.find(entry => entry.date === day.date);
    const names = selectToolNames(loadItems(day.domain, entry?.item_ids ?? []), 1).map(tool => tool.name);
    const summary = row.summary + (names.length ? ` Tools: ${names.join(", ")}.` : "");
    return `<entry><id>${escapeXml(`tag:trendbio.dev,${day.date}:${row.slug}`)}</id>
<title>${escapeXml(row.headline)}</title><link href="${escapeXml(new URL(`/topic/${row.slug}/`, site).href)}"/>
<updated>${escapeXml(updated(day))}</updated><summary type="text">${escapeXml(summary)}</summary></entry>`;
  }).join("\n")}
</feed>`;
}
