import type { CustomRecord } from "pagefind";
import { allTopics, loadTaxonomy } from "../lib/data";
import { datedPapers, isPaper, topicEvidence, topicSnapshot } from "../lib/citations";
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
    const rows = new Map(issues.map(issue => [issue.day.date, issue]));
    const seen = new Map<string, Set<string>>();
    const seenCopy = new Set<string>();
    let canonicalDate: string | undefined;
    if (canonical?.has(topic.slug)) {
      const snapshot = topicSnapshot(topic);
      canonicalDate = snapshot.issue?.day.date;
      const evidence = topicEvidence(topic, snapshot);
      // The canonical article folds a linked preprint into its published paper without printing its title.
      const linked = new Set(evidence.filter(item => item.type === "published").map(item => item.preprint_id));
      seen.set(snapshot.category, new Set(evidence.filter(item => isPaper(item) && !linked.has(item.id)).map(item => titleKey(item.title))));
    } else if (field !== "computational" && isDaily(field) && issues.length) {
      const { day, row } = issues[0];
      canonicalDate = day.date;
      const entry = topic.history.find(entry => entry.date === day.date);
      seen.set(row.category, new Set(datedPapers(field, entry).map(item => titleKey(item.title))));
    }
    for (const entry of [...topic.history].sort((a, b) => b.date.localeCompare(a.date))) {
      const issue = rows.get(entry.date);
      const published = issue?.row;
      const row = published ?? supplemental?.get(entry.date)?.get(topic.slug);
      if (!row) continue;
      const indexed = seen.get(row.category) ?? new Set<string>();
      seen.set(row.category, indexed);
      const titles: string[] = [];
      for (const paper of datedPapers(field, entry)) {
        const key = titleKey(paper.title);
        if (indexed.has(key)) continue;
        indexed.add(key);
        titles.push(paper.title);
      }
      const fallback = issue?.day.run.notes.includes(`synthesis-fallback:${topic.slug}`);
      const synthesis = fallback ? "" : published?.synthesis ?? (topic.synthesized_on === entry.date ? topic.synthesis : "");
      const copy = published ? [published.headline, published.summary, synthesis ?? ""] : [];
      const keys = published ? [JSON.stringify([row.category, published.headline, published.summary])] : [];
      if (published && synthesis) keys.push(JSON.stringify([row.category, ...copy]));
      const newCopy = entry.date !== canonicalDate && keys.some(key => !seenCopy.has(key));
      for (const key of keys) seenCopy.add(key);
      if (!titles.length && !newCopy) continue;
      const headline = "label" in row ? periodHeadline(row) : row.headline;
      const title = !newCopy && titles.length === 1 ? titles[0] : headline;
      records.push({
        url: datedEvidence(field, entry.date, topic.slug), language: "en",
        content: [...new Set([title, ...(newCopy ? copy : []), ...titles].filter(Boolean))].join("\n"),
        filters: { field: [field], category: [categories.get(row.category) ?? row.category] },
        meta: { title, field: `${fieldLabel(field)} · Archive · ${entry.date}` },
      });
    }
  }
  return records;
}

export function GET() {
  return Response.json((["computational", ...editions] as Field[]).flatMap(archiveRecords));
}
