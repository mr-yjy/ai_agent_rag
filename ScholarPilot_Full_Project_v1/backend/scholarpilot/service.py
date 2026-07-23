from __future__ import annotations

import time
from typing import Any

from .models import SearchMode, SearchStats
from .planner import build_query_plan
from .providers import DemoProvider, OpenAlexProvider, ProviderError
from .ranking import rank_papers


class SearchService:
    def __init__(
        self,
        demo_provider: DemoProvider | None = None,
        live_provider: OpenAlexProvider | None = None,
    ) -> None:
        self.demo_provider = demo_provider or DemoProvider()
        self.live_provider = live_provider or OpenAlexProvider()

    def search(
        self,
        query: str,
        mode: SearchMode = "demo",
        limit: int = 10,
    ) -> dict[str, Any]:
        query = query.strip()
        if len(query) < 6:
            raise ValueError("请输入至少6个字符的科研检索问题。")
        if len(query) > 800:
            raise ValueError("当前接口最多接受800个字符。")
        limit = max(1, min(limit, 50))

        started = time.perf_counter()
        plan = build_query_plan(query)
        provider = self.demo_provider
        actual_mode: SearchMode = mode
        warning: str | None = None

        if mode == "live":
            provider = self.live_provider
        try:
            provider_result = provider.search(plan)
        except ProviderError:
            provider = self.demo_provider
            provider_result = provider.search(plan)
            actual_mode = "demo"
            warning = (
                "实时接口暂时不可用，已自动切换到内置数据。"
                "排序流程仍完整可演示。"
            )

        ranked = rank_papers(provider_result.papers, plan, limit=limit)
        elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
        stats = SearchStats(
            elapsed_ms=elapsed_ms,
            api_calls=provider_result.api_calls,
            subquery_count=len(plan.subqueries),
            candidate_count=len(provider_result.papers),
            deduplicated_count=len(provider_result.papers),
            token_estimate=round(
                len(" ".join(plan.subqueries)) / 3.2
                + len(provider_result.papers) * 5
            ),
            cache_hits=provider_result.cache_hits,
        )
        response: dict[str, Any] = {
            "mode": actual_mode,
            "provider": provider.name,
            "plan": plan.to_api(),
            "results": [paper.to_api() for paper in ranked],
            "stats": stats.to_api(),
        }
        if warning:
            response["warning"] = warning
        return response

