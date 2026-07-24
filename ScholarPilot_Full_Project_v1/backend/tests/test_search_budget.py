import json
import unittest

from scholarpilot.config import LLMConfig
from scholarpilot.llm_client import LLMClient, LLMResponse
from scholarpilot.models import Paper
from scholarpilot.providers import ProviderError, ProviderResult
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


class OpenCircuitProvider(CapturingProvider):
    circuit_open = True


class PassThroughFilter:
    def filter_papers(self, papers, query, min_score=0):
        return papers


class RecordingFilter(PassThroughFilter):
    def __init__(self) -> None:
        self.queries: list[str] = []

    def filter_papers(self, papers, query, min_score=0):
        self.queries.append(query)
        return super().filter_papers(papers, query, min_score)


class FailingProvider:
    name = "failing"

    def search(self, plan):
        del plan
        raise ProviderError(
            "temporary network failure",
            api_calls=1,
            retryable=True,
        )


class BatchLLM:
    def __init__(self, *, relevant: bool = True) -> None:
        self.config = LLMConfig(api_key="test-key")
        self.calls = 0
        self.relevant = relevant

    def chat(self, messages, **kwargs):
        self.calls += 1
        # The production batch size is eight.  Missing indexes fail open, so a
        # fixed eight-item response is sufficient for the short final batch.
        payload = [
            {
                "index": index,
                "is_relevant": self.relevant,
                "relevance_score": 80 if self.relevant else 0,
            }
            for index in range(8)
        ]
        return LLMResponse(
            content=json.dumps({"items": payload}),
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

    def test_provider_failure_is_visible_when_other_source_succeeds(self) -> None:
        semantic = CapturingProvider("semantic")
        client = LLMClient(LLMConfig(api_key=""))
        agent = SearchAgent(
            openalex_provider=FailingProvider(),
            semantic_scholar_provider=semantic,
            llm_client=client,
            relevance_filter=PassThroughFilter(),
            use_dual_source=True,
        )
        analyzed = AnalyzedQuery(
            original_query="academic paper search",
            normalized_query="academic paper search",
            sub_queries=["one", "two"],
        )
        result = agent._execute_search_round(
            analyzed.sub_queries,
            analyzed,
            max_api_calls=3,
        )

        self.assertEqual(len(result.papers), 1)
        self.assertEqual(result.api_calls, 2)
        self.assertEqual(len(result.provider_errors), 1)
        self.assertEqual(
            result.provider_errors[0]["message"],
            "temporary network failure",
        )
        self.assertTrue(result.provider_errors[0]["retryable"])

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

    def test_selector_keeps_small_exploration_set_if_llm_rejects_all(self) -> None:
        selector = RelevanceFilter(BatchLLM(relevant=False))
        papers = [
            Paper(
                id=str(index),
                title=f"Academic paper retrieval agent {index}",
                abstract="LLM query decomposition for academic search",
                year=2024,
                authors=[],
                venue="Test",
                cited_by_count=0,
                url="#",
            )
            for index in range(6)
        ]

        selected = selector.filter_papers(
            papers,
            "LLM agent academic paper retrieval query decomposition",
            min_score=8,
        )

        self.assertEqual(len(selected), 3)

    def test_initial_routes_interleave_precision_and_recall(self) -> None:
        analyzed = AnalyzedQuery(
            original_query="academic paper search",
            normalized_query="academic paper search",
            optimized_queries=["precise one", "precise two"],
            sub_queries=["broad one", "broad two"],
        )

        self.assertEqual(
            SearchAgent._initial_query_routes(analyzed),
            ["precise one", "broad one", "precise two", "broad two"],
        )

    def test_round_filters_with_normalized_query_for_cross_language_recall(
        self,
    ) -> None:
        relevance_filter = RecordingFilter()
        agent = SearchAgent(
            openalex_provider=CapturingProvider("openalex"),
            llm_client=LLMClient(LLMConfig(api_key="")),
            relevance_filter=relevance_filter,
            use_dual_source=False,
        )
        analyzed = AnalyzedQuery(
            original_query="使用查询分解的学术论文检索智能体",
            normalized_query=(
                "academic paper retrieval agent using query decomposition"
            ),
            sub_queries=["academic paper retrieval agent"],
        )

        agent._execute_search_round(
            analyzed.sub_queries,
            analyzed,
            max_api_calls=1,
        )

        self.assertEqual(
            relevance_filter.queries,
            ["academic paper retrieval agent"],
        )

    def test_open_semantic_circuit_is_not_scheduled_again(self) -> None:
        openalex = CapturingProvider("openalex")
        semantic = OpenCircuitProvider("semantic")
        agent = SearchAgent(
            openalex_provider=openalex,
            semantic_scholar_provider=semantic,
            llm_client=LLMClient(LLMConfig(api_key="")),
            relevance_filter=PassThroughFilter(),
            use_dual_source=True,
        )
        analyzed = AnalyzedQuery(
            original_query="academic paper search",
            normalized_query="academic paper search",
            sub_queries=["one", "two", "three"],
        )

        result = agent._execute_search_round(
            analyzed.sub_queries,
            analyzed,
            max_api_calls=3,
        )

        self.assertEqual(openalex.query_counts, [3])
        self.assertEqual(semantic.query_counts, [])
        self.assertEqual(result.api_calls, 3)


if __name__ == "__main__":
    unittest.main()
