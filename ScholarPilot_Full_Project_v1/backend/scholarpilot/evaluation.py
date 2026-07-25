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
import hashlib
import json
import math
import platform
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import (
    config_hash,
    get_config,
    reproducible_config_snapshot,
)
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
    split: str = "development"


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
    precision_at_10: float = 0.0
    precision_at_20: float = 0.0
    recall_at_20: float = 0.0
    recall_at_50: float = 0.0
    f1_at_20: float = 0.0
    request_id: str = ""
    status: str = "failed"
    error_code: str = ""
    llm_calls: int = 0
    token_usage: dict[str, int] = field(default_factory=dict)
    stage_timings: dict[str, int] = field(default_factory=dict)
    retrieved_papers: list[dict[str, str]] = field(default_factory=list)


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
    latency_p50_ms: int = 0
    latency_p95_ms: int = 0
    success_rate: float = 0.0
    timeout_rate: float = 0.0
    rate_limit_rate: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


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
        *,
        random_seed: int = 20260724,
        experiment_name: str = "v0.6-default",
    ) -> None:
        self.service = search_service or SearchService()
        self.data_dir = data_dir or get_config().evaluation_data_path.parent
        self.config = get_config()
        self.random_seed = random_seed
        self.experiment_name = experiment_name
        self.dataset_version = "unknown"

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
        self.dataset_version = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
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
                split=item.get("split", "development"),
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
        limit: int = 20,
    ) -> QueryResult:
        """Evaluate search quality for a single query."""
        started = time.perf_counter()

        try:
            response = self.service.search(
                test.query,
                limit=max(50, limit),
            )
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
                error_code=str(getattr(exc, "code", type(exc).__name__)),
            )

        elapsed = int((time.perf_counter() - started) * 1000)

        retrieved_titles: list[str] = []
        for paper in results:
            retrieved_titles.append(paper.get("title", ""))

        relevant_entities = test.relevant_papers or _legacy_relevant_papers(
            test.relevant_paper_ids, test.relevant_titles
        )
        top_10 = compute_entity_f1(results[:10], relevant_entities)
        top_20 = compute_entity_f1(results[:20], relevant_entities)
        top_50 = compute_entity_f1(results[:50], relevant_entities)
        precision, recall, f1, relevant_count, relevant_misses = (
            top_20
        )

        return QueryResult(
            query_id=test.id,
            query=test.query,
            precision=precision,
            recall=recall,
            f1_score=f1,
            retrieved_count=len(results[:20]),
            relevant_retrieved=relevant_count,
            total_relevant=len(relevant_entities),
            retrieved_titles=retrieved_titles,
            relevant_misses=relevant_misses,
            api_calls=stats.get("apiCalls", 0),
            token_estimate=stats.get("tokenEstimate", 0),
            elapsed_ms=elapsed,
            candidate_count=stats.get("candidateCount", 0),
            precision_at_10=top_10[0],
            precision_at_20=top_20[0],
            recall_at_20=top_20[1],
            recall_at_50=top_50[1],
            f1_at_20=top_20[2],
            request_id=str(response.get("requestId", "")),
            status=str(response.get("status", "success")),
            llm_calls=int(stats.get("llmCalls", 0)),
            token_usage={
                str(key): int(value)
                for key, value in stats.get("tokenUsage", {}).items()
                if isinstance(value, (int, float))
            },
            stage_timings={
                str(key): int(value)
                for key, value in stats.get("stageTimings", {}).items()
                if isinstance(value, (int, float))
            },
            retrieved_papers=[
                {
                    "id": str(paper.get("id", "")),
                    "doi": str(paper.get("doi", "")),
                    "title": str(paper.get("title", "")),
                }
                for paper in results[:50]
            ],
        )

    def evaluate(
        self,
        test_queries: list[TestQuery] | None = None,
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

            result = self.evaluate_query(test, limit=limit)
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

        latencies = sorted(result.elapsed_ms for result in results)

        def percentile(values: list[int], quantile: float) -> int:
            if not values:
                return 0
            index = max(
                0,
                min(
                    len(values) - 1,
                    math.ceil(len(values) * quantile) - 1,
                ),
            )
            return values[index]

        successful = [
            result
            for result in results
            if result.status in {"success", "no_results", "degraded"}
        ]
        timeout_count = sum(
            "timeout" in result.error_code.casefold()
            or "deadline" in result.error_code.casefold()
            for result in results
        )
        rate_limit_count = sum(
            "rate_limit" in result.error_code.casefold()
            or "429" in result.error_code
            for result in results
        )
        project_root = Path(__file__).resolve().parents[2]
        worktree_hash = ""
        code_dirty = False
        try:
            code_version = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout.strip()
            status_output = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout
            code_dirty = bool(status_output.strip())
            if code_dirty:
                digest = hashlib.sha256()
                diff = subprocess.run(
                    ["git", "diff", "--binary", "HEAD"],
                    cwd=project_root,
                    check=True,
                    capture_output=True,
                    timeout=5,
                ).stdout
                digest.update(diff)
                for line in status_output.splitlines():
                    relative = line[3:].strip()
                    path = project_root / relative
                    if line.startswith("??") and path.is_file():
                        digest.update(relative.encode("utf-8"))
                        digest.update(path.read_bytes())
                worktree_hash = digest.hexdigest()[:16]
        except (OSError, subprocess.SubprocessError):
            code_version = "unknown"
        metadata = {
            "schemaVersion": "1.0",
            "experimentName": self.experiment_name,
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
            "applicationVersion": __version__,
            "codeVersion": code_version,
            "codeDirty": code_dirty,
            "worktreeHash": worktree_hash,
            "configHash": config_hash(self.config),
            "config": reproducible_config_snapshot(self.config),
            "modelVersion": self.config.llm.model,
            "datasetVersion": self.dataset_version,
            "randomSeed": self.random_seed,
            "pythonVersion": platform.python_version(),
        }

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
            latency_p50_ms=percentile(latencies, 0.50),
            latency_p95_ms=percentile(latencies, 0.95),
            success_rate=len(successful) / n if n else 0.0,
            timeout_rate=timeout_count / n if n else 0.0,
            rate_limit_rate=rate_limit_count / n if n else 0.0,
            metadata=metadata,
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
                "P@10",
                "P@20",
                "R@20",
                "R@50",
                "F1@20",
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
                    round(r.precision_at_10, 4),
                    round(r.precision_at_20, 4),
                    round(r.recall_at_20, 4),
                    round(r.recall_at_50, 4),
                    round(r.f1_at_20, 4),
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
                round(
                    sum(r.precision_at_10 for r in report.results)
                    / max(report.total_queries, 1),
                    4,
                ),
                round(report.avg_precision, 4),
                round(report.avg_recall, 4),
                round(
                    sum(r.recall_at_50 for r in report.results)
                    / max(report.total_queries, 1),
                    4,
                ),
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
    def export_json(
        report: EvaluationReport,
        path: Path,
    ) -> None:
        """Write a machine-readable, per-query reproducibility artifact."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                asdict(report),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print(f"[Evaluator] Machine-readable report exported to {path}")

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
        print(
            f"  Latency P50/P95:     "
            f"{report.latency_p50_ms}/{report.latency_p95_ms}ms"
        )
        print(f"  Success rate:        {report.success_rate:.1%}")
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
