// Mirrors pipeline/models.py. Dates and datetimes are ISO 8601 strings.
export type ItemType = "published" | "preprint" | "code" | "industry";
export type Source = "biorxiv" | "arxiv" | "pubmed" | "github" | "rss";

export interface Item {
  id: string;
  source: Source;
  type: ItemType;
  title: string;
  url: string;
  doi: string | null;
  published_at: string;
  first_seen: string;
  authors: string[];
  org: string | null;
  abstract: string;
  summary: string | null;
  primary_category: string | null;
  secondary_categories: string[];
  published_doi: string | null;
  preprint_id: string | null;
  metadata: Record<string, unknown>;
}

export interface Signals {
  published: number;
  preprint: number;
  code: number;
  industry: number;
  rise_ratio: number;
  star_gain_7d: number;
}

export interface Scores {
  rise: number;
  diversity: number;
  code_velocity: number;
  volume: number;
  penalty: number;
  total: number;
}

export interface TopicDay {
  date: string;
  rank: number | null;
  item_ids: string[];
  count_7d: number;
  signals: Signals;
  scores: Scores;
}

export interface Topic {
  slug: string;
  label: string;
  category: string;
  secondary_categories: string[];
  centroid: number[];
  history: TopicDay[];
  headline: string | null;
  summary: string | null;
  synthesis: string | null;
  synthesis_model: string | null;
  synthesized_on: string | null;
  item_one_liners: Record<string, string>;
  related: string[];
}

export interface RankedTopic {
  slug: string;
  rank: number;
  headline: string;
  summary: string;
  category: string;
  signals: Signals;
  scores: Scores;
}

export interface RunInfo {
  started: string;
  finished: string;
  status: "ok" | "degraded";
  backfilled: boolean;
  synthesis_model: string;
  source_status: Record<string, "ok" | "failed" | "skipped">;
  notes: string[];
}

export interface Day {
  domain: string;
  date: string;
  ranked: RankedTopic[];
  run: RunInfo;
}
