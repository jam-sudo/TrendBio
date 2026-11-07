import { expect, it, vi } from "vitest";
import { filterResults, matchesQuery } from "../public/search-match.js";

it.each(["qqzzxxnomatch", "zzzzqqqq", "xkcdvvv"])("rejects reverse-prefix matches for %s", query => {
  expect(matchesQuery(query, "Yang, Q. Zhang, Z. Hyper Screening X")).toBe(false);
});

it.each([
  ["PoolParty", "poolparty"], ["poolparty", "PoolParty"],
  ["alphafold", "AlphaFold3"], ["AlphaFold3", "AlphaFold3"],
  ["perturbation", "perturbations"], ["perturbations", "perturbation"],
  ["scRNA-seq", "scRNAseq"], ["single-cell", "single-cell"],
  ["Evo.2", "Evo.2"], ["evo.2", "Evo2"], ["antibodies", "antibody"],
  ["cafe", "café"], ["in PoolParty", "PoolParty"],
])("matches %s against %s", (query, content) => {
  expect(matchesQuery(query, content)).toBe(true);
});

it("requires every long query word at a word boundary", () => {
  expect(matchesQuery("alpha perturbations", "AlphaFold3 perturbation")).toBe(true);
  expect(matchesQuery("alpha missing", "AlphaFold3 perturbation")).toBe(false);
  expect(matchesQuery("fold", "AlphaFold3")).toBe(false);
  expect(matchesQuery("AlphaFold3", "AlphaFold")).toBe(false);
  expect(matchesQuery("perturbations", "perturb")).toBe(false);
});

it("loads at most 50 candidates and retains only matching data in order", async () => {
  const data = vi.fn().mockResolvedValue({ content: "Q. unrelated" });
  const match = { content: "PoolParty", url: "/topic/poolparty/" };
  const beyondLimit = vi.fn().mockResolvedValue(match);
  const candidates = Array.from({ length: 50 }, () => ({ data }));
  candidates[2] = { data: vi.fn().mockResolvedValue(match) };
  expect(await filterResults("poolparty", [...candidates, { data: beyondLimit }])).toEqual([match]);
  expect(data).toHaveBeenCalledTimes(49);
  expect(beyondLimit).not.toHaveBeenCalled();
});
