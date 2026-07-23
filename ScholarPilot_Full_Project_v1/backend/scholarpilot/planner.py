from __future__ import annotations

import re
import time

from .models import QueryPlan


TERM_MAP: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"论文检索|学术检索|文献检索|\bacademic (?:paper |literature )?search\b", re.I),
        "academic paper search",
    ),
    (re.compile(r"智能体|代理系统|\b(?:LLM|language model) agents?\b", re.I), "LLM agent"),
    (re.compile(r"查询分解|问题分解|\bquery decomposition\b", re.I), "query decomposition"),
    (re.compile(r"查询改写|查询重写|\bquery (?:reformulation|rewriting)\b", re.I), "query reformulation"),
    (re.compile(r"引文|引用网络|\bcitation (?:expansion|graph|network)\b", re.I), "citation expansion"),
    (
        re.compile(r"检索增强生成|检索增强|\bRAG\b|retrieval[- ]augmented generation", re.I),
        "retrieval augmented generation RAG",
    ),
    (re.compile(r"重排序|重排|\bre-?ranking\b", re.I), "reranking"),
    (re.compile(r"召回率|\brecall\b", re.I), "recall"),
    (re.compile(r"精确率|准确率|\bprecision\b", re.I), "precision"),
    (re.compile(r"科学研究|科研|\bscientific research\b", re.I), "scientific research"),
    (re.compile(r"大语言模型|大模型|\blarge language models?\b", re.I), "large language model"),
    (re.compile(r"反事实|\bcounterfactual\b", re.I), "counterfactual"),
    (re.compile(r"零知识证明|\bzero[- ]knowledge proofs?\b", re.I), "zero knowledge proof"),
    (re.compile(r"隐私保护|\bprivacy[- ]preserving\b", re.I), "privacy preserving"),
)

METHOD_TERMS = {
    "LLM agent",
    "query decomposition",
    "query reformulation",
    "citation expansion",
    "retrieval augmented generation RAG",
    "reranking",
    "counterfactual",
    "zero knowledge proof",
    "privacy preserving",
}

QUERY_EXPANSIONS: dict[str, str] = {
    "academic paper search": (
        "scientific literature search scholarly paper retrieval paper finding"
    ),
    "LLM agent": "language model agent autonomous research agent",
    "query decomposition": "question decomposition subquery generation",
    "query reformulation": "query rewriting query expansion",
    "citation expansion": "citation graph reference chaining",
    "retrieval augmented generation RAG": (
        "retrieval augmented generation knowledge intensive question answering"
    ),
    "reranking": "re-ranking relevance ranking cross-encoder",
    "counterfactual": "counterfactual reasoning constraint verification",
    "zero knowledge proof": "zero knowledge proof verifiable computation",
    "privacy preserving": "privacy preserving differential privacy",
}

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


def _extract_year_range(query: str) -> tuple[int | None, int | None]:
    current_year = time.gmtime().tm_year
    range_match = re.search(
        r"(?<!\d)(20\d{2})\s*(?:年)?\s*(?:[-—–~至到]|(?:to))\s*"
        r"(20\d{2})(?!\d)",
        query,
        re.IGNORECASE,
    )
    if range_match:
        first, second = int(range_match.group(1)), int(range_match.group(2))
        return min(first, second), max(first, second)

    recent_match = re.search(r"(?:近|最近)\s*(\d{1,2})\s*年", query)
    if recent_match:
        width = max(1, min(int(recent_match.group(1)), 20))
        return current_year - width + 1, current_year

    year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", query)
    if not year_match:
        return None, None
    year = int(year_match.group(1))
    prefix = query[max(0, year_match.start() - 12) : year_match.start()]
    suffix = query[year_match.end() : year_match.end() + 12]

    if re.search(r"(?:after|later than)\s*$", prefix, re.I) or re.search(
        r"^\s*年?\s*(?:以后|之后)", suffix
    ):
        return year + 1, None
    if re.search(r"(?:since|from)\s*$", prefix, re.I) or re.search(
        r"^\s*年?\s*(?:以来|起)", suffix
    ):
        return year, None
    if re.search(r"(?:before|prior to)\s*$", prefix, re.I) or re.search(
        r"^\s*年?\s*(?:以前|之前)", suffix
    ):
        return None, year - 1
    if re.search(r"(?:up to|until|through)\s*$", prefix, re.I) or re.search(
        r"^\s*年?\s*(?:及以前|截止)", suffix
    ):
        return None, year
    return year, year


def _matched_terms_with_spans(query: str) -> list[tuple[int, int, str]]:
    matches: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for pattern, replacement in TERM_MAP:
        match = pattern.search(query)
        if match and replacement not in seen:
            matches.append((match.start(), match.end(), replacement))
            seen.add(replacement)
    return sorted(matches)


def _build_constraint_groups(
    query: str, matches: list[tuple[int, int, str]]
) -> list[list[str]]:
    groups: list[list[str]] = []
    for index, (_, end, term) in enumerate(matches):
        if index + 1 >= len(matches):
            groups.append([term])
            continue
        next_start = matches[index + 1][0]
        connector = query[end:next_start]
        if re.search(r"(?:或|或者|/|\bor\b)", connector, re.I):
            next_term = matches[index + 1][2]
            groups.append([term, next_term])
        else:
            groups.append([term])

    # A term consumed as the right-hand side of an OR group must not also
    # become a standalone AND constraint.
    compact: list[list[str]] = []
    consumed: set[str] = set()
    for group in groups:
        if len(group) > 1:
            compact.append(group)
            consumed.update(group)
        elif group[0] not in consumed:
            compact.append(group)
    return compact[:8]


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
    matches = _matched_terms_with_spans(query)
    matched_terms = [item[2] for item in matches]
    methods = [term for term in matched_terms if term in METHOD_TERMS]
    constraint_groups = _build_constraint_groups(query, matches)

    preferred: list[str] = []
    if re.search(r"代码|开源|github", query, re.I):
        preferred.append("open source")
    if re.search(r"实验|benchmark|evaluation|评测|ablation", query, re.I):
        preferred.append("evaluation")
    if re.search(r"最新|近期|近年", query, re.I):
        preferred.append("recent")

    exclude: list[str] = []
    exclude_match = re.search(
        r"(?:排除|不要|不包括|excluding?|without)\s*([^，。；;,.]+)",
        query,
        re.I,
    )
    if exclude_match:
        exclude.append(exclude_match.group(1).strip())

    tokens = tokenize(normalized)
    english_terms = unique(
        re.findall(r"[a-z][a-z0-9-]{1,}", " ".join(matched_terms), re.I)
        + [token for token in tokens if re.fullmatch(r"[a-z][a-z0-9-]{1,}", token)]
    )
    key_terms = " ".join(english_terms[:12] or tokens[:10])
    expanded_terms = " ".join(
        QUERY_EXPANSIONS[term]
        for term in matched_terms
        if term in QUERY_EXPANSIONS
    )
    subqueries = unique(
        [
            " ".join(matched_terms),
            expanded_terms,
            key_terms,
            normalized,
        ]
    )
    subqueries = [item for item in subqueries if len(item) >= 4][:3]
    year_from, year_to = _extract_year_range(query)

    return QueryPlan(
        original_query=query,
        normalized_query=normalized,
        year_from=year_from,
        year_to=year_to,
        must_have=unique(matched_terms)[:8],
        preferred=preferred,
        exclude=exclude,
        subqueries=subqueries,
        constraint_groups=constraint_groups,
        methods=methods,
    )
