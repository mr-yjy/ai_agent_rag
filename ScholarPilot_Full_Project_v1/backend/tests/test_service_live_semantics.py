import unittest

from scholarpilot.config import LLMConfig
from scholarpilot.llm_client import LLMClient
from scholarpilot.search_agent import SearchResult
from scholarpilot.service import LiveSearchError, SearchService


class EmptyLiveSearchAgent:
    def __init__(self) -> None:
        self.semantic_scholar = None

    def search(self, analyzed_query):
        del analyzed_query
        return SearchResult(
            papers=[],
            total_api_calls=1,
            retrieved_candidate_count=0,
            provider_errors=[
                {
                    "provider": "SemanticScholar",
                    "message": "rate limit circuit is open",
                    "retryable": True,
                }
            ],
        )


class LiveModeSemanticsTest(unittest.TestCase):
    def test_live_provider_failure_raises_instead_of_substituting_demo(self) -> None:
        service = SearchService(
            llm_client=LLMClient(LLMConfig(api_key="")),
        )
        service.search_agent = EmptyLiveSearchAgent()

        with self.assertRaises(LiveSearchError) as context:
            service.search(
                "academic paper retrieval agent query decomposition",
                mode="live",
                limit=5,
            )
        self.assertEqual(
            context.exception.code,
            "academic_sources_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
