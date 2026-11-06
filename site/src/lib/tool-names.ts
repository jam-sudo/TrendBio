import type { Item } from "./types";

export const TOOL_NAME_STOPLIST = new Set([
  "Background", "Objective", "Purpose", "Review", "Introduction", "Correction", "Erratum",
  "Commentary", "Editorial", "Perspective", "Benchmarking", "Benchmark", "Evaluating",
  "Harnessing", "Deep", "Machine", "Single-cell", "Spatial", "Integrating", "Towards", "Toward",
  "Comparing", "Beyond", "Decoding", "Mapping", "Unlocking", "Leveraging", "Multi-omics",
  "Multiomics", "Protein", "Cancer", "Genomics", "Transcriptomics", "Proteomics", "Metabolomics",
  "Epigenomics", "Update", "Letter", "Protocol", "Methods", "Corrigendum", "Retraction", "Autoimmunity",
].map(word => word.toLowerCase()));

export interface ToolName { name: string; url: string }

export function extractToolName(title: string): string | null {
  const name = title.match(/^\s*([A-Za-z0-9][\w.\-+]{1,24}(?: \d[\d.]*)?) *: /)?.[1];
  return name && !TOOL_NAME_STOPLIST.has(name.toLowerCase().replace(/ \d[\d.]*$/, "")) ? name : null;
}

export function selectToolNames(items: Item[], rank: number): ToolName[] {
  if (rank < 1 || rank > 20) return [];
  const candidates = items.filter(item => item.type === "published" || item.type === "preprint")
    .flatMap(item => {
      const name = extractToolName(item.title);
      return name ? [{ name, url: item.url, published: item.type === "published" }] : [];
    }).sort((a, b) => Number(b.published) - Number(a.published)
      || a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
  const seen = new Set<string>();
  return candidates.filter(({ name }) => {
    const key = name.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 3).map(({ name, url }) => ({ name, url }));
}
