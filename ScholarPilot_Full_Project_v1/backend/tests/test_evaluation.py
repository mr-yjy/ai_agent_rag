import unittest

from scholarpilot.evaluation import (
    Evaluator,
    RelevantPaper,
    compute_entity_f1,
)


class EvaluationIdentityTest(unittest.TestCase):
    def test_aliases_count_as_one_relevant_work(self) -> None:
        relevant = [
            RelevantPaper(
                ids=["pasa-2025", "arxiv:2501.10120"],
                titles=[
                    "PaSa: An LLM Agent for Comprehensive Academic Paper Search"
                ],
            )
        ]
        retrieved = [
            {
                "id": "https://openalex.org/W123",
                "url": "https://arxiv.org/abs/2501.10120v2",
                "title": (
                    "PaSa: An LLM Agent for Comprehensive Academic Paper Search"
                ),
            }
        ]
        precision, recall, f1, hits, misses = compute_entity_f1(
            retrieved, relevant
        )
        self.assertEqual((precision, recall, f1), (1.0, 1.0, 1.0))
        self.assertEqual(hits, 1)
        self.assertEqual(misses, [])

    def test_legacy_dataset_collapses_parallel_alias_lists(self) -> None:
        evaluator = Evaluator()
        queries = evaluator.load_test_queries()
        first = queries[0]
        self.assertEqual(len(first.relevant_paper_ids), 8)
        self.assertEqual(len(first.relevant_papers), 4)
        self.assertEqual(len(first.relevant_papers[0].ids), 2)
        issues = evaluator.validate_test_queries(queries)
        self.assertTrue(
            any(
                issue.query_id == "q003"
                and issue.code == "year_constraint_conflict"
                for issue in issues
            )
        )


if __name__ == "__main__":
    unittest.main()
