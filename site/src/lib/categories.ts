import type { Field } from "./editions";
// Category identity is shared by every view; labels come from the taxonomy.
export const categoryIdentity: Record<string, { icon: string; hue: number }> = {
  genomics: { icon: '<path d="M6 2C6 7 18 7 18 12S6 17 6 22M18 2C18 7 6 7 6 12S18 17 18 22M8 4h8M6 12h12M8 20h8"/>', hue: 150 },
  transcriptomics: { icon: '<path d="M2 11C5 3 8 19 12 11S18 11 22 11m-3-3 3 3-3 3M5 14v4m5-3v5m5-7v5"/>', hue: 200 },
  proteomics: { icon: '<path d="M3 7c0-5 6-5 6 0s-6 5-6 0m6 0c0-5 6-5 6 0s-6 5-6 0"/><polyline points="9 7 5 15 13 21 21 16 17 10 10 16"/>', hue: 280 },
  metabolomics: { icon: '<path d="m9 3 6 4v8l-6 4-6-4V7Zm3 5v6m3 1 4 3h2"/><circle cx="21" cy="18" r="1.25" fill="currentColor" stroke="none"/>', hue: 60 },
  epigenomics: { icon: '<path d="M2 12h20M2 19h20M5 12v7m7-7v7m7-7v7M7 12V6m10 6V4"/><circle cx="7" cy="4.5" r="1.5" fill="currentColor" stroke="none"/><circle cx="17" cy="2.5" r="1.5" fill="currentColor" stroke="none"/>', hue: 320 },
  "single-cell": { icon: '<path d="M21 12c0 6-4 9-10 9S2 17 2 11 6 2 12 2s9 4 9 10Z"/><circle cx="10" cy="13" r="4"/><circle cx="9" cy="12" r="1" fill="currentColor" stroke="none"/>', hue: 190 },
  structural: { icon: '<path d="M4 2c8 0 8 7 3 7s-5-5 0-5 5 12 0 12-5-5 0-5 5 12 0 12-5-5 0-5M17 3v12h-3l5 6 4-6h-3V3"/>', hue: 240 },
  systems: { icon: '<path d="m5 5 5 5m4 0 4-5M5 5h13M5 19l5-5m4 0 4 5M5 19h13"/><circle cx="12" cy="12" r="3"/><circle cx="4" cy="4" r="2"/><circle cx="20" cy="4" r="2"/><circle cx="4" cy="20" r="2"/><circle cx="20" cy="20" r="2"/>', hue: 120 },
  "ml-ai": { icon: '<path d="m5 4 5 3M5 5l5 11M5 12l5-4m-5 4 5 4M5 19l5-11M5 20l5-3m4-9 5 3m-5 5 5-3"/><circle cx="3" cy="4" r="2"/><circle cx="3" cy="12" r="2"/><circle cx="3" cy="20" r="2"/><circle cx="12" cy="7" r="2"/><circle cx="12" cy="17" r="2"/><circle cx="21" cy="12" r="2"/>', hue: 270 },
  "tools-infra": { icon: '<path d="M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm2 4 4 4-4 4m7 0h3"/>', hue: 30 },
  industry: { icon: '<path d="M3 21V8h11v13H3Zm2-13V3h3v5M6 12h2v3H6Zm4 0h2v3h-2Zm7 5 5-6m-4 0h4v4"/>', hue: 350 },
};
const fallback = { icon: '<path d="m7 3 4-1 4 9-4 2Zm7 6c7 0 8 11-1 11H5m7-7-2 3m-3 0h7m-3 4v2m-5 0h12"/>', hue: 0 };
const atom = '<circle cx="12" cy="12" r="1.5"/><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(-35 12 12)"/><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(35 12 12)"/>';
const fieldIcons: Record<Exclude<Field, "computational"> | "materials" | "energy", string> = {
  physics: atom, "physics-expanded": atom,
  biology: categoryIdentity["single-cell"].icon,
  "computer-information": categoryIdentity["tools-infra"].icon,
  math: '<path d="M4 3v17h17M6 15c4 0 4-10 8-10s3 9 7 9"/>',
  astronomy: '<circle cx="12" cy="12" r="4"/><ellipse cx="12" cy="12" rx="11" ry="3" transform="rotate(-30 12 12)"/>',
  "earth-environment": '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
  chemistry: '<path d="M8 3h8m-6 0v7L4 20h16l-6-10V3M7 15h10"/>',
  engineering: '<path d="m4 18 13-13 4 4L8 22Zm8-9 3 3m-7 1 3 3"/>',
  "medicine-health": '<path d="M2 12h5l2-7 5 15 2-8h6"/>',
  "agriculture-food-veterinary": '<path d="M4 20C3 10 9 4 21 3c0 10-6 17-14 15m-4 4L16 9"/>',
  materials: '<path d="m12 2 9 5v10l-9 5-9-5V7Zm-9 5 9 5 9-5m-9 5v10"/>',
  energy: '<path d="m13 2-9 12h7l-1 8 10-13h-8Z"/>',
};
export type CardField = Field | "materials" | "energy";
// Related subjects share a symbol across editions, including the two Physics editions.
const subjectIcons: Record<string, string> = {};
function subjects(slugs: string[], icon: string) {
  for (const slug of slugs) subjectIcons[slug] = icon;
}
subjects(["genetics", "evolution", "plant-breeding"], categoryIdentity.genomics.icon);
subjects(["molecular-cell", "microbial-ecology", "basic-medicine", "life-physical"], categoryIdentity["single-cell"].icon);
subjects(["ai-ml", "neuroscience"], categoryIdentity["ml-ai"].icon);
subjects(["algorithms"], '<path d="M9 2h6v4H9Zm3 4v4M7 14l5-4 5 4-5 4Zm0 0H3v6h5m9-6h4v6h-5"/>');
subjects(["systems", "networks", "discrete-foundations", "bioprocesses", "health-services"], categoryIdentity.systems.icon);
subjects(["software", "scientific-computing", "computational-physics"], categoryIdentity["tools-infra"].icon);
subjects(["organic", "polymer-materials", "chemical-physics"], categoryIdentity.metabolomics.icon);
subjects(["data", "observational-data", "information"], '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>');
subjects(["privacy-security", "immunity"], '<path d="m12 2 8 4v5c0 5-4 8-8 11-4-3-8-6-8-11V6Zm-4 9 3 3 5-6"/>');
subjects(["optics", "analytical", "measurement", "diagnostic-research"], '<path d="M2 14h6l4-9 6 14H7l2-5m6-3 7-5m-6 8 6-1"/>');
subjects(["condensed-matter", "materials", "manufacturing-materials", "inorganic", "geometry-topology"], fieldIcons.materials);
subjects(["quantum", "atomic-molecular", "particle", "nuclear"], atom);
subjects(["cosmology", "galactic", "planetary"], fieldIcons.astronomy);
subjects(["stellar", "high-energy-astro"], '<path d="m12 2 2.4 6.5L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.5ZM19 2v4m-2-2h4"/>');
subjects(["oceans", "fluids", "freshwater", "fisheries", "soft-matter"], '<path d="M2 7q3-4 6 0t6 0 8 0M2 12q3-4 6 0t6 0 8 0M2 17q3-4 6 0t6 0 8 0"/>');
subjects(["geology", "earth-physics"], '<path d="m2 19 7-13 5 9 3-5 5 9Zm5-9 2 2 2-2"/>');
subjects(["atmosphere", "climate"], '<path d="M6 17a4 4 0 0 1 0-8 6 6 0 0 1 12-1 4.5 4.5 0 0 1 0 9Zm1 4 1-2m5 2 1-2"/>');
subjects(["crops-soils", "plants", "ecology", "forestry", "conservation"], fieldIcons["agriculture-food-veterinary"]);
subjects(["statistical", "statistical-methodology", "probability", "population-health"], '<path d="M3 20V4m0 16h18M6 17c3 0 2-11 6-11s3 11 8 11"/>');
subjects(["number-theory", "algebra"], '<path d="m9 3-3 18m12-18-3 18M4 9h17M3 15h17"/>');
subjects(["numerical-analysis", "quantitative", "analysis", "nonlinear"], fieldIcons.math);
subjects(["electrical-control", "plasmas"], fieldIcons.energy);
subjects(["clinical-research", "medical-devices", "animal-health"], fieldIcons["medicine-health"]);
export function categoryStyle(slug: string, field: CardField = "computational") {
  if (field === "computational") return categoryIdentity[slug] ?? fallback;
  const hue = [...slug].reduce((value, c) => (value * 31 + c.charCodeAt(0)) % 360, 0);
  return { icon: subjectIcons[slug] ?? fieldIcons[field], hue };
}
export const categoryIcon = (slug: string) => categoryStyle(slug).icon;
export const rankMedal = (rank: number) => ["🥇", "🥈", "🥉"][rank - 1] ?? String(rank);
