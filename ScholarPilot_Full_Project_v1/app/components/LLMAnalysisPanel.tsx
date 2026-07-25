"use client";

import type { QueryPlan } from "../lib/types";

interface Props {
  plan: QueryPlan;
}

export default function LLMAnalysisPanel({ plan }: Props) {
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
        <div>
          <span className="section-index">ANALYSIS / LLM</span>
          <h3>查询语义拆解</h3>
        </div>
        {typeof plan.confidence === "number" && (
          <span className="confidence-badge">
            CONFIDENCE {Math.round(plan.confidence * 100)}%
          </span>
        )}
      </div>

      <div className="analysis-grid">
        {plan.researchTopic && (
          <div className="analysis-item analysis-topic">
            <span className="analysis-label">RESEARCH TOPIC</span>
            <span className="analysis-value">{plan.researchTopic}</span>
          </div>
        )}

        {plan.intentCategory && (
          <div className="analysis-item">
            <span className="analysis-label">INTENT</span>
            <span className="analysis-value analysis-tag">
              {plan.intentCategory}
            </span>
          </div>
        )}

        {plan.methods && plan.methods.length > 0 && (
          <div className="analysis-item">
            <span className="analysis-label">METHODS</span>
            <div className="analysis-tags">
              {plan.methods.map((method) => (
                <span key={method} className="tag">
                  {method}
                </span>
              ))}
            </div>
          </div>
        )}

        {plan.domains && plan.domains.length > 0 && (
          <div className="analysis-item">
            <span className="analysis-label">DOMAINS</span>
            <div className="analysis-tags">
              {plan.domains.map((domain) => (
                <span key={domain} className="tag tag-domain">
                  {domain}
                </span>
              ))}
            </div>
          </div>
        )}

        {plan.datasets && plan.datasets.length > 0 && (
          <div className="analysis-item">
            <span className="analysis-label">DATASETS</span>
            <div className="analysis-tags">
              {plan.datasets.map((dataset) => (
                <span key={dataset} className="tag tag-data">
                  {dataset}
                </span>
              ))}
            </div>
          </div>
        )}

        {plan.venues && plan.venues.length > 0 && (
          <div className="analysis-item">
            <span className="analysis-label">VENUES</span>
            <div className="analysis-tags">
              {plan.venues.map((venue) => (
                <span key={venue} className="tag tag-venue">
                  {venue}
                </span>
              ))}
            </div>
          </div>
        )}

        {plan.optimizedQueries && plan.optimizedQueries.length > 0 && (
          <div className="analysis-item analysis-full">
            <span className="analysis-label">OPTIMIZED QUERIES</span>
            <div className="optimized-queries">
              {plan.optimizedQueries.map((query, index) => (
                <code key={index}>{query}</code>
              ))}
            </div>
          </div>
        )}
      </div>
    </article>
  );
}
