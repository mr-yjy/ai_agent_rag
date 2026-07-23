import unittest

from scholarpilot.planner import build_query_plan
from scholarpilot.providers import DemoProvider
from scholarpilot.ranking import rank_papers


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


if __name__ == "__main__":
    unittest.main()

