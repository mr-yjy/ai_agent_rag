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

export default function SearchRoundsTimeline({ rounds }: Props) {
  if (!rounds || rounds.length === 0) return null;

  return (
    <article className="rounds-timeline">
      <div className="timeline-header">
        <div>
          <span className="section-index">SEARCH / ROUNDS</span>
          <h3>检索迭代记录</h3>
        </div>
        <span className="rounds-badge">{rounds.length} ROUNDS</span>
      </div>

      <div className="timeline-track">
        {rounds.map((round, index) => (
          <div key={round.roundNumber} className="timeline-node">
            <div className="node-marker" aria-hidden="true">
              <span>{String(round.roundNumber).padStart(2, "0")}</span>
              {index < rounds.length - 1 && <i />}
            </div>

            <div className="node-card">
              <div className="node-header">
                <span className="node-strategy">
                  {STRATEGY_LABELS[round.strategy] || round.strategy}
                </span>
                <span className="node-round">
                  {round.elapsedMs} ms
                </span>
              </div>

              <div className="node-stats">
                <span>
                  <b>{round.papersFound}</b>
                  找到
                </span>
                <span>
                  <b>{round.papersAdded}</b>
                  新增
                </span>
                <span>
                  <b>{round.apiCalls}</b>
                  API 调用
                </span>
              </div>

              {round.queriesUsed && round.queriesUsed.length > 0 && (
                <div className="node-queries">
                  {round.queriesUsed.slice(0, 3).map((query, queryIndex) => (
                    <code key={queryIndex}>{query}</code>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </article>
  );
}
