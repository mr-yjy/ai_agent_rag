"use client";

import type { RankedPaper } from "../lib/types";

interface Props {
  papers: RankedPaper[];
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  onRemove: (paperId: string) => void;
  onClear: () => void;
}

function ScoreCell({
  label,
  value,
}: {
  label: string;
  value: number | undefined;
}) {
  const percentage = Math.round((value ?? 0) * 100);
  return (
    <div className="compare-score">
      <span>{label}</span>
      <i>
        <b style={{ width: `${percentage}%` }} />
      </i>
      <strong>{percentage}</strong>
    </div>
  );
}

export default function PaperComparison({
  papers,
  open,
  onOpen,
  onClose,
  onRemove,
  onClear,
}: Props) {
  if (papers.length === 0) return null;

  return (
    <>
      <div className="compare-tray" role="region" aria-label="论文对比栏">
        <div className="compare-tray-copy">
          <span>{papers.length} / 4</span>
          <p>
            <b>待对比论文</b>
            {papers.map((paper) => `#${paper.rank}`).join(" · ")}
          </p>
        </div>
        <div className="compare-tray-actions">
          <button type="button" className="subtle-button" onClick={onClear}>
            清空
          </button>
          <button
            type="button"
            className="primary-small-button"
            disabled={papers.length < 2}
            onClick={onOpen}
          >
            {papers.length < 2 ? "再选 1 篇" : "打开对比"}
          </button>
        </div>
      </div>

      {open && (
        <div
          className="comparison-overlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) onClose();
          }}
        >
          <section
            className="comparison-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="comparison-title"
          >
            <header>
              <div>
                <span>COMPARE / DECIDE</span>
                <h2 id="comparison-title">论文横向对比</h2>
                <p>把方法、影响力、核心证据和评分组成放在同一视线内。</p>
              </div>
              <button type="button" aria-label="关闭对比面板" onClick={onClose}>
                ×
              </button>
            </header>

            <div className="comparison-cards">
              {papers.map((paper) => (
                <article key={paper.id} className="comparison-paper">
                  <div className="comparison-paper-head">
                    <span>#{paper.rank}</span>
                    <button
                      type="button"
                      aria-label={`从对比中移除 ${paper.title}`}
                      onClick={() => onRemove(paper.id)}
                    >
                      移除
                    </button>
                  </div>
                  <h3>
                    <a href={paper.url} target="_blank" rel="noreferrer">
                      {paper.title} ↗
                    </a>
                  </h3>
                  <dl>
                    <div>
                      <dt>年份 / 发表源</dt>
                      <dd>
                        {paper.year} · {paper.venue || "未知"}
                      </dd>
                    </div>
                    <div>
                      <dt>引用 / 获取</dt>
                      <dd>
                        {paper.citedByCount} ·{" "}
                        {paper.openAccess ? "开放获取" : "访问状态未知"}
                      </dd>
                    </div>
                    <div>
                      <dt>方法与主题</dt>
                      <dd>
                        {[...paper.matchedTerms, ...paper.concepts]
                          .filter(
                            (value, index, values) =>
                              values.indexOf(value) === index,
                          )
                          .slice(0, 5)
                          .join(" · ") || "未提取"}
                      </dd>
                    </div>
                    <div>
                      <dt>核心证据</dt>
                      <dd>{paper.evidence}</dd>
                    </div>
                  </dl>
                  <div className="comparison-score-total">
                    <span>综合评分</span>
                    <strong>{Math.round(paper.score)}</strong>
                  </div>
                  <div className="comparison-score-list">
                    <ScoreCell
                      label="相关"
                      value={paper.scoreBreakdown.relevance}
                    />
                    <ScoreCell
                      label="约束"
                      value={paper.scoreBreakdown.constraints}
                    />
                    <ScoreCell
                      label="权威"
                      value={paper.scoreBreakdown.authority}
                    />
                    <ScoreCell
                      label="证据"
                      value={paper.scoreBreakdown.evidenceQuality}
                    />
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
