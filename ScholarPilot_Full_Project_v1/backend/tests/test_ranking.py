import unittest

from scholarpilot.planner import build_query_plan
from scholarpilot.models import Paper, QueryPlan
from scholarpilot.ranking import _constraint_coverage, rank_papers


class RankingTest(unittest.TestCase):
    def test_returns_stable_ranked_results(self) -> None:
        plan = build_query_plan(
            "寻找2024—2026年使用查询分解或引文扩展进行学术论文检索的LLM Agent论文"
        )
        titles = [
            "Query decomposition for academic search agents",
            "Citation expansion with large language model agents",
            "Iterative literature retrieval using query decomposition",
            "Evidence-aware LLM agents for scholarly search",
            "Citation graph planning for paper retrieval agents",
        ]
        papers = [
            Paper(
                id=f"paper-{index}",
                title=title,
                abstract=(
                    f"{title}. We evaluate complex academic paper retrieval "
                    "with query decomposition and citation expansion."
                ),
                year=2024 + index % 3,
                authors=["Test Author"],
                venue="Test Venue",
                cited_by_count=50 - index,
                url=f"https://example.test/paper-{index}",
            )
            for index, title in enumerate(titles)
        ]
        ranked = rank_papers(papers, plan, limit=5)

        self.assertEqual(len(ranked), 5)
        self.assertEqual([item.rank for item in ranked], [1, 2, 3, 4, 5])
        self.assertGreaterEqual(ranked[0].score, ranked[1].score)
        self.assertTrue(ranked[0].evidence)
        self.assertGreater(ranked[0].score_breakdown.relevance, 0)

    def test_or_group_accepts_either_term_and_year_is_hard_constraint(self) -> None:
        plan = QueryPlan(
            original_query="query decomposition or citation expansion after 2024",
            normalized_query="query decomposition or citation expansion",
            year_from=2025,
            constraint_groups=[
                ["query decomposition", "citation expansion"]
            ],
            must_have=["query decomposition", "citation expansion"],
            subqueries=[],
        )
        matching = Paper(
            id="matching",
            title="Citation expansion for literature search",
            abstract="We explore a citation expansion method.",
            year=2025,
            authors=[],
            venue="Test",
            cited_by_count=0,
            url="#",
        )
        out_of_range = Paper(
            id="old",
            title="Query decomposition for literature search",
            abstract="We explore query decomposition.",
            year=2024,
            authors=[],
            venue="Test",
            cited_by_count=100,
            url="#",
        )
        self.assertEqual(_constraint_coverage(matching, plan), 1.0)
        ranked = rank_papers([out_of_range, matching], plan, limit=5)
        self.assertEqual([item.paper.id for item in ranked], ["matching"])


if __name__ == "__main__":
    unittest.main()
