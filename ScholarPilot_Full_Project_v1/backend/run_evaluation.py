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
import json
import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from scholarpilot.evaluation import Evaluator, TestQuery
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
    evaluator = Evaluator()
    if args.data:
        data_path = Path(args.data)
        if not data_path.exists():
            print(f"[Error] Test data file not found: {data_path}")
            sys.exit(1)
        with data_path.open(encoding="utf-8-sig") as f:
            raw_data = json.load(f)
        test_queries = [
            TestQuery(
                id=item.get("id", f"q{idx:03d}"),
                query=item.get("query", ""),
                relevant_paper_ids=item.get("relevant_paper_ids", []),
                relevant_titles=item.get("relevant_titles", []),
                notes=item.get("notes", ""),
            )
            for idx, item in enumerate(raw_data)
        ]
        print(f"  Loaded {len(test_queries)} queries from {args.data}")
    else:
        test_queries = evaluator.load_test_queries()
        print(f"  Loaded {len(test_queries)} default evaluation queries")

    if not test_queries:
        print("[Error] No test queries loaded. Cannot evaluate.")
        sys.exit(1)

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


if __name__ == "__main__":
    main()
