"""Configuration management for ScholarPilot.

Loads settings from environment variables with sensible defaults.
All LLM interactions go through an OpenAI-compatible interface,
supporting DeepSeek, Qwen, OpenAI, and local models.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class LLMConfig:
    """LLM provider configuration (OpenAI-compatible)."""

    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    max_tokens: int = 2048
    temperature: float = 0.1
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "2048")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
            timeout_seconds=float(os.getenv("LLM_TIMEOUT", "30.0")),
        )


@dataclass(slots=True)
class SearchAPIConfig:
    """Academic search API configuration."""

    openalex_api_key: str = ""
    semantic_scholar_api_key: str = ""
    max_results_per_query: int = 25
    request_timeout: float = 15.0

    @classmethod
    def from_env(cls) -> SearchAPIConfig:
        return cls(
            openalex_api_key=os.getenv("OPENALEX_API_KEY", ""),
            semantic_scholar_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY", ""),
            max_results_per_query=int(os.getenv("MAX_RESULTS_PER_QUERY", "25")),
            request_timeout=float(os.getenv("REQUEST_TIMEOUT", "15.0")),
        )


@dataclass(slots=True)
class SearchStrategyConfig:
    """Search strategy / budget controls."""

    max_search_rounds: int = 3
    max_api_calls_per_round: int = 5
    max_total_api_calls: int = 12
    max_total_papers: int = 100
    min_papers_for_iteration: int = 3
    enable_citation_expansion: bool = True
    max_citation_hops: int = 1
    citation_expansion_per_paper: int = 5
    relevance_threshold_high: float = 0.62
    relevance_threshold_partial: float = 0.42
    selector_batch_size: int = 8
    selector_max_papers: int = 32
    llm_rerank_top_k: int = 12
    counterfactual_max_papers: int = 4
    counterfactual_boundary_margin: float = 8.0
    min_new_papers_to_continue: int = 2

    @classmethod
    def from_env(cls) -> SearchStrategyConfig:
        return cls(
            max_search_rounds=int(os.getenv("MAX_SEARCH_ROUNDS", "3")),
            max_api_calls_per_round=int(os.getenv("MAX_API_CALLS_PER_ROUND", "5")),
            max_total_api_calls=int(os.getenv("MAX_TOTAL_API_CALLS", "12")),
            max_total_papers=int(os.getenv("MAX_TOTAL_PAPERS", "100")),
            min_papers_for_iteration=int(os.getenv("MIN_PAPERS_FOR_ITERATION", "3")),
            enable_citation_expansion=os.getenv("ENABLE_CITATION_EXPANSION", "true").lower() == "true",
            max_citation_hops=int(os.getenv("MAX_CITATION_HOPS", "1")),
            citation_expansion_per_paper=int(os.getenv("CITATION_EXPANSION_PER_PAPER", "5")),
            relevance_threshold_high=float(os.getenv("RELEVANCE_THRESHOLD_HIGH", "0.62")),
            relevance_threshold_partial=float(os.getenv("RELEVANCE_THRESHOLD_PARTIAL", "0.42")),
            selector_batch_size=max(
                2, int(os.getenv("SELECTOR_BATCH_SIZE", "8"))
            ),
            selector_max_papers=max(
                4, int(os.getenv("SELECTOR_MAX_PAPERS", "32"))
            ),
            llm_rerank_top_k=max(
                1, int(os.getenv("LLM_RERANK_TOP_K", "12"))
            ),
            counterfactual_max_papers=max(
                0, int(os.getenv("COUNTERFACTUAL_MAX_PAPERS", "4"))
            ),
            counterfactual_boundary_margin=float(
                os.getenv("COUNTERFACTUAL_BOUNDARY_MARGIN", "8.0")
            ),
            min_new_papers_to_continue=max(
                1, int(os.getenv("MIN_NEW_PAPERS_TO_CONTINUE", "2"))
            ),
        )


@dataclass(slots=True)
class AppConfig:
    """Top-level application configuration."""

    llm: LLMConfig = field(default_factory=LLMConfig.from_env)
    search_api: SearchAPIConfig = field(default_factory=SearchAPIConfig.from_env)
    strategy: SearchStrategyConfig = field(default_factory=SearchStrategyConfig.from_env)
    data_dir: Path = Path(__file__).parent / "data"
    demo_data_path: Path = Path(__file__).parent / "data" / "demo_papers.json"
    evaluation_data_path: Path = Path(__file__).parent / "data" / "evaluation_queries.json"

    @classmethod
    def from_env(cls) -> AppConfig:
        return cls()


# Global singleton for convenience
_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig.from_env()
    return _config


def reload_config() -> AppConfig:
    global _config
    _config = AppConfig.from_env()
    return _config
