from __future__ import annotations

import re

from .models import QueryPlan


TERM_MAP: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"论文检索|学术检索|文献检索"), "academic paper search"),
    (re.compile(r"智能体|代理系统"), "LLM agent"),
    (re.compile(r"查询分解|问题分解"), "query decomposition"),
    (re.compile(r"查询改写|查询重写"), "query reformulation"),
    (re.compile(r"引文|引用网络"), "citation expansion"),
    (re.compile(r"检索增强生成|检索增强|RAG", re.I), "retrieval augmented generation RAG"),
    (re.compile(r"重排序|重排"), "reranking"),
    (re.compile(r"召回率"), "recall"),
    (re.compile(r"精确率|准确率"), "precision"),
    (re.compile(r"科学研究|科研"), "scientific research"),
    (re.compile(r"大语言模型|大模型"), "large language model"),
    (re.compile(r"反事实"), "counterfactual"),
    (re.compile(r"零知识证明"), "zero knowledge proof"),
    (re.compile(r"隐私保护"), "privacy preserving"),
)

STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "after",
    "before",
    "find",
    "paper",
    "papers",
    "study",
    "studies",
    "using",
    "use",
    "about",
    "面向",
    "研究",
    "论文",
    "寻找",
    "检索",
    "使用",
    "相关",
}


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def normalize_query(query: str) -> str:
    normalized = query
    for pattern, replacement in TERM_MAP:
        normalized = pattern.sub(f" {replacement} ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    english = re.findall(r"[a-z][a-z0-9-]{1,}", lowered)
    chinese_blocks = re.findall(r"[\u3400-\u9fff]{2,}", lowered)
    chinese_bigrams: list[str] = []
    for block in chinese_blocks:
        chinese_bigrams.extend(
            block[index : index + 2] for index in range(len(block) - 1)
        )
    return unique(
        [
            token
            for token in [*english, *chinese_bigrams]
            if token not in STOP_WORDS and len(token) > 1
        ]
    )


def build_query_plan(query: str) -> QueryPlan:
    query = query.strip()
    normalized = normalize_query(query)
    # 中文语句中的年份通常紧贴汉字（如“2024年”），不能依赖 \b 单词边界。
    years = sorted(
        {int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", query)}
    )

    matched_methods: list[str] = []
    for pattern, replacement in TERM_MAP:
        if pattern.search(query):
            matched_methods.append(replacement)

    preferred: list[str] = []
    if re.search(r"代码|开源|github", query, re.I):
        preferred.append("open source")
    if re.search(r"实验|benchmark|评测", query, re.I):
        preferred.append("evaluation")
    if re.search(r"最新|近期|近年", query, re.I):
        preferred.append("recent")

    exclude: list[str] = []
    exclude_match = re.search(r"(?:排除|不要|不包括)\s*([^，。；;]+)", query)
    if exclude_match:
        exclude.append(exclude_match.group(1).strip())

    tokens = tokenize(normalized)
    key_terms = " ".join(tokens[:10])
    subqueries = unique(
        [
            normalized,
            " ".join(matched_methods),
            f"academic paper search {key_terms}".strip(),
        ]
    )
    subqueries = [item for item in subqueries if len(item) >= 4][:3]

    year_from: int | None = None
    year_to: int | None = None
    if years:
        year_from = years[0]
        if len(years) > 1:
            year_to = years[-1]

    return QueryPlan(
        original_query=query,
        normalized_query=normalized,
        year_from=year_from,
        year_to=year_to,
        must_have=unique(matched_methods)[:5],
        preferred=preferred,
        exclude=exclude,
        subqueries=subqueries,
    )
