"""Configuration management for ScholarPilot.

Loads settings from environment variables with sensible defaults.
All LLM interactions go through an OpenAI-compatible interface,
supporting DeepSeek, Qwen, OpenAI, and local models.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


def _load_local_env() -> None:
    """Load backend/.env without overriding an existing process environment."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(
        dict.fromkeys(
            item.strip().rstrip("/")
            for item in value.split(",")
            if item.strip()
        )
    )


_load_local_env()


@dataclass(slots=True)
class LLMConfig:
    """LLM provider configuration (OpenAI-compatible)."""

    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"
    max_tokens: int = 4096
    temperature: float = 0.0
    timeout_seconds: float = 60.0
    thinking_mode: Literal["enabled", "disabled"] = "disabled"
    reasoning_effort: Literal["high", "max"] = "high"
    json_mode: bool = True
    max_retries: int = 1
    retry_backoff_seconds: float = 0.75

    @classmethod
    def from_env(cls) -> LLMConfig:
        thinking_mode = os.getenv(
            "LLM_THINKING_MODE", "disabled"
        ).strip().casefold()
        if thinking_mode not in {"enabled", "disabled"}:
            thinking_mode = "disabled"
        reasoning_effort = os.getenv(
            "LLM_REASONING_EFFORT", "high"
        ).strip().casefold()
        if reasoning_effort not in {"high", "max"}:
            reasoning_effort = "high"
        return cls(
            api_key=(
                os.getenv("LLM_API_KEY")
                or os.getenv("DEEPSEEK_API_KEY", "")
            ),
            base_url=os.getenv(
                "LLM_BASE_URL", "https://api.deepseek.com"
            ).rstrip("/"),
            model=os.getenv("LLM_MODEL", "deepseek-v4-pro"),
            max_tokens=max(128, int(os.getenv("LLM_MAX_TOKENS", "4096"))),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.0")),
            timeout_seconds=max(
                5.0, float(os.getenv("LLM_TIMEOUT", "60.0"))
            ),
            thinking_mode=thinking_mode,  # type: ignore[arg-type]
            reasoning_effort=reasoning_effort,  # type: ignore[arg-type]
            json_mode=_env_bool("LLM_JSON_MODE", True),
            max_retries=max(
                0, min(3, int(os.getenv("LLM_MAX_RETRIES", "1")))
            ),
            retry_backoff_seconds=max(
                0.0, float(os.getenv("LLM_RETRY_BACKOFF", "0.75"))
            ),
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
    max_total_api_calls: int = 10
    max_total_papers: int = 100
    min_papers_for_iteration: int = 3
    initial_subquery_limit: int = 3
    desired_candidate_count: int = 20
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
    search_timeout_seconds: float = 50.0
    optional_step_min_remaining_seconds: float = 2.0
    cache_ttl_seconds: int = 600
    ranking_weight_relevance: float = 0.45
    ranking_weight_constraints: float = 0.23
    ranking_weight_evidence: float = 0.10
    ranking_weight_authority: float = 0.08
    ranking_weight_recency: float = 0.07
    ranking_weight_source_consistency: float = 0.04
    ranking_weight_openness: float = 0.03
    mmr_duplicate_penalty: float = 8.0

    @classmethod
    def from_env(cls) -> SearchStrategyConfig:
        return cls(
            max_search_rounds=max(
                1, min(3, int(os.getenv("MAX_SEARCH_ROUNDS", "3")))
            ),
            max_api_calls_per_round=max(
                1, min(10, int(os.getenv("MAX_API_CALLS_PER_ROUND", "5")))
            ),
            max_total_api_calls=max(
                1, min(10, int(os.getenv("MAX_TOTAL_API_CALLS", "10")))
            ),
            max_total_papers=max(
                20, min(500, int(os.getenv("MAX_TOTAL_PAPERS", "100")))
            ),
            min_papers_for_iteration=max(
                1, int(os.getenv("MIN_PAPERS_FOR_ITERATION", "3"))
            ),
            initial_subquery_limit=max(
                1, min(3, int(os.getenv("INITIAL_SUBQUERY_LIMIT", "3")))
            ),
            desired_candidate_count=max(
                5, int(os.getenv("DESIRED_CANDIDATE_COUNT", "20"))
            ),
            enable_citation_expansion=_env_bool(
                "ENABLE_CITATION_EXPANSION", True
            ),
            max_citation_hops=max(
                0, min(1, int(os.getenv("MAX_CITATION_HOPS", "1")))
            ),
            citation_expansion_per_paper=max(
                1, int(os.getenv("CITATION_EXPANSION_PER_PAPER", "5"))
            ),
            relevance_threshold_high=float(
                os.getenv("RELEVANCE_THRESHOLD_HIGH", "0.62")
            ),
            relevance_threshold_partial=float(
                os.getenv("RELEVANCE_THRESHOLD_PARTIAL", "0.42")
            ),
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
            search_timeout_seconds=max(
                1.0, min(50.0, float(os.getenv("SEARCH_TIMEOUT_SECONDS", "50")))
            ),
            optional_step_min_remaining_seconds=max(
                0.1,
                float(
                    os.getenv(
                        "OPTIONAL_STEP_MIN_REMAINING_SECONDS",
                        "2.0",
                    )
                ),
            ),
            cache_ttl_seconds=max(
                1, int(os.getenv("CACHE_TTL_SECONDS", "600"))
            ),
            ranking_weight_relevance=max(
                0.0, float(os.getenv("RANK_WEIGHT_RELEVANCE", "0.45"))
            ),
            ranking_weight_constraints=max(
                0.0, float(os.getenv("RANK_WEIGHT_CONSTRAINTS", "0.23"))
            ),
            ranking_weight_evidence=max(
                0.0, float(os.getenv("RANK_WEIGHT_EVIDENCE", "0.10"))
            ),
            ranking_weight_authority=max(
                0.0, float(os.getenv("RANK_WEIGHT_AUTHORITY", "0.08"))
            ),
            ranking_weight_recency=max(
                0.0, float(os.getenv("RANK_WEIGHT_RECENCY", "0.07"))
            ),
            ranking_weight_source_consistency=max(
                0.0,
                float(os.getenv("RANK_WEIGHT_SOURCE_CONSISTENCY", "0.04")),
            ),
            ranking_weight_openness=max(
                0.0, float(os.getenv("RANK_WEIGHT_OPENNESS", "0.03"))
            ),
            mmr_duplicate_penalty=max(
                0.0, float(os.getenv("MMR_DUPLICATE_PENALTY", "8.0"))
            ),
        )


@dataclass(slots=True)
class SecurityConfig:
    """Fail-closed production boundary for the Python search backend."""

    backend_proxy_token: str = ""
    cors_allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
    rate_limit_requests: int = 30
    rate_limit_window_seconds: float = 60.0
    max_concurrent_searches: int = 4

    @classmethod
    def from_env(cls) -> SecurityConfig:
        return cls(
            backend_proxy_token=os.getenv("BACKEND_PROXY_TOKEN", "").strip(),
            cors_allowed_origins=_env_csv(
                "CORS_ALLOWED_ORIGINS",
                (
                    "http://127.0.0.1:5173",
                    "http://localhost:5173",
                ),
            ),
            rate_limit_requests=max(
                1, int(os.getenv("RATE_LIMIT_REQUESTS", "30"))
            ),
            rate_limit_window_seconds=max(
                1.0, float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
            ),
            max_concurrent_searches=max(
                1, int(os.getenv("MAX_CONCURRENT_SEARCHES", "4"))
            ),
        )


@dataclass(slots=True)
class AppConfig:
    """Top-level application configuration."""

    llm: LLMConfig = field(default_factory=LLMConfig.from_env)
    search_api: SearchAPIConfig = field(default_factory=SearchAPIConfig.from_env)
    strategy: SearchStrategyConfig = field(default_factory=SearchStrategyConfig.from_env)
    security: SecurityConfig = field(default_factory=SecurityConfig.from_env)
    data_dir: Path = Path(__file__).parent / "data"
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


def reproducible_config_snapshot(config: AppConfig | None = None) -> dict[str, object]:
    """Return experiment-relevant configuration without any credentials."""
    selected = config or get_config()
    return {
        "schemaVersion": "1.0",
        "llm": {
            "baseUrl": selected.llm.base_url,
            "model": selected.llm.model,
            "maxTokens": selected.llm.max_tokens,
            "temperature": selected.llm.temperature,
            "thinkingMode": selected.llm.thinking_mode,
            "reasoningEffort": selected.llm.reasoning_effort,
            "jsonMode": selected.llm.json_mode,
            "maxRetries": selected.llm.max_retries,
        },
        "searchApi": {
            "maxResultsPerQuery": selected.search_api.max_results_per_query,
            "requestTimeout": selected.search_api.request_timeout,
            "semanticScholarEnabled": bool(
                selected.search_api.semantic_scholar_api_key
            ),
        },
        "strategy": asdict(selected.strategy),
    }


def config_hash(config: AppConfig | None = None) -> str:
    payload = json.dumps(
        reproducible_config_snapshot(config),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
