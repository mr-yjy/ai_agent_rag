"use client";

import type {
  RankedPaper,
  ReliabilityDecision,
  ReliabilityResult,
} from "../lib/types";

interface Props {
  reliability: ReliabilityResult;
  papers: RankedPaper[];
}

const DECISION_LABELS: Record<ReliabilityDecision, string> = {
  ACCEPT: "通过可靠性门",
  RETRY_RETRIEVAL: "建议重新检索",
  RETRY_REASONING: "建议重新推理",
  ABSTAIN: "证据不足，拒绝下结论",
  NOT_RUN: "未运行校准",
};

function percent(value: number) {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

export default function ReliabilityPanel({
  reliability,
  papers,
}: Props) {
  if (reliability.status !== "completed") return null;

  const accepted = reliability.decision === "ACCEPT";
  const evidenceRisk = reliability.diagnosis?.evidenceRisk ?? 0;
  const reasoningRisk = reliability.diagnosis?.reasoningRisk ?? 0;
  const citedPapers = new Map(papers.map((paper) => [paper.id, paper]));
  const selected = reliability.candidates?.find(
    (candidate) => candidate.id === reliability.selectedCandidateId,
  );

  return (
    <section
      className={`reliability-panel reliability-${reliability.decision.toLowerCase()}`}
      aria-labelledby="reliability-title"
    >
      <header>
        <div>
          <span>CAUSALTRUST / WHEN TO TRUST</span>
          <h3 id="reliability-title">可信结论校准</h3>
        </div>
        <strong>{DECISION_LABELS[reliability.decision]}</strong>
      </header>

      <div className="reliability-main">
        <article className="reliability-answer">
          <span>{accepted ? "校准后结论" : "可靠性门判断"}</span>
          <p>
            {accepted
              ? reliability.answer
              : reliability.message || "当前证据不足以可靠回答。"}
          </p>
          {selected?.evidenceIds.length ? (
            <div className="reliability-citations">
              {selected.evidenceIds.map((id) => {
                const paper = citedPapers.get(id);
                return paper ? (
                  <a
                    key={id}
                    href={paper.url}
                    target="_blank"
                    rel="noreferrer"
                    title={paper.title}
                  >
                    #{paper.rank}
                  </a>
                ) : (
                  <span key={id}>证据</span>
                );
              })}
            </div>
          ) : null}
        </article>

        <div className="reliability-gauges">
          <article>
            <span>CCI 置信度</span>
            <strong>{percent(reliability.confidence)}</strong>
            <i>
              <b style={{ width: percent(reliability.confidence) }} />
            </i>
          </article>
          <article>
            <span>证据风险</span>
            <strong>{percent(evidenceRisk)}</strong>
            <i>
              <b style={{ width: percent(evidenceRisk) }} />
            </i>
          </article>
          <article>
            <span>推理风险</span>
            <strong>{percent(reasoningRisk)}</strong>
            <i>
              <b style={{ width: percent(reasoningRisk) }} />
            </i>
          </article>
        </div>
      </div>

      <details className="reliability-trace-summary">
        <summary>
          查看 t0 / t1 / t2 候选与 CCI
          <span>
            {reliability.recovery?.attempted
              ? `已执行 ${reliability.recovery.mode}`
              : "未触发恢复"}
          </span>
        </summary>
        <div>
          {(reliability.candidates ?? []).map((candidate) => (
            <article key={candidate.id}>
              <div>
                <b>{candidate.id.toUpperCase()}</b>
                <strong>{percent(candidate.cci)}</strong>
              </div>
              <p>{candidate.value}</p>
              <small>
                平均支持 {percent(candidate.meanSupport)} · 不稳定性{" "}
                {percent(candidate.instability)} · 来源{" "}
                {candidate.producedBy.join(" / ")}
              </small>
            </article>
          ))}
        </div>
      </details>
    </section>
  );
}
