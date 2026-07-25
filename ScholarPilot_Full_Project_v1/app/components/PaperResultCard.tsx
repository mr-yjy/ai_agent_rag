"use client";

import type { RankedPaper } from "../lib/types";

export type PaperQuickAction =
  | "copy-doi"
  | "copy-citation"
  | "export-bibtex"
  | "export-ris";

interface Props {
  paper: RankedPaper;
  expanded: boolean;
  bookmarked: boolean;
  compared: boolean;
  compareDisabled: boolean;
  onToggleExpanded: () => void;
  onToggleBookmark: () => void;
  onToggleCompare: () => void;
  onQuickAction: (action: PaperQuickAction) => void;
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const percentage = Math.round(value * 100);

  return (
    <div className="score-row">
      <div>
        <span>{label}</span>
        <b>{percentage}</b>
      </div>
      <div className="score-track" aria-label={`${label} ${percentage}`}>
        <i style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

function BookmarkIcon({ active }: { active: boolean }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path
        d="M5.2 3.25h9.6v13.2L10 13.35l-4.8 3.1V3.25Z"
        fill={active ? "currentColor" : "none"}
      />
    </svg>
  );
}

export default function PaperResultCard({
  paper,
  expanded,
  bookmarked,
  compared,
  compareDisabled,
  onToggleExpanded,
  onToggleBookmark,
  onToggleCompare,
  onQuickAction,
}: Props) {
  const levelClass =
    paper.level === "高度相关"
      ? "level-high"
      : paper.level === "部分相关"
        ? "level-mid"
        : "level-low";

  return (
    <article className={`paper-card compact-paper ${expanded ? "paper-expanded" : ""}`}>
      <div
        className="paper-rank"
        aria-label={`排名 ${paper.rank}，评分 ${Math.round(paper.score)}`}
      >
        <span>RANK {paper.rank.toString().padStart(2, "0")}</span>
        <strong>{Math.round(paper.score)}</strong>
        <small>/ 100</small>
      </div>

      <div className="paper-main">
        <div className="paper-topline">
          <span className={`level-pill ${levelClass}`}>{paper.level}</span>
          <span>{paper.year}</span>
          <span>{paper.venue || "未知发表源"}</span>
          <span>被引 {paper.citedByCount}</span>
          {paper.openAccess && <span className="oa-pill">OPEN ACCESS</span>}
        </div>

        <h3>
          <a href={paper.url} target="_blank" rel="noreferrer">
            {paper.title}
            <span aria-hidden="true"> ↗</span>
          </a>
        </h3>
        <p className="authors">
          {paper.authors.length
            ? paper.authors.slice(0, 5).join(" · ")
            : "作者信息暂缺"}
          {paper.authors.length > 5 ? " 等" : ""}
        </p>

        <div className="evidence compact-evidence">
          <span>{paper.evidenceInsufficient ? "EVIDENCE / LOW" : "CORE EVIDENCE"}</span>
          <p>{paper.evidence}</p>
        </div>

        <div className="paper-decision-row">
          <div className="term-list" aria-label="命中术语">
            {(paper.matchedTerms.length ? paper.matchedTerms : ["探索候选"])
              .slice(0, 4)
              .map((term) => (
                <span key={term}>{term}</span>
              ))}
          </div>
          <div className="paper-select-actions">
            <button
              type="button"
              className={`icon-text-button bookmark-button ${bookmarked ? "active" : ""}`}
              aria-pressed={bookmarked}
              onClick={onToggleBookmark}
            >
              <BookmarkIcon active={bookmarked} />
              {bookmarked ? "已收藏" : "收藏"}
            </button>
            <label
              className={`compare-check ${compared ? "active" : ""} ${
                compareDisabled ? "disabled" : ""
              }`}
            >
              <input
                type="checkbox"
                checked={compared}
                disabled={compareDisabled}
                onChange={onToggleCompare}
              />
              <span aria-hidden="true" />
              对比
            </label>
          </div>
        </div>

        <div className="paper-quick-actions" aria-label="论文快捷操作">
          <button
            type="button"
            disabled={!paper.doi}
            title={paper.doi ? `复制 ${paper.doi}` : "该论文未提供 DOI"}
            onClick={() => onQuickAction("copy-doi")}
          >
            复制 DOI
          </button>
          <button type="button" onClick={() => onQuickAction("copy-citation")}>
            复制引用
          </button>
          <button type="button" onClick={() => onQuickAction("export-bibtex")}>
            BibTeX
          </button>
          <button type="button" onClick={() => onQuickAction("export-ris")}>
            RIS
          </button>
          <a href={paper.url} target="_blank" rel="noreferrer">
            打开原文 <span aria-hidden="true">↗</span>
          </a>
          <button
            type="button"
            className="detail-button"
            onClick={onToggleExpanded}
            aria-expanded={expanded}
          >
            {expanded ? "收起详情" : "查看详情"}
          </button>
        </div>

        {expanded && (
          <div className="paper-expanded-content">
            <div className="paper-abstract">
              <span>摘要</span>
              <p>{paper.abstract || "该数据源未返回摘要。"}</p>
            </div>

            <div className="paper-provenance">
              <span>
                <b>数据源</b>
                {paper.sources?.length ? paper.sources.join(" + ") : "未标注"}
              </span>
              <span>
                <b>检索路径</b>
                {paper.retrievalRoutes?.length
                  ? paper.retrievalRoutes.join(" → ")
                  : "未标注"}
              </span>
              {paper.doi && (
                <span>
                  <b>DOI</b>
                  {paper.doi}
                </span>
              )}
            </div>

            <div className="score-panel">
              <ScoreBar label="语义相关" value={paper.scoreBreakdown.relevance} />
              <ScoreBar label="约束满足" value={paper.scoreBreakdown.constraints} />
              <ScoreBar label="论文权威" value={paper.scoreBreakdown.authority} />
              <ScoreBar label="时间新近" value={paper.scoreBreakdown.recency} />
              <ScoreBar label="开放获取" value={paper.scoreBreakdown.openness} />
              <ScoreBar
                label="证据质量"
                value={paper.scoreBreakdown.evidenceQuality ?? 0}
              />
              <ScoreBar
                label="来源一致"
                value={paper.scoreBreakdown.sourceConsistency ?? 0}
              />
            </div>
          </div>
        )}
      </div>
    </article>
  );
}
