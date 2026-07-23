from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
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
    ) -> None:
        super().__init__(message)
        self.api_calls = api_calls
        self.cache_hits = cache_hits


@dataclass(slots=True)
class ProviderResult:
    papers: list[Paper]
    api_calls: int
    cache_hits: int = 0


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
    ) -> None:
        self.api_key = api_key or os.getenv("OPENALEX_API_KEY")
        self.timeout_seconds = timeout_seconds
        self.per_page = max(5, min(per_page, 100))
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[float, list[Paper]]] = {}

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

    def _build_url(self, subquery: str, plan: QueryPlan) -> str:
        parameters: dict[str, str] = {
            "search": subquery,
            "per-page": str(self.per_page),
            "select": (
                "id,doi,title,display_name,publication_year,"
                "abstract_inverted_index,authorships,cited_by_count,"
                "primary_location,open_access,referenced_works,topics"
            ),
        }
        if self.api_key:
            parameters["api_key"] = self.api_key
        if plan.year_from or plan.year_to:
            year_from = plan.year_from or 1900
            year_to = plan.year_to or time.gmtime().tm_year
            parameters["filter"] = (
                f"from_publication_date:{year_from}-01-01,"
                f"to_publication_date:{year_to}-12-31"
            )
        return f"{self.endpoint}?{urllib.parse.urlencode(parameters)}"

    def _request(self, url: str) -> tuple[list[Paper], bool]:
        cached = self._cache.get(url)
        now = time.time()
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return cached[1], True

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ScholarPilot/0.4 (competition backend)"},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"OpenAlex request failed: {exc}") from exc

        papers = [self._map_work(item) for item in payload.get("results", [])]
        self._cache[url] = (now, papers)
        return papers, False

    def search(self, plan: QueryPlan) -> ProviderResult:
        papers_by_key: dict[str, Paper] = {}
        api_calls = 0
        cache_hits = 0
        for subquery in plan.subqueries:
            url = self._build_url(subquery, plan)
            try:
                papers, cached = self._request(url)
            except ProviderError as exc:
                raise ProviderError(
                    str(exc),
                    api_calls=api_calls + 1,
                    cache_hits=cache_hits,
                ) from exc
            if cached:
                cache_hits += 1
            else:
                api_calls += 1
            for paper in papers:
                upsert_paper(papers_by_key, paper)

        if not papers_by_key:
            raise ProviderError("OpenAlex returned no usable papers")
        return ProviderResult(
            papers=list(papers_by_key.values()),
            api_calls=api_calls,
            cache_hits=cache_hits,
        )
