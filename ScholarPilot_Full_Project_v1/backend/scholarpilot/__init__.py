"""ScholarPilot - LLM-powered Academic Paper Search Agent.

A competition entry for intelligent academic paper search and recommendation,
featuring LLM-powered query understanding, iterative search strategy,
and hybrid heuristic + LLM paper ranking.
"""

from __future__ import annotations

__version__ = "0.6.0"
__all__ = [
    "SearchService",
    "QueryAnalyzer",
    "SearchAgent",
    "LLMRanker",
    "Evaluator",
]

from .service import SearchService
from .query_analyzer import QueryAnalyzer
from .search_agent import SearchAgent
from .llm_ranker import LLMRanker
from .evaluation import Evaluator
