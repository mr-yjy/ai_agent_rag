import unittest

from scholarpilot.planner import build_query_plan
from scholarpilot.providers import DemoProvider
from scholarpilot.models import Paper, QueryPlan
from scholarpilot.ranking import _constraint_coverage, rank_papers


class RankingTest(unittest.TestCase):
    def test_returns_stable_ranked_results(self) -> None:
        plan = build_query_plan(
            "寻找2024—2026年使用查询分解或引文扩展进行学术论文检索的LLM Agent论文"
        )
        papers = DemoProvider().search(plan).papers
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
