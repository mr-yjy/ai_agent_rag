"""Iterative Search Agent for academic paper retrieval.

Implements a multi-round search strategy inspired by SPAR's query evolution
and PaSa's crawler-selector architecture:

1. **Planning**: Generates initial search queries from analyzed query
2. **Retrieval**: Executes parallel searches via OpenAlex (and optionally Semantic Scholar)
3. **Filtering**: LLM-based relevance filtering of retrieved papers
4. **Citation Expansion**: Follows citation links from high-relevance papers
5. **Iteration**: Refines search queries based on discovered papers
6. **B budget Control**: Stops when convergence or budget exhausted

Usage:
    agent = SearchAgent()
    results = await agent.search(analyzed_query)
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .config import get_config
from .identity import upsert_paper
from .llm_client import LLMClient, LLMError, create_llm_client
from .models import Paper, QueryPlan
from .providers import OpenAlexProvider, ProviderError
from .query_analyzer import AnalyzedQuery
from .semantic_scholar import SemanticScholarProvider


@dataclass(slots=True)
class SearchRound:
    """Record of one search round."""

    round_number: int
    queries_used: list[str]
    papers_found: int
    papers_added: int
    api_calls: int
    elapsed_ms: int
    strategy: str  # "initial" | "refinement" | "citation_expansion"
    stop_reason: str | None = None

    def to_api(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "roundNumber": self.round_number,
            "queriesUsed": self.queries_used,
            "papersFound": self.papers_found,
            "papersAdded": self.papers_added,
            "apiCalls": self.api_calls,
            "elapsedMs": self.elapsed_ms,
            "strategy": self.strategy,
        }
        if self.stop_reason:
            payload["stopReason"] = self.stop_reason
        return payload


@dataclass(slots=True)
class SearchResult:
    """Final aggregated search result."""

    papers: list[Paper]
    rounds: list[SearchRound] = field(default_factory=list)
    total_api_calls: int = 0
    total_cache_hits: int = 0
    total_elapsed_ms: int = 0
    token_estimate: int = 0
    retrieved_candidate_count: int = 0


# LLM Prompt for paper relevance filtering
RELEVANCE_FILTER_PROMPT = """你是一位论文检索专家。请评估以下论文是否与用户的搜索查询相关。

用户查询: {query}

论文标题: {title}
论文摘要: {abstract}
论文关键词: {concepts}
年份: {year}

请从以下维度评估，并以JSON格式输出：
{{
  "is_relevant": true/false,
  "relevance_score": 0-100,
  "reason": "一句话说明判断理由",
  "relevance_aspects": {{
    "topic_match": 0-100,
    "method_match": 0-100,
    "domain_match": 0-100
  }}
}}

如果论文完全跑题或质量太低（无摘要、无引用、非学术），is_relevant设为false。"""


# LLM Prompt for search query refinement
QUERY_REFINEMENT_PROMPT = """你是一位学术搜索策略专家。基于已找到的相关论文，请生成新的搜索查询来找到更多相关论文。

原始查询: {original_query}

已找到的高相关论文:
{found_papers}

当前搜索中缺失的方面（如果有）:
{gaps}

请生成2-3个新的搜索查询来填补这些缺口。以JSON格式输出：
{{
  "new_queries": ["查询1", "查询2", "查询3"],
  "strategy": "说明你的搜索策略调整思路",
  "identified_gaps": ["缺口1", "缺口2"]
}}"""


BATCH_RELEVANCE_FILTER_PROMPT = """你是学术检索 Selector。判断候选论文与用户查询是否相关。
只依据标题、摘要和关键词，不得根据常识补全缺失证据。

用户查询: {query}

候选论文(JSON):
{papers}

输出 JSON 数组，每篇恰好一个对象：
[
  {{"index": 0, "is_relevant": true, "relevance_score": 0-100}}
]
只输出 JSON。"""


class RelevanceFilter:
    """LLM-based paper relevance filter.

    Rejects irrelevant or low-quality papers before they enter the candidate pool.
    Implements PaSa's Selector concept with a learned (LLM-as-judge) approach.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm = llm_client or create_llm_client()
        self.use_llm = bool(self.llm.config.api_key)
        strategy = get_config().strategy
        self.batch_size = strategy.selector_batch_size
        self.max_papers = strategy.selector_max_papers
        # Cache of (title/query hash -> relevance, score) to avoid re-judging.
        self._cache: dict[int, tuple[bool, float]] = {}

    def filter_papers(
        self,
        papers: list[Paper],
        query: str,
        min_score: float = 20.0,
    ) -> list[Paper]:
        """Use a recall-safe lexical stage followed by a batched LLM Selector."""
        shortlist = self._keyword_filter(papers, query, min_score)
        if not self.use_llm or not shortlist:
            return shortlist
        return self._llm_filter(shortlist[: self.max_papers], query, min_score)

    def _keyword_filter(
        self, papers: list[Paper], query: str, min_score: float
    ) -> list[Paper]:
        """Rank candidates with normalized bilingual terms before filtering."""
        from .planner import build_query_plan, normalize_query, tokenize

        plan = build_query_plan(query)
        query_tokens = set(tokenize(normalize_query(query)))
        if not query_tokens:
            return papers

        scored: list[tuple[float, Paper]] = []
        for paper in papers:
            text = paper.searchable_text().casefold()
            paper_tokens = set(tokenize(text))
            matches = len(query_tokens & paper_tokens)
            cosine = matches / max(
                1.0, (len(query_tokens) * max(len(paper_tokens), 1)) ** 0.5
            )
            concept_coverage = (
                sum(term.casefold() in text for term in plan.must_have)
                / len(plan.must_have)
                if plan.must_have
                else 0.0
            )
            score = (
                concept_coverage * 0.65 + min(1.0, cosine * 3.0) * 0.35
            ) * 100
            if score >= min_score:
                scored.append((score, paper))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [paper for _, paper in scored]

    def _llm_filter(
        self, papers: list[Paper], query: str, min_score: float
    ) -> list[Paper]:
        """Batched LLM filtering; malformed batches fail open for recall."""
        filtered: list[Paper] = []
        uncached: list[Paper] = []
        for paper in papers:
            cache_key = hash((paper.title.casefold(), query.casefold()))
            cached = self._cache.get(cache_key)
            if cached is None:
                uncached.append(paper)
            elif cached[0] and cached[1] >= min_score:
                filtered.append(paper)

        for start in range(0, len(uncached), self.batch_size):
            batch = uncached[start : start + self.batch_size]
            judgments = self._judge_batch(batch, query)
            for paper, judgment in zip(batch, judgments):
                cache_key = hash((paper.title.casefold(), query.casefold()))
                self._cache[cache_key] = judgment
                if judgment[0] and judgment[1] >= min_score:
                    filtered.append(paper)
        return filtered

    def _judge_batch(
        self, papers: list[Paper], query: str
    ) -> list[tuple[bool, float]]:
        payload = [
            {
                "index": index,
                "title": paper.title,
                "abstract": paper.abstract[:450],
                "concepts": paper.concepts[:5],
                "year": paper.year,
            }
            for index, paper in enumerate(papers)
        ]
        prompt = BATCH_RELEVANCE_FILTER_PROMPT.format(
            query=query,
            papers=json.dumps(payload, ensure_ascii=False),
        )
        try:
            response = self.llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.05,
                max_tokens=max(512, len(papers) * 80),
            )
            match = re.search(r"\[.*\]", response.content, re.DOTALL)
            data = json.loads(match.group(0) if match else "[]")
            by_index = {
                int(item.get("index", -1)): (
                    bool(item.get("is_relevant", False)),
                    float(item.get("relevance_score", 0)),
                )
                for item in data
                if isinstance(item, dict)
            }
            return [by_index.get(index, (True, 50.0)) for index in range(len(papers))]
        except (json.JSONDecodeError, LLMError, KeyError, TypeError, ValueError):
            return [(True, 50.0) for _ in papers]


@dataclass(slots=True)
class CitationExpansionResult:
    papers: list[Paper]
    api_calls: int
    elapsed_ms: int


class CitationExpander:
    """Citation graph explorer.

    Given high-relevance papers, follows their reference lists
    to discover additional relevant papers.
    """

    def __init__(self, openalex: OpenAlexProvider | None = None) -> None:
        self.openalex = openalex or OpenAlexProvider()
        self._fetched: set[str] = set()

    def expand(
        self,
        seed_papers: list[Paper],
        max_per_paper: int = 5,
        max_api_calls: int = 1,
    ) -> CitationExpansionResult:
        """Expand by fetching referenced works from seed papers."""
        started = time.perf_counter()
        target_ids: list[str] = []
        for paper in seed_papers:
            count = 0
            for ref_id in paper.referenced_works:
                if ref_id not in self._fetched:
                    target_ids.append(ref_id)
                    self._fetched.add(ref_id)
                    count += 1
                    if count >= max_per_paper:
                        break

        if not target_ids:
            return CitationExpansionResult([], 0, 0)

        papers, api_calls = self._fetch_by_ids(
            target_ids, max_api_calls=max_api_calls
        )
        return CitationExpansionResult(
            papers=papers,
            api_calls=api_calls,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    def _fetch_by_ids(
        self, ids: list[str], max_api_calls: int
    ) -> tuple[list[Paper], int]:
        """Fetch papers by OpenAlex IDs."""
        results: list[Paper] = []
        api_calls = 0
        # Batch requests to avoid too many calls
        batch_size = 25
        for offset in range(0, len(ids), batch_size):
            if api_calls >= max_api_calls:
                break
            batch = [
                value.rstrip("/").rsplit("/", 1)[-1]
                for value in ids[offset : offset + batch_size]
            ]
            try:
                parameters = {
                    "filter": f"openalex:{'|'.join(batch)}",
                    "select": (
                        "id,doi,title,publication_year,abstract_inverted_index,"
                        "authorships,cited_by_count,primary_location,open_access,"
                        "referenced_works,topics"
                    ),
                }
                if self.openalex.api_key:
                    parameters["api_key"] = self.openalex.api_key
                url = (
                    "https://api.openalex.org/works?"
                    + urllib.parse.urlencode(parameters)
                )
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "ScholarPilot/0.4 (competition)"},
                )
                api_calls += 1
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.load(resp)
                for work in data.get("results", []):
                    paper = self.openalex._map_work(work)  # type: ignore[attr-defined]
                    paper.retrieval_routes = list(
                        dict.fromkeys(
                            [*paper.retrieval_routes, "citation_backward"]
                        )
                    )
                    results.append(paper)
            except Exception:
                continue
        return results, api_calls


class SearchAgent:
    """Autonomous search agent with iterative refinement and dual-source retrieval.

    Architecture inspired by SPAR (query evolution via RefChain) and
    PaSa (crawler for broad retrieval, selector for filtering).

    Key improvements over v1:
    - Dual-source retrieval: OpenAlex + Semantic Scholar for higher recall
    - Each sub-query is sent to both sources; results are merged and deduplicated
    - Source tracking: each paper records which provider(s) returned it
    """

    def __init__(
        self,
        openalex_provider: OpenAlexProvider | None = None,
        semantic_scholar_provider: SemanticScholarProvider | None = None,
        llm_client: LLMClient | None = None,
        relevance_filter: RelevanceFilter | None = None,
        citation_expander: CitationExpander | None = None,
        use_dual_source: bool = True,
    ) -> None:
        self.config = get_config().strategy
        self.openalex = openalex_provider or OpenAlexProvider()
        self.llm = llm_client or create_llm_client()
        self.filter = relevance_filter or RelevanceFilter(self.llm)
        self.expander = citation_expander or CitationExpander(self.openalex)
        self.use_llm = bool(self.llm.config.api_key)

        # Dual-source retrieval (OpenAlex + Semantic Scholar)
        self.use_dual_source = use_dual_source
        if use_dual_source:
            try:
                self.semantic_scholar = semantic_scholar_provider or SemanticScholarProvider()
            except Exception:
                self.use_dual_source = False
                self.semantic_scholar = None
        else:
            self.semantic_scholar = None

    def search(self, analyzed_query: AnalyzedQuery) -> SearchResult:
        """Execute multi-round iterative search based on analyzed query.

        Args:
            analyzed_query: The output of QueryAnalyzer.analyze()

        Returns:
            SearchResult with aggregated papers and search metadata.
        """
        started = time.perf_counter()
        all_papers: dict[str, Paper] = {}
        rounds: list[SearchRound] = []
        total_api_calls = 0
        total_cache_hits = 0
        retrieved_candidate_count = 0
        query_text = analyzed_query.original_query

        def add_candidate(paper: Paper) -> bool:
            before = len(all_papers)
            added = upsert_paper(all_papers, paper)
            if added and before >= self.config.max_total_papers:
                all_papers.popitem()
                return False
            return added

        # ---- Round 1: complementary query routes within a hard API budget ----
        initial_queries = (
            analyzed_query.optimized_queries
            or analyzed_query.sub_queries
            or [analyzed_query.normalized_query or query_text]
        )
        round1_result = self._execute_search_round(
            queries=initial_queries,
            analyzed_query=analyzed_query,
            max_api_calls=min(
                self.config.max_api_calls_per_round,
                self.config.max_total_api_calls,
            ),
        )
        total_api_calls += round1_result.api_calls
        total_cache_hits += round1_result.cache_hits
        retrieved_candidate_count += round1_result.candidate_count
        round1_added = sum(add_candidate(paper) for paper in round1_result.papers)
        rounds.append(
            SearchRound(
                round_number=1,
                queries_used=round1_result.queries_used,
                papers_found=round1_result.candidate_count,
                papers_added=round1_added,
                api_calls=round1_result.api_calls,
                elapsed_ms=round1_result.elapsed_ms,
                strategy="initial",
            )
        )

        heuristic_plan = QueryPlan(
            original_query=query_text,
            normalized_query=analyzed_query.normalized_query,
            year_from=analyzed_query.year_from,
            year_to=analyzed_query.year_to,
            must_have=analyzed_query.must_have,
            preferred=analyzed_query.preferred,
            exclude=analyzed_query.exclude,
            subqueries=analyzed_query.sub_queries,
            constraint_groups=analyzed_query.constraint_groups,
            methods=analyzed_query.methods,
            datasets=analyzed_query.datasets,
            domains=analyzed_query.domains,
            venues=analyzed_query.venues,
        )

        # ---- Round 2: one batched backward-citation expansion ----
        remaining_budget = self.config.max_total_api_calls - total_api_calls
        if (
            self.config.enable_citation_expansion
            and all_papers
            and remaining_budget > 0
            and len(rounds) < self.config.max_search_rounds
        ):
            from .ranking import rank_papers

            ranked_seeds = rank_papers(
                list(all_papers.values()), heuristic_plan, limit=15
            )
            seed_papers = [
                item.paper
                for item in ranked_seeds
                if item.score >= 42 and item.paper.referenced_works
            ][:5]
            if seed_papers:
                expansion = self.expander.expand(
                    seed_papers,
                    max_per_paper=self.config.citation_expansion_per_paper,
                    max_api_calls=min(1, remaining_budget),
                )
                total_api_calls += expansion.api_calls
                retrieved_candidate_count += len(expansion.papers)
                relevant_expanded = self.filter.filter_papers(
                    expansion.papers, query_text, min_score=8.0
                )
                expand_added = sum(
                    add_candidate(paper) for paper in relevant_expanded
                )
                rounds.append(
                    SearchRound(
                        round_number=len(rounds) + 1,
                        queries_used=[
                            f"backward citations from {len(seed_papers)} seeds"
                        ],
                        papers_found=len(expansion.papers),
                        papers_added=expand_added,
                        api_calls=expansion.api_calls,
                        elapsed_ms=expansion.elapsed_ms,
                        strategy="citation_expansion",
                    )
                )

        # ---- Final rounds: gap-driven query refinement with convergence stop ----
        while (
            self.use_llm
            and len(all_papers) >= self.config.min_papers_for_iteration
            and len(all_papers) < self.config.max_total_papers
            and len(rounds) < self.config.max_search_rounds
            and total_api_calls < self.config.max_total_api_calls
        ):
            round_number = len(rounds) + 1
            refined_queries = self._generate_refined_queries(
                query_text,
                list(all_papers.values()),
                round_number,
            )
            if not refined_queries:
                break

            remaining_budget = self.config.max_total_api_calls - total_api_calls
            round_result = self._execute_search_round(
                queries=refined_queries,
                analyzed_query=analyzed_query,
                max_api_calls=min(
                    self.config.max_api_calls_per_round, remaining_budget
                ),
            )
            total_api_calls += round_result.api_calls
            total_cache_hits += round_result.cache_hits
            retrieved_candidate_count += round_result.candidate_count
            round_added = sum(
                add_candidate(paper) for paper in round_result.papers
            )
            stop_reason = None
            if round_added < self.config.min_new_papers_to_continue:
                stop_reason = "marginal_yield_below_threshold"
            elif total_api_calls >= self.config.max_total_api_calls:
                stop_reason = "api_budget_exhausted"
            rounds.append(
                SearchRound(
                    round_number=round_number,
                    queries_used=round_result.queries_used,
                    papers_found=round_result.candidate_count,
                    papers_added=round_added,
                    api_calls=round_result.api_calls,
                    elapsed_ms=round_result.elapsed_ms,
                    strategy="refinement",
                    stop_reason=stop_reason,
                )
            )
            if stop_reason:
                break

        elapsed = int((time.perf_counter() - started) * 1000)
        papers_list = list(all_papers.values())
        token_est = sum(
            len(paper.title) + len(paper.abstract) for paper in papers_list
        ) // 3

        return SearchResult(
            papers=papers_list,
            rounds=rounds,
            total_api_calls=total_api_calls,
            total_cache_hits=total_cache_hits,
            total_elapsed_ms=elapsed,
            token_estimate=token_est,
            retrieved_candidate_count=retrieved_candidate_count,
        )

    def _execute_search_round(
        self,
        queries: list[str],
        analyzed_query: AnalyzedQuery,
        max_api_calls: int,
    ) -> "RoundResult":
        """Execute parallel searches across dual sources for a set of queries.

        Each query is sent to both OpenAlex and (if enabled) Semantic Scholar.
        Results are merged and deduplicated by DOI > paper ID > normalized title.
        """
        round_started = time.perf_counter()
        all_papers: dict[str, Paper] = {}
        api_calls = 0
        cache_hits = 0
        candidate_count = 0

        unique_queries = list(
            dict.fromkeys(
                query.strip()
                for query in queries
                if query and len(query.strip()) >= 3
            )
        )
        if not unique_queries or max_api_calls <= 0:
            return RoundResult(
                papers=[],
                api_calls=0,
                cache_hits=0,
                elapsed_ms=0,
                candidate_count=0,
                queries_used=[],
            )

        def make_plan(selected_queries: list[str]) -> QueryPlan:
            return QueryPlan(
                original_query=analyzed_query.original_query,
                normalized_query=analyzed_query.normalized_query,
                year_from=analyzed_query.year_from,
                year_to=analyzed_query.year_to,
                must_have=analyzed_query.must_have,
                preferred=analyzed_query.preferred,
                exclude=analyzed_query.exclude,
                subqueries=selected_queries,
                constraint_groups=analyzed_query.constraint_groups,
                methods=analyzed_query.methods,
                datasets=analyzed_query.datasets,
                domains=analyzed_query.domains,
                venues=analyzed_query.venues,
            )

        jobs: list[tuple[Any, QueryPlan]] = []
        openalex_count = min(
            len(unique_queries),
            (max_api_calls + 1) // 2
            if self.use_dual_source and self.semantic_scholar is not None
            else max_api_calls,
        )
        if openalex_count:
            jobs.append(
                (self.openalex, make_plan(unique_queries[:openalex_count]))
            )
        remaining = max_api_calls - openalex_count
        if (
            remaining > 0
            and self.use_dual_source
            and self.semantic_scholar is not None
        ):
            semantic_count = min(len(unique_queries), remaining)
            jobs.append(
                (
                    self.semantic_scholar,
                    make_plan(unique_queries[:semantic_count]),
                )
            )

        # Independent providers run concurrently; their internal per-provider
        # rate limits still apply.
        with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
            futures = [
                executor.submit(provider.search, plan)
                for provider, plan in jobs
            ]
            for future in futures:
                try:
                    provider_result = future.result()
                except ProviderError as exc:
                    api_calls += exc.api_calls
                    cache_hits += exc.cache_hits
                    continue
                except Exception:
                    continue
                api_calls += provider_result.api_calls
                cache_hits += provider_result.cache_hits
                candidate_count += len(provider_result.papers)
                for paper in provider_result.papers:
                    upsert_paper(all_papers, paper)

        # Apply relevance filtering
        papers_list = list(all_papers.values())
        filtered = self.filter.filter_papers(
            papers_list,
            analyzed_query.original_query,
            min_score=8.0,
        )

        elapsed = int((time.perf_counter() - round_started) * 1000)
        return RoundResult(
            papers=filtered,
            api_calls=api_calls,
            cache_hits=cache_hits,
            elapsed_ms=elapsed,
            candidate_count=candidate_count,
            queries_used=list(
                dict.fromkeys(
                    query
                    for _, plan in jobs
                    for query in plan.subqueries
                )
            ),
        )

    def _generate_refined_queries(
        self,
        original_query: str,
        found_papers: list[Paper],
        round_num: int,
    ) -> list[str]:
        """Use LLM to generate refined search queries."""
        # Format found papers for the prompt
        paper_summaries = []
        for p in found_papers[:5]:
            paper_summaries.append(
                f"- {p.title} ({p.year}) - {p.abstract[:100]}..."
            )

        prompt = QUERY_REFINEMENT_PROMPT.format(
            original_query=original_query,
            found_papers="\n".join(paper_summaries),
            gaps=f"第{round_num}轮迭代：寻找尚未覆盖的研究方向",
        )

        try:
            response = self.llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1024,
            )
            match = re.search(r"\{.*\}", response.content, re.DOTALL)
            json_str = match.group(0) if match else "{}"
            data = json.loads(json_str)
            return data.get("new_queries", [])[:3]
        except (json.JSONDecodeError, LLMError, KeyError):
            return []


@dataclass(slots=True)
class RoundResult:
    papers: list[Paper]
    api_calls: int
    cache_hits: int
    elapsed_ms: int
    candidate_count: int
    queries_used: list[str]
