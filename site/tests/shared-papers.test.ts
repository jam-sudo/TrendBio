import { afterEach, expect, it, vi } from "vitest";
import * as data from "../src/lib/data";
import { crossCoverage, matchRankings, type SharedRanking } from "../src/lib/shared-papers";
import type { Item } from "../src/lib/types";

const day = data.loadDay("physics", "2026-11-01")!;
const topic = data.loadTopic("physics", day.ranked[0].slug)!;
const fixture = data.loadItems("physics", topic.history[0].item_ids)[0];
function paper(id: string, overrides: Partial<Item> = {}): Item {
  return { ...fixture, id, title: "Measuring light in optical cavities", ...overrides };
}
function ranking(field: SharedRanking["field"], rank: number, papers: Item[]): SharedRanking {
  return { field, rank, papers, slug: "optics-" + rank, headline: "Light measurement" };
}
afterEach(() => vi.restoreAllMocks());

it("links shared identifiers in both directions, counting versions once per topic", () => {
  const arxiv = paper("arxiv:2611.00001v2");
  const published = paper("pubmed:pmid:12345", { source: "pubmed", type: "published", doi: "doi:10.1234/OPTICS" });
  const journal = paper("doi:10.1234/optics", { source: "crossref", type: "published",
    metadata: { preprint_dois: ["https://doi.org/10.48550/arXiv.2611.00001v1"] } });
  const index = paper("med:12345", { source: "europepmc", type: "published", metadata: { pmid: "12345" } });
  const other = paper("arxiv:2611.00002", { published_doi: "https://doi.org/10.1234/other" });
  const otherJournal = paper("doi:10.1234/other", { source: "crossref", type: "published" });
  const matches = matchRankings([ranking("physics", 3, [arxiv, published, other]),
    ranking("biology", 8, [journal, otherJournal]), ranking("biology", 2, [index])]);
  expect(matches.get("physics/optics-3")?.map(row => [row.rank, row.papers.map(p => p.id)])).toEqual([
    [8, [published.id, other.id]], [2, [published.id]]]);
  expect(matches.get("biology/optics-8")?.[0].papers).toEqual([journal, otherJournal]);
  expect(matches.get("biology/optics-2")?.[0].papers).toEqual([index]);
});

it("requires paper identity and discards shared project deposits, datasets and code", () => {
  const deposit = "10.1234/shared-deposit";
  const first = paper("arxiv:2611.00001", { doi: deposit });
  const second = paper("arxiv:2611.00002", { doi: deposit });
  const work = paper("doi:10.1234/journal", { source: "crossref", type: "published", metadata: { dataset_dois: [deposit] } });
  const code = paper("github:optics", { source: "github", type: "code" });
  expect(matchRankings([ranking("physics", 1, [first, code]), ranking("biology", 1, [second, work, code])]).size).toBe(0);
  const withdrawnClaim = paper("arxiv:2611.00003", { metadata: { arxiv_reported_doi: deposit } });
  const separate = paper("doi:" + deposit, { source: "crossref", type: "published" });
  expect(matchRankings([ranking("physics", 1, [first, withdrawnClaim]), ranking("biology", 1, [separate])]).size).toBe(0);
  const linked = paper("doi:10.1234/version", { source: "crossref", type: "published", preprint_id: first.id });
  expect(matchRankings([ranking("physics", 1, [first, second]), ranking("biology", 1, [linked])])
    .get("physics/optics-1")?.[0].papers).toEqual([first]);
});

it("compares only the dated ranked evidence of public editions", () => {
  const date = "2026-10-12";
  const shared = paper("arxiv:2610.30001");
  const attached = paper("arxiv:2610.30002");
  const lookup = vi.spyOn(data, "loadDay").mockImplementation((field, when) =>
    (when === date && ["physics", "biology", "math"].includes(field)) ? { ...day, date } : null);
  vi.spyOn(data, "loadTopic").mockImplementation((field) => ({ ...topic, history: [
    { ...topic.history[0], date: "2026-10-13", item_ids: [attached.id] },
    { ...topic.history[0], date, item_ids: field === "physics" ? [shared.id, attached.id] : [shared.id],
      attached_item_ids: [attached.id] }] }));
  vi.spyOn(data, "loadItems").mockImplementation((_, ids) => [shared, attached].filter(p => ids.includes(p.id)));
  const found = crossCoverage("physics", date, day.ranked[0].slug);
  expect(found.map(row => [row.field, row.rank, row.papers])).toEqual([["biology", 1, [shared]]]);
  expect(crossCoverage("physics", date, "unranked")).toEqual([]);
  expect(crossCoverage("physics", "2026-10-13", day.ranked[0].slug)).toEqual([]);
  expect(lookup.mock.calls.some(([field]) => field === "math")).toBe(false);
});
