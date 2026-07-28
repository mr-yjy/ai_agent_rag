"use client";

import type { CSSProperties } from "react";
import type {
  RankedPaper,
  ReliabilityDecision,
  ReliabilityResult,
} from "../lib/types";

interface Props {
  reliability: ReliabilityResult;
  papers: RankedPaper[];
}

const DECISION_COPY: Record<
  ReliabilityDecision,
  { label: string; heading: string; explanation: string }
> = {
  ACCEPT: {
    label: "可以采信",
    heading: "这条结论经受住了两次质疑",
    explanation:
      "即使分别假设召回证据有缺口、推理过程有错误，当前证据仍然指向同一判断。",
  },
  RETRY_RETRIEVAL: {
    label: "暂缓采信",
    heading: "结论对证据变化较敏感",
    explanation:
      "改变对现有证据的信任方式后，结论明显波动；更适合补充检索后再判断。",
  },
  RETRY_REASONING: {
    label: "暂缓采信",
    heading: "结论对推理方式较敏感",
    explanation:
      "重新检查条件、实体和推导过程后，结论出现变化；更适合严格重算后再判断。",
  },
  ABSTAIN: {
    label: "保留判断",
    heading: "当前证据不足以支撑稳定结论",
    explanation:
      "系统没有把不稳定的第一版答案当作事实，请先阅读论文或放宽检索范围。",
  },
  NOT_RUN: {
    label: "尚未复核",
    heading: "本次只返回可阅读的论文证据",
    explanation: "可用论文或剩余预算不足，因此没有形成需要用户采信的结论。",
  },
};

const STRESS_TESTS = [
  {
    key: "baseline",
    code: "01 / FIRST PASS",
    label: "按现有证据判断",
    note: "形成第一版核心结论",
  },
  {
    key: "evidence_quality",
    code: "02 / EVIDENCE CHALLENGE",
    label: "假设召回证据有缺口",
    note: "排除弱相关、冲突和不完整证据",
  },
  {
    key: "reasoning_reliability",
    code: "03 / REASONING CHALLENGE",
    label: "假设理解或推理有错误",
    note: "重查实体、条件、数字与推导",
  },
] as const;

function percent(value: number) {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function skippedMessage(reason?: string) {
  if (reason === "insufficient_evidence") {
    return "可用论文不足 3 篇，本次不强行生成结论。";
  }
  if (reason === "budget_not_available" || reason === "budget_or_cancelled") {
    return "检索已经使用大部分时间预算，本次优先完整返回论文。";
  }
  if (reason === "llm_not_configured") {
    return "当前没有可用的个人模型配置，本次仅返回真实论文。";
  }
  return "本次未形成可供采信的稳定结论，请直接查看论文证据。";
}

export default function ReliabilityPanel({
  reliability,
  papers,
}: Props) {
  if (reliability.status !== "completed") {
    return (
      <section className="trust-deferred" aria-live="polite">
        <span aria-hidden="true">—</span>
        <div>
          <b>本次保留判断</b>
          <p>{skippedMessage(reliability.reason)}</p>
        </div>
        <small>论文结果不受影响</small>
      </section>
    );
  }

  const copy = DECISION_COPY[reliability.decision];
  const accepted = reliability.decision === "ACCEPT";
  const citedPapers = new Map(papers.map((paper) => [paper.id, paper]));
  const selected = reliability.candidates?.find(
    (candidate) => candidate.id === reliability.selectedCandidateId,
  );
  const selectedEvidence = (selected?.evidenceIds ?? [])
    .map((id) => citedPapers.get(id))
    .filter((paper): paper is RankedPaper => Boolean(paper));
  const recoveryText =
    reliability.recovery?.mode === "RETRY_RETRIEVAL"
      ? "系统发现结论对证据较敏感，已补充检索并重新复核。"
      : "系统发现结论对推理较敏感，已严格重算并重新复核。";

  return (
    <section
      className={`reliability-panel trust-decision trust-${reliability.decision.toLowerCase()}`}
      aria-labelledby="reliability-title"
    >
      <header className="trust-decision-header">
        <div>
          <span>DECISION / AFTER CHALLENGE</span>
          <h3 id="reliability-title">{copy.heading}</h3>
        </div>
        <strong>
          <i aria-hidden="true" />
          {copy.label}
        </strong>
      </header>

      <div className="trust-conclusion-grid">
        <div
          className="trust-stability-seal"
          style={
            {
              "--trust-score": percent(reliability.confidence),
            } as CSSProperties
          }
        >
          <div>
            <strong>{Math.round(reliability.confidence * 100)}</strong>
            <span>/ 100</span>
          </div>
          <small>跨质疑稳定度</small>
          <i aria-hidden="true" />
        </div>

        <article className="trust-answer">
          <span>{accepted ? "结论" : "系统判断"}</span>
          <p>
            {accepted
              ? reliability.answer
              : reliability.message || copy.explanation}
          </p>
          <small>{copy.explanation}</small>
          {accepted && selectedEvidence.length > 0 && (
            <div className="trust-evidence-links" aria-label="支撑该结论的论文">
              {selectedEvidence.slice(0, 5).map((paper) => (
                <a
                  key={paper.id}
                  href={`#paper-${paper.rank}`}
                  title={paper.title}
                >
                  <b>#{paper.rank}</b>
                  <span>{paper.title}</span>
                </a>
              ))}
              {selectedEvidence.length > 5 && (
                <span>+{selectedEvidence.length - 5}</span>
              )}
            </div>
          )}
        </article>
      </div>

      {reliability.recovery?.attempted && (
        <div className="trust-recovery-note">
          <i aria-hidden="true" />
          <span>{recoveryText}</span>
          <b>{reliability.recovery.recovered ? "复核通过" : "仍不足以采信"}</b>
        </div>
      )}

      <div className="trust-stress-tests" aria-label="结论压力测试">
        {STRESS_TESTS.map((test) => {
          const score = selected?.interventionScores[test.key] ?? 0;
          const sameConclusion = selected?.producedBy.includes(test.key) ?? false;
          return (
            <article key={test.key}>
              <span>{test.code}</span>
              <div>
                <b>{test.label}</b>
                <small>{test.note}</small>
              </div>
              <div
                className="trust-support-track"
                role="meter"
                aria-label={test.label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(score * 100)}
              >
                <i style={{ width: percent(score) }} />
              </div>
              <strong>{percent(score)}</strong>
              <em className={sameConclusion ? "stable" : "shifted"}>
                {sameConclusion ? "结论保持" : "结论偏移"}
              </em>
            </article>
          );
        })}
      </div>

      <details className="reliability-trace-summary">
        <summary>
          <span>查看其他候选与计算记录</span>
          <small>
            不是模型自报信心，而是结论在不同失败假设下的稳定程度
          </small>
        </summary>
        <div>
          {(reliability.candidates ?? []).map((candidate) => (
            <article
              key={candidate.id}
              className={
                candidate.id === reliability.selectedCandidateId
                  ? "selected"
                  : ""
              }
            >
              <div>
                <b>
                  {candidate.id === reliability.selectedCandidateId
                    ? "最终候选"
                    : candidate.id.toUpperCase()}
                </b>
                <strong>{percent(candidate.cci)}</strong>
              </div>
              <p>{candidate.value}</p>
              <small>
                平均支持 {percent(candidate.meanSupport)} · 跨质疑波动{" "}
                {percent(candidate.instability)}
              </small>
            </article>
          ))}
        </div>
      </details>
    </section>
  );
}
