import unittest

from scholarpilot.planner import build_query_plan


class QueryPlannerTest(unittest.TestCase):
    def test_long_english_query_uses_compact_provider_routes(self) -> None:
        query = (
            "vision transformer self-supervised learning "
            "medical image segmentation"
        )
        plan = build_query_plan(query)

        self.assertIn(
            "vision transformer medical image segmentation",
            plan.subqueries,
        )
        self.assertIn(
            "vision transformer self-supervised learning",
            plan.subqueries,
        )
        self.assertTrue(
            all(len(route.split()) <= 5 for route in plan.subqueries[:3])
        )

    def test_extracts_years_and_methods(self) -> None:
        plan = build_query_plan(
            "寻找2024—2026年使用查询分解或引文扩展进行学术论文检索的LLM Agent论文"
        )
        self.assertEqual(plan.year_from, 2024)
        self.assertEqual(plan.year_to, 2026)
        self.assertIn("query decomposition", plan.must_have)
        self.assertIn("citation expansion", plan.must_have)
        self.assertIn("academic paper search", plan.normalized_query)
        self.assertGreaterEqual(len(plan.subqueries), 2)

    def test_extracts_preferences_and_exclusions(self) -> None:
        plan = build_query_plan(
            "检索RAG重排序论文，优先开源代码和实验，排除纯综述"
        )
        self.assertIn("open source", plan.preferred)
        self.assertIn("evaluation", plan.preferred)
        self.assertEqual(plan.exclude, ["纯综述"])

    def test_understands_relative_years_and_boolean_or(self) -> None:
        plan = build_query_plan(
            "Find papers after 2024 using query decomposition or citation expansion"
        )
        self.assertEqual(plan.year_from, 2025)
        self.assertIsNone(plan.year_to)
        self.assertIn(
            ["query decomposition", "citation expansion"],
            plan.constraint_groups,
        )


if __name__ == "__main__":
    unittest.main()
