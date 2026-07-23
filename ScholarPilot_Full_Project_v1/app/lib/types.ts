export type SearchMode = "demo" | "live";

export interface Paper {
  id: string;
  title: string;
  abstract: string;
  year: number;
  authors: string[];
  venue: string;
  citedByCount: number;
  url: string;
  doi?: string;
  openAccess: boolean;
  referencedWorks: string[];
  concepts: string[];
}

export interface QueryPlan {
  originalQuery: string;
  normalizedQuery: string;
  yearFrom?: number;
  yearTo?: number;
  mustHave: string[];
  preferred: string[];
  exclude: string[];
  subqueries: string[];
}

export interface ScoreBreakdown {
  relevance: number;
  constraints: number;
  authority: number;
  recency: number;
  openness: number;
}

export interface RankedPaper extends Paper {
  rank: number;
  score: number;
  level: "高度相关" | "部分相关" | "探索性";
  evidence: string;
  matchedTerms: string[];
  scoreBreakdown: ScoreBreakdown;
}

export interface SearchStats {
  elapsedMs: number;
  apiCalls: number;
  subqueryCount: number;
  candidateCount: number;
  deduplicatedCount: number;
  tokenEstimate: number;
  cacheHits: number;
}

export interface SearchResponse {
  mode: SearchMode;
  provider: string;
  warning?: string;
  plan: QueryPlan;
  results: RankedPaper[];
  stats: SearchStats;
}

