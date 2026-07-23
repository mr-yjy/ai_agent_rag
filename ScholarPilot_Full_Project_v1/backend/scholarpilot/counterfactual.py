"""Counterfactual Evidence Verifier for ScholarPilot paper ranking.

Implements the counterfactual constraint verification approach described in
the project plan (创新点三：反事实约束核验):

1. For top-ranked papers, verify each paper satisfies the query's constraints
   by asking the LLM to extract supporting evidence from the paper's metadata.
2. Generate a counterfactual query by modifying one key constraint
   (e.g., change "query decomposition" to "text summarization").
3. If the paper's relevance judgment stays largely unchanged between the
   original and counterfactual queries, reduce confidence — this indicates
   the paper may not truly depend on the specific constraint.

This module acts only on the top-N candidates (typically 10-20 papers)
to control cost, consistent with the competition's efficiency requirements.

Reference: Inspired by counterfactual reasoning in causal inference,
adapted for academic search verification.

Usage:
    verifier = CounterfactualVerifier()
    verified = verifier.verify(ranked_papers, analyzed_query)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .config import get_config
from .llm_client import LLMClient, LLMError, create_llm_client
from .models import Paper, QueryPlan, RankedPaper, ScoreBreakdown
from .query_analyzer import AnalyzedQuery


# Prompt for evidence-based constraint verification
CONSTRAINT_VERIFY_PROMPT = """你是一位严格的学术论文评审员。请判断以下论文是否真正满足用户查询中的约束条件。

## 用户原始查询
{query}

## 查询约束条件
- 必须满足 (must_have): {must_have}
- 优先满足 (preferred): {preferred}
- 排除条件 (exclude): {exclude}

## 论文信息
标题: {title}
摘要: {abstract}
关键词: {concepts}
发表年份: {year}
发表源: {venue}

## 请逐条验证，以JSON格式输出：
{{
  "constraint_checks": [
    {{"constraint": "约束名称", "satisfied": true/false, "evidence": "论文中的证据或'无证据'"}}
  ],
  "overall_satisfaction": 0-100,
  "confidence": 0-100,
  "issues": ["可能的问题1", "可能的问题2"],
  "verdict": "满足约束|部分满足|不满足约束"
}}

只输出JSON，不要额外文字。"""


# Prompt for counterfactual evaluation
COUNTERFACTUAL_PROMPT = """你是一位严格的学术论文评审员。请比较同一篇论文在原始查询和反事实查询下的相关性变化。

## 原始查询
{original_query}

## 反事实查询（修改了一个关键约束）
{counterfactual_query}

## 论文信息
标题: {title}
摘要: {abstract}

## 请比较判断，以JSON格式输出：
{{
  "original_relevance": 0-100,
  "counterfactual_relevance": 0-100,
  "relevance_change": 0,
  "discriminative": true/false,
  "explanation": "简要说明为什么相关性分数变化了{change}分"
}}

关键规则：
- discriminative = true 意味着改变约束后论文的相关性显著下降，说明原约束是有效的区分条件
- discriminative = false 意味着无论约束如何变，论文看起来都差不多"相关"，这个约束没有区分力
- 如果反事实查询下相关性下降>=20分，则标记discriminative=true

只输出JSON，不要额外文字。"""


@dataclass(slots=True)
class VerificationResult:
    """Result of counterfactual verification for a single paper."""

    paper_id: str
    paper_title: str

    # Constraint verification
    constraints_satisfied: float = 0.0  # 0-1, proportion of constraints met
    constraint_checks: list[dict[str, Any]] = field(default_factory=list)
    constraint_confidence: float = 0.0

    # Counterfactual check
    original_relevance: float = 0.0
    counterfactual_relevance: float = 0.0
    is_discriminative: bool = False  # Whether the constraint truly distinguishes this paper
    counterfactual_explanation: str = ""

    # Adjusted score
    original_score: float = 0.0
    adjusted_score: float = 0.0
    score_penalty: float = 0.0  # How much was deducted

    # Verdict
    verdict: str = "未验证"  # "可信"|"可疑"|"降级"


class CounterfactualVerifier:
    """Counterfactual evidence verifier for paper ranking quality.

    This module implements the counterfactual verification approach:
    1. Verifies top papers against query constraints with evidence extraction
    2. Generates counterfactual queries by modifying key constraints
    3. Compares relevance judgments to detect non-discriminative constraints
    4. Adjusts scores downward for papers that don't truly depend on the constraints

    Cost control: Only processes top_k papers (default 10) to limit LLM calls.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        top_k: int = 10,
        penalty_weight: float = 0.15,
    ) -> None:
        self.llm = llm_client or create_llm_client()
        self.use_llm = bool(self.llm.config.api_key)
        self.top_k = top_k
        self.penalty_weight = penalty_weight  # How much to penalize non-discriminative papers
        self._cache: dict[int, VerificationResult] = {}

    def verify(
        self,
        ranked_papers: list[RankedPaper],
        analyzed_query: AnalyzedQuery | None = None,
        query_text: str = "",
    ) -> list[RankedPaper]:
        """Verify and potentially adjust scores for top-ranked papers.

        Args:
            ranked_papers: Ranked papers from the ranking pipeline.
            analyzed_query: Optional analyzed query with constraint details.
            query_text: Original query text (used if analyzed_query is None).

        Returns:
            Ranked papers with potentially adjusted scores. Papers that fail
            verification get their scores reduced.
        """
        if not self.use_llm or not ranked_papers:
            return ranked_papers

        # Build query info
        if analyzed_query:
            must_have = analyzed_query.must_have
            preferred = analyzed_query.preferred
            exclude = analyzed_query.exclude
            query = analyzed_query.original_query
        else:
            must_have = []
            preferred = []
            exclude = []
            query = query_text

        # Only verify top papers (cost control)
        papers_to_verify = ranked_papers[:self.top_k]
        verified_count = 0

        for ranked in papers_to_verify:
            try:
                vr = self._verify_single(
                    ranked.paper,
                    query,
                    must_have,
                    preferred,
                    exclude,
                )
                if vr and vr.score_penalty > 0:
                    # Adjust the score
                    ranked.score = max(
                        1.0,
                        ranked.score * (1.0 - vr.score_penalty),
                    )
                    # Update level based on new score
                    rounded = round(ranked.score, 1)
                    if rounded >= 62:
                        ranked.level = "高度相关"  # type: ignore[assignment]
                    elif rounded >= 42:
                        ranked.level = "部分相关"  # type: ignore[assignment]
                    else:
                        ranked.level = "探索性"  # type: ignore[assignment]

                    # Append verification info to evidence
                    if vr.verdict == "降级":
                        ranked.evidence = (
                            f"[反事实核验] 该论文在修改关键约束后相关性未显著变化，"
                            f"可能存在约束不匹配。{ranked.evidence}"
                        )
                    verified_count += 1
            except Exception:
                continue

        return ranked_papers

    def _verify_single(
        self,
        paper: Paper,
        query: str,
        must_have: list[str],
        preferred: list[str],
        exclude: list[str],
    ) -> VerificationResult | None:
        """Run full counterfactual verification on a single paper."""
        cache_key = hash((paper.title.lower(), query.lower()))
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Only verify if we have constraints to check
        if not must_have and not preferred:
            return None

        # Step 1: Constraint verification
        cv_result = self._check_constraints(paper, query, must_have, preferred, exclude)
        if cv_result is None:
            return None

        # Step 2: Generate counterfactual query (modify first must_have constraint)
        cf_query = self._generate_counterfactual(query, must_have)
        if not cf_query:
            return None

        # Step 3: Counterfactual comparison
        cf_result = self._compare_counterfactual(paper, query, cf_query)
        if cf_result is None:
            return None

        # Step 4: Compute score adjustment
        score_penalty = 0.0
        verdict = "可信"

        # Penalty factors:
        # 1. Constraints not satisfied → higher penalty
        missed_constraints = 1.0 - cv_result.get("overall_satisfaction", 100) / 100.0
        if missed_constraints > 0.3:
            score_penalty += self.penalty_weight * 0.5
            verdict = "降级"

        # 2. Not discriminative → moderate penalty
        if not cf_result.get("discriminative", True):
            score_penalty += self.penalty_weight * 0.5
            if verdict == "可信":
                verdict = "可疑"

        vr = VerificationResult(
            paper_id=paper.id,
            paper_title=paper.title,
            constraints_satisfied=cv_result.get("overall_satisfaction", 100) / 100.0,
            constraint_confidence=cv_result.get("confidence", 50) / 100.0,
            original_relevance=cf_result.get("original_relevance", 50),
            counterfactual_relevance=cf_result.get("counterfactual_relevance", 50),
            is_discriminative=cf_result.get("discriminative", True),
            counterfactual_explanation=cf_result.get("explanation", ""),
            score_penalty=min(score_penalty, 0.3),  # Cap penalty at 30%
            verdict=verdict,
        )
        self._cache[cache_key] = vr
        return vr

    def _check_constraints(
        self,
        paper: Paper,
        query: str,
        must_have: list[str],
        preferred: list[str],
        exclude: list[str],
    ) -> dict[str, Any] | None:
        """Verify paper against query constraints with evidence extraction."""
        prompt = CONSTRAINT_VERIFY_PROMPT.format(
            query=query,
            must_have=", ".join(must_have) if must_have else "无特殊要求",
            preferred=", ".join(preferred) if preferred else "无偏好",
            exclude=", ".join(exclude) if exclude else "无排除条件",
            title=paper.title,
            abstract=paper.abstract[:600] if paper.abstract else "N/A",
            concepts=", ".join(paper.concepts[:5]),
            year=paper.year,
            venue=paper.venue,
        )

        try:
            response = self.llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.05,
                max_tokens=1024,
            )
            json_str = self._extract_json(response.content)
            return json.loads(json_str)
        except (json.JSONDecodeError, LLMError, KeyError):
            return None

    def _generate_counterfactual(
        self, query: str, must_have: list[str]
    ) -> str | None:
        """Generate a counterfactual query by modifying a key constraint.

        The simplest approach: replace the first must_have term with a
        semantically different term from the same domain.
        """
        if not must_have:
            return None

        # Use a simple template-based counterfactual generation
        # (More sophisticated version would use LLM to generate)
        cf_replacements = {
            "query decomposition": "text summarization",
            "query reformulation": "text classification",
            "citation expansion": "graph neural networks",
            "retrieval augmented generation": "traditional information retrieval",
            "LLM agent": "rule-based system",
            "reranking": "clustering",
            "large language model": "traditional machine learning",
            "RAG": "keyword search",
        }

        modified = query
        replaced = False
        for term in must_have:
            term_lower = term.lower()
            for original, replacement in cf_replacements.items():
                if original in term_lower or term_lower in original:
                    modified = modified.replace(term, replacement)
                    replaced = True
                    break
            if replaced:
                break

        if not replaced:
            # Generic fallback: remove the first must_have term
            modified = query.replace(must_have[0], "")
            modified = re.sub(r"\s+", " ", modified).strip()

        return modified if modified != query else None

    def _compare_counterfactual(
        self, paper: Paper, original_query: str, cf_query: str
    ) -> dict[str, Any] | None:
        """Compare paper relevance between original and counterfactual queries."""
        prompt = COUNTERFACTUAL_PROMPT.format(
            original_query=original_query,
            counterfactual_query=cf_query,
            title=paper.title,
            abstract=paper.abstract[:500] if paper.abstract else "N/A",
        )

        try:
            response = self.llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.05,
                max_tokens=512,
            )
            json_str = self._extract_json(response.content)
            return json.loads(json_str)
        except (json.JSONDecodeError, LLMError, KeyError):
            return None

    @staticmethod
    def _extract_json(text: str) -> str:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return match.group(0) if match else "{}"

    def verify_batch(
        self,
        ranked_papers: list[RankedPaper],
        analyzed_query: AnalyzedQuery,
    ) -> tuple[list[RankedPaper], list[VerificationResult]]:
        """Verify papers and return both adjusted rankings and detailed results.

        Returns:
            (adjusted papers, detailed verification results)
        """
        papers = self.verify(ranked_papers, analyzed_query)
        details = [
            self._cache.get(hash((p.paper.title.lower(), analyzed_query.original_query.lower())))
            for p in papers[:self.top_k]
        ]
        return papers, [d for d in details if d is not None]
