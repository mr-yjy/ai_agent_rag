from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .identity import normalize_doi, upsert_paper
from .models import Paper, QueryPlan


class ProviderError(RuntimeError):
    """Raised when a search provider cannot return usable results."""

    def __init__(
        self,
        message: str,
        *,
        api_calls: int = 0,
        cache_hits: int = 0,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
        user_action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.api_calls = api_calls
        self.cache_hits = cache_hits
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.user_action = user_action


@dataclass(slots=True)
class ProviderResult:
    papers: list[Paper]
    api_calls: int
    cache_hits: int = 0
    errors: list[ProviderError] = field(default_factory=list)


class PaperProvider(Protocol):
    name: str

    def search(self, plan: QueryPlan) -> ProviderResult: ...


def _paper_from_dict(item: dict[str, Any]) -> Paper:
    return Paper(
        id=str(item["id"]),
        title=str(item["title"]),
        abstract=str(item.get("abstract", "")),
        year=int(item.get("year", 0)),
        authors=[str(value) for value in item.get("authors", [])],
        venue=str(item.get("venue", "Unknown venue")),
        cited_by_count=int(item.get("citedByCount", 0)),
        url=str(item.get("url", "#")),
        doi=item.get("doi"),
        open_access=bool(item.get("openAccess", False)),
        referenced_works=[
            str(value) for value in item.get("referencedWorks", [])
        ],
        concepts=[str(value) for value in item.get("concepts", [])],
        sources=[str(value) for value in item.get("sources", ["demo"])],
        retrieval_routes=[
            str(value) for value in item.get("retrievalRoutes", ["demo"])
        ],
    )


class DemoProvider:
    name = "内置比赛演示数据"

    def __init__(self, data_path: Path | None = None) -> None:
        self.data_path = data_path or Path(__file__).parent / "data" / "demo_papers.json"

    def search(self, plan: QueryPlan) -> ProviderResult:
        del plan
        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        return ProviderResult(
            papers=[_paper_from_dict(item) for item in payload],
            api_calls=0,
            cache_hits=1,
        )


class OpenAlexProvider:
    name = "OpenAlex 实时学术图谱"
    endpoint = "https://api.openalex.org/works"

    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: float = 12.0,
        per_page: int = 25,
        cache_ttl_seconds: int = 600,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.4,
        max_retry_wait_seconds: float = 3.0,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("OPENALEX_API_KEY", "")
        )
        self.timeout_seconds = timeout_seconds
        self.per_page = max(5, min(per_page, 100))
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_retries = max(0, min(max_retries, 3))
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.max_retry_wait_seconds = max(0.0, max_retry_wait_seconds)
        self._cache: dict[str, tuple[float, list[Paper]]] = {}
        self._last_request_time = 0.0
        self._request_lock = threading.Lock()
        self._rate_limited_until = 0.0

    @staticmethod
    def _reconstruct_abstract(
        inverted_index: dict[str, list[int]] | None,
    ) -> str:
        if not inverted_index:
            return ""
        positioned_words: list[tuple[int, str]] = []
        for word, positions in inverted_index.items():
            positioned_words.extend((position, word) for position in positions)
        positioned_words.sort(key=lambda item: item[0])
        return " ".join(word for _, word in positioned_words)

    @classmethod
    def _map_work(cls, work: dict[str, Any]) -> Paper:
        authors = [
            str(entry.get("author", {}).get("display_name", ""))
            for entry in work.get("authorships", [])
            if entry.get("author", {}).get("display_name")
        ][:6]
        primary_location = work.get("primary_location") or {}
        source = primary_location.get("source") or {}
        open_access = work.get("open_access") or {}
        topics = [
            str(topic.get("display_name", ""))
            for topic in work.get("topics", [])
            if topic.get("display_name")
        ][:8]
        openalex_id = str(work.get("id", ""))
        raw_doi = work.get("doi")
        doi = normalize_doi(str(raw_doi)) if raw_doi else None
        return Paper(
            id=openalex_id or str(doi) or str(work.get("title", "untitled")),
            title=str(work.get("title") or work.get("display_name") or "Untitled"),
            abstract=cls._reconstruct_abstract(work.get("abstract_inverted_index")),
            year=int(work.get("publication_year") or 0),
            authors=authors,
            venue=str(source.get("display_name") or "Unknown venue"),
            cited_by_count=int(work.get("cited_by_count") or 0),
            url=str(
                f"https://doi.org/{doi}"
                if doi
                else primary_location.get("landing_page_url") or openalex_id or "#"
            ),
            doi=doi,
            open_access=bool(open_access.get("is_oa")),
            referenced_works=[
                str(value) for value in work.get("referenced_works", [])[:30]
            ],
            concepts=topics,
            sources=["openalex"],
            retrieval_routes=["query_search"],
        )

    @staticmethod
    def _sanitize_search_query(query: str) -> str:
        """Remove syntax that OpenAlex's `search` parameter rejects.

        OpenAlex accepts quoted phrases and Boolean AND/OR expressions, but
        does not accept Lucene-style `*`/`?` wildcards. LLM query rewriters
        may still emit them, so the provider enforces compatibility at the
        network boundary.
        """
        query = query.replace("*", " ").replace("?", " ")
        query = re.sub(r"[\x00-\x1f\x7f]+", " ", query)
        return re.sub(r"\s+", " ", query).strip()[:500]

    def _build_url(self, subquery: str, plan: QueryPlan) -> str:
        search_query = self._sanitize_search_query(subquery)
        if not search_query:
            search_query = self._sanitize_search_query(plan.normalized_query)
        parameters: dict[str, str] = {
            "search": search_query,
            "per-page": str(self.per_page),
            "select": (
                "id,doi,title,display_name,publication_year,"
                "abstract_inverted_index,authorships,cited_by_count,"
                "primary_location,open_access,referenced_works,topics"
            ),
        }
        if self.api_key:
            parameters["api_key"] = self.api_key
        mailto = os.getenv("OPENALEX_MAILTO", "").strip()
        if mailto:
            parameters["mailto"] = mailto
        if plan.year_from or plan.year_to:
            year_from = plan.year_from or 1900
            year_to = plan.year_to or time.gmtime().tm_year
            parameters["filter"] = (
                f"from_publication_date:{year_from}-01-01,"
                f"to_publication_date:{year_to}-12-31"
            )
        return f"{self.endpoint}?{urllib.parse.urlencode(parameters)}"

    @staticmethod
    def _is_retryable_http_status(status: int) -> bool:
        return status in {408, 425, 429, 500, 502, 503, 504}

    def _retry_delay(
        self,
        retry_index: int,
        error: urllib.error.HTTPError | None = None,
    ) -> float:
        if error is not None and error.headers is not None:
            retry_after = error.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    pass
        return self.retry_backoff_seconds * (2**retry_index)

    @property
    def min_request_interval_seconds(self) -> float:
        """Use a conservative anonymous rate and a bounded keyed rate."""
        return 0.12 if self.api_key else 1.05

    def _rate_limit(self) -> None:
        """Serialize this provider's calls and avoid burst-based HTTP 429s."""
        with self._request_lock:
            elapsed = time.monotonic() - self._last_request_time
            delay = self.min_request_interval_seconds - elapsed
            if delay > 0:
                time.sleep(delay)
            self._last_request_time = time.monotonic()

    def _rate_limit_error(
        self,
        *,
        api_calls: int,
        retry_after_seconds: float,
    ) -> ProviderError:
        wait_seconds = max(1, int(round(retry_after_seconds)))
        if self.api_key:
            message = (
                "OpenAlex rate limited the request (HTTP 429); "
                f"retry after about {wait_seconds}s"
            )
            user_action = "Wait for the OpenAlex quota window to reset."
        else:
            message = (
                "OpenAlex anonymous quota is exhausted (HTTP 429); "
                f"retry after about {wait_seconds}s. "
                "Configure OPENALEX_API_KEY for reliable live search."
            )
            user_action = (
                "Add a free OpenAlex API key to backend/.env as "
                "OPENALEX_API_KEY, then restart the backend."
            )
        return ProviderError(
            message,
            api_calls=api_calls,
            retryable=True,
            status_code=429,
            retry_after_seconds=float(wait_seconds),
            user_action=user_action,
        )

    def _request(self, url: str) -> tuple[list[Paper], bool, int]:
        cached = self._cache.get(url)
        now = time.time()
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return cached[1], True, 0

        if now < self._rate_limited_until:
            raise self._rate_limit_error(
                api_calls=0,
                retry_after_seconds=self._rate_limited_until - now,
            )

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ScholarPilot/0.4 (competition backend)",
                "Accept": "application/json",
            },
        )
        attempts = 0
        payload: dict[str, Any] | None = None
        for retry_index in range(self.max_retries + 1):
            self._rate_limit()
            attempts += 1
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    payload = json.load(response)
                self._rate_limited_until = 0.0
                break
            except urllib.error.HTTPError as exc:
                retryable = self._is_retryable_http_status(exc.code)
                retry_delay = self._retry_delay(retry_index, exc)
                if exc.code == 429:
                    circuit_seconds = retry_delay or 60.0
                    self._rate_limited_until = max(
                        self._rate_limited_until,
                        time.time() + circuit_seconds,
                    )
                    if (
                        retry_index < self.max_retries
                        and retry_delay <= self.max_retry_wait_seconds
                    ):
                        time.sleep(retry_delay)
                        continue
                    raise self._rate_limit_error(
                        api_calls=attempts,
                        retry_after_seconds=circuit_seconds,
                    ) from exc
                if retryable and retry_index < self.max_retries:
                    time.sleep(retry_delay)
                    continue
                raise ProviderError(
                    f"OpenAlex request failed with HTTP {exc.code}",
                    api_calls=attempts,
                    retryable=retryable,
                    status_code=exc.code,
                ) from exc
            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
            ) as exc:
                if retry_index < self.max_retries:
                    time.sleep(self._retry_delay(retry_index))
                    continue
                reason = getattr(exc, "reason", None)
                detail = str(reason or exc).replace("\r", " ").replace("\n", " ")
                raise ProviderError(
                    f"OpenAlex request failed: {detail[:240]}",
                    api_calls=attempts,
                    retryable=True,
                ) from exc

        if payload is None:
            raise ProviderError(
                "OpenAlex request failed without a response",
                api_calls=attempts,
                retryable=True,
            )

        papers = [self._map_work(item) for item in payload.get("results", [])]
        self._cache[url] = (now, papers)
        return papers, False, attempts

    def search(self, plan: QueryPlan) -> ProviderResult:
        papers_by_key: dict[str, Paper] = {}
        api_calls = 0
        cache_hits = 0
        errors: list[ProviderError] = []
        for subquery in plan.subqueries:
            url = self._build_url(subquery, plan)
            try:
                papers, cached, request_attempts = self._request(url)
            except ProviderError as exc:
                api_calls += exc.api_calls
                cache_hits += exc.cache_hits
                errors.append(exc)
                if exc.status_code == 429:
                    break
                continue
            if cached:
                cache_hits += 1
            else:
                api_calls += request_attempts
            for paper in papers:
                upsert_paper(papers_by_key, paper)

        if not papers_by_key:
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
            raise ProviderError("OpenAlex returned no usable papers")
        return ProviderResult(
            papers=list(papers_by_key.values()),
            api_calls=api_calls,
            cache_hits=cache_hits,
            errors=errors,
        )
