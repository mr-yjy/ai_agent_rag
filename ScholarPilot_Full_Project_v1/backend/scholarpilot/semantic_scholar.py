"""Semantic Scholar API provider for ScholarPilot.

Adds a second academic search data source alongside OpenAlex to improve
recall and coverage. Semantic Scholar provides:
- Title/abstract search with relevance ranking
- Citation graph data (references + citations)
- Influential citation counts
- TLDR (auto-generated summaries) where available
- Field of study classification

API docs: https://api.semanticscholar.org/api-docs/

This provider implements the dual-source retrieval strategy described in
the competition requirements: using multiple academic APIs to maximize
recall while controlling for noise through deduplication.

Usage:
    provider = SemanticScholarProvider()
    result = provider.search(plan)
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .budget import SearchDeadline
from .identity import normalize_doi, upsert_paper
from .models import Paper, QueryPlan
from .providers import PaperProvider, ProviderError, ProviderResult


# Semantic Scholar API endpoint
S2_API_BASE = "https://api.semanticscholar.org/graph/v1"

# Fields to request from Semantic Scholar
S2_PAPER_FIELDS = (
    "paperId,externalIds,title,abstract,year,authors,"
    "venue,publicationVenue,citationCount,influentialCitationCount,"
    "isOpenAccess,openAccessPdf,fieldsOfStudy,"
    "publicationTypes,referenceCount,citationStyles,tldr"
)

# Rate limits: Semantic Scholar recommends 1 request/sec without API key,
# 100 requests/sec with API key
S2_RATE_LIMIT_NO_KEY = 1.0  # seconds between requests
S2_RATE_LIMIT_WITH_KEY = 0.01  # 100 req/sec


@dataclass
class S2SearchResult:
    """Raw result from Semantic Scholar search API."""
    paper_id: str
    external_ids: dict[str, str]
    title: str
    abstract: str | None
    year: int | None
    authors: list[dict[str, str]]
    venue: str
    citation_count: int
    influential_citation_count: int
    is_open_access: bool
    fields_of_study: list[str]
    tldr: str | None  # Auto-generated TLDR summary
    url: str


class SemanticScholarProvider:
    """Semantic Scholar academic paper search provider.

    Features:
    - Title/abstract search with relevance ranking
    - Rich metadata (citations, venues, fields of study)
    - TLDR summaries when available
    - Rate-limit aware with configurable API key support
    - In-memory caching with TTL
    """

    name = "Semantic Scholar 学术图谱"
    endpoint = f"{S2_API_BASE}/paper/search"

    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: float = 15.0,
        per_page: int = 25,
        cache_ttl_seconds: int = 600,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.4,
        max_retry_wait_seconds: float = 3.0,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
        )
        self.timeout_seconds = timeout_seconds
        self.per_page = max(5, min(per_page, 100))
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_retries = max(0, min(max_retries, 2))
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.max_retry_wait_seconds = max(0.0, max_retry_wait_seconds)
        self._cache: dict[str, tuple[float, list[Paper]]] = {}
        self._cache_lock = threading.Lock()
        self._last_request_time: float = 0.0
        self._rate_limited_until: float = 0.0
        self._request_lock = threading.Lock()

    @property
    def rate_limit_seconds(self) -> float:
        """Get the rate limit delay based on whether we have an API key."""
        return S2_RATE_LIMIT_WITH_KEY if self.api_key else S2_RATE_LIMIT_NO_KEY

    @property
    def circuit_open(self) -> bool:
        """Report whether a previous 429 still suppresses new requests."""
        return time.time() < self._rate_limited_until

    def _rate_limit(self, deadline: SearchDeadline | None = None) -> None:
        """Enforce rate limits between API calls."""
        with self._request_lock:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self.rate_limit_seconds:
                delay = self.rate_limit_seconds - elapsed
                if deadline is not None and not deadline.can_wait(delay):
                    raise ProviderError(
                        "Semantic Scholar request skipped because the "
                        "remaining search budget cannot accommodate its "
                        "rate-limit wait",
                        retryable=True,
                        retry_after_seconds=delay,
                    )
                time.sleep(delay)
            self._last_request_time = time.monotonic()

    def _build_search_url(self, query: str, plan: QueryPlan) -> str:
        """Build Semantic Scholar search API URL.

        Semantic Scholar uses query parameters for filtering:
        - query: search terms
        - limit: results per page
        - year: year range filter (format: YYYY-YYYY)
        - fieldsOfStudy: comma-separated fields
        - fields: comma-separated return fields
        """
        params: dict[str, str] = {
            "query": query,
            "limit": str(self.per_page),
            "fields": S2_PAPER_FIELDS,
        }

        # Year range filter (Semantic Scholar supports year filter)
        year_from = plan.year_from
        year_to = plan.year_to
        if year_from or year_to:
            y_from = year_from or 1900
            y_to = year_to or 2030
            params["year"] = f"{y_from}-{y_to}"

        return f"{self.endpoint}?{urllib.parse.urlencode(params)}"

    def _map_paper(self, s2_paper: dict[str, Any]) -> Paper:
        """Map a Semantic Scholar paper to our unified Paper model."""
        # Extract external IDs
        external_ids = s2_paper.get("externalIds", {}) or {}
        doi = normalize_doi(external_ids.get("DOI"))
        paper_id = s2_paper.get("paperId", "")

        # Extract authors
        authors = [
            author.get("name", "")
            for author in (s2_paper.get("authors", []) or [])
            if author.get("name")
        ][:6]

        # Extract venue info
        venue_info = s2_paper.get("venue", "") or ""
        pub_venue = s2_paper.get("publicationVenue") or {}
        if pub_venue and not venue_info:
            venue_info = pub_venue.get("name", "")

        # Use TLDR as abstract enhancement if abstract is missing
        abstract = s2_paper.get("abstract") or ""
        tldr = s2_paper.get("tldr") or {}
        if not abstract and tldr:
            abstract = tldr.get("text", "")

        # Fields of study as concepts
        fields_of_study = s2_paper.get("fieldsOfStudy", []) or []

        # Build URL
        url = s2_paper.get("url", "")
        if not url and doi:
            url = f"https://doi.org/{doi}"

        return Paper(
            id=paper_id or doi or s2_paper.get("title", "untitled"),
            title=str(s2_paper.get("title", "Untitled")),
            abstract=abstract,
            year=int(s2_paper.get("year") or 0),
            authors=authors,
            venue=str(venue_info or "Unknown venue"),
            cited_by_count=int(s2_paper.get("citationCount") or 0),
            url=str(url or f"https://api.semanticscholar.org/{paper_id}"),
            doi=str(doi) if doi else None,
            open_access=bool(s2_paper.get("isOpenAccess", False)),
            referenced_works=[],  # Semantic Scholar search doesn't include refs
            concepts=fields_of_study[:8],
            sources=["semantic_scholar"],
            retrieval_routes=["query_search"],
        )

    def _request(
        self,
        url: str,
        *,
        deadline: SearchDeadline | None = None,
    ) -> tuple[list[Paper], bool, int]:
        """Make an HTTP request to Semantic Scholar with rate limiting and caching."""
        # Check cache first
        now = time.time()
        with self._cache_lock:
            cached = self._cache.get(url)
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return list(cached[1]), True, 0
        if now < self._rate_limited_until:
            retry_after = max(1, int(round(self._rate_limited_until - now)))
            raise ProviderError(
                "Semantic Scholar rate limit circuit is open; "
                f"retry after about {retry_after}s",
                retryable=True,
                status_code=429,
                retry_after_seconds=float(retry_after),
                user_action=(
                    "Add SEMANTIC_SCHOLAR_API_KEY to backend/.env or wait "
                    "for the anonymous quota window to reset."
                ),
            )

        headers: dict[str, str] = {
            "User-Agent": "ScholarPilot/0.4 (competition backend)",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

        request = urllib.request.Request(url, headers=headers)

        payload: dict[str, Any] | None = None
        attempts = 0
        for retry_index in range(self.max_retries + 1):
            if deadline is not None:
                deadline.ensure_available("semantic_scholar_retrieval")
            self._rate_limit(deadline)
            attempts += 1
            try:
                request_timeout = (
                    deadline.timeout_for(
                        "semantic_scholar_retrieval",
                        self.timeout_seconds,
                    )
                    if deadline is not None
                    else self.timeout_seconds
                )
                with urllib.request.urlopen(
                    request, timeout=request_timeout
                ) as response:
                    payload = json.load(response)
                self._rate_limited_until = 0.0
                break
            except urllib.error.HTTPError as exc:
                retry_after = self.retry_backoff_seconds * (
                    2**retry_index
                ) * random.uniform(0.85, 1.15)
                if exc.code == 429:
                    retry_after = 60.0
                    if exc.headers is not None:
                        raw_retry_after = exc.headers.get("Retry-After")
                        if raw_retry_after:
                            try:
                                retry_after = max(
                                    1.0, float(raw_retry_after)
                                )
                            except ValueError:
                                pass
                    self._rate_limited_until = time.time() + retry_after
                    if (
                        retry_index < self.max_retries
                        and retry_after <= self.max_retry_wait_seconds
                        and (
                            deadline is None
                            or deadline.can_wait(retry_after)
                        )
                    ):
                        time.sleep(retry_after)
                        continue
                    raise ProviderError(
                        "Semantic Scholar rate limited the request "
                        "(HTTP 429); retry window exceeds the current "
                        f"budget ({int(round(retry_after))}s)",
                        api_calls=attempts,
                        retryable=True,
                        status_code=429,
                        retry_after_seconds=retry_after,
                        user_action=(
                            "Add SEMANTIC_SCHOLAR_API_KEY to backend/.env "
                            "or wait for the anonymous quota window to reset."
                        ),
                    ) from exc
                retryable = exc.code in {408, 425, 500, 502, 503, 504}
                if (
                    retryable
                    and retry_index < self.max_retries
                    and (
                        deadline is None
                        or deadline.can_wait(retry_after)
                    )
                ):
                    time.sleep(retry_after)
                    continue
                raise ProviderError(
                    f"Semantic Scholar request failed with HTTP {exc.code}",
                    api_calls=attempts,
                    retryable=retryable,
                    status_code=exc.code,
                    retry_after_seconds=(
                        retry_after if retryable else None
                    ),
                ) from exc
            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
            ) as exc:
                retry_delay = self.retry_backoff_seconds * (
                    2**retry_index
                ) * random.uniform(0.85, 1.15)
                if (
                    retry_index < self.max_retries
                    and (
                        deadline is None
                        or deadline.can_wait(retry_delay)
                    )
                ):
                    time.sleep(retry_delay)
                    continue
                reason = getattr(exc, "reason", None)
                detail = str(reason or exc).replace("\r", " ").replace(
                    "\n", " "
                )
                raise ProviderError(
                    f"Semantic Scholar request failed: {detail[:240]}",
                    api_calls=attempts,
                    retryable=True,
                    retry_after_seconds=retry_delay,
                ) from exc

        if payload is None:
            raise ProviderError(
                "Semantic Scholar request failed without a response",
                api_calls=attempts,
                retryable=True,
            )

        papers = [
            self._map_paper(item)
            for item in payload.get("data", [])
            if item.get("title")
        ]
        with self._cache_lock:
            self._cache[url] = (time.time(), list(papers))
        return papers, False, attempts

    def search(
        self,
        plan: QueryPlan,
        *,
        deadline: SearchDeadline | None = None,
    ) -> ProviderResult:
        """Search Semantic Scholar using all sub-queries from the plan.

        Deduplicates by DOI, paperId, and normalized title.
        """
        papers_by_key: dict[str, Paper] = {}
        api_calls = 0
        cache_hits = 0
        errors: list[ProviderError] = []
        successful_requests = 0

        for subquery in plan.subqueries:
            url = self._build_search_url(subquery, plan)
            try:
                papers, cached, request_attempts = self._request(
                    url,
                    deadline=deadline,
                )
                successful_requests += 1
                if cached:
                    cache_hits += 1
                else:
                    api_calls += request_attempts

                for paper in papers:
                    upsert_paper(papers_by_key, paper)
            except ProviderError as exc:
                # Count the actual failed request.  When the 429 circuit is
                # already open no new request was made.
                api_calls += exc.api_calls
                errors.append(exc)
                # Continue with other sub-queries if one fails
                if exc.status_code == 429:
                    break
                continue

        if not papers_by_key and not successful_requests:
            if errors:
                last_error = errors[-1]
                raise ProviderError(
                    str(last_error),
                    api_calls=api_calls,
                    cache_hits=cache_hits,
                    retryable=any(error.retryable for error in errors),
                    status_code=last_error.status_code,
                    retry_after_seconds=last_error.retry_after_seconds,
                    user_action=last_error.user_action,
                ) from last_error
        return ProviderResult(
            papers=list(papers_by_key.values()),
            api_calls=api_calls,
            cache_hits=cache_hits,
            errors=errors,
        )

    def search_single(
        self,
        query: str,
        plan: QueryPlan,
        *,
        deadline: SearchDeadline | None = None,
    ) -> ProviderResult:
        """Search with a single query string (used for quick lookups)."""
        plan_with_single = QueryPlan(
            original_query=query,
            normalized_query=query,
            year_from=plan.year_from,
            year_to=plan.year_to,
            subqueries=[query],
        )
        return self.search(plan_with_single, deadline=deadline)
