import unittest

from scholarpilot.identity import normalize_doi, upsert_paper
from scholarpilot.models import Paper


def make_paper(
    paper_id: str,
    doi: str,
    *,
    abstract: str,
    source: str,
) -> Paper:
    return Paper(
        id=paper_id,
        title="A Shared Academic Paper",
        abstract=abstract,
        year=2025,
        authors=["Ada Author"],
        venue="ACL",
        cited_by_count=10,
        url=doi,
        doi=doi,
        sources=[source],
    )


class PaperIdentityTest(unittest.TestCase):
    def test_normalizes_and_merges_cross_provider_doi_records(self) -> None:
        self.assertEqual(
            normalize_doi("https://doi.org/10.1234/ABC.5"),
            "10.1234/abc.5",
        )
        store: dict[str, Paper] = {}
        self.assertTrue(
            upsert_paper(
                store,
                make_paper(
                    "https://openalex.org/W1",
                    "https://doi.org/10.1234/ABC.5",
                    abstract="short",
                    source="openalex",
                ),
            )
        )
        self.assertFalse(
            upsert_paper(
                store,
                make_paper(
                    "s2-paper-id",
                    "10.1234/abc.5",
                    abstract="a much richer abstract from another provider",
                    source="semantic_scholar",
                ),
            )
        )
        self.assertEqual(len(store), 1)
        merged = next(iter(store.values()))
        self.assertEqual(merged.doi, "10.1234/abc.5")
        self.assertEqual(
            merged.sources, ["openalex", "semantic_scholar"]
        )
        self.assertIn("richer abstract", merged.abstract)


if __name__ == "__main__":
    unittest.main()
