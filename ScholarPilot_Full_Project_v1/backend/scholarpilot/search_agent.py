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
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import get_config
from .llm_client import LLMClient, create_llm_client
from .models import Paper, QueryPlan
from .providers import OpenAlexProvider
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


@dataclass(slots=True)
class SearchResult:
    """Final aggregated search result."""

    papers: list[Paper]
    rounds: list[SearchRound] = field(default_factory=list)
    total_api_calls: int = 0
    total_cache_hits: int = 0
    total_elapsed_ms: int = 0
    token_estimate: int = 0


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


class RelevanceFilter:
    """LLM-based paper relevance filter.

    Rejects irrelevant or low-quality papers before they enter the candidate pool.
    Implements PaSa's Selector concept with a learned (LLM-as-judge) approach.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm = llm_client or create_llm_client()
        self.use_llm = bool(self.llm.config.api_key)
        # Cache of (title_hash -> relevance) to avoid re-judging
        self._cache: dict[int, bool] = {}

    def filter_papers(
        self,
        papers: list[Paper],
        query: str,
        min_score: float = 20.0,
    ) -> list[Paper]:
        """Filter papers by relevance. Uses LLM when available, falls back to keyword."""
        if not self.use_llm:
            return self._keyword_filter(papers, query, min_score)
        return self._llm_filter(papers, query, min_score)

    def _keyword_filter(
        self, papers: list[Paper], query: str, min_score: float
    ) -> list[Paper]:
        """Quick keyword overlap filter (fallback when no LLM)."""
        from .planner import tokenize

        query_tokens = set(tokenize(query))
        if not query_tokens:
            return papers

        filtered: list[Paper] = []
        for paper in papers:
            text = paper.searchable_text().lower()
            matches = sum(1 for t in query_tokens if t.lower() in text)
            score = matches / len(query_tokens) * 100
            if score >= min_score:
                filtered.append(paper)
        return filtered

    def _llm_filter(
        self, papers: list[Paper], query: str, min_score: float
    ) -> list[Paper]:
        """LLM-based relevance filtering."""
        filtered: list[Paper] = []
        for paper in papers:
            # Check cache
            cache_key = hash((paper.title.lower(), query.lower()))
            if cache_key in self._cache:
                if self._cache[cache_key]:
                    filtered.append(paper)
                continue

            is_rel, score = self._judge_paper(paper, query)
            self._cache[cache_key] = is_rel
            if is_rel and score >= min_score:
                filtered.append(paper)
        return filtered

    def _judge_paper(self, paper: Paper, query: str) -> tuple[bool, float]:
        """Ask LLM to judge a single paper's relevance."""
        prompt = RELEVANCE_FILTER_PROMPT.format(
            query=query,
            title=paper.title,
            abstract=paper.abstract[:500] if paper.abstract else "N/A",
            concepts=", ".join(paper.concepts[:5]),
            year=paper.year,
        )
        try:
            response = self.llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.05,
                max_tokens=512,
            )
            json_str = self._extract_json(response.content)
            data = json.loads(json_str)
            is_rel = data.get("is_relevant", False)
            score = data.get("relevance_score", 0)
            return bool(is_rel), float(score)
        except (json.JSONDecodeError, LLMError, KeyError):
            # Fallback: accept the paper (better to keep than discard on error)
            return True, 50.0

    @staticmethod
    def _extract_json(text: str) -> str:
        import re
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return match.group(0) if match else "{}"


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
    ) -> list[Paper]:
        """Expand by fetching referenced works from seed papers."""
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
            return []

        papers = self._fetch_by_ids(target_ids)
        return papers

    def _fetch_by_ids(self, ids: list[str]) -> list[Paper]:
        """Fetch papers by OpenAlex IDs."""
        results: list[Paper] = []
        # Batch requests to avoid too many calls
        batch_size = 25
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            try:
                url = (
                    f"https://api.openalex.org/works?filter=openalex:{'|'.join(batch)}"
                    f"&select=id,doi,title,publication_year,abstract_inverted_index,"
                    f"authorships,cited_by_count,primary_location,open_access,topics"
                )
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "ScholarPilot/0.2 (competition)"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.load(resp)
                for work in data.get("results", []):
                    papers = self.openalex._map_work(work)  # type: ignore[attr-defined]
                    # _map_work returns a single Paper
                    results.append(papers)
            except Exception:
                continue
        return results


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

        query_text = analyzed_query.original_query

        # ---- Round 1: Initial search with optimized queries ----
        initial_queries = analyzed_query.optimized_queries or analyzed_query.sub_queries
        round1_result = self._execute_search_round(
            queries=initial_queries,
            analyzed_query=analyzed_query,
        )
        total_api_calls += round1_result.api_calls
        total_cache_hits += round1_result.cache_hits
        for p in round1_result.papers:
            key = p.doi or p.id or p.title.casefold()
            all_papers[key] = p

        rounds.append(SearchRound(
            round_number=1,
            queries_used=initial_queries,
            papers_found=len(round1_result.papers),
            papers_added=len(round1_result.papers),
            api_calls=round1_result.api_calls,
            elapsed_ms=round1_result.elapsed_ms,
            strategy="initial",
        ))

        # ---- Round 2: Citation expansion from high-relevance papers ----
        if self.config.enable_citation_expansion and len(all_papers) > 0:
            # Rank current papers by heuristic score and pick top ones for expansion
            papers_list = list(all_papers.values())
            heuristic_plan = QueryPlan(
                original_query=query_text,
                normalized_query=analyzed_query.normalized_query,
                year_from=analyzed_query.year_from,
                year_to=analyzed_query.year_to,
                must_have=analyzed_query.must_have,
                preferred=analyzed_query.preferred,
                exclude=analyzed_query.exclude,
                subqueries=analyzed_query.sub_queries,
            )
            # Use the existing ranking to find high-quality seeds
            from .ranking import rank_papers
            ranked_seeds = rank_papers(
                papers_list, heuristic_plan, limit=5
            )
            seed_papers = [rs.paper for rs in ranked_seeds if rs.score >= 50]

            if seed_papers:
                expanded = self.expander.expand(
                    seed_papers,
                    max_per_paper=self.config.citation_expansion_per_paper,
                )
                expand_added = 0
                for p in expanded:
                    key = p.doi or p.id or p.title.casefold()
                    if key not in all_papers:
                        all_papers[key] = p
                        expand_added += 1

                rounds.append(SearchRound(
                    round_number=2,
                    queries_used=[f"citation expansion from {len(seed_papers)} seeds"],
                    papers_found=len(expanded),
                    papers_added=expand_added,
                    api_calls=len(expanded),  # Rough: one API call per batch
                    elapsed_ms=0,
                    strategy="citation_expansion",
                ))

        # ---- Round 3+: Iterative refinement (if LLM available) ----
        if self.use_llm and len(all_papers) >= self.config.min_papers_for_iteration:
            for round_num in range(2, self.config.max_search_rounds + 1):
                if len(all_papers) >= self.config.max_total_papers:
                    break

                # Generate refined queries based on current findings
                refined_queries = self._generate_refined_queries(
                    query_text,
                    list(all_papers.values()),
                    round_num,
                )
                if not refined_queries:
                    break

                round_result = self._execute_search_round(
                    queries=refined_queries,
                    analyzed_query=analyzed_query,
                )
                total_api_calls += round_result.api_calls
                total_cache_hits += round_result.cache_hits

                round_added = 0
                for p in round_result.papers:
                    key = p.doi or p.id or p.title.casefold()
                    if key not in all_papers:
                        all_papers[key] = p
                        round_added += 1

                rounds.append(SearchRound(
                    round_number=round_num + 1,
                    queries_used=refined_queries,
                    papers_found=len(round_result.papers),
                    papers_added=round_added,
                    api_calls=round_result.api_calls,
                    elapsed_ms=round_result.elapsed_ms,
                    strategy="refinement",
                ))

                # Stop if no new papers found
                if round_added == 0:
                    break

        elapsed = int((time.perf_counter() - started) * 1000)
        papers_list = list(all_papers.values())

        token_est = sum(
            len(p.title) + len(p.abstract) for p in papers_list
        ) // 3 + total_api_calls * 200

        return SearchResult(
            papers=papers_list,
            rounds=rounds,
            total_api_calls=total_api_calls,
            total_cache_hits=total_cache_hits,
            total_elapsed_ms=elapsed,
            token_estimate=token_est,
        )

    def _execute_search_round(
        self,
        queries: list[str],
        analyzed_query: AnalyzedQuery,
    ) -> "RoundResult":
        """Execute parallel searches across dual sources for a set of queries.

        Each query is sent to both OpenAlex and (if enabled) Semantic Scholar.
        Results are merged and deduplicated by DOI > paper ID > normalized title.
        """
        round_started = time.perf_counter()
        all_papers: dict[str, Paper] = {}
        api_calls = 0
        cache_hits = 0

        # Create a temporary QueryPlan for the providers
        plan = QueryPlan(
            original_query=analyzed_query.original_query,
            normalized_query=analyzed_query.normalized_query,
            year_from=analyzed_query.year_from,
            year_to=analyzed_query.year_to,
            must_have=analyzed_query.must_have,
            preferred=analyzed_query.preferred,
            exclude=analyzed_query.exclude,
            subqueries=queries,
        )

        # ---- Source 1: OpenAlex ----
        try:
            provider_result = self.openalex.search(plan)
            api_calls += provider_result.api_calls
            cache_hits += provider_result.cache_hits
            for p in provider_result.papers:
                key = p.doi or p.id or p.title.casefold()
                all_papers[key] = p
        except Exception:
            pass

        # ---- Source 2: Semantic Scholar (dual-source enhancement) ----
        if self.use_dual_source and self.semantic_scholar is not None:
            try:
                s2_result = self.semantic_scholar.search(plan)
                api_calls += s2_result.api_calls
                cache_hits += s2_result.cache_hits
                for p in s2_result.papers:
                    # Dedup key: prefer DOI > paper ID > normalized title
                    key = p.doi or p.id or p.title.casefold()
                    if key not in all_papers:
                        all_papers[key] = p
                    # If same key exists, keep the one with more metadata (prefer OpenAlex)
            except Exception:
                pass  # Semantic Scholar failure is non-fatal; continue with OpenAlex results

        # Apply relevance filtering
        papers_list = list(all_papers.values())
        filtered = self.filter.filter_papers(
            papers_list,
            analyzed_query.original_query,
            min_score=15.0,
        )

        elapsed = int((time.perf_counter() - round_started) * 1000)
        return RoundResult(
            papers=filtered,
            api_calls=api_calls,
            cache_hits=cache_hits,
            elapsed_ms=elapsed,
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
            json_str = RelevanceFilter._extract_json(response.content)
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
