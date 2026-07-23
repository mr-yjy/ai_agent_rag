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

  // New LLM-enhanced fields (optional, available in live mode)
  researchTopic?: string;
  methods?: string[];
  datasets?: string[];
  domains?: string[];
  venues?: string[];
  optimizedQueries?: string[];
  intentCategory?: string;
  confidence?: number;
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

export interface SearchRound {
  roundNumber: number;
  queriesUsed: string[];
  papersFound: number;
  papersAdded: number;
  apiCalls: number;
  elapsedMs: number;
  strategy: "initial" | "refinement" | "citation_expansion";
}

export interface SearchStats {
  elapsedMs: number;
  apiCalls: number;
  subqueryCount: number;
  candidateCount: number;
  deduplicatedCount: number;
  tokenEstimate: number;
  cacheHits: number;
  searchRounds?: SearchRound[];
  searchStrategy?: string;
}

export interface SearchResponse {
  mode: SearchMode;
  provider: string;
  warning?: string;
  plan: QueryPlan;
  results: RankedPaper[];
  stats: SearchStats;
}

export interface PaperCluster {
  label: string;
  papers: RankedPaper[];
}

export interface TimelinePoint {
  year: number;
  papers: RankedPaper[];
}
