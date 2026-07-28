export type SearchStatus = "success" | "no_results" | "degraded";

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
  sources?: string[];
  retrievalRoutes?: string[];
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
  constraintGroups?: string[][];

  // LLM-enhanced fields are optional because rule planning is the fallback.
  researchTopic?: string;
  methods?: string[];
  tasks?: string[];
  datasets?: string[];
  domains?: string[];
  venues?: string[];
  optimizedQueries?: string[];
  intentCategory?: string;
  confidence?: number;
  retrievalPreference?: "precision" | "balanced" | "recall";
}

export interface ScoreBreakdown {
  relevance: number;
  constraints: number;
  authority: number;
  recency: number;
  openness: number;
  evidenceQuality?: number;
  sourceConsistency?: number;
}

export interface RankedPaper extends Paper {
  rank: number;
  score: number;
  level: "高度相关" | "部分相关" | "探索性";
  evidence: string;
  evidenceSource?: "abstract" | "title" | "metadata" | "insufficient";
  evidenceInsufficient?: boolean;
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
  strategy:
    | "initial"
    | "refinement"
    | "citation_expansion"
    | "causal_trust_recovery";
  stopReason?: string;
}

export interface SourceStatus {
  source: string;
  status:
    | "success"
    | "partial"
    | "failed"
    | "timeout"
    | "rate_limited"
    | "cancelled";
  round?: number;
  apiCalls: number;
  cacheHits?: number;
  resultCount: number;
  elapsedMs?: number;
  retryable?: boolean;
  retryAfterSeconds?: number;
}

export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  estimatedTokens: number;
}

export interface SearchStats {
  elapsedMs: number;
  apiCalls: number;
  subqueryCount: number;
  candidateCount: number;
  deduplicatedCount: number;
  tokenEstimate: number;
  cacheHits: number;
  llmCalls?: number;
  llmRequestAttempts?: number;
  searchRounds?: SearchRound[];
  searchStrategy?: string;
  stageTimings: Record<string, number>;
  tokenUsage: TokenUsage;
  stopReason: string;
  budgetRemainingMs: number;
  configHash: string;
}

export type ReliabilityDecision =
  | "ACCEPT"
  | "RETRY_RETRIEVAL"
  | "RETRY_REASONING"
  | "ABSTAIN"
  | "NOT_RUN";

export interface ReliabilityCandidate {
  id: string;
  value: string;
  response: string;
  evidenceIds: string[];
  producedBy: string[];
  meanSupport: number;
  instability: number;
  cci: number;
  interventionScores: Record<string, number>;
}

export interface ReliabilityResult {
  status: "completed" | "skipped" | "failed";
  answer: string;
  confidence: number;
  decision: ReliabilityDecision;
  message: string;
  reason?: string;
  selectedCandidateId?: string;
  diagnosis?: {
    evidenceRisk: number;
    reasoningRisk: number;
    recommendedRecovery: string;
  };
  candidates?: ReliabilityCandidate[];
  recovery?: {
    attempted: boolean;
    mode: string;
    attempts: number;
    recovered: boolean;
  };
  trace?: {
    queryId: string;
    evidenceIds: string[];
    passes: unknown[];
    selected: string;
    decision: ReliabilityDecision;
    latencyMs: number;
  };
}

export interface SearchResponse {
  schemaVersion: "1.0";
  requestId: string;
  status: SearchStatus;
  degraded: boolean;
  provider: string;
  warning?: string;
  queryPlan: QueryPlan;
  plan: QueryPlan;
  results: RankedPaper[];
  sourceStatus: SourceStatus[];
  stats: SearchStats;
  reliability?: ReliabilityResult;
  degradationReasons?: string[];
  recoveryActions?: string[];
}

export interface ApiError {
  code: string;
  message: string;
  requestId: string;
  retryable: boolean;
  retryAfterSeconds: number;
  stage?: string;
  upstreamStatus?: number;
}

export interface ApiErrorResponse {
  error: ApiError;
}

export interface PaperCluster {
  label: string;
  papers: RankedPaper[];
}

export interface TimelinePoint {
  year: number;
  papers: RankedPaper[];
}
