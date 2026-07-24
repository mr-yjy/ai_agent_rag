#!/usr/bin/env python3
"""Evaluation runner for ScholarPilot.

Usage:
    # Evaluate using built-in demo data (requires no API keys)
    python run_evaluation.py --mode demo

    # Evaluate using OpenAlex + LLM (requires API keys in .env)
    python run_evaluation.py --mode live --verbose

    # Evaluate with custom test queries
    python run_evaluation.py --mode demo --data path/to/queries.json

    # Export results to CSV
    python run_evaluation.py --mode demo --export results.csv
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from scholarpilot.evaluation import Evaluator
from scholarpilot.config import get_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ScholarPilot Evaluation Runner"
    )
    parser.add_argument(
        "--mode",
        choices=["demo", "live"],
        default="demo",
        help="Search mode (demo=built-in data, live=OpenAlex+LLM)",
    )
    parser.add_argument(
        "--data",
        type=str,
        default=None,
        help="Path to test queries JSON file",
    )
    parser.add_argument(
        "--export",
        type=str,
        default=None,
        help="Export results to CSV file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=True,
        help="Print per-query details",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max papers to retrieve per query",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Audit benchmark aliases, identifiers, and year constraints, then exit",
    )
    parser.add_argument(
        "--json-output",
        type=str,
        default=None,
        help="Machine-readable report path (defaults to outputs/evaluation/)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260724,
        help="Random seed recorded in the reproducibility metadata",
    )
    parser.add_argument(
        "--experiment",
        default="v0.6-default",
        help="Experiment/ablation name recorded in the report",
    )
    parser.add_argument(
        "--split",
        choices=["all", "development", "holdout"],
        default="all",
        help="Evaluate only one frozen dataset split",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  ScholarPilot Evaluation")
    print("=" * 60)
    config = get_config()
    print(f"  Mode:             {args.mode}")
    print(f"  LLM available:    {bool(config.llm.api_key)}")
    print(f"  LLM provider:     {config.llm.base_url}")
    print(f"  LLM model:        {config.llm.model}")
    print(f"  Max search rounds:{config.strategy.max_search_rounds}")
    print(f"  Citation expand:  {config.strategy.enable_citation_expansion}")
    print()

    # Load test queries
    evaluator = Evaluator(
        random_seed=args.seed,
        experiment_name=args.experiment,
    )
    if args.data:
        data_path = Path(args.data)
        if not data_path.exists():
            print(f"[Error] Test data file not found: {data_path}")
            sys.exit(1)
        test_queries = evaluator.load_test_queries(data_path)
        print(f"  Loaded {len(test_queries)} queries from {args.data}")
    else:
        test_queries = evaluator.load_test_queries()
        print(f"  Loaded {len(test_queries)} default evaluation queries")

    if not test_queries:
        print("[Error] No test queries loaded. Cannot evaluate.")
        sys.exit(1)
    if args.split != "all":
        test_queries = [
            query for query in test_queries if query.split == args.split
        ]
        print(f"  Selected {len(test_queries)} queries from {args.split}")
        if not test_queries:
            print("[Error] The selected split has no queries.")
            sys.exit(1)

    issues = evaluator.validate_test_queries(test_queries)
    issue_counts = {
        severity: sum(issue.severity == severity for issue in issues)
        for severity in ("error", "warning", "info")
    }
    print(
        "  Benchmark audit: "
        f"{issue_counts['error']} errors, "
        f"{issue_counts['warning']} warnings, "
        f"{issue_counts['info']} info"
    )
    if args.validate_only:
        for issue in issues:
            print(
                f"  [{issue.severity.upper()}] {issue.query_id} "
                f"{issue.code}: {issue.message}"
            )
        sys.exit(1 if issue_counts["error"] else 0)

    # Run evaluation
    started = time.perf_counter()
    report = evaluator.evaluate(
        test_queries,
        mode=args.mode,
        limit=args.limit,
        verbose=args.verbose,
    )
    total_elapsed = time.perf_counter() - started

    # Print report
    evaluator.print_report(report)
    print(f"\n  Total evaluation time: {total_elapsed:.1f}s")

    # Export if requested
    if args.export:
        export_path = Path(args.export)
        evaluator.export_results(report, export_path)

    if args.json_output:
        json_path = Path(args.json_output)
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        json_path = (
            Path(__file__).resolve().parent.parent
            / "outputs"
            / "evaluation"
            / f"{args.experiment}-{timestamp}.json"
        )
    evaluator.export_json(report, json_path)


if __name__ == "__main__":
    main()
