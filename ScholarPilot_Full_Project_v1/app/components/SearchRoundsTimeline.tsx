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
          width: min(1320px, calc(100% - 48px));
          margin: 20px auto 0;
          padding: 28px;
          background: var(--surface);
          border: 1px solid #dfe5f0;
          border-radius: 26px 26px 26px 9px;
          box-shadow: var(--shadow-soft);
        }
        .timeline-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 20px;
        }
        .timeline-header h3 {
          margin: 0;
          font-size: 18px;
          font-weight: 700;
        }
        .rounds-badge {
          margin-left: auto;
          border: 1px solid rgba(82, 102, 223, 0.14);
          border-radius: 999px;
          padding: 6px 10px;
          background: var(--accent-pale);
          color: var(--accent-dark);
          font-size: 11px;
          font-weight: 700;
        }
        .timeline-track {
          display: flex;
          flex-direction: column;
          gap: 16px;
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
          background: linear-gradient(135deg, var(--accent), #7181e8);
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 14px;
          font-weight: 700;
          flex-shrink: 0;
          box-shadow: 0 6px 16px rgba(82, 102, 223, 0.22);
        }
        .node-connector {
          width: 2px;
          flex: 1;
          background: linear-gradient(var(--accent-pale), var(--line));
          min-height: 20px;
        }
        .node-card {
          flex: 1;
          background: linear-gradient(135deg, #fafbff, #f6f8fb);
          border: 1px solid #e1e6ef;
          border-radius: 16px 16px 16px 6px;
          padding: 17px 18px;
          margin-bottom: 4px;
        }
        .node-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }
        .node-strategy {
          font-weight: 700;
          font-size: 14px;
          color: var(--accent-dark);
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
          background: white;
          border: 1px solid var(--line);
          padding: 4px 8px;
          border-radius: 7px;
          color: var(--text-secondary);
          max-width: 200px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        @media (max-width: 760px) {
          .rounds-timeline {
            width: min(100% - 28px, 1320px);
            padding: 21px 18px;
            border-radius: 22px 22px 22px 8px;
          }
          .timeline-header {
            flex-wrap: wrap;
          }
          .rounds-badge {
            margin-left: 0;
          }
          .timeline-node {
            gap: 11px;
          }
          .node-marker {
            min-width: 32px;
          }
          .node-icon {
            width: 32px;
            height: 32px;
          }
          .node-stats {
            gap: 8px 14px;
            flex-wrap: wrap;
          }
          .node-queries code {
            max-width: 100%;
          }
        }
      `}</style>
    </article>
  );
}
