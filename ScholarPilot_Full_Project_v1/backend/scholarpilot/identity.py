"""Canonical paper identity and multi-source metadata fusion.

Academic APIs use different identifiers for the same work.  OpenAlex commonly
returns DOI URLs, Semantic Scholar returns bare DOIs and its own paper IDs, and
benchmarks often use arXiv IDs.  Keeping identity handling in one module avoids
inflated candidate counts and incorrect F1 measurements.
"""

from __future__ import annotations

import html
import re
import unicodedata
import urllib.parse
from dataclasses import replace

from .models import Paper


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
ARXIV_RE = re.compile(
    r"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)?"
    r"(?P<id>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})(?:v\d+)?)",
    re.IGNORECASE,
)


def normalize_doi(value: str | None) -> str | None:
    """Return a lowercase bare DOI, or ``None`` when no DOI is present."""
    if not value:
        return None
    decoded = urllib.parse.unquote(str(value)).strip()
    match = DOI_RE.search(decoded)
    if not match:
        return None
    return match.group(0).rstrip(".,;)]}").casefold()


def normalize_arxiv_id(value: str | None) -> str | None:
    """Return an arXiv identifier without version suffix."""
    if not value:
        return None
    match = ARXIV_RE.search(urllib.parse.unquote(str(value)).strip())
    if not match:
        return None
    return re.sub(r"v\d+$", "", match.group("id"), flags=re.IGNORECASE).casefold()


def normalize_title(value: str | None) -> str:
    """Normalize a title for conservative cross-provider matching."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", html.unescape(value)).casefold()
    normalized = re.sub(r"[^\w\u3400-\u9fff]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_external_id(value: str | None) -> set[str]:
    """Build comparable aliases from a DOI, arXiv ID, graph ID, or URL."""
    if not value:
        return set()
    raw = urllib.parse.unquote(str(value)).strip().casefold().rstrip("/")
    aliases = {raw}

    doi = normalize_doi(raw)
    if doi:
        aliases.add(f"doi:{doi}")

    arxiv_id = normalize_arxiv_id(raw)
    if arxiv_id:
        aliases.add(f"arxiv:{arxiv_id}")

    openalex_match = re.search(r"(?:openalex\.org/)?(w\d+)$", raw)
    if openalex_match:
        aliases.add(f"openalex:{openalex_match.group(1)}")

    return aliases


def paper_aliases(paper: Paper, *, include_title: bool = True) -> set[str]:
    aliases = normalize_external_id(paper.id)
    aliases.update(normalize_external_id(paper.doi))
    aliases.update(normalize_external_id(paper.url))
    if include_title:
        title = normalize_title(paper.title)
        if title:
            aliases.add(f"title:{title}")
    return aliases


def canonical_paper_key(paper: Paper) -> str:
    """Return a stable deduplication key shared across academic providers."""
    doi = normalize_doi(paper.doi) or normalize_doi(paper.url)
    if doi:
        return f"doi:{doi}"

    for value in (paper.id, paper.url):
        arxiv_id = normalize_arxiv_id(value)
        if arxiv_id:
            return f"arxiv:{arxiv_id}"

    title = normalize_title(paper.title)
    if title:
        return f"title:{title}"
    return f"id:{paper.id.casefold()}"


def _prefer_text(left: str, right: str) -> str:
    return right if len(right.strip()) > len(left.strip()) else left


def merge_papers(existing: Paper, incoming: Paper) -> Paper:
    """Fuse duplicate records while retaining the richest available metadata."""
    existing_doi = normalize_doi(existing.doi) or normalize_doi(existing.url)
    incoming_doi = normalize_doi(incoming.doi) or normalize_doi(incoming.url)
    doi = existing_doi or incoming_doi

    authors = list(dict.fromkeys([*existing.authors, *incoming.authors]))[:12]
    concepts = list(dict.fromkeys([*existing.concepts, *incoming.concepts]))[:16]
    references = list(
        dict.fromkeys([*existing.referenced_works, *incoming.referenced_works])
    )[:60]
    sources = list(dict.fromkeys([*existing.sources, *incoming.sources]))
    routes = list(
        dict.fromkeys([*existing.retrieval_routes, *incoming.retrieval_routes])
    )

    preferred_url = existing.url
    if (not preferred_url or preferred_url == "#") and incoming.url:
        preferred_url = incoming.url
    if doi:
        preferred_url = f"https://doi.org/{doi}"

    return replace(
        existing,
        title=_prefer_text(existing.title, incoming.title),
        abstract=_prefer_text(existing.abstract, incoming.abstract),
        year=existing.year or incoming.year,
        authors=authors,
        venue=(
            incoming.venue
            if existing.venue in {"", "Unknown venue"} and incoming.venue
            else existing.venue
        ),
        cited_by_count=max(existing.cited_by_count, incoming.cited_by_count),
        url=preferred_url,
        doi=doi,
        open_access=existing.open_access or incoming.open_access,
        referenced_works=references,
        concepts=concepts,
        sources=sources,
        retrieval_routes=routes,
    )


def upsert_paper(store: dict[str, Paper], paper: Paper) -> bool:
    """Insert/merge a paper and return ``True`` only for a new unique work."""
    key = canonical_paper_key(paper)
    if key in store:
        store[key] = merge_papers(store[key], paper)
        return False

    # A DOI may be absent in one source, so perform a conservative title alias
    # fallback before adding a second record.
    title = normalize_title(paper.title)
    if title:
        title_key = f"title:{title}"
        for existing_key, existing in store.items():
            if canonical_paper_key(existing) == title_key or normalize_title(
                existing.title
            ) == title:
                store[existing_key] = merge_papers(existing, paper)
                return False

    store[key] = paper
    return True
