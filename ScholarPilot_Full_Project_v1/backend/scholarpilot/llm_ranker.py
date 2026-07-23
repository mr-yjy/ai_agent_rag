"""LLM-enhanced paper ranking engine.

Combines heuristic scoring (token overlap, citation count, recency) with
LLM-based semantic relevance assessment for fine-grained paper ranking.

Architecture:
1. Coarse filter: Heuristic scoring (fast, from ranking.py)
2. Fine ranking: LLM-based relevance assessment for top candidates
3. Final fusion: Weighted combination of heuristic + LLM scores

This implements a lightweight version of the Cross-Encoder re-ranking
paradigm, using an LLM-as-judge instead of a trained cross-encoder.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .config import get_config
from .llm_client import LLMClient, LLMError, create_llm_client
from .models import Paper, QueryPlan, RankedPaper, ScoreBreakdown
from .planner import tokenize
from .ranking import (
    _base_score,
    clamp,
    evidence_sentence,
    jaccard,
    rank_papers as heuristic_rank,
)


# LLM prompt for fine-grained relevance scoring
RELEVANCE_JUDGE_PROMPT = """你是一位论文相关性评审专家。请评估一篇学术论文与用户搜索查询的相关程度。

## 用户查询
{query}

## 论文信息
标题: {title}
摘要: {abstract}
关键词: {concepts}
发表年份: {year}
发表源: {venue}
引用数: {cited_by_count}

## 评估维度
请从以下维度进行0-100分评估：

1. **topic_match** (主题匹配): 论文的研究主题是否与查询核心意图一致？
2. **method_match** (方法匹配): 论文使用的方法是否与查询要求的方法匹配？
3. **domain_match** (领域匹配): 论文所属领域是否与查询相关？
4. **novelty** (新颖性): 论文是否提供了新的见解或方法？（考虑年份和创新性）
5. **authority** (权威性): 论文的发表源、引用数所反映的学术影响力

## 输出格式 (JSON)
{{
  "scores": {{
    "topic_match": 85,
    "method_match": 70,
    "domain_match": 90,
    "novelty": 75,
    "authority": 80
  }},
  "overall_relevance": 82,
  "verdict": "高度相关|部分相关|不相关",
  "evidence": "一句话说明这篇论文为什么相关/不相关",
  "reasoning": "简要的推理过程"
}}

只输出JSON，不要额外文字。"""


BATCH_RELEVANCE_JUDGE_PROMPT = """你是论文相关性精排器。基于用户查询逐篇评估候选论文，
只使用给出的标题、摘要和元数据，不得补全不存在的证据。

用户查询:
{query}

候选论文(JSON):
{papers}

输出 JSON 数组，每篇恰好一个对象，并保持 index：
[
  {{
    "index": 0,
    "scores": {{
      "topic_match": 0-100,
      "method_match": 0-100,
      "domain_match": 0-100,
      "novelty": 0-100,
      "authority": 0-100
    }},
    "overall_relevance": 0-100,
    "verdict": "高度相关|部分相关|不相关",
    "evidence": "一句有文本依据的理由"
  }}
]
只输出 JSON。"""


@dataclass(slots=True)
class LLMScore:
    """LLM-assessed relevance scores for a paper."""

    topic_match: float = 0.0
    method_match: float = 0.0
    domain_match: float = 0.0
    novelty: float = 0.0
    authority: float = 0.0
    overall_relevance: float = 0.0
    verdict: str = "不相关"
    evidence: str = ""
    reasoning: str = ""
    llm_used: bool = False


class LLMRanker:
    """LLM-enhanced paper ranker.

    Uses a two-stage approach:
    Stage 1: Heuristic scoring (fast, low cost)
    Stage 2: LLM fine-scoring for top candidates (precise, higher cost)
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        llm_top_k: int = 15,
        llm_weight: float = 0.4,
    ) -> None:
        self.llm = llm_client or create_llm_client()
        self.use_llm = bool(self.llm.config.api_key)
        self.llm_top_k = llm_top_k  # How many top papers get LLM evaluation
        self.llm_weight = llm_weight  # Weight of LLM score vs heuristic score
        self.batch_size = min(8, get_config().strategy.selector_batch_size)
        self._score_cache: dict[int, LLMScore] = {}

    def rank(
        self,
        papers: list[Paper],
        plan: QueryPlan,
        limit: int = 10,
    ) -> list[RankedPaper]:
        """Rank papers using hybrid heuristic + LLM scoring.

        Args:
            papers: Candidate papers to rank
            plan: Query plan with constraints
            limit: Max number of papers to return

        Returns:
            Ranked list of papers with full score breakdowns
        """
        if not self.use_llm or len(papers) < 3:
            return heuristic_rank(papers, plan, limit)

        # Stage 1: Heuristic scoring (fast)
        candidates: list[tuple[Paper, float, ScoreBreakdown, list[str]]] = []
        for paper in papers:
            lowered = paper.searchable_text().casefold()
            if any(term.casefold() in lowered for term in plan.exclude):
                continue
            if paper.year and (
                (plan.year_from is not None and paper.year < plan.year_from)
                or (plan.year_to is not None and paper.year > plan.year_to)
            ):
                continue
            score, breakdown, matched_terms = _base_score(paper, plan)
            candidates.append((paper, score, breakdown, matched_terms))

        candidates.sort(key=lambda item: item[1], reverse=True)

        # Stage 2: LLM fine-scoring for top candidates
        top_candidates = candidates[:self.llm_top_k]
        llm_scores = self._get_llm_scores(
            [paper for paper, _, _, _ in top_candidates],
            plan.original_query,
        )

        # Stage 3: Fuse scores
        fused_results: list[tuple[Paper, float, ScoreBreakdown, list[str], LLMScore]] = []
        for paper, heuristic_score, breakdown, matched_terms in candidates:
            llm_score = llm_scores.get(paper.id)

            if llm_score and llm_score.llm_used:
                # Normalize LLM score to 0-1
                llm_norm = llm_score.overall_relevance / 100.0 * 100
                # Fuse: weighted average
                fused_score = (
                    (1 - self.llm_weight) * heuristic_score +
                    self.llm_weight * llm_norm
                )
                # Update breakdown to reflect LLM assessment
                adjusted_breakdown = ScoreBreakdown(
                    relevance=llm_score.topic_match / 100.0,
                    constraints=(
                        (llm_score.topic_match + llm_score.method_match) / 200.0
                    ),
                    authority=llm_score.authority / 100.0,
                    recency=breakdown.recency,
                    openness=breakdown.openness,
                )
                fused_results.append((
                    paper, fused_score, adjusted_breakdown, matched_terms, llm_score
                ))
            else:
                fused_results.append((
                    paper, heuristic_score, breakdown, matched_terms, llm_score or LLMScore()
                ))

        # Stage 4: MMR diversity re-ranking
        fused_results.sort(key=lambda item: item[1], reverse=True)
        selected: list[tuple[Paper, float, ScoreBreakdown, list[str], LLMScore]] = []
        while fused_results and len(selected) < limit:
            best_idx = 0
            best_mmr = float("-inf")
            for idx, item in enumerate(fused_results):
                tokens = tokenize(item[0].searchable_text())
                redundancy = (
                    max(
                        jaccard(tokens, tokenize(s[0].searchable_text()))
                        for s in selected
                    )
                    if selected
                    else 0.0
                )
                mmr = item[1] - redundancy * 8
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = idx
            selected.append(fused_results.pop(best_idx))

        # Format output
        ranked = []
        for idx, (paper, score, breakdown, matched_terms, llm_score) in enumerate(
            selected, start=1
        ):
            rounded = round(score * 10) / 10
            config = get_config().strategy
            if rounded >= config.relevance_threshold_high * 100:
                level = "高度相关"
            elif rounded >= config.relevance_threshold_partial * 100:
                level = "部分相关"
            else:
                level = "探索性"

            evidence = (
                llm_score.evidence
                if llm_score.llm_used and llm_score.evidence
                else evidence_sentence(paper.abstract, matched_terms)
            )

            ranked.append(RankedPaper(
                paper=paper,
                rank=idx,
                score=rounded,
                level=level,  # type: ignore[arg-type]
                evidence=evidence,
                matched_terms=matched_terms[:6],
                score_breakdown=breakdown,
            ))

        return ranked

    def _get_llm_score(self, paper: Paper, query: str) -> LLMScore:
        """Get LLM-based relevance score for a paper."""
        return self._get_llm_scores([paper], query).get(paper.id, LLMScore())

    def _get_llm_scores(
        self, papers: list[Paper], query: str
    ) -> dict[str, LLMScore]:
        """Score candidates in batches to reduce LLM calls by ~batch_size."""
        results: dict[str, LLMScore] = {}
        uncached: list[Paper] = []
        for paper in papers:
            cache_key = hash((paper.title.casefold(), query.casefold()))
            cached = self._score_cache.get(cache_key)
            if cached is not None:
                results[paper.id] = cached
            else:
                uncached.append(paper)

        if not self.use_llm:
            return results

        for start in range(0, len(uncached), self.batch_size):
            batch = uncached[start : start + self.batch_size]
            payload = [
                {
                    "index": index,
                    "title": paper.title,
                    "abstract": paper.abstract[:700],
                    "concepts": paper.concepts[:5],
                    "year": paper.year,
                    "venue": paper.venue,
                    "cited_by_count": paper.cited_by_count,
                }
                for index, paper in enumerate(batch)
            ]
            prompt = BATCH_RELEVANCE_JUDGE_PROMPT.format(
                query=query,
                papers=json.dumps(payload, ensure_ascii=False),
            )
            try:
                response = self.llm.chat(
                    [{"role": "user", "content": prompt}],
                    temperature=0.05,
                    max_tokens=max(768, len(batch) * 160),
                )
                match = re.search(r"\[.*\]", response.content, re.DOTALL)
                data = json.loads(match.group(0) if match else "[]")
                by_index = {
                    int(item.get("index", -1)): item
                    for item in data
                    if isinstance(item, dict)
                }
            except (json.JSONDecodeError, LLMError, KeyError, TypeError, ValueError):
                by_index = {}

            for index, paper in enumerate(batch):
                item = by_index.get(index)
                llm_score = self._score_from_payload(item)
                cache_key = hash((paper.title.casefold(), query.casefold()))
                if llm_score.llm_used:
                    self._score_cache[cache_key] = llm_score
                results[paper.id] = llm_score
        return results

    @staticmethod
    def _score_from_payload(data: dict[str, Any] | None) -> LLMScore:
        if not data:
            return LLMScore()
        try:
            scores = data.get("scores", {})
            return LLMScore(
                topic_match=float(scores.get("topic_match", 0)),
                method_match=float(scores.get("method_match", 0)),
                domain_match=float(scores.get("domain_match", 0)),
                novelty=float(scores.get("novelty", 0)),
                authority=float(scores.get("authority", 0)),
                overall_relevance=float(data.get("overall_relevance", 0)),
                verdict=str(data.get("verdict", "不相关")),
                evidence=str(data.get("evidence", "")),
                reasoning=str(data.get("reasoning", "")),
                llm_used=True,
            )
        except (TypeError, ValueError, AttributeError):
            return LLMScore()

    def _get_llm_score_legacy(self, paper: Paper, query: str) -> LLMScore:
        """Legacy single-item parser retained for backward-compatible debugging."""
        cache_key = hash((paper.title.lower(), query.lower()))
        if cache_key in self._score_cache:
            return self._score_cache[cache_key]

        if not self.use_llm:
            return LLMScore()

        prompt = RELEVANCE_JUDGE_PROMPT.format(
            query=query,
            title=paper.title,
            abstract=paper.abstract[:800] if paper.abstract else "N/A",
            concepts=", ".join(paper.concepts[:5]),
            year=paper.year,
            venue=paper.venue,
            cited_by_count=paper.cited_by_count,
        )

        try:
            response = self.llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.05,
                max_tokens=1024,
            )

            json_str = self._extract_json(response.content)
            data = json.loads(json_str)

            scores = data.get("scores", {})
            llm_score = LLMScore(
                topic_match=float(scores.get("topic_match", 0)),
                method_match=float(scores.get("method_match", 0)),
                domain_match=float(scores.get("domain_match", 0)),
                novelty=float(scores.get("novelty", 0)),
                authority=float(scores.get("authority", 0)),
                overall_relevance=float(data.get("overall_relevance", 0)),
                verdict=str(data.get("verdict", "不相关")),
                evidence=str(data.get("evidence", "")),
                reasoning=str(data.get("reasoning", "")),
                llm_used=True,
            )
            self._score_cache[cache_key] = llm_score
            return llm_score

        except (json.JSONDecodeError, LLMError, KeyError, AttributeError):
            return LLMScore()

    @staticmethod
    def _extract_json(text: str) -> str:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return match.group(0) if match else "{}"
