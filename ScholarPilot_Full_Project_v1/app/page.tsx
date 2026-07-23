"use client";

import { useEffect, useMemo, useState } from "react";
import type {
  RankedPaper,
  SearchMode,
  SearchResponse,
} from "./lib/types";

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
          <span>命中证据</span>
          <p>{paper.evidence}</p>
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
          </div>
        )}
      </div>
    </article>
  );
}

export default function Home() {
  const [query, setQuery] = useState(EXAMPLE_QUERIES[0]);
  const [mode, setMode] = useState<SearchMode>("demo");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expandedPaper, setExpandedPaper] = useState<string | null>(null);

  async function search(nextQuery = query, nextMode = mode) {
    setLoading(true);
    setError("");
    setExpandedPaper(null);
    try {
      const result = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: nextQuery, mode: nextMode }),
      });
      const payload = (await result.json()) as SearchResponse & {
        error?: string;
      };
      if (!result.ok) throw new Error(payload.error || "搜索失败");
      setResponse(payload);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "搜索失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: EXAMPLE_QUERIES[0],
        mode: "demo",
      }),
      signal: controller.signal,
    })
      .then(async (result) => {
        const payload = (await result.json()) as SearchResponse & {
          error?: string;
        };
        if (!result.ok) throw new Error(payload.error || "搜索失败");
        return payload;
      })
      .then(setResponse)
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        setError(caught instanceof Error ? caught.message : "搜索失败");
      });

    return () => controller.abort();
  }, []);

  const highRelevance = useMemo(
    () =>
      response?.results.filter((paper) => paper.level === "高度相关").length ??
      0,
    [response],
  );

  function selectExample(example: string) {
    setQuery(example);
    void search(example, mode);
  }

  function selectMode(nextMode: SearchMode) {
    setMode(nextMode);
    void search(query, nextMode);
  }

  return (
    <main>
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
        <span className="version-badge">MVP · 0.1</span>
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
            查询分解、多路线召回、约束评分与结构化证据，在同一个可复现工作流中完成。
            当前版本提供透明基线，下一阶段接入Embedding、Cross-Encoder和反事实核验。
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
          <div className="mode-switch" role="group" aria-label="数据源选择">
            <button
              type="button"
              className={mode === "demo" ? "active" : ""}
              onClick={() => selectMode("demo")}
            >
              内置演示
            </button>
            <button
              type="button"
              className={mode === "live" ? "active" : ""}
              onClick={() => selectMode("live")}
            >
              OpenAlex实时
            </button>
          </div>
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

        {error && <div className="message error-message">{error}</div>}
        {response?.warning && (
          <div className="message warning-message">{response.warning}</div>
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
              value={String(response.stats.tokenEstimate)}
              hint="预算控制基线"
            />
          </section>

          <section className="results-section" id="results">
            <div className="results-header">
              <div>
                <p className="section-index">03 / RANK</p>
                <h2>结构化论文结果</h2>
              </div>
              <p>
                综合分 = 相关性55% + 约束20% + 权威10% + 时效10% +
                开放获取5%
              </p>
            </div>

            <div className="result-layout">
              <div className="paper-list">
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
                    <strong>下一版本</strong>
                    Embedding召回、Cross-Encoder精排、反事实核验。
                  </span>
                </div>
              </aside>
            </div>
          </section>
        </>
      )}

      <section className="roadmap-section" id="roadmap">
        <div>
          <p className="section-index">04 / BUILD</p>
          <h2>从可运行Demo到比赛作品</h2>
          <p>
            当前版本已经跑通“问题—计划—检索—排序—证据—统计”闭环。后续每次升级都必须通过公开验证集和消融实验证明有效。
          </p>
        </div>
        <div className="roadmap-list">
          <article>
            <span>NOW</span>
            <b>透明检索基线</b>
            <p>真实API、可解释打分、成本记录、降级演示。</p>
          </article>
          <article>
            <span>NEXT</span>
            <b>语义召回与精排</b>
            <p>Embedding、Cross-Encoder、难负样本和阈值调优。</p>
          </article>
          <article>
            <span>THEN</span>
            <b>Agent迭代与核验</b>
            <p>引文扩展、预算停止、反事实证据检查。</p>
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
          演示数据仅用于流程验证；实时模式的论文元数据来自OpenAlex。
        </p>
      </footer>
    </main>
  );
}
