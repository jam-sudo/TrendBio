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
export const categoryStyle = (slug: string) => categoryIdentity[slug] ?? fallback;
export const categoryIcon = (slug: string) => categoryStyle(slug).icon;
export const rankMedal = (rank: number) => ["🥇", "🥈", "🥉"][rank - 1] ?? String(rank);
