"""Evaluation pipeline for ScholarPilot competition.

Computes Precision, Recall, F1 Score against ground-truth paper sets.
Supports both public and private test sets.

Key metrics (competition scoring):
- F1 Score (70% weight): Primary measure of precision-recall balance
- API Calls / Token Usage (20% weight): Efficiency measure
- Result Structuredness (10% weight): Output quality

Usage:
    evaluator = Evaluator()
    results = evaluator.evaluate(test_queries)
    evaluator.print_report(results)
"""

from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import get_config
from .models import Paper
from .service import SearchService


@dataclass(slots=True)
class TestQuery:
    """Single test query with ground truth."""

    id: str
    query: str
    relevant_paper_ids: list[str]  # Ground truth: set of relevant paper DOIs/IDs
    relevant_titles: list[str] = field(default_factory=list)  # Display purposes
    notes: str = ""
    discipline: str = ""  # "computer_science"|"biomedical"|"chemistry_materials"|"finance_economics"|"security_crypto"


@dataclass(slots=True)
class QueryResult:
    """Evaluation result for a single query."""

    query_id: str
    query: str
    precision: float
    recall: float
    f1_score: float
    retrieved_count: int
    relevant_retrieved: int
    total_relevant: int
    retrieved_titles: list[str]
    relevant_misses: list[str]
    api_calls: int
    token_estimate: int
    elapsed_ms: int
    candidate_count: int


@dataclass(slots=True)
class DisciplineReport:
    """Per-discipline evaluation metrics."""
    discipline: str = ""
    query_count: int = 0
    avg_precision: float = 0.0
    avg_recall: float = 0.0
    avg_f1: float = 0.0


@dataclass(slots=True)
class EvaluationReport:
    """Full evaluation report."""

    results: list[QueryResult] = field(default_factory=list)
    total_queries: int = 0
    avg_precision: float = 0.0
    avg_recall: float = 0.0
    avg_f1: float = 0.0
    micro_precision: float = 0.0
    micro_recall: float = 0.0
    micro_f1: float = 0.0
    total_api_calls: int = 0
    total_tokens: int = 0
    total_elapsed_ms: int = 0
    avg_api_calls_per_query: float = 0.0
    discipline_reports: list[DisciplineReport] = field(default_factory=list)


def compute_f1(
    retrieved: list[str],
    relevant: list[str],
) -> tuple[float, float, float, int]:
    """Compute Precision, Recall, and F1 Score.

    Args:
        retrieved: List of paper IDs that were retrieved
        relevant: List of paper IDs that are relevant (ground truth)

    Returns:
        (precision, recall, f1, relevant_retrieved_count)
    """
    retrieved_set = set(retrieved)
    relevant_set = set(relevant)

    relevant_retrieved = len(retrieved_set & relevant_set)

    precision = relevant_retrieved / len(retrieved_set) if retrieved_set else 0.0
    recall = relevant_retrieved / len(relevant_set) if relevant_set else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return precision, recall, f1, relevant_retrieved


class Evaluator:
    """Evaluation pipeline for ScholarPilot search system."""

    def __init__(
        self,
        search_service: SearchService | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.service = search_service or SearchService()
        self.data_dir = data_dir or get_config().evaluation_data_path.parent
        self.config = get_config()

    def load_test_queries(self, path: Path | None = None) -> list[TestQuery]:
        """Load test queries from a JSON file.

        Expected format:
        [
            {
                "id": "q001",
                "query": "Find papers about...",
                "relevant_paper_ids": ["doi:10.xxx/xxx", "arxiv:2501.10120"],
                "relevant_titles": ["Title 1", "Title 2"],
                "notes": "Covers method X"
            },
            ...
        ]
        """
        path = path or self.config.evaluation_data_path
        if not path.exists():
            print(f"[Evaluator] No test queries found at {path}")
            return []

        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return [
            TestQuery(
                id=item.get("id", f"q{idx:03d}"),
                query=item.get("query", ""),
                relevant_paper_ids=item.get("relevant_paper_ids", []),
                relevant_titles=item.get("relevant_titles", []),
                notes=item.get("notes", ""),
                discipline=item.get("discipline", ""),
            )
            for idx, item in enumerate(data)
            if item.get("query")
        ]

    def evaluate_query(
        self,
        test: TestQuery,
        mode: str = "live",
        limit: int = 20,
    ) -> QueryResult:
        """Evaluate search quality for a single query."""
        started = time.perf_counter()

        try:
            response = self.service.search(test.query, mode=mode, limit=limit)
            results = response.get("results", [])
            stats = response.get("stats", {})
        except Exception as exc:
            # Return zero result on failure
            return QueryResult(
                query_id=test.id,
                query=test.query,
                precision=0.0,
                recall=0.0,
                f1_score=0.0,
                retrieved_count=0,
                relevant_retrieved=0,
                total_relevant=len(test.relevant_paper_ids),
                retrieved_titles=[],
                relevant_misses=test.relevant_titles or [],
                api_calls=0,
                token_estimate=0,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                candidate_count=0,
            )

        elapsed = int((time.perf_counter() - started) * 1000)

        # Extract retrieved paper IDs
        retrieved_ids: list[str] = []
        retrieved_titles: list[str] = []
        for paper in results:
            pid = paper.get("doi") or paper.get("id") or paper.get("title", "")
            retrieved_ids.append(pid)
            retrieved_titles.append(paper.get("title", ""))

        precision, recall, f1, relevant_count = compute_f1(
            retrieved_ids, test.relevant_paper_ids
        )

        # Find missed relevant papers
        retrieved_set = set(retrieved_ids)
        relevant_misses = [
            title
            for i, (pid, title) in enumerate(
                zip(test.relevant_paper_ids, test.relevant_titles or [])
            )
            if pid not in retrieved_set
        ]

        return QueryResult(
            query_id=test.id,
            query=test.query,
            precision=precision,
            recall=recall,
            f1_score=f1,
            retrieved_count=len(retrieved_ids),
            relevant_retrieved=relevant_count,
            total_relevant=len(test.relevant_paper_ids),
            retrieved_titles=retrieved_titles,
            relevant_misses=relevant_misses,
            api_calls=stats.get("apiCalls", 0),
            token_estimate=stats.get("tokenEstimate", 0),
            elapsed_ms=elapsed,
            candidate_count=stats.get("candidateCount", 0),
        )

    def evaluate(
        self,
        test_queries: list[TestQuery] | None = None,
        mode: str = "live",
        limit: int = 20,
        verbose: bool = True,
    ) -> EvaluationReport:
        """Run full evaluation on a set of test queries."""
        if test_queries is None:
            test_queries = self.load_test_queries()

        if not test_queries:
            print("[Evaluator] No test queries to evaluate.")
            return EvaluationReport()

        results: list[QueryResult] = []
        for idx, test in enumerate(test_queries):
            if verbose:
                print(
                    f"\n[{idx + 1}/{len(test_queries)}] Evaluating: {test.query[:60]}..."
                )

            result = self.evaluate_query(test, mode=mode, limit=limit)
            results.append(result)

            if verbose:
                print(
                    f"  F1={result.f1_score:.3f}  "
                    f"P={result.precision:.3f}  "
                    f"R={result.recall:.3f}  "
                    f"({result.relevant_retrieved}/{result.total_relevant} relevant)"
                )

        # Macro averages
        n = len(results)
        avg_precision = sum(r.precision for r in results) / n
        avg_recall = sum(r.recall for r in results) / n
        avg_f1 = sum(r.f1_score for r in results) / n

        # Micro averages (aggregate all retrieved/relevant)
        total_retrieved = sum(r.retrieved_count for r in results)
        total_relevant = sum(r.total_relevant for r in results)
        total_relevant_retrieved = sum(r.relevant_retrieved for r in results)
        micro_precision = total_relevant_retrieved / total_retrieved if total_retrieved else 0.0
        micro_recall = total_relevant_retrieved / total_relevant if total_relevant else 0.0
        micro_f1 = (
            2 * micro_precision * micro_recall / (micro_precision + micro_recall)
            if (micro_precision + micro_recall) > 0
            else 0.0
        )

        total_api = sum(r.api_calls for r in results)
        total_tokens = sum(r.token_estimate for r in results)
        total_elapsed = sum(r.elapsed_ms for r in results)

        # ---- Per-discipline breakdown ----
        discipline_map: dict[str, list[QueryResult]] = {}
        for idx, result in enumerate(results):
            test_query = test_queries[idx] if idx < len(test_queries) else None
            disc = test_query.discipline if test_query else "unknown"
            if disc not in discipline_map:
                discipline_map[disc] = []
            discipline_map[disc].append(result)

        discipline_reports: list[DisciplineReport] = []
        disc_labels = {
            "computer_science": "计算机科学",
            "biomedical": "生物医学",
            "chemistry_materials": "化学与材料",
            "finance_economics": "金融与经济",
            "security_crypto": "安全与密码学",
            "": "未分类",
        }
        for disc, disc_results in discipline_map.items():
            dn = len(disc_results)
            discipline_reports.append(DisciplineReport(
                discipline=disc_labels.get(disc, disc),
                query_count=dn,
                avg_precision=sum(r.precision for r in disc_results) / dn,
                avg_recall=sum(r.recall for r in disc_results) / dn,
                avg_f1=sum(r.f1_score for r in disc_results) / dn,
            ))

        return EvaluationReport(
            results=results,
            total_queries=n,
            avg_precision=avg_precision,
            avg_recall=avg_recall,
            avg_f1=avg_f1,
            micro_precision=micro_precision,
            micro_recall=micro_recall,
            micro_f1=micro_f1,
            total_api_calls=total_api,
            total_tokens=total_tokens,
            total_elapsed_ms=total_elapsed,
            avg_api_calls_per_query=total_api / n if n else 0.0,
            discipline_reports=discipline_reports,
        )

    def export_results(
        self,
        report: EvaluationReport,
        path: Path | None = None,
    ) -> None:
        """Export evaluation results to CSV."""
        path = path or self.data_dir / "evaluation_results.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Query ID",
                "Query",
                "Precision",
                "Recall",
                "F1",
                "Retrieved",
                "Relevant Retrieved",
                "Total Relevant",
                "API Calls",
                "Tokens",
                "Elapsed (ms)",
            ])
            for r in report.results:
                writer.writerow([
                    r.query_id,
                    r.query[:80],
                    round(r.precision, 4),
                    round(r.recall, 4),
                    round(r.f1_score, 4),
                    r.retrieved_count,
                    r.relevant_retrieved,
                    r.total_relevant,
                    r.api_calls,
                    r.token_estimate,
                    r.elapsed_ms,
                ])
            writer.writerow([])
            writer.writerow([
                "AVERAGE",
                "",
                round(report.avg_precision, 4),
                round(report.avg_recall, 4),
                round(report.avg_f1, 4),
                "",
                "",
                "",
                round(report.avg_api_calls_per_query, 1),
                round(report.total_tokens / report.total_queries, 0),
                round(report.total_elapsed_ms / report.total_queries, 0),
            ])
        print(f"[Evaluator] Results exported to {path}")

    @staticmethod
    def print_report(report: EvaluationReport) -> None:
        """Print a formatted evaluation report with discipline breakdown."""
        print("\n" + "=" * 60)
        print("  ScholarPilot Evaluation Report")
        print("=" * 60)
        print(f"  Total queries:      {report.total_queries}")
        print(f"  Total API calls:     {report.total_api_calls}")
        print(f"  Total tokens:        {report.total_tokens}")
        print(f"  Total time:          {report.total_elapsed_ms}ms")
        print()
        print(f"  +- Macro F1:         {report.avg_f1:.4f}")
        print(f"  +- Macro Precision:  {report.avg_precision:.4f}")
        print(f"  +- Macro Recall:     {report.avg_recall:.4f}")
        print(f"  +- Micro F1:         {report.micro_f1:.4f}")
        print(f"  +- Micro Precision:  {report.micro_precision:.4f}")
        print(f"  +- Micro Recall:     {report.micro_recall:.4f}")
        print()
        if report.discipline_reports:
            print("  --- Discipline Breakdown ---")
            for dr in report.discipline_reports:
                print(
                    f"  [{dr.discipline}] {dr.query_count} queries | "
                    f"F1={dr.avg_f1:.4f} P={dr.avg_precision:.4f} R={dr.avg_recall:.4f}"
                )
            print()
        print(f"  [-] Avg API calls:    {report.avg_api_calls_per_query:.1f}/query")
        print(f"  [-] Avg tokens:       {report.total_tokens / max(report.total_queries, 1):.0f}/query")
        print(f"  [-] Avg latency:      {report.total_elapsed_ms / max(report.total_queries, 1):.0f}ms/query")
        print("=" * 60)
