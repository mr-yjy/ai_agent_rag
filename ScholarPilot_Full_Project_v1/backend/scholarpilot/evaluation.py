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
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_config
from .identity import normalize_external_id, normalize_title
from .service import SearchService


@dataclass(slots=True)
class RelevantPaper:
    """One ground-truth work with provider-specific identifier aliases."""

    ids: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TestQuery:
    """Single test query with ground truth."""

    id: str
    query: str
    relevant_paper_ids: list[str]  # Ground truth: set of relevant paper DOIs/IDs
    relevant_titles: list[str] = field(default_factory=list)  # Display purposes
    notes: str = ""
    discipline: str = ""  # "computer_science"|"biomedical"|"chemistry_materials"|"finance_economics"|"security_crypto"
    relevant_papers: list[RelevantPaper] = field(default_factory=list)


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


@dataclass(slots=True)
class BenchmarkIssue:
    query_id: str
    severity: str
    code: str
    message: str


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
    def canonical(value: str) -> str:
        aliases = normalize_external_id(value)
        preferred = sorted(
            aliases,
            key=lambda item: (
                not item.startswith("doi:"),
                not item.startswith("arxiv:"),
                item,
            ),
        )
        return preferred[0] if preferred else value.casefold().strip()

    retrieved_set = {canonical(value) for value in retrieved if value}
    relevant_set = {canonical(value) for value in relevant if value}

    relevant_retrieved = len(retrieved_set & relevant_set)

    precision = relevant_retrieved / len(retrieved_set) if retrieved_set else 0.0
    recall = relevant_retrieved / len(relevant_set) if relevant_set else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return precision, recall, f1, relevant_retrieved


def _legacy_relevant_papers(
    ids: list[str], titles: list[str]
) -> list[RelevantPaper]:
    """Convert the v0.3 parallel lists without counting aliases as papers."""
    if not titles:
        return [RelevantPaper(ids=[value]) for value in ids]
    if len(ids) == len(titles) * 2:
        return [
            RelevantPaper(ids=[ids[index], ids[index + len(titles)]], titles=[title])
            for index, title in enumerate(titles)
        ]
    entities = [
        RelevantPaper(
            ids=[ids[index]] if index < len(ids) else [],
            titles=[title],
        )
        for index, title in enumerate(titles)
    ]
    entities.extend(
        RelevantPaper(ids=[value]) for value in ids[len(titles) :]
    )
    return entities


def _title_matches(left: str, right: str) -> bool:
    left_normalized = normalize_title(left)
    right_normalized = normalize_title(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    shorter = min(len(left_tokens), len(right_tokens))
    if shorter < 4:
        return False
    containment = len(left_tokens & right_tokens) / shorter
    return containment >= 0.92


def compute_entity_f1(
    retrieved: list[dict[str, Any]],
    relevant: list[RelevantPaper],
) -> tuple[float, float, float, int, list[str]]:
    """Match works by any ID alias or a conservative normalized-title match."""
    unique_retrieved: dict[str, dict[str, Any]] = {}
    for paper in retrieved:
        title = str(paper.get("title", ""))
        aliases: set[str] = set()
        for key in ("doi", "id", "url"):
            aliases.update(normalize_external_id(str(paper.get(key, ""))))
        canonical = next(
            (
                value
                for value in sorted(aliases)
                if value.startswith(("doi:", "arxiv:", "openalex:"))
            ),
            f"title:{normalize_title(title)}",
        )
        unique_retrieved.setdefault(canonical, paper)

    matched_entities: set[int] = set()
    for paper in unique_retrieved.values():
        aliases: set[str] = set()
        for key in ("doi", "id", "url"):
            aliases.update(normalize_external_id(str(paper.get(key, ""))))
        title = str(paper.get("title", ""))
        for index, entity in enumerate(relevant):
            if index in matched_entities:
                continue
            entity_aliases: set[str] = set()
            for identifier in entity.ids:
                entity_aliases.update(normalize_external_id(identifier))
            id_match = bool(aliases & entity_aliases)
            title_match = any(
                _title_matches(title, expected) for expected in entity.titles
            )
            if id_match or title_match:
                matched_entities.add(index)
                break

    true_positives = len(matched_entities)
    precision = (
        true_positives / len(unique_retrieved) if unique_retrieved else 0.0
    )
    recall = true_positives / len(relevant) if relevant else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    misses = [
        (entity.titles[0] if entity.titles else entity.ids[0])
        for index, entity in enumerate(relevant)
        if index not in matched_entities and (entity.titles or entity.ids)
    ]
    return precision, recall, f1, true_positives, misses


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
        queries: list[TestQuery] = []
        for idx, item in enumerate(data):
            if not item.get("query"):
                continue
            relevant_papers_payload = item.get("relevant_papers", [])
            if relevant_papers_payload:
                relevant_papers = [
                    RelevantPaper(
                        ids=[str(value) for value in paper.get("ids", [])],
                        titles=[str(value) for value in paper.get("titles", [])],
                    )
                    for paper in relevant_papers_payload
                ]
            else:
                relevant_papers = _legacy_relevant_papers(
                    item.get("relevant_paper_ids", []),
                    item.get("relevant_titles", []),
                )
            queries.append(TestQuery(
                id=item.get("id", f"q{idx:03d}"),
                query=item.get("query", ""),
                relevant_paper_ids=item.get("relevant_paper_ids", []),
                relevant_titles=item.get("relevant_titles", []),
                notes=item.get("notes", ""),
                discipline=item.get("discipline", ""),
                relevant_papers=relevant_papers,
            ))
        return queries

    @staticmethod
    def validate_test_queries(
        test_queries: list[TestQuery],
    ) -> list[BenchmarkIssue]:
        """Audit ground truth before an experiment is treated as evidence."""
        from .planner import build_query_plan

        issues: list[BenchmarkIssue] = []
        for test in test_queries:
            entities = test.relevant_papers or _legacy_relevant_papers(
                test.relevant_paper_ids, test.relevant_titles
            )
            if not entities:
                issues.append(
                    BenchmarkIssue(
                        test.id,
                        "error",
                        "missing_ground_truth",
                        "查询没有相关论文标注。",
                    )
                )
                continue
            if len(test.relevant_paper_ids) > len(entities):
                issues.append(
                    BenchmarkIssue(
                        test.id,
                        "info",
                        "aliases_collapsed",
                        (
                            f"{len(test.relevant_paper_ids)} 个旧 ID 已折叠为 "
                            f"{len(entities)} 篇论文实体。"
                        ),
                    )
                )

            plan = build_query_plan(test.query)
            for entity in entities:
                aliases = {
                    alias
                    for identifier in entity.ids
                    for alias in normalize_external_id(identifier)
                }
                if not any(
                    alias.startswith(("doi:", "arxiv:", "openalex:"))
                    for alias in aliases
                ):
                    issues.append(
                        BenchmarkIssue(
                            test.id,
                            "warning",
                            "non_resolvable_identifier",
                            (
                                f"标注 {entity.ids!r} 没有 DOI/arXiv/OpenAlex "
                                "等可跨数据源复现的 ID。"
                            ),
                        )
                    )

                # Local IDs in the current development set end in a year.
                # Flag obvious query/label contradictions for human review.
                years = {
                    int(match.group(1))
                    for identifier in entity.ids
                    if (
                        match := re.search(
                            r"[-_:]((?:19|20)\d{2})$", identifier
                        )
                    )
                }
                for year in years:
                    outside = (
                        plan.year_from is not None and year < plan.year_from
                    ) or (
                        plan.year_to is not None and year > plan.year_to
                    )
                    if outside:
                        issues.append(
                            BenchmarkIssue(
                                test.id,
                                "warning",
                                "year_constraint_conflict",
                                (
                                    f"标注 ID 暗示年份 {year}，但查询时间范围为 "
                                    f"{plan.year_from or '*'}—{plan.year_to or '*'}。"
                                ),
                            )
                        )
        return issues

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
            relevant_entities = test.relevant_papers or _legacy_relevant_papers(
                test.relevant_paper_ids, test.relevant_titles
            )
            return QueryResult(
                query_id=test.id,
                query=test.query,
                precision=0.0,
                recall=0.0,
                f1_score=0.0,
                retrieved_count=0,
                relevant_retrieved=0,
                total_relevant=len(relevant_entities),
                retrieved_titles=[],
                relevant_misses=[
                    entity.titles[0] if entity.titles else entity.ids[0]
                    for entity in relevant_entities
                    if entity.titles or entity.ids
                ],
                api_calls=0,
                token_estimate=0,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                candidate_count=0,
            )

        elapsed = int((time.perf_counter() - started) * 1000)

        retrieved_titles: list[str] = []
        for paper in results:
            retrieved_titles.append(paper.get("title", ""))

        relevant_entities = test.relevant_papers or _legacy_relevant_papers(
            test.relevant_paper_ids, test.relevant_titles
        )
        precision, recall, f1, relevant_count, relevant_misses = (
            compute_entity_f1(results, relevant_entities)
        )

        return QueryResult(
            query_id=test.id,
            query=test.query,
            precision=precision,
            recall=recall,
            f1_score=f1,
            retrieved_count=len(results),
            relevant_retrieved=relevant_count,
            total_relevant=len(relevant_entities),
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
