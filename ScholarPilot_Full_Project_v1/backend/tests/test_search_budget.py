import json
import unittest

from scholarpilot.config import LLMConfig
from scholarpilot.llm_client import LLMClient, LLMResponse
from scholarpilot.models import Paper
from scholarpilot.providers import ProviderResult
from scholarpilot.query_analyzer import AnalyzedQuery
from scholarpilot.search_agent import RelevanceFilter, SearchAgent


class CapturingProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.query_counts: list[int] = []

    def search(self, plan):
        self.query_counts.append(len(plan.subqueries))
        papers = [
            Paper(
                id=f"{self.name}-{query}",
                title=f"Academic paper search {self.name} {query}",
                abstract="academic paper search query decomposition",
                year=2025,
                authors=[],
                venue="Test",
                cited_by_count=0,
                url="#",
                sources=[self.name],
            )
            for query in plan.subqueries
        ]
        return ProviderResult(papers=papers, api_calls=len(plan.subqueries))


class PassThroughFilter:
    def filter_papers(self, papers, query, min_score=0):
        return papers


class BatchLLM:
    def __init__(self) -> None:
        self.config = LLMConfig(api_key="test-key")
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        # The production batch size is eight.  Missing indexes fail open, so a
        # fixed eight-item response is sufficient for the short final batch.
        payload = [
            {
                "index": index,
                "is_relevant": True,
                "relevance_score": 80,
            }
            for index in range(8)
        ]
        return LLMResponse(
            content=json.dumps(payload),
            model="fake",
        )


class SearchBudgetTest(unittest.TestCase):
    def test_dual_source_round_respects_five_call_budget(self) -> None:
        openalex = CapturingProvider("openalex")
        semantic = CapturingProvider("semantic")
        client = LLMClient(LLMConfig(api_key=""))
        agent = SearchAgent(
            openalex_provider=openalex,
            semantic_scholar_provider=semantic,
            llm_client=client,
            relevance_filter=PassThroughFilter(),
            use_dual_source=True,
        )
        analyzed = AnalyzedQuery(
            original_query="academic paper search",
            normalized_query="academic paper search",
            sub_queries=["one", "two", "three", "four"],
        )
        result = agent._execute_search_round(
            analyzed.sub_queries,
            analyzed,
            max_api_calls=5,
        )
        self.assertEqual(result.api_calls, 5)
        self.assertEqual(openalex.query_counts, [3])
        self.assertEqual(semantic.query_counts, [2])
        self.assertEqual(result.queries_used, ["one", "two", "three"])

    def test_selector_batches_instead_of_calling_per_paper(self) -> None:
        llm = BatchLLM()
        selector = RelevanceFilter(llm)
        papers = [
            Paper(
                id=str(index),
                title=f"Paper {index}",
                abstract="academic search",
                year=2025,
                authors=[],
                venue="Test",
                cited_by_count=0,
                url="#",
            )
            for index in range(17)
        ]
        selected = selector._llm_filter(
            papers, "academic search", min_score=0
        )
        self.assertEqual(len(selected), 17)
        self.assertEqual(llm.calls, 3)


if __name__ == "__main__":
    unittest.main()
