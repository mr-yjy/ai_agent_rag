import { DEMO_PAPERS } from "./demo-data";
import type {
  Paper,
  QueryPlan,
  RankedPaper,
  ScoreBreakdown,
  SearchResponse,
} from "./types";

const TERM_MAP: Array<[RegExp, string]> = [
  [/论文检索|学术检索|文献检索/g, "academic paper search"],
  [/智能体|代理系统/g, "LLM agent"],
  [/查询分解|问题分解/g, "query decomposition"],
  [/查询改写|查询重写/g, "query reformulation"],
  [/引文|引用网络/g, "citation expansion"],
  [/检索增强生成|检索增强|RAG/gi, "retrieval augmented generation RAG"],
  [/重排序|重排/g, "reranking"],
  [/召回率/g, "recall"],
  [/精确率|准确率/g, "precision"],
  [/科学研究|科研/g, "scientific research"],
  [/大语言模型|大模型/g, "large language model"],
  [/反事实/g, "counterfactual"],
  [/零知识证明/g, "zero knowledge proof"],
  [/隐私保护/g, "privacy preserving"],
];

const STOP_WORDS = new Set([
  "the", "and", "for", "with", "from", "that", "this",
  "after", "before", "find", "paper", "papers", "study",
  "studies", "using", "use", "about",
  "面向", "研究", "论文", "寻找", "检索", "使用", "相关",
]);

function unique<T>(items: T[]): T[] {
  return [...new Set(items)];
}

function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

function normalizeChineseQuery(query: string): string {
  let normalized = query;
  for (const [pattern, replacement] of TERM_MAP) {
    normalized = normalized.replace(pattern, ` ${replacement} `);
  }
  return normalized.replace(/\s+/g, " ").trim();
}

function tokenize(text: string): string[] {
  const lowered = text.toLowerCase();
  const english = lowered.match(/[a-z][a-z0-9-]{1,}/g) ?? [];
  const chineseBlocks = lowered.match(/[㐀-鿿]{2,}/g) ?? [];
  const chineseBigrams: string[] = [];
  for (const block of chineseBlocks) {
    for (let index = 0; index < block.length - 1; index += 1) {
      chineseBigrams.push(block.slice(index, index + 2));
    }
  }
  return unique(
    [...english, ...chineseBigrams].filter(
      (token) => !STOP_WORDS.has(token) && token.length > 1,
    ),
  );
}

export function buildQueryPlan(query: string): QueryPlan {
  const normalizedQuery = normalizeChineseQuery(query);
  const years = unique(
    (query.match(/\b20\d{2}\b/g) ?? []).map((value) => Number(value)),
  ).sort((a, b) => a - b);
  const tokens = tokenize(normalizedQuery);

  const mustHave = unique(
    TERM_MAP.filter(([pattern]) => {
      pattern.lastIndex = 0;
      return pattern.test(query);
    }).map(([, replacement]) => replacement.split(" ")[0]),
  ).slice(0, 5);

  const preferred: string[] = [];
  if (/代码|开源|github/i.test(query)) preferred.push("open source");
  if (/实验|benchmark|评测/i.test(query)) preferred.push("evaluation");
  if (/最新|近期|近年/i.test(query)) preferred.push("recent");

  const exclude: string[] = [];
  const excludeMatch = query.match(/(?:排除|不要|不包括)\s*([^，。；;]+)/);
  if (excludeMatch?.[1]) exclude.push(excludeMatch[1].trim());

  const keyTerms = tokens.slice(0, 10).join(" ");
  const methodTerms = unique(
    TERM_MAP.filter(([, replacement]) =>
      normalizedQuery.toLowerCase().includes(replacement.toLowerCase()),
    ).map(([, replacement]) => replacement),
  );

  // Simple LLM-like analysis extraction (for frontend demo)
  const methods = methodTerms.slice(0, 3);
  const domains = query.includes("科研") || query.includes("学术")
    ? ["学术研究"]
    : [];
  const researchTopic = normalizedQuery.split(" ").slice(0, 6).join(" ") || normalizedQuery;

  const subqueries = unique(
    [
      normalizedQuery,
      methodTerms.join(" "),
      `academic paper search ${keyTerms}`,
    ]
      .map((item) => item.trim())
      .filter((item) => item.length >= 4),
  ).slice(0, 3);

  return {
    originalQuery: query,
    normalizedQuery,
    yearFrom: years[0],
    yearTo: years.length > 1 ? years[years.length - 1] : undefined,
    mustHave,
    preferred,
    exclude,
    subqueries,
    // Enhanced fields
    researchTopic: researchTopic.length > 5 ? researchTopic : undefined,
    methods: methods.length > 0 ? methods : undefined,
    domains: domains.length > 0 ? domains : undefined,
    intentCategory: methodTerms.includes("query decomposition") ? "method_comparison" : "literature_survey",
    confidence: 0.3,
  };
}

function calculateOverlap(queryTokens: string[], textTokens: string[]): number {
  if (!queryTokens.length || !textTokens.length) return 0;
  const textSet = new Set(textTokens);
  const matched = queryTokens.filter((token) => textSet.has(token)).length;
  return matched / Math.sqrt(queryTokens.length * textSet.size);
}

function sentenceEvidence(text: string, matchedTerms: string[]): string {
  if (!text) return "该记录没有可用摘要，当前评分主要依据标题和元数据。";
  const sentences = text.split(/(?<=[.!?。！？])\s+/);
  const best =
    sentences
      .map((sentence) => ({
        sentence,
        hits: matchedTerms.filter((term) =>
          sentence.toLowerCase().includes(term.toLowerCase()),
        ).length,
      }))
      .sort((a, b) => b.hits - a.hits)[0]?.sentence ?? text;
  return best.length > 220 ? `${best.slice(0, 217)}...` : best;
}

function baseScore(paper: Paper, plan: QueryPlan) {
  const queryTokens = tokenize(plan.normalizedQuery);
  const titleTokens = tokenize(paper.title);
  const bodyTokens = tokenize(
    `${paper.title} ${paper.abstract} ${paper.concepts.join(" ")}`,
  );
  const titleOverlap = calculateOverlap(queryTokens, titleTokens);
  const bodyOverlap = calculateOverlap(queryTokens, bodyTokens);
  const matchedTerms = queryTokens.filter((token) =>
    bodyTokens.includes(token),
  );
  const relevance = clamp(titleOverlap * 1.7 + bodyOverlap * 1.3);

  const yearPass =
    (!plan.yearFrom || paper.year >= plan.yearFrom) &&
    (!plan.yearTo || paper.year <= plan.yearTo);
  const methodCoverage = plan.mustHave.length
    ? plan.mustHave.filter((term) =>
        `${paper.title} ${paper.abstract} ${paper.concepts.join(" ")}`
          .toLowerCase()
          .includes(term.toLowerCase()),
      ).length / plan.mustHave.length
    : 1;
  const constraints = clamp(methodCoverage * 0.7 + (yearPass ? 0.3 : 0));
  const authority = clamp(Math.log10(paper.citedByCount + 1) / 3);
  const recency = clamp((paper.year - 2019) / 7);
  const openness = paper.openAccess ? 1 : 0;
  const breakdown: ScoreBreakdown = {
    relevance,
    constraints,
    authority,
    recency,
    openness,
  };

  const score =
    (relevance * 0.55 +
      constraints * 0.2 +
      authority * 0.1 +
      recency * 0.1 +
      openness * 0.05) *
    100;

  return { score, breakdown, matchedTerms };
}

function jaccard(left: string[], right: string[]): number {
  const a = new Set(left);
  const b = new Set(right);
  const intersection = [...a].filter((item) => b.has(item)).length;
  const union = new Set([...a, ...b]).size;
  return union ? intersection / union : 0;
}

export function rankPapers(
  papers: Paper[],
  plan: QueryPlan,
  limit = 10,
): RankedPaper[] {
  const candidates = papers
    .filter((paper) => {
      const haystack = `${paper.title} ${paper.abstract}`.toLowerCase();
      return !plan.exclude.some((term) =>
        haystack.includes(term.toLowerCase()),
      );
    })
    .map((paper) => ({ paper, ...baseScore(paper, plan) }))
    .sort((a, b) => b.score - a.score);

  const selected: typeof candidates = [];
  while (candidates.length && selected.length < limit) {
    let bestIndex = 0;
    let bestMmr = -Infinity;
    candidates.forEach((candidate, index) => {
      const tokens = tokenize(
        `${candidate.paper.title} ${candidate.paper.abstract}`,
      );
      const redundancy = selected.length
        ? Math.max(
            ...selected.map((picked) =>
              jaccard(
                tokens,
                tokenize(`${picked.paper.title} ${picked.paper.abstract}`),
              ),
            ),
          )
        : 0;
      const mmr = candidate.score - redundancy * 8;
      if (mmr > bestMmr) {
        bestMmr = mmr;
        bestIndex = index;
      }
    });
    selected.push(candidates.splice(bestIndex, 1)[0]);
  }

  return selected.map(({ paper, score, breakdown, matchedTerms }, index) => {
    const roundedScore = Math.round(score * 10) / 10;
    return {
      ...paper,
      rank: index + 1,
      score: roundedScore,
      level:
        roundedScore >= 62
          ? "高度相关"
          : roundedScore >= 42
            ? "部分相关"
            : "探索性",
      evidence: sentenceEvidence(paper.abstract, matchedTerms),
      matchedTerms: matchedTerms.slice(0, 6),
      scoreBreakdown: breakdown,
    };
  });
}

export function runDemoSearch(query: string): SearchResponse {
  const started = performance.now();
  const plan = buildQueryPlan(query);
  const papers = DEMO_PAPERS;
  const ranked = rankPapers(DEMO_PAPERS, plan, 10);
  const elapsedMs = Math.max(12, Math.round(performance.now() - started));

  return {
    mode: "demo",
    provider: "内置比赛演示数据",
    plan,
    results: ranked,
    stats: {
      elapsedMs,
      apiCalls: 0,
      subqueryCount: plan.subqueries.length,
      candidateCount: papers.length,
      deduplicatedCount: papers.length,
      tokenEstimate: Math.round(
        plan.subqueries.join(" ").length / 3.2 + papers.length * 5,
      ),
      cacheHits: 1,
      searchRounds: undefined,
    },
  };
}
