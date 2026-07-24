from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SearchMode = Literal["demo", "live"]


@dataclass(slots=True)
class QueryPlan:
    original_query: str
    normalized_query: str
    year_from: int | None = None
    year_to: int | None = None
    must_have: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    subqueries: list[str] = field(default_factory=list)
    # Every inner list is an OR group; all groups are required.  For example,
    # [["query decomposition", "citation expansion"], ["LLM agent"]].
    constraint_groups: list[list[str]] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    venues: list[str] = field(default_factory=list)
    research_topic: str = ""
    retrieval_preference: Literal["precision", "balanced", "recall"] = "balanced"

    def to_api(self) -> dict[str, Any]:
        return {
            "originalQuery": self.original_query,
            "normalizedQuery": self.normalized_query,
            "yearFrom": self.year_from,
            "yearTo": self.year_to,
            "mustHave": self.must_have,
            "preferred": self.preferred,
            "exclude": self.exclude,
            "subqueries": self.subqueries,
            "constraintGroups": self.constraint_groups,
            "methods": self.methods,
            "tasks": self.tasks,
            "datasets": self.datasets,
            "domains": self.domains,
            "venues": self.venues,
            "researchTopic": self.research_topic,
            "retrievalPreference": self.retrieval_preference,
        }


@dataclass(slots=True)
class Paper:
    id: str
    title: str
    abstract: str
    year: int
    authors: list[str]
    venue: str
    cited_by_count: int
    url: str
    doi: str | None = None
    open_access: bool = False
    referenced_works: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    retrieval_routes: list[str] = field(default_factory=list)

    def searchable_text(self) -> str:
        return " ".join([self.title, self.abstract, *self.concepts])


@dataclass(slots=True)
class ScoreBreakdown:
    relevance: float
    constraints: float
    authority: float
    recency: float
    openness: float
    evidence_quality: float = 0.0
    source_consistency: float = 0.0


@dataclass(slots=True)
class RankedPaper:
    paper: Paper
    rank: int
    score: float
    level: Literal["高度相关", "部分相关", "探索性"]
    evidence: str
    matched_terms: list[str]
    score_breakdown: ScoreBreakdown
    evidence_source: Literal["abstract", "title", "metadata", "insufficient"] = (
        "insufficient"
    )
    evidence_insufficient: bool = False

    def to_api(self) -> dict[str, Any]:
        payload = asdict(self.paper)
        payload.update(
            {
                "citedByCount": payload.pop("cited_by_count"),
                "openAccess": payload.pop("open_access"),
                "referencedWorks": payload.pop("referenced_works"),
                "retrievalRoutes": payload.pop("retrieval_routes"),
                "rank": self.rank,
                "score": self.score,
                "level": self.level,
                "evidence": self.evidence,
                "evidenceSource": self.evidence_source,
                "evidenceInsufficient": self.evidence_insufficient,
                "matchedTerms": self.matched_terms,
                "scoreBreakdown": {
                    **asdict(self.score_breakdown),
                    "evidenceQuality": self.score_breakdown.evidence_quality,
                    "sourceConsistency": (
                        self.score_breakdown.source_consistency
                    ),
                },
            }
        )
        payload["scoreBreakdown"].pop("evidence_quality", None)
        payload["scoreBreakdown"].pop("source_consistency", None)
        return payload


@dataclass(slots=True)
class SearchStats:
    elapsed_ms: int
    api_calls: int
    subquery_count: int
    candidate_count: int
    deduplicated_count: int
    token_estimate: int
    cache_hits: int
    llm_calls: int = 0

    def to_api(self) -> dict[str, int]:
        return {
            "elapsedMs": self.elapsed_ms,
            "apiCalls": self.api_calls,
            "subqueryCount": self.subquery_count,
            "candidateCount": self.candidate_count,
            "deduplicatedCount": self.deduplicated_count,
            "tokenEstimate": self.token_estimate,
            "cacheHits": self.cache_hits,
            "llmCalls": self.llm_calls,
        }
