import unittest

from scholarpilot.config import LLMConfig
from scholarpilot.llm_client import LLMClient
from scholarpilot.search_agent import SearchResult
from scholarpilot.service import SearchService


class EmptyLiveSearchAgent:
    def __init__(self) -> None:
        self.semantic_scholar = None

    def search(self, analyzed_query):
        del analyzed_query
        return SearchResult(
            papers=[],
            total_api_calls=1,
            retrieved_candidate_count=7,
            provider_errors=[
                {
                    "provider": "SemanticScholar",
                    "message": "rate limit circuit is open",
                    "retryable": True,
                }
            ],
        )


class LiveModeSemanticsTest(unittest.TestCase):
    def test_live_empty_result_never_substitutes_demo_papers(self) -> None:
        service = SearchService(
            llm_client=LLMClient(LLMConfig(api_key="")),
        )
        service.search_agent = EmptyLiveSearchAgent()

        payload = service.search(
            "academic paper retrieval agent query decomposition",
            mode="live",
            limit=5,
        )

        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["stats"]["candidateCount"], 7)
        self.assertIn("未使用内置数据", payload["warning"])
        self.assertNotIn("自动切换", payload["warning"])


if __name__ == "__main__":
    unittest.main()
