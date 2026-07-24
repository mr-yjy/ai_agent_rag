"""Enhanced SearchService for ScholarPilot.

Orchestrates the full search pipeline:
1. Query Analysis (LLM-powered) → AnalyzedQuery
2. Iterative Search (multi-round + citation expansion) → Candidate papers
3. Hybrid Ranking (heuristic + LLM) → Ranked results
4. Structured Output → API response

Planning fallback: LLM → Heuristic. Demo data is used only in demo mode;
live requests never substitute unrelated built-in papers.
"""

from __future__ import annotations

import inspect
import re
import threading
import time
import uuid
from typing import Any

from .budget import (
    SearchCancelled,
    SearchDeadline,
    SearchDeadlineExceeded,
    bind_deadline,
)
from .config import config_hash, get_config
from .counterfactual import CounterfactualVerifier
from .llm_client import LLMClient, create_llm_client
from .models import QueryPlan, SearchStats
from .planner import build_query_plan as build_heuristic_plan
from .providers import DemoProvider, OpenAlexProvider
from .query_analyzer import AnalyzedQuery, QueryAnalyzer
from .ranking import rank_papers as heuristic_rank
from .search_agent import RelevanceFilter, SearchAgent
from .llm_ranker import LLMRanker


class LiveSearchError(RuntimeError):
    """A live request could not reach any usable academic backend."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "live_backend_failed",
        provider_errors: list[dict[str, Any]] | None = None,
        request_id: str = "",
        stage: str = "",
        retryable: bool = True,
        retry_after_seconds: int = 0,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider_errors = provider_errors or []
        self.request_id = request_id
        self.stage = stage
        self.retryable = retryable
        self.retry_after_seconds = max(0, retry_after_seconds)

    def to_api(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": self.code,
            "message": str(self),
            "requestId": self.request_id,
            "retryable": self.retryable,
            "retryAfterSeconds": self.retry_after_seconds,
        }
        if self.stage:
            error["stage"] = self.stage
        if self.provider_errors:
            error["providerErrors"] = self.provider_errors
            error["reasons"] = list(
                dict.fromkeys(
                    f"{item.get('provider', 'unknown')}: "
                    f"{item.get('message', 'provider failed')}"
                    for item in self.provider_errors
                )
            )
        return {"error": error}


def new_request_id(value: str | None = None) -> str:
    """Return a bounded opaque request identifier safe for logs and JSON."""
    candidate = re.sub(r"[^a-zA-Z0-9_.:-]", "", (value or ""))[:80]
    return candidate or uuid.uuid4().hex


def api_error(
    *,
    code: str,
    message: str,
    request_id: str,
    retryable: bool = False,
    retry_after_seconds: int = 0,
    **details: Any,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "requestId": request_id,
        "retryable": retryable,
        "retryAfterSeconds": max(0, retry_after_seconds),
    }
    error.update(
        {
            key: value
            for key, value in details.items()
            if value not in (None, "", [], {})
        }
    )
    return {"error": error}


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

    def llm_info(self) -> dict[str, Any]:
        """Return safe model metadata without exposing credentials."""
        return {
            "configured": self.use_llm,
            "status": (
                "configured_unverified"
                if self.use_llm
                else "not_configured"
            ),
            "model": self.llm.config.model,
            "baseUrl": self.llm.config.base_url,
            "thinkingMode": self.llm.config.thinking_mode,
            "reasoningEffort": self.llm.config.reasoning_effort,
            "jsonMode": self.llm.config.json_mode,
        }

    def academic_sources_info(self) -> dict[str, Any]:
        """Return credential-safe academic provider configuration metadata."""
        semantic_scholar = self.search_agent.semantic_scholar
        openalex_retry_after = max(
            0,
            round(
                float(
                    getattr(self.live_provider, "_rate_limited_until", 0.0)
                )
                - time.time()
            ),
        )
        semantic_retry_after = max(
            0,
            round(
                float(
                    getattr(semantic_scholar, "_rate_limited_until", 0.0)
                )
                - time.time()
            ),
        )
        return {
            "openalex": {
                "enabled": True,
                "apiKeyConfigured": bool(
                    getattr(self.live_provider, "api_key", "")
                ),
                "circuitOpen": openalex_retry_after > 0,
                "retryAfterSeconds": openalex_retry_after,
                "status": (
                    "rate_limited"
                    if openalex_retry_after > 0
                    else (
                        "configured_unverified"
                        if getattr(self.live_provider, "api_key", "")
                        else "anonymous_unverified"
                    )
                ),
            },
            "semanticScholar": {
                "enabled": semantic_scholar is not None,
                "apiKeyConfigured": bool(
                    getattr(semantic_scholar, "api_key", "")
                ),
                "circuitOpen": semantic_retry_after > 0,
                "retryAfterSeconds": semantic_retry_after,
                "status": (
                    "disabled"
                    if semantic_scholar is None
                    else (
                        "rate_limited"
                        if semantic_retry_after > 0
                        else (
                            "configured_unverified"
                            if getattr(semantic_scholar, "api_key", "")
                            else "anonymous_unverified"
                        )
                    )
                ),
            },
        }

    def search(
        self,
        query: str,
        mode: str = "demo",
        limit: int = 10,
        *,
        request_id: str | None = None,
        cancel_event: threading.Event | None = None,
        auth_queue_ms: int = 0,
    ) -> dict[str, Any]:
        """Execute one request with isolated metrics and one total deadline."""
        resolved_request_id = new_request_id(request_id)
        deadline = SearchDeadline(
            request_id=resolved_request_id,
            total_seconds=self.config.strategy.search_timeout_seconds,
            cancel_event=cancel_event,
        )
        if auth_queue_ms:
            deadline.add_stage_timing("auth_queue", max(0, auth_queue_ms))
        metrics_token = self.llm.begin_request_metrics()
        try:
            with bind_deadline(deadline):
                return self._search(
                    query=query,
                    mode=mode,
                    limit=limit,
                    request_id=resolved_request_id,
                    deadline=deadline,
                )
        except SearchCancelled as exc:
            raise LiveSearchError(
                "搜索请求已由客户端取消。",
                code="search_cancelled",
                request_id=resolved_request_id,
                stage=exc.stage,
                retryable=True,
            ) from exc
        except SearchDeadlineExceeded as exc:
            raise LiveSearchError(
                "实时检索已耗尽总时间预算。",
                code="search_deadline_exceeded",
                request_id=resolved_request_id,
                stage=exc.stage,
                retryable=True,
            ) from exc
        finally:
            self.llm.end_request_metrics(metrics_token)

    def _search(
        self,
        query: str,
        mode: str = "demo",
        limit: int = 10,
        *,
        request_id: str,
        deadline: SearchDeadline,
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
        if mode not in {"demo", "live"}:
            raise ValueError("mode 必须是 demo 或 live。")
        limit = max(1, min(limit, 50))

        warning: str | None = None
        api_calls = 0
        cache_hits = 0
        search_result = None
        provider_errors: list[dict[str, Any]] = []
        source_status: list[dict[str, Any]] = []

        # ---- Step 1: Query Analysis ----
        analyzed: AnalyzedQuery | None = None
        with deadline.measure("query_understanding"):
            if mode == "live" and self.use_llm:
                try:
                    analyzed = self.query_analyzer.analyze(query)
                except (SearchCancelled, SearchDeadlineExceeded):
                    raise
                except Exception:
                    analyzed = None

        # ---- Step 2: Build plan (from analyzer or heuristic) ----
        with deadline.measure("subquery_generation"):
            if analyzed and analyzed.confidence > 0.2:
                search_strategy = (
                    analyzed.search_strategy
                    if analyzed.search_strategy
                    in {"precision", "balanced", "recall"}
                    else "balanced"
                )
                plan = QueryPlan(
                    original_query=analyzed.original_query,
                    normalized_query=analyzed.normalized_query,
                    year_from=analyzed.year_from,
                    year_to=analyzed.year_to,
                    must_have=analyzed.must_have,
                    preferred=analyzed.preferred,
                    exclude=analyzed.exclude,
                    subqueries=(
                        analyzed.optimized_queries
                        or analyzed.sub_queries
                    )[: self.config.strategy.initial_subquery_limit],
                    constraint_groups=analyzed.constraint_groups,
                    methods=analyzed.methods,
                    datasets=analyzed.datasets,
                    domains=analyzed.domains,
                    venues=analyzed.venues,
                    research_topic=analyzed.research_topic,
                    retrieval_preference=search_strategy,  # type: ignore[arg-type]
                )
                plan_api = {
                    **analyzed.to_api(),
                    "retrievalPreference": search_strategy,
                }
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
                analyzed_for_search = (
                    analyzed or self.query_analyzer._rule_baseline(query)
                )
                search_parameters = inspect.signature(
                    self.search_agent.search
                ).parameters
                search_result = (
                    self.search_agent.search(
                        analyzed_for_search,
                        deadline=deadline,
                    )
                    if "deadline" in search_parameters
                    else self.search_agent.search(analyzed_for_search)
                )
                papers = search_result.papers
                api_calls = search_result.total_api_calls
                cache_hits = search_result.total_cache_hits
                provider_errors = search_result.provider_errors
                source_status = search_result.source_status
                provider_name = "OpenAlex + Semantic Scholar 双源检索 Agent"

                if not papers:
                    successful_source = any(
                        item.get("status") in {"success", "partial"}
                        for item in source_status
                    )
                    if (
                        search_result.retrieved_candidate_count > 0
                        or successful_source
                        or not provider_errors
                    ):
                        provider_name = "实时学术检索（暂无匹配结果）"
                        if search_result.retrieved_candidate_count > 0:
                            warning = (
                                "实时接口已返回 "
                                f"{search_result.retrieved_candidate_count} "
                                "篇候选，但没有论文通过当前相关性过滤；"
                                "未使用内置数据。"
                            )
                    elif provider_errors:
                        retry_after = max(
                            (
                                int(
                                    item.get(
                                        "retryAfterSeconds", 0
                                    )
                                )
                                for item in provider_errors
                            ),
                            default=0,
                        )
                        raise LiveSearchError(
                            "所有实时学术数据源均不可用。",
                            code="academic_sources_unavailable",
                            provider_errors=provider_errors,
                            request_id=request_id,
                            stage="academic_retrieval",
                            retryable=any(
                                bool(item.get("retryable"))
                                for item in provider_errors
                            ),
                            retry_after_seconds=retry_after,
                        )
            except Exception as exc:
                if isinstance(exc, LiveSearchError):
                    raise
                if isinstance(
                    exc, (SearchCancelled, SearchDeadlineExceeded)
                ):
                    raise
                raise LiveSearchError(
                    "Python 实时检索后端执行失败。",
                    provider_errors=provider_errors,
                    request_id=request_id,
                    stage="academic_retrieval",
                ) from exc
        else:
            # Demo mode: use built-in data
            demo_result = self.demo_provider.search(plan)
            papers = demo_result.papers
            provider_name = "内置比赛演示数据"

        if mode == "live" and papers:
            available_sources = {
                source
                for paper in papers
                for source in getattr(paper, "sources", [])
            }
            if {"openalex", "semantic_scholar"} <= available_sources:
                provider_name = "OpenAlex + Semantic Scholar 双源检索 Agent"
            elif "openalex" in available_sources:
                provider_name = "OpenAlex 实时学术检索"
            elif "semantic_scholar" in available_sources:
                provider_name = "Semantic Scholar 实时学术检索"

        # ---- Step 4: Ranking ----
        if mode == "live" and self.use_llm and len(papers) >= 3:
            if deadline.can_start(
                "llm_rerank",
                minimum_seconds=(
                    self.config.strategy.optional_step_min_remaining_seconds
                ),
                reserve_seconds=0.5,
            ):
                try:
                    with deadline.measure(
                        "llm_rerank",
                        reserve_seconds=0.5,
                    ):
                        ranked = self.llm_ranker.rank(
                            papers, plan, limit=limit
                        )
                except (SearchCancelled, SearchDeadlineExceeded):
                    deadline.set_stop_reason("rerank_budget_exhausted")
                    ranked = heuristic_rank(papers, plan, limit=limit)
                except Exception:
                    ranked = heuristic_rank(papers, plan, limit=limit)
            else:
                deadline.set_stop_reason("rerank_budget_exhausted")
                ranked = heuristic_rank(papers, plan, limit=limit)
        else:
            ranked = heuristic_rank(papers, plan, limit=limit)

        # ---- Step 4.5: Counterfactual Verification (top papers only) ----
        if (
            mode == "live"
            and self.use_llm
            and len(ranked) >= 3
            and deadline.can_start(
                "counterfactual_verification",
                minimum_seconds=(
                    self.config.strategy.optional_step_min_remaining_seconds
                ),
                reserve_seconds=0.5,
            )
        ):
            try:
                with deadline.measure(
                    "counterfactual_verification",
                    reserve_seconds=0.5,
                ):
                    ranked = self.counterfactual.verify(
                        ranked,
                        (
                            analyzed
                            if analyzed and analyzed.confidence > 0.2
                            else None
                        ),
                        query_text=query,
                    )
            except (SearchCancelled, SearchDeadlineExceeded):
                deadline.set_stop_reason(
                    "counterfactual_budget_exhausted"
                )
            except Exception:
                pass  # Non-critical; continue with unverified rankings

        # ---- Step 5: Build API Response ----
        response_started = time.perf_counter()
        request_llm_metrics = self.llm.request_metrics_snapshot()
        llm_calls = request_llm_metrics["calls"]
        llm_request_attempts = request_llm_metrics["requestAttempts"]
        token_estimate = request_llm_metrics["totalTokens"]
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
            elapsed_ms=max(12, deadline.elapsed_ms),
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
        stop_reason = (
            search_result.stop_reason
            if search_result is not None and search_result.stop_reason
            else deadline.stop_reason or "completed"
        )
        stats_api["llmRequestAttempts"] = llm_request_attempts
        stats_api["tokenUsage"] = {
            "promptTokens": request_llm_metrics.get("promptTokens", 0),
            "completionTokens": request_llm_metrics.get(
                "completionTokens", 0
            ),
            "totalTokens": request_llm_metrics.get("totalTokens", 0),
            "estimatedTokens": request_llm_metrics.get(
                "estimatedTokens", 0
            ),
        }
        stats_api["stageTimings"] = deadline.stage_timings()
        stats_api["stopReason"] = stop_reason
        stats_api["budgetRemainingMs"] = deadline.remaining_ms
        stats_api["configHash"] = config_hash(self.config)

        degraded = bool(
            provider_errors
            or any(
                item.get("status")
                not in {"success", None}
                for item in source_status
            )
        )
        if not ranked:
            response_status = "no_results"
        elif degraded:
            response_status = "degraded"
        else:
            response_status = "success"
        response: dict[str, Any] = {
            "schemaVersion": "1.0",
            "requestId": request_id,
            "status": response_status,
            "degraded": degraded,
            "mode": mode,
            "provider": provider_name,
            "model": self.llm_info(),
            "queryPlan": plan_api,
            "plan": plan_api,
            "results": [paper.to_api() for paper in ranked],
            "sourceStatus": source_status,
            "stats": stats_api,
        }
        if warning:
            response["warning"] = warning
        if provider_errors:
            response["providerErrors"] = provider_errors
            response["degradationReasons"] = list(
                dict.fromkeys(
                    f"{item['provider']}: {item['message']}"
                    for item in provider_errors
                )
            )
            recovery_actions = list(
                dict.fromkeys(
                    str(item["userAction"])
                    for item in provider_errors
                    if item.get("userAction")
                )
            )
            if recovery_actions:
                response["recoveryActions"] = recovery_actions

        deadline.add_stage_timing(
            "response_assembly",
            int((time.perf_counter() - response_started) * 1000),
        )
        stats_api["stageTimings"] = deadline.stage_timings()
        stats_api["elapsedMs"] = max(12, deadline.elapsed_ms)
        stats_api["budgetRemainingMs"] = deadline.remaining_ms
        return response
