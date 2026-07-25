import threading
import time
import unittest
from unittest.mock import Mock, patch

from scholarpilot.budget import (
    SearchCancelled,
    SearchDeadline,
    SearchDeadlineExceeded,
)
from scholarpilot.config import LLMConfig
from scholarpilot.llm_client import LLMClient
from scholarpilot.models import Paper, QueryPlan
from scholarpilot.providers import OpenAlexProvider
from scholarpilot.search_agent import SearchAgent, SearchResult
from scholarpilot.service import LiveSearchError, SearchService


def live_paper(suffix: str = "123") -> Paper:
    return Paper(
        id=f"https://openalex.org/W{suffix}",
        title=f"Reliable academic paper retrieval {suffix}",
        abstract="A real live paper about academic search and retrieval.",
        year=2025,
        authors=["Researcher"],
        venue="ACL",
        cited_by_count=5,
        url=f"https://openalex.org/W{suffix}",
        sources=["openalex"],
        retrieval_routes=["query_search"],
    )


class StaticSearchAgent:
    semantic_scholar = None

    def __init__(self, result: SearchResult) -> None:
        self.result = result

    def search(self, analyzed_query, *, deadline=None):
        del analyzed_query
        if deadline is not None:
            deadline.ensure_available("openalex_retrieval")
        return self.result


class CancelAfterRetrievalAgent(StaticSearchAgent):
    def __init__(
        self,
        result: SearchResult,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__(result)
        self.cancel_event = cancel_event

    def search(self, analyzed_query, *, deadline=None):
        result = super().search(analyzed_query, deadline=deadline)
        self.cancel_event.set()
        return result


class DeadlineTest(unittest.TestCase):
    def test_step_timeout_is_capped_by_stage_and_total_budget(self) -> None:
        deadline = SearchDeadline("req-budget", total_seconds=1.0)
        timeout = deadline.timeout_for(
            "query_understanding",
            requested_seconds=60,
        )
        self.assertLessEqual(timeout, 1.0)
        self.assertGreater(timeout, 0)

    def test_cancel_event_prevents_a_new_stage(self) -> None:
        event = threading.Event()
        event.set()
        deadline = SearchDeadline(
            "req-cancel",
            total_seconds=5,
            cancel_event=event,
        )
        with self.assertRaises(SearchCancelled):
            deadline.ensure_available("llm_rerank")

    def test_expired_deadline_prevents_a_new_stage(self) -> None:
        deadline = SearchDeadline("req-expired", total_seconds=0.05)
        deadline.started_at -= 1
        with self.assertRaises(SearchDeadlineExceeded):
            deadline.ensure_available("citation_expansion")

    def test_stage_limit_applies_to_cumulative_stage_work(self) -> None:
        deadline = SearchDeadline(
            "req-stage-limit",
            total_seconds=2,
            stage_limits_seconds={"query_understanding": 0.05},
        )
        with deadline.measure("query_understanding"):
            time.sleep(0.06)
            with self.assertRaises(SearchDeadlineExceeded):
                deadline.ensure_available("query_understanding")

    def test_expired_selector_uses_lexical_fallback(self) -> None:
        agent = SearchAgent(
            llm_client=LLMClient(LLMConfig(api_key="")),
        )
        papers = [
            live_paper("201"),
            live_paper("202"),
            live_paper("203"),
        ]
        deadline = SearchDeadline(
            "req-selector-fallback",
            total_seconds=0.05,
        )
        deadline.started_at -= 1

        filtered = agent._filter_candidates(
            papers,
            "academic paper retrieval",
            0.0,
            deadline,
        )

        self.assertEqual(
            [paper.id for paper in filtered],
            [paper.id for paper in papers],
        )


class ProviderEmptyResultTest(unittest.TestCase):
    def test_successful_empty_openalex_response_is_not_a_provider_failure(
        self,
    ) -> None:
        provider = OpenAlexProvider(api_key="test", max_retries=0)
        with patch.object(
            provider,
            "_request",
            return_value=([], False, 1),
        ):
            result = provider.search(
                plan=QueryPlan(
                    original_query="academic search",
                    normalized_query="academic search",
                    subqueries=["academic search"],
                )
            )
        self.assertEqual(result.papers, [])
        self.assertEqual(result.api_calls, 1)


class StructuredLiveSemanticsTest(unittest.TestCase):
    def make_service(self, result: SearchResult) -> SearchService:
        service = SearchService(
            llm_client=LLMClient(LLMConfig(api_key="")),
        )
        service.search_agent = StaticSearchAgent(result)
        return service

    def test_successful_empty_source_returns_no_results_schema(self) -> None:
        service = self.make_service(
            SearchResult(
                papers=[],
                total_api_calls=1,
                source_status=[
                    {
                        "source": "openalex",
                        "status": "success",
                        "apiCalls": 1,
                        "resultCount": 0,
                    }
                ],
                stop_reason="retrieval_complete",
            )
        )
        response = service.search(
            "academic paper retrieval agent",
            request_id="req-no-results",
        )
        self.assertEqual(response["schemaVersion"], "1.0")
        self.assertEqual(response["requestId"], "req-no-results")
        self.assertEqual(response["status"], "no_results")
        self.assertEqual(response["results"], [])
        self.assertIn("stageTimings", response["stats"])

    def test_one_source_failure_returns_degraded_real_results(self) -> None:
        service = self.make_service(
            SearchResult(
                papers=[live_paper()],
                total_api_calls=2,
                retrieved_candidate_count=1,
                provider_errors=[
                    {
                        "provider": "SemanticScholar",
                        "message": "upstream timeout",
                        "retryable": True,
                    }
                ],
                source_status=[
                    {
                        "source": "openalex",
                        "status": "success",
                        "apiCalls": 1,
                        "resultCount": 1,
                    },
                    {
                        "source": "semantic_scholar",
                        "status": "timeout",
                        "apiCalls": 1,
                        "resultCount": 0,
                    },
                ],
            )
        )
        response = service.search(
            "academic paper retrieval agent",
            request_id="req-degraded",
        )
        self.assertEqual(response["status"], "degraded")
        self.assertTrue(response["degraded"])
        self.assertEqual(response["results"][0]["id"], live_paper().id)

    def test_cancelled_request_returns_structured_error(self) -> None:
        service = self.make_service(SearchResult(papers=[]))
        event = threading.Event()
        event.set()
        with self.assertRaises(LiveSearchError) as context:
            service.search(
                "academic paper retrieval agent",
                request_id="req-cancelled",
                cancel_event=event,
            )
        payload = context.exception.to_api()
        self.assertEqual(payload["error"]["code"], "search_cancelled")
        self.assertEqual(payload["error"]["requestId"], "req-cancelled")
        self.assertTrue(payload["error"]["retryable"])

    def test_cancellation_after_retrieval_skips_optional_llm_stages(
        self,
    ) -> None:
        cancel_event = threading.Event()
        service = self.make_service(
            SearchResult(
                papers=[
                    live_paper("101"),
                    live_paper("102"),
                    live_paper("103"),
                ],
                total_api_calls=1,
                retrieved_candidate_count=3,
                source_status=[
                    {
                        "source": "openalex",
                        "status": "success",
                        "apiCalls": 1,
                        "resultCount": 3,
                    }
                ],
            )
        )
        service.use_llm = True
        service.search_agent = CancelAfterRetrievalAgent(
            service.search_agent.result,
            cancel_event,
        )
        service.llm_ranker.rank = Mock()
        service.counterfactual.verify = Mock()

        response = service.search(
            "academic paper retrieval agent",
            request_id="req-cancel-after-retrieval",
            cancel_event=cancel_event,
        )

        service.llm_ranker.rank.assert_not_called()
        service.counterfactual.verify.assert_not_called()
        self.assertEqual(response["stats"]["stopReason"], "client_cancelled")


if __name__ == "__main__":
    unittest.main()
