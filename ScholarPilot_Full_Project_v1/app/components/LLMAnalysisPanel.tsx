"use client";

import type { QueryPlan } from "../lib/types";

interface Props {
  plan: QueryPlan;
}

export default function LLMAnalysisPanel({ plan }: Props) {
  // Only show if we have LLM-enhanced data
  const hasEnhanced =
    plan.researchTopic ||
    (plan.methods && plan.methods.length > 0) ||
    (plan.datasets && plan.datasets.length > 0) ||
    (plan.domains && plan.domains.length > 0) ||
    (plan.optimizedQueries && plan.optimizedQueries.length > 0);

  if (!hasEnhanced) return null;

  return (
    <article className="llm-analysis">
      <div className="analysis-header">
        <span className="section-index">ANALYSIS</span>
        <h3>LLM 查询分析</h3>
        {plan.confidence && (
          <span className="confidence-badge">
            {Math.round(plan.confidence * 100)}% 置信度
          </span>
        )}
      </div>

      <div className="analysis-grid">
        {/* Research Topic */}
        {plan.researchTopic && (
          <div className="analysis-item">
            <span className="analysis-label">研究主题</span>
            <span className="analysis-value">{plan.researchTopic}</span>
          </div>
        )}

        {/* Intent Category */}
        {plan.intentCategory && (
          <div className="analysis-item">
            <span className="analysis-label">意图类别</span>
            <span className="analysis-value analysis-tag">
              {plan.intentCategory}
            </span>
          </div>
        )}

        {/* Methods */}
        {plan.methods && plan.methods.length > 0 && (
          <div className="analysis-item">
            <span className="analysis-label">研究方法</span>
            <div className="analysis-tags">
              {plan.methods.map((m) => (
                <span key={m} className="tag">
                  {m}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Domains */}
        {plan.domains && plan.domains.length > 0 && (
          <div className="analysis-item">
            <span className="analysis-label">研究领域</span>
            <div className="analysis-tags">
              {plan.domains.map((d) => (
                <span key={d} className="tag tag-domain">
                  {d}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Datasets */}
        {plan.datasets && plan.datasets.length > 0 && (
          <div className="analysis-item">
            <span className="analysis-label">数据集</span>
            <div className="analysis-tags">
              {plan.datasets.map((d) => (
                <span key={d} className="tag tag-data">
                  {d}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Venues */}
        {plan.venues && plan.venues.length > 0 && (
          <div className="analysis-item">
            <span className="analysis-label">目标发表源</span>
            <div className="analysis-tags">
              {plan.venues.map((v) => (
                <span key={v} className="tag tag-venue">
                  {v}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Optimized Queries */}
        {plan.optimizedQueries && plan.optimizedQueries.length > 0 && (
          <div className="analysis-item analysis-full">
            <span className="analysis-label">优化搜索式</span>
            <div className="optimized-queries">
              {plan.optimizedQueries.map((q, i) => (
                <code key={i}>{q}</code>
              ))}
            </div>
          </div>
        )}
      </div>

      <style>{`
        .llm-analysis {
          background: linear-gradient(135deg, var(--surface), #1a1a2e);
          border: 1px solid var(--line);
          border-radius: 12px;
          padding: 20px;
          margin-bottom: 24px;
        }
        .analysis-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;
        }
        .analysis-header h3 {
          margin: 0;
          font-size: 16px;
        }
        .confidence-badge {
          background: #059669;
          color: #fff;
          font-size: 10px;
          font-weight: 600;
          padding: 2px 10px;
          border-radius: 20px;
          margin-left: auto;
        }
        .analysis-grid {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .analysis-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .analysis-full {
          grid-column: 1 / -1;
        }
        .analysis-label {
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .analysis-value {
          font-size: 14px;
        }
        .analysis-tag {
          background: rgba(99, 102, 241, 0.1);
          color: var(--accent);
          padding: 2px 10px;
          border-radius: 6px;
          font-size: 12px;
          display: inline-block;
        }
        .analysis-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .tag {
          font-size: 12px;
          background: rgba(99, 102, 241, 0.08);
          padding: 3px 10px;
          border-radius: 6px;
          color: var(--text);
        }
        .tag-domain {
          background: rgba(16, 185, 129, 0.1);
          color: #34d399;
        }
        .tag-data {
          background: rgba(245, 158, 11, 0.1);
          color: #fbbf24;
        }
        .tag-venue {
          background: rgba(139, 92, 246, 0.1);
          color: #a78bfa;
        }
        .optimized-queries {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .optimized-queries code {
          font-size: 12px;
          background: var(--bg);
          padding: 4px 10px;
          border-radius: 6px;
          color: var(--text-secondary);
          font-family: ui-monospace, monospace;
        }
      `}</style>
    </article>
  );
}
