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
          width: min(1320px, calc(100% - 48px));
          margin: 20px auto 0;
          padding: 28px;
          overflow: hidden;
          position: relative;
          background:
            radial-gradient(circle at 100% 0%, rgba(82, 102, 223, 0.12), transparent 22rem),
            linear-gradient(135deg, #ffffff, #f8f9ff);
          border: 1px solid #dfe5f0;
          border-radius: 26px 26px 26px 9px;
          box-shadow: var(--shadow-soft);
        }
        .analysis-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 20px;
        }
        .analysis-header h3 {
          margin: 0;
          font-size: 18px;
          font-weight: 700;
        }
        .confidence-badge {
          margin-left: auto;
          border: 1px solid rgba(18, 165, 148, 0.18);
          border-radius: 999px;
          padding: 6px 10px;
          background: #e2f7f2;
          color: #087665;
          font-size: 10px;
          font-weight: 700;
        }
        .analysis-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 1px;
          overflow: hidden;
          border: 1px solid var(--line);
          border-radius: 18px;
          background: var(--line);
        }
        .analysis-item {
          min-width: 0;
          min-height: 96px;
          padding: 18px;
          display: flex;
          flex-direction: column;
          justify-content: center;
          gap: 8px;
          background: rgba(255, 255, 255, 0.92);
        }
        .analysis-full {
          grid-column: 1 / -1;
          min-height: auto;
        }
        .analysis-label {
          color: #818ba0;
          font-size: 10px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.1em;
        }
        .analysis-value {
          color: var(--ink);
          font-size: 14px;
          line-height: 1.6;
        }
        .analysis-tag {
          width: fit-content;
          border: 1px solid rgba(82, 102, 223, 0.14);
          border-radius: 999px;
          padding: 5px 10px;
          background: var(--accent-pale);
          color: var(--accent-dark);
          font-size: 12px;
        }
        .analysis-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .tag {
          border: 1px solid rgba(82, 102, 223, 0.1);
          border-radius: 999px;
          padding: 5px 9px;
          background: var(--accent-pale);
          color: var(--accent-dark);
          font-size: 12px;
        }
        .tag-domain {
          border-color: rgba(18, 165, 148, 0.12);
          background: #e3f7f3;
          color: #087665;
        }
        .tag-data {
          border-color: rgba(215, 149, 42, 0.16);
          background: #fff3dc;
          color: #936014;
        }
        .tag-venue {
          border-color: rgba(138, 105, 215, 0.14);
          background: #f1eafe;
          color: #6f4cba;
        }
        .optimized-queries {
          display: flex;
          flex-direction: column;
          gap: 7px;
        }
        .optimized-queries code {
          overflow-wrap: anywhere;
          border: 1px solid #e1e6f0;
          border-radius: 9px;
          padding: 8px 10px;
          background: #f6f7fb;
          color: #5e6a80;
          font-size: 12px;
          font-family: var(--font-geist-mono), ui-monospace, monospace;
          line-height: 1.55;
        }
        @media (max-width: 900px) {
          .analysis-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }
        @media (max-width: 760px) {
          .llm-analysis {
            width: min(100% - 28px, 1320px);
            padding: 21px 18px;
            border-radius: 22px 22px 22px 8px;
          }
          .analysis-header {
            align-items: flex-start;
            flex-wrap: wrap;
          }
          .confidence-badge {
            margin-left: 0;
          }
          .analysis-grid {
            grid-template-columns: 1fr;
          }
          .analysis-full {
            grid-column: auto;
          }
        }
      `}</style>
    </article>
  );
}
