"use client";

import type { SearchRound } from "../lib/types";

interface Props {
  rounds: SearchRound[];
}

const STRATEGY_LABELS: Record<string, string> = {
  initial: "初始检索",
  refinement: "迭代精化",
  citation_expansion: "引文扩展",
};

const STRATEGY_ICONS: Record<string, string> = {
  initial: "1",
  refinement: "2",
  citation_expansion: "3",
};

export default function SearchRoundsTimeline({ rounds }: Props) {
  if (!rounds || rounds.length === 0) return null;

  return (
    <article className="rounds-timeline">
      <div className="timeline-header">
        <span className="section-index">SEARCH</span>
        <h3>搜索迭代过程</h3>
        <span className="rounds-badge">{rounds.length} 轮</span>
      </div>

      <div className="timeline-track">
        {rounds.map((round, index) => (
          <div key={round.roundNumber} className="timeline-node">
            <div className="node-marker">
              <span className="node-icon">
                {STRATEGY_ICONS[round.strategy] || round.roundNumber}
              </span>
              {index < rounds.length - 1 && <div className="node-connector" />}
            </div>

            <div className="node-card">
              <div className="node-header">
                <span className="node-strategy">
                  {STRATEGY_LABELS[round.strategy] || round.strategy}
                </span>
                <span className="node-round">Round {round.roundNumber}</span>
              </div>

              <div className="node-stats">
                <span className="node-stat">
                  <b>{round.papersFound}</b> 检索到
                </span>
                <span className="node-stat">
                  <b>{round.papersAdded}</b> 新增
                </span>
                <span className="node-stat">
                  <b>{round.apiCalls}</b> API调用
                </span>
              </div>

              {round.queriesUsed && round.queriesUsed.length > 0 && (
                <div className="node-queries">
                  {round.queriesUsed.slice(0, 3).map((q, i) => (
                    <code key={i}>{q}</code>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <style>{`
        .rounds-timeline {
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: 12px;
          padding: 20px;
          margin-bottom: 24px;
        }
        .timeline-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 20px;
        }
        .timeline-header h3 {
          margin: 0;
          font-size: 16px;
        }
        .rounds-badge {
          background: var(--accent);
          color: #fff;
          font-size: 11px;
          font-weight: 600;
          padding: 2px 10px;
          border-radius: 20px;
          margin-left: auto;
        }
        .timeline-track {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }
        .timeline-node {
          display: flex;
          gap: 16px;
          position: relative;
        }
        .node-marker {
          display: flex;
          flex-direction: column;
          align-items: center;
          min-width: 36px;
        }
        .node-icon {
          width: 36px;
          height: 36px;
          border-radius: 50%;
          background: var(--accent);
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 14px;
          font-weight: 700;
          flex-shrink: 0;
        }
        .node-connector {
          width: 2px;
          flex: 1;
          background: var(--line);
          min-height: 20px;
        }
        .node-card {
          flex: 1;
          background: var(--bg);
          border: 1px solid var(--line);
          border-radius: 10px;
          padding: 14px 16px;
          margin-bottom: 4px;
        }
        .node-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }
        .node-strategy {
          font-weight: 600;
          font-size: 14px;
          color: var(--accent);
        }
        .node-round {
          font-size: 12px;
          color: var(--text-secondary);
        }
        .node-stats {
          display: flex;
          gap: 16px;
          margin-bottom: 8px;
        }
        .node-stat {
          font-size: 12px;
          color: var(--text-secondary);
        }
        .node-stat b {
          color: var(--text);
          font-weight: 600;
        }
        .node-queries {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .node-queries code {
          font-size: 11px;
          background: var(--surface);
          padding: 2px 8px;
          border-radius: 6px;
          color: var(--text-secondary);
          max-width: 200px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
      `}</style>
    </article>
  );
}
