"""LLM-powered Query Analyzer for complex academic search queries.

Replaces the rule-based planner.py with an LLM-driven approach that:
1. Extracts multi-dimensional constraints from natural language queries
2. Identifies core research intent, methods, datasets, domains, venues
3. Decomposes complex queries into independently searchable sub-queries
4. Generates optimized search queries for semantic search APIs (OpenAlex)

This implements the RefChain query decomposition approach from SPAR
(Shi et al., 2025), enhanced with multi-step chain-of-thought reasoning
for better constraint extraction and query evolution tracking.

Key improvements over v1:
- RefChain multi-step reasoning: Step 1 (Parse constraints) → Step 2 (Generate
  atomic sub-queries) → Step 3 (Optimize for search APIs) → Step 4 (Validate)
- Query evolution tracking: records how each sub-query derives from the original
- Constraint hierarchy: explicit must/preferred/exclude with rationale
- Multi-perspective search: topic-focused, method-focused, and hybrid queries

Usage:
    analyzer = QueryAnalyzer()
    plan = analyzer.analyze("Find papers about query decomposition using LLMs after 2023")
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .config import get_config
from .llm_client import LLMClient, LLMError, create_llm_client


@dataclass(slots=True)
class SubQueryInfo:
    """Metadata for a decomposed sub-query (RefChain tracking)."""

    query: str = ""
    rationale: str = ""  # Why this sub-query was generated
    perspective: str = ""  # "topic" | "method" | "hybrid" | "expansion"
    priority: int = 1  # 1=highest, 3=lowest


@dataclass(slots=True)
class AnalyzedQuery:
    """Structured output of query analysis."""

    # Original user query
    original_query: str = ""

    # Normalized / cleaned version
    normalized_query: str = ""

    # Core research topic (the main subject)
    research_topic: str = ""

    # Research methods / techniques mentioned
    methods: list[str] = field(default_factory=list)

    # Datasets / benchmarks / resources mentioned
    datasets: list[str] = field(default_factory=list)

    # Research domains / fields
    domains: list[str] = field(default_factory=list)

    # Publication venues (journals/conferences)
    venues: list[str] = field(default_factory=list)

    # Time constraints
    year_from: int | None = None
    year_to: int | None = None

    # Must-have terms (required for relevance)
    must_have: list[str] = field(default_factory=list)

    # Preferred terms (bonus for relevance)
    preferred: list[str] = field(default_factory=list)

    # Terms to exclude
    exclude: list[str] = field(default_factory=list)

    # Decomposed sub-queries for independent retrieval
    sub_queries: list[str] = field(default_factory=list)

    # Detailed sub-query info with RefChain metadata
    sub_query_details: list[SubQueryInfo] = field(default_factory=list)

    # Search queries optimized for OpenAlex / Semantic Scholar
    optimized_queries: list[str] = field(default_factory=list)

    # The query's primary intent category
    intent_category: str = "literature_survey"

    # Secondary intent categories (multi-intent queries)
    secondary_intents: list[str] = field(default_factory=list)

    # Does this query need multi-turn search?
    needs_multi_turn: bool = False

    # Search breadth strategy: "precision" | "balanced" | "recall"
    search_strategy: str = "balanced"

    # Confidence score (0-1) of analysis quality
    confidence: float = 0.0

    # Query evolution: how the search plan developed
    evolution_notes: list[str] = field(default_factory=list)

    # Raw LLM response for debugging
    _raw_response: str = ""

    def to_api(self) -> dict[str, Any]:
        return {
            "originalQuery": self.original_query,
            "normalizedQuery": self.normalized_query,
            "researchTopic": self.research_topic,
            "methods": self.methods,
            "datasets": self.datasets,
            "domains": self.domains,
            "venues": self.venues,
            "yearFrom": self.year_from,
            "yearTo": self.year_to,
            "mustHave": self.must_have,
            "preferred": self.preferred,
            "exclude": self.exclude,
            "subqueries": self.sub_queries,
            "optimizedQueries": self.optimized_queries,
            "intentCategory": self.intent_category,
            "confidence": self.confidence,
            "searchStrategy": self.search_strategy,
            "needsMultiTurn": self.needs_multi_turn,
            "evolutionNotes": self.evolution_notes,
        }


# ============================================================
# RefChain Multi-Step Query Analysis Prompt (SPAR-inspired)
# ============================================================
# This implements a chain-of-thought approach where the LLM
# reasons through 4 steps before producing the final output.
# Reference: Shi et al., "SPAR: Scholar Paper Retrieval with
# LLM-based Agents for Enhanced Academic Search", 2025.
# ============================================================

REFCHAIN_SYSTEM_PROMPT = """你是一位世界顶级的学术搜索查询分析师。你的任务是将研究人员复杂的自然语言查询，
通过多步推理（RefChain），解析为结构化的学术检索策略。

## 你的四步推理流程

**Step 1 — 约束提取 (Constraint Extraction):**
识别查询中的所有约束维度：
- 核心主题 (core topic): 用户真正想研究什么？
- 方法约束 (method constraints): 指定了哪些技术/方法？
- 数据/资源约束 (data constraints): 提到了哪些数据集或基准？
- 领域约束 (domain constraints): 限定在哪些学科领域？
- 时间约束 (time constraints): 年份范围？
- 发表源约束 (venue constraints): 特定期刊或会议？
- 质量约束 (quality constraints): 开源？有实验？高引用？

**Step 2 — 约束层次化 (Constraint Hierarchy):**
将约束分为三个层次：
- **must_have** (必须满足): 不满足直接排除。例如：用户明确说"必须使用Transformer"
- **preferred** (优先满足): 满足加分，不满足不排除。例如："优先有开源代码"
- **exclude** (明确排除): 包含这些的论文要过滤掉。例如："排除纯综述"

**Step 3 — 子查询生成 (Sub-query Generation):**
生成3-5个互补的原子子查询，每条查询应：
- 可独立检索（能直接在学术搜索引擎中执行）
- 覆盖不同的检索角度（主题角度、方法角度、混合角度）
- 优先输出英文查询（学术API主要支持英文）
- 每个子查询需说明生成理由(rationale)和角度(perspective)

**Step 4 — 查询优化 (Query Optimization):**
将子查询优化为适合OpenAlex的搜索式：
- 使用学术术语而非口语
- 去除停用词，保留关键概念
- 考虑同义词扩展（如 "LLM agent" ↔ "language model agent"）
- 标注搜索策略：precision（精确优先）、recall（召回优先）、balanced（平衡）

## 输出JSON格式
```json
{
  "step1_constraints": {
    "core_topic": "...",
    "methods": [...],
    "datasets": [...],
    "domains": [...],
    "venues": [...],
    "year_range": {"from": null, "to": null}
  },
  "step2_hierarchy": {
    "must_have": [{"term": "...", "reason": "用户明确要求"}],
    "preferred": [{"term": "...", "reason": "用户表达偏好"}],
    "exclude": [{"term": "...", "reason": "用户明确排除"}]
  },
  "step3_subqueries": [
    {
      "query": "English search query for APIs",
      "rationale": "为什么生成这个子查询",
      "perspective": "topic|method|hybrid|expansion",
      "priority": 1
    }
  ],
  "step4_final": {
    "normalized_query": "规范化后的完整查询",
    "optimized_queries": ["优化后的英文搜索式1", "优化后的英文搜索式2"],
    "intent_category": "survey|method_comparison|benchmark_evaluation|system_design|literature_review|specific_paper",
    "secondary_intents": [],
    "needs_multi_turn": false,
    "search_strategy": "precision|balanced|recall",
    "evolution_notes": ["查询演化说明1"],
    "confidence": 0.90
  }
}
```

## 重要规则
1. 中文查询必须转换为英文学术术语进行检索
2. 每条子查询应该从不同角度覆盖用户需求
3. 必须区分must_have和preferred，不要将偏好当作必须
4. 时间范围精确到年份
5. 如果查询很简单（如找特定论文），标记为"specific_paper"意图
6. 只输出最终的step4_final合并结果，包含所有字段的扁平化JSON

只输出JSON，不要添加任何额外文字。"""

# Flattened output prompt for easier parsing
QUERY_ANALYST_SYSTEM_PROMPT = """你是一位顶级的学术搜索查询分析师。使用多步推理分析学术查询。

## 分析步骤
Step 1: 提取所有约束维度（主题、方法、数据、领域、时间、发表源）
Step 2: 约束分层次：must_have（必须满足）、preferred（优先满足）、exclude（明确排除）
Step 3: 生成3-5个互补的原子子查询（英文），每条覆盖不同检索角度
Step 4: 优化为OpenAlex搜索式，确定搜索策略

## 输出JSON格式
```json
{
  "normalized_query": "规范化的查询文本",
  "research_topic": "核心研究主题（英文，简短精确）",
  "methods": ["method1", "method2"],
  "datasets": ["dataset1"],
  "domains": ["domain1"],
  "venues": ["venue1"],
  "year_from": 2024,
  "year_to": 2026,
  "must_have": [
    {"term": "concept", "reason": "用户明确要求"}
  ],
  "preferred": [
    {"term": "concept", "reason": "用户表达偏好"}
  ],
  "exclude": [
    {"term": "concept", "reason": "用户明确排除"}
  ],
  "sub_queries": [
    {
      "query": "English sub-query for search API",
      "rationale": "为什么生成这个子查询",
      "perspective": "topic|method|hybrid|expansion",
      "priority": 1
    }
  ],
  "optimized_queries": [
    "optimized English search string 1",
    "optimized English search string 2"
  ],
  "intent_category": "survey|method_comparison|benchmark_evaluation|system_design|literature_review|specific_paper",
  "secondary_intents": [],
  "needs_multi_turn": false,
  "search_strategy": "precision|balanced|recall",
  "evolution_notes": ["query evolution note"],
  "confidence": 0.90
}
```

## 重要规则
1. 中文学术查询必须转换为英文学术术语
2. 每条子查询应覆盖不同检索角度（主题/方法/混合/扩展）
3. must_have和preferred必须严格区分
4. 时间范围精确到年份
5. 子查询优先英文，适合OpenAlex等学术API
6. must_have、preferred、exclude现在是对象数组，每个包含term和reason

只输出JSON，不要添加任何额外文字。"""


# Lightweight extraction prompt (used when LLM is unavailable or cost-saving)
LIGHTWEIGHT_ANALYSIS_PROMPT = """提取以下学术查询的关键信息，以JSON格式返回:
{{
  "normalized_query": "...",
  "research_topic": "...",
  "methods": [...],
  "domains": [...],
  "year_from": null,
  "year_to": null,
  "must_have": [...],
  "preferred": [...],
  "sub_queries": [...],
  "optimized_queries": [...],
  "intent_category": "literature_survey",
  "search_strategy": "balanced",
  "confidence": 0.5
}}

查询: {query}
"""


def _normalize_constraint_terms(items: list[Any]) -> list[str]:
    """Normalize constraint items that may be strings or {term, reason} dicts.

    The new RefChain prompt outputs objects with 'term' and 'reason' fields.
    This function handles both old (string) and new (dict) formats.
    """
    result: list[str] = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            term = item.get("term", "")
            if term:
                result.append(str(term))
    return result


def _normalize_sub_queries(items: list[Any]) -> list[dict[str, Any]]:
    """Normalize sub-query items that may be strings or {query, rationale, ...} dicts."""
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            result.append({
                "query": item,
                "rationale": "",
                "perspective": "hybrid",
                "priority": 2,
            })
        elif isinstance(item, dict):
            result.append(item)
    return result


class QueryAnalyzer:
    """LLM-powered academic query analyzer with SPAR RefChain multi-step reasoning.

    Uses multi-step chain-of-thought prompting (inspired by SPAR's RefChain)
    to decompose complex queries, then falls back to rule-based extraction
    when the LLM is unavailable.

    Key improvements over v1:
    - RefChain 4-step reasoning: constraint extraction → hierarchy →
      sub-query generation → optimization
    - Constraint objects with rationale (not just term strings)
    - Query evolution tracking
    - Multi-perspective search strategy selection
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        use_llm: bool = True,
    ) -> None:
        self.llm = llm_client or create_llm_client()
        self.use_llm = use_llm and bool(self.llm.config.api_key)

    def analyze(self, query: str) -> AnalyzedQuery:
        """Analyze a complex academic search query with RefChain reasoning.

        Args:
            query: Natural language academic search query (Chinese or English).

        Returns:
            AnalyzedQuery with structured extraction results.
        """
        # Start with basic rule-based extraction as baseline
        result = self._rule_baseline(query)

        # Enhance with LLM RefChain analysis if available
        if self.use_llm:
            try:
                llm_result = self._llm_analysis(query)
                result = self._merge_results(result, llm_result)
                result._raw_response = llm_result.get("_raw", "")
            except (LLMError, json.JSONDecodeError, KeyError):
                # Log but continue with rule-based result
                result.confidence = max(result.confidence, 0.3)

        # Ensure minimum requirements
        result.original_query = query
        if not result.sub_queries:
            result.sub_queries = self._generate_fallback_subqueries(query, result)
        if not result.optimized_queries:
            result.optimized_queries = self._generate_optimized_queries(result)

        return result

    def _rule_baseline(self, query: str) -> AnalyzedQuery:
        """Quick rule-based extraction that always works (baseline/fallback)."""
        from .planner import build_query_plan

        plan = build_query_plan(query)
        return AnalyzedQuery(
            original_query=query,
            normalized_query=plan.normalized_query,
            must_have=plan.must_have,
            preferred=plan.preferred,
            exclude=plan.exclude,
            year_from=plan.year_from,
            year_to=plan.year_to,
            sub_queries=plan.subqueries,
            search_strategy="balanced",
            confidence=0.15,
        )

    def _llm_analysis(self, query: str) -> dict[str, Any]:
        """Send query to LLM for RefChain multi-step deep analysis.

        Uses the enhanced RefChain prompt that guides the LLM through:
        Step 1: Constraint extraction
        Step 2: Constraint hierarchy
        Step 3: Sub-query generation
        Step 4: Query optimization
        """
        response = self.llm.chat(
            [
                {"role": "system", "content": QUERY_ANALYST_SYSTEM_PROMPT},
                {"role": "user", "content": f"请使用多步推理分析以下学术查询：\n\n{query}"},
            ],
            temperature=0.05,  # Low temperature for deterministic extraction
            max_tokens=3072,    # Increased for multi-step reasoning output
        )

        raw = response.content.strip()
        # Extract JSON from the response (handle markdown code blocks)
        json_str = self._extract_json(raw)
        parsed: dict[str, Any] = json.loads(json_str)
        parsed["_raw"] = raw
        return parsed

    def _extract_json(self, text: str) -> str:
        """Extract JSON string from LLM response (handles markdown fences)."""
        # Try to find JSON within ```json ... ``` blocks
        json_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL
        )
        if json_match:
            return json_match.group(1).strip()

        # Try to find {...} directly
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            return brace_match.group(0).strip()

        return text

    def _merge_results(
        self, baseline: AnalyzedQuery, llm_result: dict[str, Any]
    ) -> AnalyzedQuery:
        """Merge LLM RefChain results into baseline, preferring LLM for structured fields.

        Handles the new object-array format for must_have/preferred/exclude
        where each item is {term, reason} instead of a plain string.
        """
        # ---- String fields ----
        for field, llm_key in [
            ("normalized_query", "normalized_query"),
            ("research_topic", "research_topic"),
            ("intent_category", "intent_category"),
            ("search_strategy", "search_strategy"),
        ]:
            value = llm_result.get(llm_key)
            if value and isinstance(value, str) and len(value) > 2:
                setattr(baseline, field, value)

        # ---- Simple list fields ----
        for field, llm_key in [
            ("methods", "methods"),
            ("datasets", "datasets"),
            ("domains", "domains"),
            ("venues", "venues"),
            ("optimized_queries", "optimized_queries"),
            ("evolution_notes", "evolution_notes"),
            ("secondary_intents", "secondary_intents"),
        ]:
            llm_values = llm_result.get(llm_key, [])
            if llm_values and isinstance(llm_values, list):
                # Filter to strings only for simple list fields
                str_values = [str(v) for v in llm_values if isinstance(v, str)]
                current = getattr(baseline, field, [])
                merged = list(dict.fromkeys([*current, *str_values]))
                setattr(baseline, field, merged[:10])

        # ---- Constraint fields (handle both string and {term, reason} formats) ----
        for field, llm_key in [
            ("must_have", "must_have"),
            ("preferred", "preferred"),
            ("exclude", "exclude"),
        ]:
            llm_values = llm_result.get(llm_key, [])
            if llm_values and isinstance(llm_values, list):
                normalized_terms = _normalize_constraint_terms(llm_values)
                current = getattr(baseline, field, [])
                merged = list(dict.fromkeys([*current, *normalized_terms]))
                setattr(baseline, field, merged[:10])

        # ---- Sub-queries (handle both string and {query, rationale, ...} formats) ----
        llm_subqueries = llm_result.get("sub_queries", [])
        if llm_subqueries and isinstance(llm_subqueries, list):
            normalized = _normalize_sub_queries(llm_subqueries)
            # Extract just the query strings for sub_queries
            query_strings = [sq["query"] for sq in normalized if sq.get("query")]
            if query_strings:
                current = list(baseline.sub_queries)
                merged = list(dict.fromkeys([*current, *query_strings]))
                baseline.sub_queries = merged[:8]
            # Store full details
            baseline.sub_query_details = [
                SubQueryInfo(
                    query=sq.get("query", ""),
                    rationale=sq.get("rationale", ""),
                    perspective=sq.get("perspective", "hybrid"),
                    priority=sq.get("priority", 2),
                )
                for sq in normalized
                if sq.get("query")
            ][:8]

        # ---- Numeric fields ----
        year_range = llm_result.get("year_from") or llm_result
        year_from = llm_result.get("year_from")
        if year_from and isinstance(year_from, (int, float)):
            baseline.year_from = int(year_from)
        year_to = llm_result.get("year_to")
        if year_to and isinstance(year_to, (int, float)):
            baseline.year_to = int(year_to)

        # ---- Boolean fields ----
        needs_multi = llm_result.get("needs_multi_turn")
        if needs_multi is not None:
            baseline.needs_multi_turn = bool(needs_multi)

        confidence = llm_result.get("confidence")
        if confidence and isinstance(confidence, (int, float)):
            baseline.confidence = min(max(float(confidence), 0.0), 1.0)

        return baseline

    def _generate_fallback_subqueries(self, query: str, result: AnalyzedQuery) -> list[str]:
        """Generate sub-queries when LLM doesn't produce them.

        Uses a multi-perspective approach: topic-focused, method-focused,
        and hybrid queries to maximize coverage.
        """
        from .planner import build_query_plan

        plan = build_query_plan(query)
        subqueries = list(plan.subqueries)

        # Perspective 1: Method-specific sub-queries
        for method in result.methods:
            subq = f"{method} in academic research"
            if subq not in subqueries:
                subqueries.append(subq)

        # Perspective 2: Topic-focused sub-query
        if result.research_topic and len(result.research_topic) > 5:
            subqueries.append(result.research_topic)

        # Perspective 3: Hybrid (topic + method combination)
        if result.research_topic and result.methods:
            hybrid = f"{result.research_topic} {' '.join(result.methods[:2])}"
            if hybrid not in subqueries:
                subqueries.append(hybrid)

        return subqueries[:5]

    def _generate_optimized_queries(self, result: AnalyzedQuery) -> list[str]:
        """Generate OpenAlex-optimized search queries using multiple strategies.

        Strategy 1: Topic + Methods (precision-oriented)
        Strategy 2: Methods + Domain (recall-oriented)
        Strategy 3: Broader concept search (coverage-oriented)
        """
        queries: list[str] = []

        # Strategy 1: Precision query (topic + key methods)
        parts = [result.research_topic]
        if result.methods:
            parts.extend(result.methods[:2])
        if parts and any(p for p in parts if p):
            queries.append(" ".join(p for p in parts if p))

        # Strategy 2: Must-have focused query
        if result.must_have:
            queries.append(" ".join(result.must_have[:5]))

        # Strategy 3: Method-focused query (for recall)
        if result.methods:
            queries.append(" ".join(result.methods[:4]))

        # Strategy 4: Broad domain + topic query
        if result.domains and result.research_topic:
            queries.append(f"{' '.join(result.domains[:2])} {result.research_topic}")

        return [q for q in queries if len(q) >= 5][:5]


# Convenience function
def analyze_query(query: str, use_llm: bool = True) -> AnalyzedQuery:
    """One-shot query analysis with RefChain multi-step reasoning."""
    analyzer = QueryAnalyzer(use_llm=use_llm)
    return analyzer.analyze(query)
