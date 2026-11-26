import type { CustomRecord } from "pagefind";
import { allTopics, loadItems, loadTaxonomy } from "../lib/data";
import { isPaper, topicEvidence, topicSnapshot } from "../lib/citations";
import { datedEvidence, editions, fieldLabel, isDaily, topicAppearances, type Field } from "../lib/editions";
import { loadPeriods, topicPages } from "../lib/period-data";
import { periodHeadline } from "../lib/periods";

const titleKey = (title: string) => title.normalize("NFKC").trim().replace(/\s+/g, " ").toLowerCase();

function archiveRecords(field: Field): CustomRecord[] {
  const records: CustomRecord[] = [];
  const appearances = topicAppearances(field);
  const supplemental = isDaily(field) ? loadPeriods(field).supplemental : undefined;
  const categories = new Map(loadTaxonomy(field).map(category => [category.slug, category.label]));
  const canonical = field === "computational" ? new Set(topicPages().map(topic => topic.slug)) : null;
  for (const topic of allTopics(field)) {
    const issues = appearances.get(topic.slug) ?? [];
    const rows = new Map(issues.map(({ day, row }) => [day.date, row]));
    const seen = new Map<string, Set<string>>();
    if (canonical?.has(topic.slug)) {
      const snapshot = topicSnapshot(topic);
      const evidence = topicEvidence(topic, snapshot);
      // The canonical article folds a linked preprint into its published paper without printing its title.
      const linked = new Set(evidence.filter(item => item.type === "published").map(item => item.preprint_id));
      seen.set(snapshot.category, new Set(evidence.filter(item => isPaper(item) && !linked.has(item.id)).map(item => titleKey(item.title))));
    } else if (field !== "computational" && isDaily(field) && issues.length) {
      const { day, row } = issues[0];
      const ids = topic.history.find(entry => entry.date === day.date)?.item_ids ?? [];
      seen.set(row.category, new Set(loadItems(field, ids).filter(isPaper).map(item => titleKey(item.title))));
    }
    for (const entry of [...topic.history].sort((a, b) => b.date.localeCompare(a.date))) {
      const row = rows.get(entry.date) ?? supplemental?.get(entry.date)?.get(topic.slug);
      if (!row) continue;
      const indexed = seen.get(row.category) ?? new Set<string>();
      seen.set(row.category, indexed);
      const titles: string[] = [];
      for (const paper of loadItems(field, entry.item_ids).filter(isPaper)) {
        const key = titleKey(paper.title);
        if (indexed.has(key)) continue;
        indexed.add(key);
        titles.push(paper.title);
      }
      if (!titles.length) continue;
      records.push({
        url: datedEvidence(field, entry.date, topic.slug), language: "en", content: titles.join("\n"),
        filters: { field: [field], category: [categories.get(row.category) ?? row.category] },
        meta: { title: titles.length === 1 ? titles[0] : "label" in row ? periodHeadline(row) : row.headline,
          field: `${fieldLabel(field)} · Archive · ${entry.date}` },
      });
    }
  }
  return records;
}

export function GET() {
  return Response.json((["computational", ...editions] as Field[]).flatMap(archiveRecords));
}
