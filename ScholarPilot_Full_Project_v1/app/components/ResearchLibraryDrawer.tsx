"use client";

import { useState } from "react";
import type { SearchHistoryEntry } from "../lib/research-ui";
import type { RankedPaper } from "../lib/types";

interface Props {
  open: boolean;
  history: SearchHistoryEntry[];
  savedPapers: RankedPaper[];
  comparedIds: Set<string>;
  compareFull: boolean;
  onClose: () => void;
  onRerun: (query: string) => void;
  onClearHistory: () => void;
  onRemoveSaved: (paper: RankedPaper) => void;
  onToggleCompare: (paper: RankedPaper) => void;
}

export default function ResearchLibraryDrawer({
  open,
  history,
  savedPapers,
  comparedIds,
  compareFull,
  onClose,
  onRerun,
  onClearHistory,
  onRemoveSaved,
  onToggleCompare,
}: Props) {
  const [tab, setTab] = useState<"history" | "saved">("history");

  if (!open) return null;

  return (
    <div
      className="drawer-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose();
      }}
    >
      <aside
        className="library-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="library-title"
      >
        <header>
          <div>
            <span>LOCAL / LIBRARY</span>
            <h2 id="library-title">查询历史与收藏</h2>
          </div>
          <button type="button" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="library-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "history"}
            className={tab === "history" ? "active" : ""}
            onClick={() => setTab("history")}
          >
            最近查询 <span>{history.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "saved"}
            className={tab === "saved" ? "active" : ""}
            onClick={() => setTab("saved")}
          >
            收藏论文 <span>{savedPapers.length}</span>
          </button>
        </div>

        <div className="library-content" role="tabpanel">
          {tab === "history" && (
            <>
              <div className="library-content-heading">
                <p>历史仅保存在当前浏览器中。</p>
                {history.length > 0 && (
                  <button type="button" onClick={onClearHistory}>
                    清空历史
                  </button>
                )}
              </div>
              {history.length === 0 ? (
                <div className="library-empty">
                  <b>还没有查询历史</b>
                  <p>完成一次检索后，可从这里快速重新运行。</p>
                </div>
              ) : (
                <div className="history-list">
                  {history.map((item) => (
                    <article key={item.id}>
                      <div>
                        <span>
                          {new Intl.DateTimeFormat("zh-CN", {
                            month: "2-digit",
                            day: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                          }).format(new Date(item.searchedAt))}
                        </span>
                        <small>
                          {item.resultCount} 篇 · {item.status}
                        </small>
                      </div>
                      <p>{item.query}</p>
                      <div className="library-card-footer">
                        <code>{item.requestId}</code>
                        <button type="button" onClick={() => onRerun(item.query)}>
                          重新检索 →
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </>
          )}

          {tab === "saved" && (
            <>
              <div className="library-content-heading">
                <p>收藏保存在本地，可直接加入当前对比。</p>
              </div>
              {savedPapers.length === 0 ? (
                <div className="library-empty">
                  <b>还没有收藏论文</b>
                  <p>在论文卡片上点击“收藏”，稍后从这里继续筛选。</p>
                </div>
              ) : (
                <div className="saved-list">
                  {savedPapers.map((paper) => {
                    const compared = comparedIds.has(paper.id);
                    return (
                      <article key={paper.id}>
                        <div className="saved-paper-meta">
                          <span>#{paper.rank}</span>
                          <span>{paper.year}</span>
                          <span>{Math.round(paper.score)} 分</span>
                        </div>
                        <h3>
                          <a href={paper.url} target="_blank" rel="noreferrer">
                            {paper.title} ↗
                          </a>
                        </h3>
                        <p>{paper.authors.slice(0, 3).join(" · ")}</p>
                        <div className="library-card-footer">
                          <button
                            type="button"
                            onClick={() => onRemoveSaved(paper)}
                          >
                            取消收藏
                          </button>
                          <button
                            type="button"
                            disabled={!compared && compareFull}
                            onClick={() => onToggleCompare(paper)}
                          >
                            {compared ? "移出对比" : "加入对比"}
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
