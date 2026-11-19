import { loadDays } from "./data";

export const editionInfo = {
  physics: { label: "Physics", source: "arXiv", stage: "" },
  biology: { label: "Biology", source: "bioRxiv and PubMed", stage: "Beta" },
  math: { label: "Math & Stats", source: "arXiv", stage: "Pilot" },
  "earth-environment": { label: "Earth & Environment", source: "five Copernicus journals via Crossref", stage: "Pilot" },
  chemistry: { label: "Chemistry", source: "five chemistry journals via Crossref", stage: "Pilot" },
  astronomy: { label: "Stellar & Galactic Astronomy", source: "arXiv", stage: "Pilot" },
  "computer-information": { label: "Computing & Information", source: "arXiv, DROPS and Crossref", stage: "Pilot" },
  engineering: { label: "Engineering", source: "arXiv and five engineering journals via Crossref", stage: "Pilot" },
  "agriculture-food-veterinary": { label: "Agriculture, Food & Veterinary Science", source: "Crossref and journal publishers", stage: "Pilot" },
  "medicine-health": { label: "Medicine & Health", source: "Europe PMC and Crossref", stage: "Pilot" },
  "social-sciences": { label: "Economics & Psychology", source: "arXiv, the World Bank and Crossref", stage: "Pilot" },
} as const;
export type Edition = keyof typeof editionInfo;
export const editions = (Object.keys(editionInfo) as Edition[]).filter(field =>
  editionInfo[field].stage !== "Pilot" || loadDays(field).length > 0);
