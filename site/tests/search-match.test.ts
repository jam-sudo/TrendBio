import { expect, it, vi } from "vitest";
import { matchingPages, matchesQuery } from "../src/lib/search-match.js";

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
  ["뼈", "뼈의 구조"], ["양자", "양자물리학"], ["유전체".normalize("NFD"), "유전체 분석"],
])("matches %s against %s", (query, content) => {
  expect(matchesQuery(query, content)).toBe(true);
});

it("requires every long query word at a word boundary", () => {
  expect(matchesQuery("alpha perturbations", "AlphaFold3 perturbation")).toBe(true);
  expect(matchesQuery("alpha missing", "AlphaFold3 perturbation")).toBe(false);
  expect(matchesQuery("fold", "AlphaFold3")).toBe(false);
  expect(matchesQuery("AlphaFold3", "AlphaFold")).toBe(false);
  expect(matchesQuery("perturbations", "perturb")).toBe(false);
  expect(matchesQuery("양자", "세포와 유전체")).toBe(false);
});

it("matches short scientific terms as whole words, including hyphenated modifiers", () => {
  expect(matchesQuery("pH", "Phase transitions in solids")).toBe(false);
  expect(matchesQuery("pH", "pH-dependent emission")).toBe(true);
  expect(matchesQuery("UV light", "Ultraviolet light")).toBe(false);
  expect(matchesQuery("UV light", "Light measured in the UV")).toBe(true);
  expect(matchesQuery("2D", "2D-materials")).toBe(true);
  expect(matchesQuery("2D", "2D5 spectra")).toBe(false);
  expect(matchesQuery("R", "Rotation")).toBe(false);
  expect(matchesQuery("in PoolParty", "PoolParty")).toBe(true);
});

it("reads bounded pages through the last candidate, keeping matches ordered across retries", async () => {
  const candidates = Array.from({ length: 91 }, (_, id) => ({
    data: vi.fn().mockResolvedValue({ content: id < 20 || id >= 68 ? "PoolParty" : "unrelated", id }),
  }));
  const pages = matchingPages("poolparty", candidates);
  const current = () => true;
  expect(await pages.next(current)).toMatchObject({ count: 20, shown: 20, more: true, complete: false });
  expect(candidates[20].data).not.toHaveBeenCalled();
  candidates[60].data.mockRejectedValueOnce(new Error("offline"));
  await expect(pages.next(current)).rejects.toThrow("offline");
  expect(await pages.next(() => false)).toBeNull();
  const next = await pages.next(current);
  expect(next!.page.map(row => row.id)).toEqual(Array.from({ length: 20 }, (_, i) => 68 + i));
  expect(next).toMatchObject({ count: 43, shown: 40, more: true, complete: true });
  expect(candidates[20].data).toHaveBeenCalledTimes(1);
  expect((await pages.next(current))!).toMatchObject({ count: 43, shown: 43, more: false });
});

it("stops after six matches without fetching the remaining fragments", async () => {
  const { firstMatches } = await import('../src/lib/search-match.js');
  const miss = vi.fn().mockResolvedValue({ content: 'unrelated' });
  const hit = vi.fn().mockResolvedValue({ content: 'PoolParty' });
  const candidates = [{ data: miss }, ...Array.from({ length: 70 }, () => ({ data: hit }))];
  expect(await firstMatches('PoolParty', candidates, () => true)).toHaveLength(6);
  expect(hit).toHaveBeenCalledTimes(6);
  expect(miss).toHaveBeenCalledTimes(1);
  hit.mockClear();
  expect(await firstMatches('nonsense', candidates, () => true)).toHaveLength(0);
  expect(hit).toHaveBeenCalledTimes(70);
  expect(await firstMatches('PoolParty', [...Array.from({ length: 60 }, () => ({ data: miss })), { data: hit }], () => true)).toHaveLength(1);
  hit.mockClear();
  expect(await firstMatches('PoolParty', candidates, () => false)).toEqual([]);
  expect(hit).not.toHaveBeenCalled();
});
