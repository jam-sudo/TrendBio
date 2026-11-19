import { loadDays } from "./data";

export const editionInfo = {
  physics: { label: "Physics", source: "arXiv", stage: "" },
  biology: { label: "Biology", source: "bioRxiv and PubMed", stage: "Beta" },
  math: { label: "Math & Stats", source: "arXiv", stage: "Pilot" },
  "earth-environment": { label: "Earth & Environment", source: "five Copernicus journals via Crossref", stage: "Pilot" },
} as const;
export type Edition = keyof typeof editionInfo;
export const editions = (Object.keys(editionInfo) as Edition[]).filter(field =>
  editionInfo[field].stage !== "Pilot" || loadDays(field).length > 0);
