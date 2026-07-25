"use client";

import { useState } from "react";
import type { SearchResponse } from "../lib/types";
import LLMAnalysisPanel from "./LLMAnalysisPanel";
import PaperRelationGraph from "./PaperRelationGraph";
import SearchRoundsTimeline from "./SearchRoundsTimeline";

type RecordTab = "path" | "performance" | "sources";

interface Props {
  response: SearchResponse;
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <article className="detail-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </article>
  );
}

export default function RetrievalDetails({ response }: Props) {
  const [activeTab, setActiveTab] = useState<RecordTab>("path");
  const highRelevance = response.results.filter(
    (paper) => paper.level === "高度相关",
  ).length;

  const relatedPapers = response.results
    .map((paper) => ({
      paper,
      relationCount: response.results.filter(
        (candidate) =>
          candidate.id !== paper.id &&
          candidate.concepts.some((concept) => paper.concepts.includes(concept)),
      ).length,
    }))
    .sort(
      (left, right) =>
        right.relationCount - left.relationCount ||
        left.paper.rank - right.paper.rank,
    )
    .slice(0, 5);

  return (
    <details className="retrieval-details" id="details">
      <summary>
        <span className="details-summary-mark" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span>
          <b>检索详情</b>
          <small>
            查询理解、本次检索记录与高级分析
          </small>
        </span>
        <span className="details-request">
          REQUEST {response.requestId}
        </span>
        <span className="details-chevron" aria-hidden="true">
          ↓
        </span>
      </summary>

      <div className="retrieval-details-body">
        <section className="query-understanding" aria-labelledby="understanding-title">
          <div className="detail-section-heading">
            <div>
              <span>UNDERSTANDING / PLAN</span>
              <h3 id="understanding-title">系统如何理解这次查询</h3>
            </div>
            <span className="provider-label">{response.provider}</span>
          </div>

          <div className="understanding-grid">
            <article className="normalized-query">
              <span>规范化查询</span>
              <p>{response.plan.normalizedQuery}</p>
              <div className="constraint-list">
                {response.plan.yearFrom && (
                  <span>
                    年份 ≥ {response.plan.yearFrom}
                    {response.plan.yearTo ? `，≤ ${response.plan.yearTo}` : ""}
                  </span>
                )}
                {response.plan.mustHave.map((term) => (
                  <span key={`must-${term}`}>必须 / {term}</span>
                ))}
                {response.plan.preferred.map((term) => (
                  <span key={`prefer-${term}`}>偏好 / {term}</span>
                ))}
                {response.plan.exclude.map((term) => (
                  <span key={`exclude-${term}`}>排除 / {term}</span>
                ))}
              </div>
            </article>

            <article className="parallel-queries">
              <span>并行检索式</span>
              <ol>
                {response.plan.subqueries.map((subquery) => (
                  <li key={subquery}>{subquery}</li>
                ))}
              </ol>
            </article>
          </div>

          <LLMAnalysisPanel plan={response.plan} />
        </section>

        <section className="search-record" aria-labelledby="record-title">
          <div className="detail-section-heading">
            <div>
              <span>RUN / RECORD</span>
              <h3 id="record-title">本次检索记录</h3>
            </div>
            <div className="record-tabs" role="tablist" aria-label="本次检索记录">
              {(
                [
                  ["path", "路径"],
                  ["performance", "性能"],
                  ["sources", "数据源"],
                ] as const
              ).map(([tab, label]) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab}
                  className={activeTab === tab ? "active" : ""}
                  onClick={() => setActiveTab(tab)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="record-panel" role="tabpanel">
            {activeTab === "path" && (
              <>
                {response.stats.searchRounds?.length ? (
                  <SearchRoundsTimeline rounds={response.stats.searchRounds} />
                ) : (
                  <p className="record-empty">后端未返回分轮检索记录。</p>
                )}
                <div className="stop-note">
                  <span>停止原因</span>
                  <b>{response.stats.stopReason}</b>
                  <small>剩余预算 {response.stats.budgetRemainingMs} ms</small>
                </div>
              </>
            )}

            {activeTab === "performance" && (
              <div className="detail-metrics-grid">
                <Metric
                  label="候选论文"
                  value={String(response.stats.candidateCount)}
                  hint={`去重后 ${response.stats.deduplicatedCount}`}
                />
                <Metric
                  label="高度相关"
                  value={String(highRelevance)}
                  hint={`最终返回 ${response.results.length}`}
                />
                <Metric
                  label="端到端耗时"
                  value={`${response.stats.elapsedMs} ms`}
                  hint={`${response.stats.apiCalls} 次 API`}
                />
                <Metric
                  label="子查询"
                  value={String(response.stats.subqueryCount)}
                  hint={response.stats.searchStrategy || "自动策略"}
                />
                <Metric
                  label="Token"
                  value={String(response.stats.tokenUsage.totalTokens)}
                  hint={`${response.stats.llmCalls ?? 0} 次 LLM`}
                />
                <Metric
                  label="缓存命中"
                  value={String(response.stats.cacheHits)}
                  hint={`配置 ${response.stats.configHash}`}
                />
                <div className="stage-timings">
                  <span>阶段耗时</span>
                  {Object.entries(response.stats.stageTimings).map(
                    ([stage, elapsed]) => (
                      <div key={stage}>
                        <b>{stage}</b>
                        <span>{elapsed} ms</span>
                      </div>
                    ),
                  )}
                </div>
              </div>
            )}

            {activeTab === "sources" && (
              <div className="detail-sources-grid">
                {response.sourceStatus.map((source, index) => (
                  <article
                    key={`${source.source}-${source.round ?? 0}-${index}`}
                  >
                    <div>
                      <span>S.{String(index + 1).padStart(2, "0")}</span>
                      <strong>{source.source}</strong>
                    </div>
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
                <article className="request-record">
                  <div>
                    <span>REQ</span>
                    <strong>请求审计</strong>
                  </div>
                  <code>{response.requestId}</code>
                  <small>配置 {response.stats.configHash}</small>
                </article>
              </div>
            )}
          </div>
        </section>

        {response.results.length > 0 && (
          <details className="advanced-analysis">
            <summary>
              <span>
                <b>高级分析</b>
                <small>按需查看论文关系坐标；不会阻挡论文结果</small>
              </span>
              <span aria-hidden="true">+</span>
            </summary>
            <div className="desktop-relation-graph">
              <PaperRelationGraph papers={response.results} />
            </div>
            <div className="mobile-relation-summary">
              <p>关联度较高的论文</p>
              {relatedPapers.map(({ paper, relationCount }) => (
                <a key={paper.id} href={paper.url} target="_blank" rel="noreferrer">
                  <span>#{paper.rank}</span>
                  <b>{paper.title}</b>
                  <small>{relationCount} 个主题关联</small>
                </a>
              ))}
            </div>
          </details>
        )}
      </div>
    </details>
  );
}
