import { industryItems, loadItems, loadTopic } from "./data";
import { datedTopic, fieldLabel, type Edition } from "./editions";
import { selectToolNames } from "./tool-names";
import type { Day } from "./types";

export const escapeXml = (text: string) => text.replace(/[&<>"']/g, char =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[char]!);

export function atomFeed(days: Day[], site: URL, category?: { slug: string; label: string }, edition?: Edition): string {
  const recent = [...days].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 30);
  const updated = (day?: Day) => day?.run.finished || `${day?.date ?? "1970-01-01"}T00:00:00Z`;
  const home = new URL(edition ? `/${edition}/` : "/", site);
  const self = new URL(category ? `feed/${category.slug}.xml` : "feed.xml", home).href;
  const title = edition ? `TrendBio — ${fieldLabel(edition)}` : "TrendBio";
  const rows = recent.flatMap(day => [...day.ranked].sort((a, b) => a.rank - b.rank)
    .filter(row => category ? row.category === category.slug : row.rank >= 1 && row.rank <= 5)
    .map(row => ({ day, row }))).slice(0, category ? 100 : 150);
  return `<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">
<title>${escapeXml(`${title} — ${category?.label ?? "Top 5"}`)}</title>
<id>${escapeXml(self)}</id><link rel="self" href="${escapeXml(self)}"/><link href="${escapeXml(home.href)}"/>
<updated>${escapeXml(updated(recent[0]))}</updated><author><name>TrendBio</name></author>
${!edition && category?.slug === "industry" ? (recent[0] ? industryItems(recent[0].domain, recent[0].date, 30, 100) : []).map(item =>
    `<entry><id>${escapeXml(`tag:trendbio.dev,${item.first_seen}:${item.id}`)}</id>
<title>${escapeXml(item.title)}</title><link href="${escapeXml(item.url)}"/>
<updated>${escapeXml(item.first_seen)}T00:00:00Z</updated><summary type="text">${escapeXml(item.summary ?? "")}</summary>
<author><name>${escapeXml(item.org ?? "TrendBio")}</name></author></entry>`).join("\n") : rows.map(({ day, row }) => {
    let summary = row.summary;
    if (!edition) {
      const entry = loadTopic(day.domain, row.slug)?.history.find(entry => entry.date === day.date);
      const names = selectToolNames(loadItems(day.domain, entry?.item_ids ?? []), 1).map(tool => tool.name);
      if (names.length) summary += ` Tools: ${names.join(", ")}.`;
    }
    const key = edition ? `${edition}/${row.slug}` : row.slug;
    const path = edition ? datedTopic(edition, day.date, row.slug) : `/topic/${row.slug}/`;
    return `<entry><id>${escapeXml(`tag:trendbio.dev,${day.date}:${key}`)}</id>
<title>${escapeXml(row.headline)}</title><link href="${escapeXml(new URL(path, site).href)}"/>
<updated>${escapeXml(updated(day))}</updated><summary type="text">${escapeXml(summary)}</summary></entry>`;
  }).join("\n")}
</feed>`;
}
