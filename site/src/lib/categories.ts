// Category identity is shared by every view; labels come from the taxonomy.
export const categoryIdentity: Record<string, { emoji: string; hue: number }> = {
  genomics: { emoji: "🧬", hue: 150 },
  transcriptomics: { emoji: "🧵", hue: 200 },
  proteomics: { emoji: "🧩", hue: 280 },
  metabolomics: { emoji: "⚗️", hue: 60 },
  epigenomics: { emoji: "🎚️", hue: 320 },
  "single-cell": { emoji: "🫧", hue: 190 },
  structural: { emoji: "🧊", hue: 240 },
  systems: { emoji: "🕸️", hue: 120 },
  "ml-ai": { emoji: "🤖", hue: 270 },
  "tools-infra": { emoji: "🧰", hue: 30 },
  industry: { emoji: "🏢", hue: 350 },
};
export const categoryStyle = (slug: string) => categoryIdentity[slug] ?? { emoji: "🔬", hue: 0 };
export const rankMedal = (rank: number) => ["🥇", "🥈", "🥉"][rank - 1] ?? String(rank);
