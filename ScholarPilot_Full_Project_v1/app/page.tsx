"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  isSearchResponse,
  NonJsonResponseError,
  protocolError,
  readApiError,
  readJsonResponse,
} from "./lib/api-schema";
import type {
  ApiError,
  RankedPaper,
  SearchResponse,
} from "./lib/types";
import LLMAnalysisPanel from "./components/LLMAnalysisPanel";
import PaperRelationGraph from "./components/PaperRelationGraph";
import SearchRoundsTimeline from "./components/SearchRoundsTimeline";
import TopicClusters from "./components/TopicClusters";

const EXAMPLE_QUERIES = [
  "寻找2024—2026年使用查询分解或引文扩展进行复杂学术论文检索的LLM Agent论文",
  "检索RAG中使用查询改写和重排序提高召回率的论文，并优先展示有实验的工作",
  "Find benchmarks after 2024 that evaluate AI agents for scientific research and literature search",
];

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <article className="metric-card">
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{hint}</span>
    </article>
  );
}

function ScoreBar({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div className="score-row">
      <div>
        <span>{label}</span>
        <b>{Math.round(value * 100)}</b>
      </div>
      <div className="score-track" aria-label={`${label} ${Math.round(value * 100)}`}>
        <i style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
    </div>
  );
}

function PaperCard({
  paper,
  expanded,
  onToggle,
}: {
  paper: RankedPaper;
  expanded: boolean;
  onToggle: () => void;
}) {
  const levelClass =
    paper.level === "高度相关"
      ? "level-high"
      : paper.level === "部分相关"
        ? "level-mid"
        : "level-low";

  return (
    <article className={`paper-card ${expanded ? "paper-expanded" : ""}`}>
      <div className="rank-column">
        <span>#{paper.rank.toString().padStart(2, "0")}</span>
        <div
          className="score-orbit"
          style={{
            background: `conic-gradient(var(--accent) ${paper.score * 3.6}deg, var(--line) 0deg)`,
          }}
        >
          <b>{Math.round(paper.score)}</b>
        </div>
      </div>

      <div className="paper-main">
        <div className="paper-topline">
          <span className={`level-pill ${levelClass}`}>{paper.level}</span>
          <span>{paper.year}</span>
          <span>{paper.venue || "未知发表源"}</span>
          <span>被引 {paper.citedByCount}</span>
          {paper.openAccess && <span className="oa-pill">OPEN</span>}
        </div>

        <h3>
          <a href={paper.url} target="_blank" rel="noreferrer">
            {paper.title}
          </a>
        </h3>
        <p className="authors">
          {paper.authors.length
            ? paper.authors.slice(0, 4).join(" · ")
            : "作者信息暂缺"}
        </p>

        <div className="evidence">
          <span>
            命中证据
            {paper.evidenceInsufficient ? " · 证据不足" : ""}
          </span>
          <p>{paper.evidence}</p>
        </div>

        <div className="paper-provenance">
          <span>
            来源：{paper.sources?.length
              ? paper.sources.join(" + ")
              : "未标注"}
          </span>
          <span>
            路线：{paper.retrievalRoutes?.length
              ? paper.retrievalRoutes.join(" → ")
              : "未标注"}
          </span>
        </div>

        <div className="paper-footer">
          <div className="term-list">
            {paper.matchedTerms.length ? (
              paper.matchedTerms.map((term) => (
                <span key={term}>{term}</span>
              ))
            ) : (
              <span>探索候选</span>
            )}
          </div>
          <button type="button" className="detail-button" onClick={onToggle}>
            {expanded ? "收起评分" : "查看评分"}
          </button>
        </div>

        {expanded && (
          <div className="score-panel">
            <ScoreBar
              label="语义相关"
              value={paper.scoreBreakdown.relevance}
            />
            <ScoreBar
              label="约束满足"
              value={paper.scoreBreakdown.constraints}
            />
            <ScoreBar
              label="论文权威"
              value={paper.scoreBreakdown.authority}
            />
            <ScoreBar label="时间新近" value={paper.scoreBreakdown.recency} />
            <ScoreBar label="开放获取" value={paper.scoreBreakdown.openness} />
            <ScoreBar
              label="证据质量"
              value={paper.scoreBreakdown.evidenceQuality ?? 0}
            />
            <ScoreBar
              label="来源一致"
              value={paper.scoreBreakdown.sourceConsistency ?? 0}
            />
          </div>
        )}
      </div>
    </article>
  );
}

export default function Home() {
  const [query, setQuery] = useState(EXAMPLE_QUERIES[0]);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [expandedPaper, setExpandedPaper] = useState<string | null>(null);
  const [health, setHealth] = useState<{
    ready: boolean;
    adapter: string;
    model: string;
  } | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  async function search(nextQuery = query) {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    setError(null);
    // Never let papers from a previous request survive a new request or failure.
    setResponse(null);
    setExpandedPaper(null);
    try {
      const result = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: nextQuery }),
        signal: controller.signal,
      });
      const payload = await readJsonResponse(result);
      if (!result.ok) {
        setError(
          readApiError(
            payload,
            "搜索失败，请稍后重试。",
            "request-id-unavailable",
          ),
        );
        return;
      }
      if (!isSearchResponse(payload)) {
        setError(
          protocolError(
            "request-id-unavailable",
          ).error,
        );
        return;
      }
      setResponse(payload);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        return;
      }
      if (caught instanceof NonJsonResponseError) {
        setError({
          code: "search_gateway_non_json_response",
          message:
            "公网访问通道返回了非 JSON 响应。请刷新页面后重试；若持续出现，请检查 Cloudflare 隧道是否在线。",
          requestId: "request-id-unavailable",
          retryable: true,
          retryAfterSeconds: 2,
          upstreamStatus: caught.status || undefined,
        });
        return;
      }
      setError({
        code: "search_network_error",
        message:
          caught instanceof Error ? caught.message : "搜索网络请求失败。",
        requestId: "request-id-unavailable",
        retryable: true,
        retryAfterSeconds: 0,
      });
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal })
      .then(async (result) => {
        const payload = await readJsonResponse(result) as Record<string, unknown>;
        const backend = payload.backend as Record<string, unknown> | undefined;
        const llm = payload.llm as Record<string, unknown> | undefined;
        setHealth({
          ready: payload.ready === true,
          adapter: typeof backend?.adapter === "string"
            ? backend.adapter
            : "unreachable",
          model: typeof llm?.model === "string" ? llm.model : "未配置",
        });
      })
      .catch(() => setHealth({
        ready: false,
        adapter: "unreachable",
        model: "unknown",
      }));

    return () => controller.abort();
  }, []);

  function cancelSearch() {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setLoading(false);
    setResponse(null);
    setError({
      code: "search_cancelled",
      message: "搜索已取消，后端不会再启动后续检索轮次或精排。",
      requestId: "cancelled-before-response",
      retryable: true,
      retryAfterSeconds: 0,
    });
  }

  const highRelevance = useMemo(
    () =>
      response?.results.filter((paper) => paper.level === "高度相关").length ??
      0,
    [response],
  );

  function exportResults() {
    if (!response) return;
    const headers = [
      "排名", "标题", "作者", "年份", "发表源", "引用数",
      "综合评分", "相关级别", "证据", "DOI", "URL",
    ];
    const rows = response.results.map((paper) => [
      paper.rank,
      `"${paper.title.replace(/"/g, '""')}"`,
      paper.authors.slice(0, 3).join("; "),
      paper.year,
      paper.venue,
      paper.citedByCount,
      paper.score,
      paper.level,
      `"${(paper.evidence || "").replace(/"/g, '""')}"`,
      paper.doi || "",
      paper.url,
    ]);
    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob(["﻿" + csv], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `scholarpilot-results-${Date.now()}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function selectExample(example: string) {
    setQuery(example);
    setError(null);
  }

  return (
    <main className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="返回顶部">
          <span className="brand-mark">S</span>
          <span>
            <b>研索智航</b>
            <small>ScholarPilot</small>
          </span>
        </a>
        <nav aria-label="页面导航">
          <a href="#workspace">检索工作台</a>
          <a href="#results">结果</a>
          <a href="#roadmap">实施路线</a>
        </nav>
        <span className="version-badge">v0.6 · Reliable Search</span>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">
            华为企业赛题三 · 复杂学术查询智能论文搜索
          </p>
          <h1>
            把一个复杂科研问题，
            <em>拆成可以验证的检索过程。</em>
          </h1>
          <p className="hero-description">
            查询分解、预算感知双源召回、约束评分与结构化证据，
            在同一个带请求追踪和总截止时间的可复现工作流中完成。
          </p>
        </div>

        <aside className="competition-card">
          <div className="competition-title">
            <span>评测目标</span>
            <b>100</b>
          </div>
          <div className="weight-row">
            <div style={{ width: "70%" }}>
              <b>70%</b>
              <span>F1 Score</span>
            </div>
            <div style={{ width: "20%" }}>
              <b>20%</b>
              <span>运行效率</span>
            </div>
            <div style={{ width: "10%" }}>
              <b>10%</b>
              <span>结构化</span>
            </div>
          </div>
          <p>
            产品界面中的每一项统计，都对应后续实验报告需要记录的指标。
          </p>
        </aside>
      </section>

      <section className="search-workspace" id="workspace">
        <div className="workspace-header">
          <div>
            <p className="section-index">01 / QUERY</p>
            <h2>描述你的真实科研需求</h2>
          </div>
          <span className="provider-pill">Python 实时检索</span>
        </div>

        <div className="query-box">
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="例如：寻找2024年以后使用查询分解或引文网络进行学术检索的LLM Agent论文……"
            aria-label="复杂学术查询"
          />
          <div className="query-actions">
            <span>{query.length} / 800</span>
            <button
              type="button"
              className="search-button"
              disabled={loading || query.trim().length < 6}
              onClick={() => void search()}
            >
              {loading ? "正在规划检索…" : "开始智能检索"}
            </button>
            {loading && (
              <button
                type="button"
                className="cancel-button"
                onClick={cancelSearch}
              >
                取消
              </button>
            )}
          </div>
        </div>

        <div className="examples">
          <span>试试这些问题</span>
          {EXAMPLE_QUERIES.map((example, index) => (
            <button
              type="button"
              key={example}
              onClick={() => selectExample(example)}
            >
              示例 {index + 1}
            </button>
          ))}
        </div>

        <div className={`health-strip ${health?.ready ? "ready" : ""}`}>
          <span>Python 后端：{health?.ready ? "已就绪" : "未就绪"}</span>
          <span>适配器：{health?.adapter ?? "检测中"}</span>
          <span>模型：{health?.model ?? "检测中"}</span>
        </div>

        {error && (
          <div className="message error-message error-detail" role="alert">
            <strong>{error.message}</strong>
            <span>错误代码：{error.code}</span>
            <span>请求 ID：{error.requestId}</span>
            {error.stage && <span>失败阶段：{error.stage}</span>}
            <span>
              建议：
              {error.retryable
                ? `稍后重试${error.retryAfterSeconds
                  ? `（约 ${error.retryAfterSeconds} 秒）`
                  : ""}`
                : "检查查询或服务配置后重试"}
            </span>
          </div>
        )}
        {response?.warning && (
          <div className="message warning-message">{response.warning}</div>
        )}
        {response?.status === "degraded" && (
          <div className="message warning-message">
            部分数据源不可用，本页只展示已成功返回的真实检索结果。
            请求 ID：{response.requestId}
          </div>
        )}
        {response?.status === "no_results" && (
          <div className="message empty-message">
            数据源请求成功，但没有找到满足当前约束的论文。
            请求 ID：{response.requestId}
          </div>
        )}
      </section>

      {response && (
        <>
          <section className="plan-section">
            <div className="plan-heading">
              <div>
                <p className="section-index">02 / PLAN</p>
                <h2>Agent 查询计划</h2>
              </div>
              <span className="provider-pill">{response.provider}</span>
            </div>

            <div className="plan-grid">
              <article className="plan-card plan-primary">
                <span>规范化查询</span>
                <p>{response.plan.normalizedQuery}</p>
                <div className="constraint-list">
                  {response.plan.yearFrom && (
                    <span>
                      年份 ≥ {response.plan.yearFrom}
                      {response.plan.yearTo
                        ? `，≤ ${response.plan.yearTo}`
                        : ""}
                    </span>
                  )}
                  {response.plan.mustHave.map((term) => (
                    <span key={term}>必须：{term}</span>
                  ))}
                  {response.plan.preferred.map((term) => (
                    <span key={term}>偏好：{term}</span>
                  ))}
                </div>
              </article>

              <article className="plan-card">
                <span>并行子查询</span>
                <ol>
                  {response.plan.subqueries.map((subquery) => (
                    <li key={subquery}>{subquery}</li>
                  ))}
                </ol>
              </article>

              <article className="plan-card plan-flow">
                <span>当前执行链</span>
                <div className="flow-line">
                  <i className="done">1</i>
                  <b>约束解析</b>
                  <i className="done">2</i>
                  <b>多路召回</b>
                  <i className="done">3</i>
                  <b>透明重排</b>
                  <i className="done">4</i>
                  <b>证据输出</b>
                </div>
              </article>
            </div>
          </section>

          <LLMAnalysisPanel plan={response.plan} />

          {response.results.length > 0 && (
            <PaperRelationGraph papers={response.results} />
          )}

          {response.stats.searchRounds && response.stats.searchRounds.length > 0 && (
            <SearchRoundsTimeline rounds={response.stats.searchRounds} />
          )}

          <section className="metrics-section">
            <MetricCard
              label="候选论文"
              value={String(response.stats.candidateCount)}
              hint="召回后、排序前"
            />
            <MetricCard
              label="高度相关"
              value={String(highRelevance)}
              hint="当前透明阈值"
            />
            <MetricCard
              label="端到端耗时"
              value={`${response.stats.elapsedMs} ms`}
              hint="服务端实测"
            />
            <MetricCard
              label="API 调用"
              value={String(response.stats.apiCalls)}
              hint={`${response.stats.subqueryCount} 条子查询`}
            />
            <MetricCard
              label="Token 估算"
              value={String(response.stats.tokenUsage.totalTokens)}
              hint={`${response.stats.llmCalls ?? 0} 次 LLM 调用`}
            />
          </section>

          <section className="source-status-section" aria-label="数据源状态">
            <div>
              <p className="section-index">SOURCE STATUS</p>
              <h2>实时数据源与截止时间</h2>
            </div>
            <div className="source-status-grid">
              {response.sourceStatus.map((source, index) => (
                <article key={`${source.source}-${source.round ?? 0}-${index}`}>
                  <strong>{source.source}</strong>
                  <span className={`source-state state-${source.status}`}>
                    {source.status}
                  </span>
                  <small>
                    {source.resultCount} 篇 · {source.apiCalls} 次 API
                    {typeof source.elapsedMs === "number"
                      ? ` · ${source.elapsedMs} ms`
                      : ""}
                  </small>
                </article>
              ))}
              <article>
                <strong>停止原因</strong>
                <span>{response.stats.stopReason}</span>
                <small>
                  配置 {response.stats.configHash} · 请求 {response.requestId}
                </small>
              </article>
            </div>
          </section>

          {response.results.length > 0 && (
          <section className="results-section" id="results">
            <div className="results-header">
              <div>
                <p className="section-index">03 / RANK</p>
                <h2>结构化论文结果</h2>
              </div>
              <div className="results-actions">
                <p>
                  综合分由相关性、硬约束覆盖、证据质量、权威性、
                  时效性、来源一致性与开放获取共同计算
                </p>
                <button
                  type="button"
                  className="export-button"
                  onClick={exportResults}
                  title="导出CSV"
                >
                  导出CSV
                </button>
              </div>
            </div>

            <div className="result-layout">
              <div className="paper-list">
                <TopicClusters papers={response.results} />
                {response.results.map((paper) => (
                  <PaperCard
                    key={paper.id}
                    paper={paper}
                    expanded={expandedPaper === paper.id}
                    onToggle={() =>
                      setExpandedPaper((current) =>
                        current === paper.id ? null : paper.id,
                      )
                    }
                  />
                ))}
              </div>

              <aside className="insight-rail">
                <p className="rail-label">检索审计</p>
                <h3>这次结果如何产生？</h3>
                <div className="audit-item">
                  <b>01</b>
                  <span>
                    <strong>查询约束</strong>
                    从自然语言中识别主题、方法和年份。
                  </span>
                </div>
                <div className="audit-item">
                  <b>02</b>
                  <span>
                    <strong>候选扩展</strong>
                    多个英文检索式扩大覆盖范围。
                  </span>
                </div>
                <div className="audit-item">
                  <b>03</b>
                  <span>
                    <strong>多维排序</strong>
                    相关性优先，同时考虑约束和论文元数据。
                  </span>
                </div>
                <div className="audit-item next">
                  <b>+</b>
                  <span>
                    <strong>预算停止</strong>
                    API、Token 或时间不足时不再启动下一步。
                  </span>
                </div>
              </aside>
            </div>
          </section>
          )}
        </>
      )}

      <section className="roadmap-section" id="roadmap">
        <div>
          <p className="section-index">04 / BUILD</p>
          <h2>从可靠检索到可信评测</h2>
          <p>
            v0.6 把“问题—计划—检索—排序—证据—统计”放进同一个
            50 秒预算；算法改动仍必须通过清洗后的固定验证集和消融实验。
          </p>
        </div>
        <div className="roadmap-list">
          <article>
            <span>NOW</span>
            <b>可靠检索闭环</b>
            <p>统一截止时间、结构化状态、双源降级与请求级指标。</p>
          </article>
          <article>
            <span>NEXT</span>
            <b>验证集清洗</b>
            <p>真实 DOI/跨源 ID、开发/保留集和标注复核。</p>
          </article>
          <article>
            <span>THEN</span>
            <b>量化消融</b>
            <p>查询分解、双源、引文扩展、精排和早停逐项比较。</p>
          </article>
          <article>
            <span>FINAL</span>
            <b>评测与参赛材料</b>
            <p>F1、延迟、API/Token成本、消融实验和五分钟视频。</p>
          </article>
        </div>
      </section>

      <footer>
        <div className="brand footer-brand">
          <span className="brand-mark">S</span>
          <span>
            <b>研索智航</b>
            <small>ScholarPilot · Competition MVP</small>
          </span>
        </div>
        <p>
          所有论文结果均由受保护的 Python 后端从真实学术数据源检索。
        </p>
      </footer>
    </main>
  );
}
