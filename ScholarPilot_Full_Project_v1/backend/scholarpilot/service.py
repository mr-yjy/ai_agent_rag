"""Enhanced SearchService for ScholarPilot.

Orchestrates the full search pipeline:
1. Query Analysis (LLM-powered) → AnalyzedQuery
2. Iterative Search (multi-round + citation expansion) → Candidate papers
3. Hybrid Ranking (heuristic + LLM) → Ranked results
4. Structured Output → API response

Fallback chain: LLM → Heuristic → Demo data
"""

from __future__ import annotations

import time
from typing import Any

from .config import get_config
from .counterfactual import CounterfactualVerifier
from .llm_client import LLMClient, create_llm_client
from .models import QueryPlan, SearchStats
from .planner import build_query_plan as build_heuristic_plan
from .providers import DemoProvider, OpenAlexProvider, ProviderError
from .query_analyzer import AnalyzedQuery, QueryAnalyzer
from .ranking import rank_papers as heuristic_rank
from .search_agent import RelevanceFilter, SearchAgent
from .llm_ranker import LLMRanker


class SearchService:
    """End-to-end search service orchestrating the full pipeline."""

    def __init__(
        self,
        demo_provider: DemoProvider | None = None,
        live_provider: OpenAlexProvider | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.config = get_config()
        self.demo_provider = demo_provider or DemoProvider()
        self.live_provider = live_provider or OpenAlexProvider()
        self.llm = llm_client or create_llm_client()
        self.use_llm = bool(self.llm.config.api_key)

        # Pipeline components
        self.query_analyzer = QueryAnalyzer(self.llm, use_llm=self.use_llm)
        self.relevance_filter = RelevanceFilter(self.llm)
        self.search_agent = SearchAgent(
            openalex_provider=self.live_provider,
            llm_client=self.llm,
            relevance_filter=self.relevance_filter,
        )
        self.llm_ranker = LLMRanker(
            self.llm,
            llm_top_k=self.config.strategy.llm_rerank_top_k,
            llm_weight=0.35,
        )
        self.counterfactual = CounterfactualVerifier(
            self.llm,
            top_k=self.config.strategy.counterfactual_max_papers,
            penalty_weight=0.15,
            boundary_margin=self.config.strategy.counterfactual_boundary_margin,
        )

    def search(
        self,
        query: str,
        mode: str = "demo",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Execute the full search pipeline.

        Args:
            query: Natural language academic search query
            mode: "demo" (built-in data) or "live" (OpenAlex + LLM)
            limit: Max papers to return

        Returns:
            API response dict matching the frontend's expected format.
        """
        query = query.strip()
        if len(query) < 6:
            raise ValueError("请输入至少6个字符的科研检索问题。")
        if len(query) > 800:
            raise ValueError("当前接口最多接受800个字符。")
        limit = max(1, min(limit, 50))

        started = time.perf_counter()
        llm_metrics_before = self.llm.metrics_snapshot()
        warning: str | None = None
        actual_mode: str = mode
        api_calls = 0
        cache_hits = 0
        search_result = None

        # ---- Step 1: Query Analysis ----
        analyzed: AnalyzedQuery | None = None
        if mode == "live" and self.use_llm:
            try:
                analyzed = self.query_analyzer.analyze(query)
            except Exception:
                pass

        # ---- Step 2: Build plan (from analyzer or heuristic) ----
        if analyzed and analyzed.confidence > 0.2:
            plan = QueryPlan(
                original_query=analyzed.original_query,
                normalized_query=analyzed.normalized_query,
                year_from=analyzed.year_from,
                year_to=analyzed.year_to,
                must_have=analyzed.must_have,
                preferred=analyzed.preferred,
                exclude=analyzed.exclude,
                subqueries=analyzed.optimized_queries or analyzed.sub_queries,
                constraint_groups=analyzed.constraint_groups,
                methods=analyzed.methods,
                datasets=analyzed.datasets,
                domains=analyzed.domains,
                venues=analyzed.venues,
            )
            plan_api = analyzed.to_api()
        else:
            # Fallback to heuristic planner
            plan = build_heuristic_plan(query)
            plan_api = plan.to_api()

        # ---- Step 3: Paper Retrieval ----
        provider_name = "内置比赛演示数据"
        papers: list[Any] = []

        if mode == "live":
            try:
                # Use the iterative search agent
                search_result = self.search_agent.search(
                    analyzed or self.query_analyzer._rule_baseline(query)
                )
                papers = search_result.papers
                api_calls = search_result.total_api_calls
                cache_hits = search_result.total_cache_hits
                provider_name = "OpenAlex + Semantic Scholar 双源检索 Agent"

                if not papers:
                    raise ProviderError("No papers found")
            except Exception as exc:
                # Fallback to demo data
                try:
                    demo_result = self.demo_provider.search(plan)
                    papers = demo_result.papers
                    provider_name = "内置比赛演示数据"
                    actual_mode = "demo"
                except Exception:
                    pass
                warning = (
                    f"实时接口暂时不可用 ({exc!s})，已自动切换到内置数据。"
                )
        else:
            # Demo mode: use built-in data
            demo_result = self.demo_provider.search(plan)
            papers = demo_result.papers
            provider_name = "内置比赛演示数据"

        # ---- Step 4: Ranking ----
        if actual_mode == "live" and self.use_llm and len(papers) >= 3:
            try:
                ranked = self.llm_ranker.rank(papers, plan, limit=limit)
            except Exception:
                ranked = heuristic_rank(papers, plan, limit=limit)
        else:
            ranked = heuristic_rank(papers, plan, limit=limit)

        # ---- Step 4.5: Counterfactual Verification (top papers only) ----
        if actual_mode == "live" and self.use_llm and len(ranked) >= 3:
            try:
                ranked = self.counterfactual.verify(
                    ranked,
                    analyzed if analyzed and analyzed.confidence > 0.2 else None,
                    query_text=query,
                )
            except Exception:
                pass  # Non-critical; continue with unverified rankings

        # ---- Step 5: Build API Response ----
        elapsed_ms = max(12, round((time.perf_counter() - started) * 1000))

        llm_metrics_after = self.llm.metrics_snapshot()
        llm_calls = (
            llm_metrics_after["calls"] - llm_metrics_before["calls"]
        )
        token_estimate = (
            llm_metrics_after["totalTokens"]
            - llm_metrics_before["totalTokens"]
        )
        retrieved_candidate_count = (
            search_result.retrieved_candidate_count
            if search_result is not None
            else len(papers)
        )
        subquery_count = (
            sum(len(item.queries_used) for item in search_result.rounds)
            if search_result is not None
            else len(plan.subqueries)
        )

        stats = SearchStats(
            elapsed_ms=elapsed_ms,
            api_calls=api_calls,
            subquery_count=subquery_count,
            candidate_count=retrieved_candidate_count,
            deduplicated_count=len(papers),
            token_estimate=token_estimate,
            cache_hits=cache_hits,
            llm_calls=llm_calls,
        )

        stats_api = stats.to_api()
        if search_result is not None:
            stats_api["searchRounds"] = [
                item.to_api() for item in search_result.rounds
            ]
            stats_api["searchStrategy"] = (
                analyzed.search_strategy if analyzed else "balanced"
            )

        response: dict[str, Any] = {
            "mode": actual_mode,
            "provider": provider_name,
            "plan": plan_api,
            "results": [paper.to_api() for paper in ranked],
            "stats": stats_api,
        }
        if warning:
            response["warning"] = warning

        return response
