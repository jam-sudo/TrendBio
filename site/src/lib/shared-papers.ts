import { loadDay, loadItems, loadTopic } from "./data";
import { publicEditions, type Field } from "./editions";
import type { Item, RankedTopic } from "./types";

export type SharedRanking = Pick<RankedTopic, "rank" | "slug" | "headline"> & { field: Field; papers: Item[] };

function arxivId(id: string) {
  return id.toLowerCase().replace(/(\d)v\d+$/, "$1");
}

function doi(value: unknown): string | undefined {
  if (typeof value !== "string") return;
  const id = value.trim().toLowerCase().replace(/^doi:\s*/, "").replace(/^https?:\/\/(?:dx\.)?doi\.org\//, "");
  if (!/^10\.\d{4,9}\/\S+$/.test(id)) return;
  return id.startsWith("10.48550/arxiv.") ? arxivId("arxiv:" + id.slice("10.48550/arxiv.".length)) : "doi:" + id;
}

function nativeId(id: string): string {
  if (id.startsWith("arxiv:")) return arxivId(id);
  if (id.startsWith("pubmed:pmid:")) return id.slice("pubmed:".length);
  return doi(id) ?? id;
}

export function matchRankings(rows: SharedRanking[]): Map<string, SharedRanking[]> {
  const papers = rows.flatMap(row => row.papers).filter(p => p.type === "published" || p.type === "preprint");
  const arxivClaims = new Map<string, string>();
  const ambiguous = new Set<string>();
  for (const p of papers) {
    if (p.source !== "arxiv") continue;
    const disclaimed = doi(p.metadata.arxiv_reported_doi);
    if (disclaimed) ambiguous.add(disclaimed);
    const reported = doi(p.doi);
    if (!reported) continue;
    const native = nativeId(p.id);
    if (arxivClaims.has(reported) && arxivClaims.get(reported) !== native) ambiguous.add(reported);
    arxivClaims.set(reported, native);
  }

  // A DOI, a repository ID and an explicitly linked publication can denote one work.
  const parent = new Map<string, string>();
  function root(id: string): string {
    const next = parent.get(id);
    if (!next) return id;
    const canonical = root(next);
    parent.set(id, canonical);
    return canonical;
  }
  for (const p of papers) {
    const id = root(nativeId(p.id));
    const aliases = [doi(p.doi), doi(p.published_doi), doi(p.metadata.preprint_doi)];
    if (Array.isArray(p.metadata.preprint_dois)) aliases.push(...p.metadata.preprint_dois.map(doi));
    if (p.preprint_id) aliases.push(nativeId(p.preprint_id));
    if (typeof p.metadata.pmid === "string" && /^\d+$/.test(p.metadata.pmid)) aliases.push("pmid:" + p.metadata.pmid);
    for (const alias of aliases) {
      if (!alias || (p.source === "arxiv" && ambiguous.has(alias))) continue;
      const other = root(alias);
      if (other !== id) parent.set(other, id);
    }
  }

  const appearances = new Map<string, Map<SharedRanking, Item>>();
  for (const row of rows) {
    for (const p of row.papers) {
      if (p.type !== "published" && p.type !== "preprint") continue;
      const work = root(nativeId(p.id));
      const byRow = appearances.get(work) ?? new Map<SharedRanking, Item>();
      if (!byRow.has(row) || p.type === "published") byRow.set(row, p);
      appearances.set(work, byRow);
    }
  }
  const matches = new Map<SharedRanking, Map<SharedRanking, SharedRanking>>();
  for (const byRow of appearances.values()) {
    for (const [source, paper] of byRow) {
      for (const target of byRow.keys()) {
        if (target.field === source.field) continue;
        const other = matches.get(source) ?? new Map<SharedRanking, SharedRanking>();
        const match = other.get(target) ?? { ...target, papers: [] };
        match.papers.push(paper);
        other.set(target, match);
        matches.set(source, other);
      }
    }
  }
  return new Map(Array.from(matches, ([row, other]) => [row.field + "/" + row.slug,
    [...other.values()].sort((a, b) => b.papers.length - a.papers.length || a.rank - b.rank || a.field.localeCompare(b.field))]));
}

const byDate = new Map<string, ReturnType<typeof matchRankings>>();

export function crossCoverage(field: Field, date: string, slug: string): SharedRanking[] {
  if (!byDate.has(date)) {
    const fields: Field[] = ["computational", ...publicEditions];
    const days = fields.flatMap(field => {
      const day = loadDay(field, date);
      return day?.ranked.length ? [{ field, day }] : [];
    });
    const rows = days.length < 2 ? [] : days.flatMap(({ field, day }) => day.ranked.map(row => {
      const history = loadTopic(field, row.slug)?.history.find(h => h.date === date);
      return { field, rank: row.rank, slug: row.slug, headline: row.headline, papers: loadItems(field, history?.item_ids ?? []) };
    }));
    byDate.set(date, matchRankings(rows));
  }
  return byDate.get(date)!.get(field + "/" + slug) ?? [];
}
