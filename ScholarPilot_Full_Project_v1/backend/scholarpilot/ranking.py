from __future__ import annotations

import math
import re

from .models import Paper, QueryPlan, RankedPaper, ScoreBreakdown
from .planner import tokenize


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


def overlap(query_tokens: list[str], text_tokens: list[str]) -> float:
    if not query_tokens or not text_tokens:
        return 0.0
    text_set = set(text_tokens)
    matches = sum(token in text_set for token in query_tokens)
    return matches / math.sqrt(len(query_tokens) * len(text_set))


def jaccard(left: list[str], right: list[str]) -> float:
    a, b = set(left), set(right)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def evidence_sentence(text: str, matched_terms: list[str]) -> str:
    if not text:
        return "该记录没有可用摘要，当前评分主要依据标题和元数据。"
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    best = max(
        sentences,
        key=lambda sentence: sum(
            term.casefold() in sentence.casefold() for term in matched_terms
        ),
    )
    return f"{best[:217]}…" if len(best) > 220 else best


def _constraint_coverage(paper: Paper, plan: QueryPlan) -> float:
    """Score the query contract with correct AND/OR semantics."""
    lowered = paper.searchable_text().casefold()
    groups = [list(group) for group in plan.constraint_groups if group]
    grouped_terms = {term for group in groups for term in group}
    groups.extend([[term] for term in plan.must_have if term not in grouped_terms])

    checks: list[float] = []
    checks.extend(
        1.0 if any(term.casefold() in lowered for term in group) else 0.0
        for group in groups
    )
    checks.extend(
        1.0 if dataset.casefold() in lowered else 0.0
        for dataset in plan.datasets
    )
    if plan.venues:
        venue_text = paper.venue.casefold()
        checks.append(
            1.0
            if any(venue.casefold() in venue_text for venue in plan.venues)
            else 0.0
        )
    return sum(checks) / len(checks) if checks else 1.0


def _base_score(
    paper: Paper, plan: QueryPlan
) -> tuple[float, ScoreBreakdown, list[str]]:
    query_tokens = tokenize(plan.normalized_query)
    title_tokens = tokenize(paper.title)
    body_tokens = tokenize(paper.searchable_text())
    title_overlap = overlap(query_tokens, title_tokens)
    body_overlap = overlap(query_tokens, body_tokens)
    relevance = clamp(title_overlap * 1.7 + body_overlap * 1.3)
    matched_terms = [token for token in query_tokens if token in set(body_tokens)]

    year_pass = (plan.year_from is None or paper.year >= plan.year_from) and (
        plan.year_to is None or paper.year <= plan.year_to
    )
    contract_coverage = _constraint_coverage(paper, plan)
    constraints = clamp(contract_coverage * 0.7 + (0.3 if year_pass else 0.0))
    authority = clamp(math.log10(paper.cited_by_count + 1) / 3)
    recency = (
        clamp((paper.year - 2019) / 7)
        if plan.year_from is not None or "recent" in plan.preferred
        else 0.5
    )
    openness = 1.0 if paper.open_access else 0.0
    breakdown = ScoreBreakdown(
        relevance=relevance,
        constraints=constraints,
        authority=authority,
        recency=recency,
        openness=openness,
    )
    score = (
        relevance * 0.55
        + constraints * 0.20
        + authority * 0.10
        + recency * 0.10
        + openness * 0.05
    ) * 100
    return score, breakdown, matched_terms


def rank_papers(
    papers: list[Paper], plan: QueryPlan, limit: int = 10
) -> list[RankedPaper]:
    candidates: list[tuple[Paper, float, ScoreBreakdown, list[str]]] = []
    for paper in papers:
        lowered = paper.searchable_text().casefold()
        if any(term.casefold() in lowered for term in plan.exclude):
            continue
        # Explicit dates are hard retrieval constraints.  Unknown years are
        # retained, but known out-of-range papers cannot displace valid works.
        if paper.year and (
            (plan.year_from is not None and paper.year < plan.year_from)
            or (plan.year_to is not None and paper.year > plan.year_to)
        ):
            continue
        score, breakdown, matched_terms = _base_score(paper, plan)
        candidates.append((paper, score, breakdown, matched_terms))
    candidates.sort(key=lambda item: item[1], reverse=True)

    selected: list[tuple[Paper, float, ScoreBreakdown, list[str]]] = []
    while candidates and len(selected) < limit:
        best_index = 0
        best_mmr = float("-inf")
        for index, candidate in enumerate(candidates):
            candidate_tokens = tokenize(candidate[0].searchable_text())
            redundancy = (
                max(
                    jaccard(
                        candidate_tokens,
                        tokenize(selected_item[0].searchable_text()),
                    )
                    for selected_item in selected
                )
                if selected
                else 0.0
            )
            mmr_score = candidate[1] - redundancy * 8
            if mmr_score > best_mmr:
                best_mmr = mmr_score
                best_index = index
        selected.append(candidates.pop(best_index))

    ranked: list[RankedPaper] = []
    for index, (paper, score, breakdown, matched_terms) in enumerate(selected, start=1):
        rounded = round(score, 1)
        if rounded >= 62:
            level = "高度相关"
        elif rounded >= 42:
            level = "部分相关"
        else:
            level = "探索性"
        ranked.append(
            RankedPaper(
                paper=paper,
                rank=index,
                score=rounded,
                level=level,
                evidence=evidence_sentence(paper.abstract, matched_terms),
                matched_terms=matched_terms[:6],
                score_breakdown=breakdown,
            )
        )
    return ranked
