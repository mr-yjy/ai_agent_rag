import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from scholarpilot.config import LLMConfig
from scholarpilot.llm_client import LLMClient, LLMResponse
from scholarpilot.search_agent import SearchResult
from scholarpilot.service import SearchService


class BarrierLLMClient(LLMClient):
    def __init__(self, parties: int) -> None:
        super().__init__(
            LLMConfig(
                api_key="test-key",
                model="test-model",
                max_retries=0,
            )
        )
        self.barrier = threading.Barrier(parties)

    def _try_openai_package(
        self,
        messages,
        model,
        temperature,
        max_tokens,
        thinking_mode,
        reasoning_effort,
        json_mode,
    ):
        del (
            messages,
            temperature,
            max_tokens,
            thinking_mode,
            reasoning_effort,
            json_mode,
        )
        self._increment_metrics("requestAttempts")
        self.barrier.wait(timeout=5)
        return LLMResponse(
            content=json.dumps(
                {
                    "normalized_query": "academic paper retrieval agent",
                    "research_topic": "academic paper retrieval",
                    "sub_queries": ["academic paper retrieval agent"],
                    "optimized_queries": ["academic paper retrieval agent"],
                    "confidence": 0.9,
                }
            ),
            model=model,
            usage={
                "prompt_tokens": 7,
                "completion_tokens": 4,
                "total_tokens": 11,
            },
            elapsed_ms=5,
        )


class EmptySuccessfulSearchAgent:
    semantic_scholar = None

    def search(self, analyzed_query):
        del analyzed_query
        return SearchResult(
            papers=[],
            total_api_calls=1,
            retrieved_candidate_count=1,
        )


class ConcurrentMetricsTest(unittest.TestCase):
    def test_twenty_requests_keep_token_metrics_request_local(self) -> None:
        llm = BarrierLLMClient(parties=20)
        service = SearchService(llm_client=llm)
        service.search_agent = EmptySuccessfulSearchAgent()

        def execute(index: int):
            return service.search(
                f"academic paper retrieval agent query {index:02d}",
                mode="live",
                limit=5,
            )

        with ThreadPoolExecutor(max_workers=20) as executor:
            responses = list(executor.map(execute, range(20)))

        self.assertEqual(
            [response["stats"]["tokenEstimate"] for response in responses],
            [11] * 20,
        )
        self.assertEqual(
            [response["stats"]["llmCalls"] for response in responses],
            [1] * 20,
        )
        self.assertEqual(
            len({response["requestId"] for response in responses}),
            20,
        )
        self.assertEqual(
            [
                response["stats"]["tokenUsage"]["totalTokens"]
                for response in responses
            ],
            [11] * 20,
        )
        self.assertEqual(llm.metrics_snapshot()["totalTokens"], 220)


if __name__ == "__main__":
    unittest.main()
