"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import PaperComparison from "./components/PaperComparison";
import PaperResultCard, {
  type PaperQuickAction,
} from "./components/PaperResultCard";
import ResearchLibraryDrawer from "./components/ResearchLibraryDrawer";
import RetrievalDetails from "./components/RetrievalDetails";
import {
  isSearchResponse,
  NonJsonResponseError,
  protocolError,
  readApiError,
  readJsonResponse,
} from "./lib/api-schema";
import {
  copyText,
  downloadText,
  formatBibtex,
  formatCitation,
  formatRis,
  getTopicOptions,
  removeYearConstraint,
  safeFilename,
  type SearchHistoryEntry,
} from "./lib/research-ui";
import type { ApiError, RankedPaper, SearchResponse } from "./lib/types";

const EXAMPLE_QUERIES = [
  {
    title: "查询分解",
    description: "复杂检索 · 引文扩展",
    query:
      "寻找2024—2026年使用查询分解或引文扩展进行复杂学术论文检索的LLM Agent论文",
  },
  {
    title: "RAG 重排序",
    description: "召回优化 · 实验优先",
    query:
      "检索RAG中使用查询改写和重排序提高召回率的论文，并优先展示有实验的工作",
  },
  {
    title: "科研 Agent 评测",
    description: "2024 后 · 文献检索",
    query:
      "Find benchmarks after 2024 that evaluate AI agents for scientific research and literature search",
  },
];

const HISTORY_STORAGE_KEY = "scholarpilot:search-history:v1";
const SAVED_STORAGE_KEY = "scholarpilot:saved-papers:v1";

type SortMode = "relevance" | "year" | "citations";

interface Filters {
  sort: SortMode;
  year: string;
  level: string;
  source: string;
  topic: string;
  openAccessOnly: boolean;
}

const DEFAULT_FILTERS: Filters = {
  sort: "relevance",
  year: "all",
  level: "all",
  source: "all",
  topic: "all",
  openAccessOnly: false,
};

function Brand() {
  return (
    <span className="brand" aria-label="ScholarPilot 研索智航">
      <svg className="brand-mark" viewBox="0 0 42 42" aria-hidden="true">
        <path d="M8 29L20 10L34 28" />
        <path d="M8 29L25 32L34 28" />
        <circle cx="20" cy="10" r="3.5" />
        <circle cx="8" cy="29" r="3.5" />
        <circle cx="34" cy="28" r="3.5" />
      </svg>
      <span>
        <b>ScholarPilot</b>
        <small>研索智航</small>
      </span>
    </span>
  );
}

function TraceHero() {
  return (
    <section className="hero" id="top">
      <div className="hero-copy">
        <p className="eyebrow">TRACEABLE LITERATURE RETRIEVAL</p>
        <h1>
          把复杂问题，
          <em>变成一条可核验的证据链。</em>
        </h1>
        <p className="hero-description">
          ScholarPilot 将自然语言研究问题拆成检索约束、并行查询与排序证据。
          先帮你找到值得读的论文，技术解释则留在需要核验时查看。
        </p>
        <div className="hero-facts" aria-label="系统能力">
          <span>
            <b>02</b>
            实时学术数据源
          </span>
          <span>
            <b>50s</b>
            请求级总预算
          </span>
          <span>
            <b>01</b>
            可追踪请求链
          </span>
        </div>
      </div>

      <aside className="trace-map" aria-labelledby="trace-title">
        <div className="trace-map-header">
          <div>
            <span>SP / DECISION TRACE</span>
            <h2 id="trace-title">一次搜索如何成为证据</h2>
          </div>
          <code>06.0</code>
        </div>
        <ol className="trace-route">
          <li>
            <span>Q.00</span>
            <div>
              <b>研究问题</b>
              <small>自然语言输入</small>
            </div>
          </li>
          <li>
            <span>P.01</span>
            <div>
              <b>约束与子查询</b>
              <small>主题 · 方法 · 年份</small>
            </div>
          </li>
          <li className="trace-branch">
            <span>R.02</span>
            <div>
              <b>双源召回</b>
              <small>OpenAlex / Semantic Scholar</small>
            </div>
          </li>
          <li>
            <span>E.03</span>
            <div>
              <b>结果优先</b>
              <small>筛选 · 对比 · 引用</small>
            </div>
          </li>
        </ol>
        <div className="trace-coordinate" aria-hidden="true">
          READ / FILTER / VERIFY
        </div>
      </aside>
    </section>
  );
}

function ResultSkeleton() {
  return (
    <section className="loading-deck" aria-live="polite" aria-busy="true">
      <div className="loading-copy">
        <span>LIVE RETRIEVAL</span>
        <h2>正在整理可决策的论文结果</h2>
        <p>规划查询、召回真实论文并生成排序证据；复杂问题可能需要几十秒。</p>
      </div>
      <div className="loading-route" aria-hidden="true">
        <span className="complete">问题</span>
        <i />
        <span className="active">召回</span>
        <i />
        <span>排序</span>
        <i />
        <span>证据</span>
      </div>
      <div className="skeleton-paper">
        <i />
        <div>
          <b />
          <b />
          <span />
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const [query, setQuery] = useState(EXAMPLE_QUERIES[0].query);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [expandedPaper, setExpandedPaper] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [health, setHealth] = useState<{
    ready: boolean;
    adapter: string;
    model: string;
  } | null>(null);
  const [history, setHistory] = useState<SearchHistoryEntry[]>([]);
  const [savedPapers, setSavedPapers] = useState<RankedPaper[]>([]);
  const [comparedPapers, setComparedPapers] = useState<RankedPaper[]>([]);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      try {
        const storedHistory = JSON.parse(
          localStorage.getItem(HISTORY_STORAGE_KEY) || "[]",
        ) as unknown;
        if (Array.isArray(storedHistory)) {
          setHistory(storedHistory.slice(0, 12) as SearchHistoryEntry[]);
        }

        const storedPapers = JSON.parse(
          localStorage.getItem(SAVED_STORAGE_KEY) || "[]",
        ) as unknown;
        if (Array.isArray(storedPapers)) {
          setSavedPapers(storedPapers as RankedPaper[]);
        }
      } catch {
        localStorage.removeItem(HISTORY_STORAGE_KEY);
        localStorage.removeItem(SAVED_STORAGE_KEY);
      }
    });

    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    fetch("/api/health", { signal: controller.signal })
      .then(async (result) => {
        const payload = (await readJsonResponse(result)) as Record<
          string,
          unknown
        >;
        const backend = payload.backend as Record<string, unknown> | undefined;
        const llm = payload.llm as Record<string, unknown> | undefined;
        setHealth({
          ready: payload.ready === true,
          adapter:
            typeof backend?.adapter === "string"
              ? backend.adapter
              : "unreachable",
          model: typeof llm?.model === "string" ? llm.model : "未配置",
        });
      })
      .catch(() =>
        setHealth({
          ready: false,
          adapter: "unreachable",
          model: "unknown",
        }),
      );

    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setLibraryOpen(false);
      setComparisonOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);

  async function search(nextQuery = query) {
    const cleanQuery = nextQuery.trim();
    if (cleanQuery.length < 6) return;

    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setQuery(cleanQuery);
    setLoading(true);
    setError(null);
    setResponse(null);
    setExpandedPaper(null);
    setFilters(DEFAULT_FILTERS);

    try {
      const result = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: cleanQuery }),
        signal: controller.signal,
      });
      const payload = await readJsonResponse(result);

      if (!result.ok) {
        setError(
          readApiError(
            payload,
            "搜索失败，请稍后重试。",
            "request-id-unavailable",
          ),
        );
        return;
      }

      if (!isSearchResponse(payload)) {
        setError(protocolError("request-id-unavailable").error);
        return;
      }

      setResponse(payload);
      const historyEntry: SearchHistoryEntry = {
        id: `${Date.now()}-${payload.requestId}`,
        query: cleanQuery,
        searchedAt: new Date().toISOString(),
        resultCount: payload.results.length,
        requestId: payload.requestId,
        status: payload.status,
      };
      setHistory((current) => {
        const next = [
          historyEntry,
          ...current.filter((entry) => entry.query !== cleanQuery),
        ].slice(0, 12);
        localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(next));
        return next;
      });
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        return;
      }

      if (caught instanceof NonJsonResponseError) {
        setError({
          code: "search_gateway_non_json_response",
          message:
            "公网访问通道返回了非 JSON 响应。请刷新页面后重试；若持续出现，请检查 Cloudflare 隧道是否在线。",
          requestId: "request-id-unavailable",
          retryable: true,
          retryAfterSeconds: 2,
          upstreamStatus: caught.status || undefined,
        });
        return;
      }

      setError({
        code: "search_network_error",
        message:
          caught instanceof Error ? caught.message : "搜索网络请求失败。",
        requestId: "request-id-unavailable",
        retryable: true,
        retryAfterSeconds: 0,
      });
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        setLoading(false);
      }
    }
  }

  function cancelSearch() {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setLoading(false);
    setResponse(null);
    setError({
      code: "search_cancelled",
      message: "搜索已取消，后端不会再启动后续检索轮次或精排。",
      requestId: "cancelled-before-response",
      retryable: true,
      retryAfterSeconds: 0,
    });
  }

  const topics = useMemo(
    () => getTopicOptions(response?.results ?? []),
    [response],
  );

  const years = useMemo(
    () =>
      Array.from(
        new Set((response?.results ?? []).map((paper) => paper.year)),
      ).sort((left, right) => right - left),
    [response],
  );

  const sources = useMemo(
    () =>
      Array.from(
        new Set(
          (response?.results ?? []).flatMap((paper) => paper.sources ?? []),
        ),
      ).sort((left, right) => left.localeCompare(right)),
    [response],
  );

  const filteredPapers = useMemo(() => {
    if (!response) return [];
    const next = response.results.filter((paper) => {
      if (filters.year !== "all" && paper.year !== Number(filters.year)) {
        return false;
      }
      if (filters.level !== "all" && paper.level !== filters.level) {
        return false;
      }
      if (
        filters.source !== "all" &&
        !(paper.sources ?? []).includes(filters.source)
      ) {
        return false;
      }
      if (
        filters.topic !== "all" &&
        !paper.concepts.some(
          (concept) =>
            concept.toLocaleLowerCase() === filters.topic.toLocaleLowerCase(),
        )
      ) {
        return false;
      }
      if (filters.openAccessOnly && !paper.openAccess) return false;
      return true;
    });

    return next.sort((left, right) => {
      if (filters.sort === "year") {
        return right.year - left.year || left.rank - right.rank;
      }
      if (filters.sort === "citations") {
        return right.citedByCount - left.citedByCount || left.rank - right.rank;
      }
      return left.rank - right.rank;
    });
  }, [filters, response]);

  const activeFilterCount = [
    filters.year !== "all",
    filters.level !== "all",
    filters.source !== "all",
    filters.topic !== "all",
    filters.openAccessOnly,
  ].filter(Boolean).length;

  const totalHighRelevance =
    response?.results.filter((paper) => paper.level === "高度相关").length ?? 0;
  const openAccessCount =
    response?.results.filter((paper) => paper.openAccess).length ?? 0;
  const healthState =
    health === null ? "checking" : health.ready ? "ready" : "offline";
  const resultMode = loading || Boolean(response) || Boolean(error);
  const comparedIds = useMemo(
    () => new Set(comparedPapers.map((paper) => paper.id)),
    [comparedPapers],
  );
  const savedIds = useMemo(
    () => new Set(savedPapers.map((paper) => paper.id)),
    [savedPapers],
  );

  function updateSavedPapers(next: RankedPaper[]) {
    setSavedPapers(next);
    localStorage.setItem(SAVED_STORAGE_KEY, JSON.stringify(next));
  }

  function toggleBookmark(paper: RankedPaper) {
    const exists = savedIds.has(paper.id);
    const next = exists
      ? savedPapers.filter((candidate) => candidate.id !== paper.id)
      : [paper, ...savedPapers];
    updateSavedPapers(next);
    setToast(exists ? "已取消收藏" : "已保存到本地收藏");
  }

  function toggleCompare(paper: RankedPaper) {
    if (comparedIds.has(paper.id)) {
      setComparedPapers((current) =>
        current.filter((candidate) => candidate.id !== paper.id),
      );
      return;
    }
    if (comparedPapers.length >= 4) {
      setToast("最多同时对比 4 篇论文");
      return;
    }
    setComparedPapers((current) => [...current, paper]);
  }

  async function handleQuickAction(
    paper: RankedPaper,
    action: PaperQuickAction,
  ) {
    if (action === "copy-doi") {
      if (!paper.doi) return;
      await copyText(paper.doi);
      setToast("DOI 已复制");
      return;
    }
    if (action === "copy-citation") {
      await copyText(formatCitation(paper));
      setToast("引用已复制");
      return;
    }
    if (action === "export-bibtex") {
      downloadText(safeFilename(paper, "bib"), formatBibtex(paper));
      setToast("BibTeX 已导出");
      return;
    }
    downloadText(safeFilename(paper, "ris"), formatRis(paper));
    setToast("RIS 已导出");
  }

  function exportResults() {
    if (!response || filteredPapers.length === 0) return;
    const escapeCell = (value: string | number) =>
      `"${String(value).replace(/"/g, '""')}"`;
    const headers = [
      "排名",
      "标题",
      "作者",
      "年份",
      "发表源",
      "引用数",
      "综合评分",
      "相关级别",
      "证据",
      "DOI",
      "URL",
    ];
    const rows = filteredPapers.map((paper) => [
      paper.rank,
      paper.title,
      paper.authors.join("; "),
      paper.year,
      paper.venue,
      paper.citedByCount,
      paper.score,
      paper.level,
      paper.evidence,
      paper.doi || "",
      paper.url,
    ]);
    const csv = [headers, ...rows]
      .map((row) => row.map(escapeCell).join(","))
      .join("\n");
    downloadText(
      `scholarpilot-results-${Date.now()}.csv`,
      `\uFEFF${csv}`,
      "text/csv;charset=utf-8",
    );
  }

  function applyQuerySuggestion(nextQuery: string) {
    setQuery(nextQuery);
    document.getElementById("research-query")?.focus();
    document
      .getElementById("workspace")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
    setToast("已填入查询栏，可继续修改或重新检索");
  }

  function clearHistory() {
    setHistory([]);
    localStorage.removeItem(HISTORY_STORAGE_KEY);
  }

  return (
    <main className={`app-shell ${resultMode ? "result-mode" : "landing-mode"}`}>
      <a className="skip-link" href="#workspace">
        跳到检索输入
      </a>

      <header className="site-header">
        <a href="#top" aria-label="返回 ScholarPilot 顶部">
          <Brand />
        </a>

        <nav aria-label="页面导航">
          <a href="#workspace">修改查询</a>
          {response && <a href="#results">论文结果</a>}
          {response && <a href="#details">检索详情</a>}
        </nav>

        <div className="header-utilities">
          <button type="button" onClick={() => setLibraryOpen(true)}>
            我的研究库
            {(history.length > 0 || savedPapers.length > 0) && (
              <span>{history.length + savedPapers.length}</span>
            )}
          </button>
          <div className={`version-badge status-${healthState}`}>
            <i aria-hidden="true" />
            <span>
              v0.6 / {health?.ready ? "LIVE" : health ? "CHECK" : "SYNC"}
            </span>
          </div>
        </div>
      </header>

      {!resultMode && <TraceHero />}

      <section
        className={`search-workspace ${
          resultMode ? "workspace-compact" : "workspace-expanded"
        }`}
        id="workspace"
      >
        {!resultMode ? (
          <>
            <div className="workspace-header">
              <div>
                <p className="section-index">QUERY / START</p>
                <h2>你现在要回答什么研究问题？</h2>
              </div>
              <div
                className={`workspace-status status-${healthState}`}
                aria-live="polite"
              >
                <i aria-hidden="true" />
                <span>
                  {health === null
                    ? "正在检查检索服务"
                    : health.ready
                      ? "实时检索服务已就绪"
                      : "检索服务暂未就绪"}
                </span>
              </div>
            </div>

            <div className="query-box">
              <label htmlFor="research-query">研究问题</label>
              <textarea
                id="research-query"
                value={query}
                maxLength={800}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    (event.ctrlKey || event.metaKey) &&
                    event.key === "Enter" &&
                    !loading &&
                    query.trim().length >= 6
                  ) {
                    event.preventDefault();
                    void search();
                  }
                }}
                placeholder="描述主题、时间范围、方法和你更关心的证据类型……"
              />
              <div className="query-actions">
                <span>{query.length} / 800 · Ctrl/⌘ + Enter 提交</span>
                <div>
                  <button
                    type="button"
                    className="search-button"
                    disabled={loading || query.trim().length < 6}
                    onClick={() => void search()}
                  >
                    <span>开始检索</span>
                    <i aria-hidden="true">→</i>
                  </button>
                </div>
              </div>
            </div>

            <div className="examples" aria-label="示例问题">
              <span>从示例开始</span>
              {EXAMPLE_QUERIES.map((example) => (
                <button
                  type="button"
                  key={example.title}
                  onClick={() => {
                    setQuery(example.query);
                    setError(null);
                  }}
                  title={example.query}
                >
                  <strong>{example.title}</strong>
                  <small>{example.description}</small>
                </button>
              ))}
            </div>

            <div className="health-strip" aria-label="检索服务状态">
              <span>
                <b>BACKEND</b>
                {health?.ready ? "READY" : health ? "UNAVAILABLE" : "CHECKING"}
              </span>
              <span>
                <b>ADAPTER</b>
                {health?.adapter ?? "检测中"}
              </span>
              <span>
                <b>MODEL</b>
                {health?.model ?? "检测中"}
              </span>
            </div>
          </>
        ) : (
          <div className="compact-search">
            <label htmlFor="research-query">
              <span>修改查询</span>
              <input
                id="research-query"
                value={query}
                maxLength={800}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    (event.ctrlKey || event.metaKey) &&
                    event.key === "Enter" &&
                    !loading &&
                    query.trim().length >= 6
                  ) {
                    event.preventDefault();
                    void search();
                  }
                }}
              />
            </label>
            <div className={`compact-health status-${healthState}`}>
              <i aria-hidden="true" />
              <span>{health?.ready ? "LIVE" : health ? "CHECK" : "SYNC"}</span>
            </div>
            {loading && (
              <button
                type="button"
                className="compact-cancel"
                onClick={cancelSearch}
              >
                取消
              </button>
            )}
            <button
              type="button"
              className="compact-submit"
              disabled={loading || query.trim().length < 6}
              onClick={() => void search()}
            >
              {loading ? "检索中…" : "重新检索"}
              <span aria-hidden="true">→</span>
            </button>
          </div>
        )}
      </section>

      {loading && <ResultSkeleton />}

      {error && (
        <section className="message error-message error-detail result-message" role="alert">
          <div>
            <span>SEARCH ERROR / {error.code}</span>
            <strong>{error.message}</strong>
          </div>
          <dl>
            <div>
              <dt>请求 ID</dt>
              <dd>{error.requestId}</dd>
            </div>
            {error.stage && (
              <div>
                <dt>失败阶段</dt>
                <dd>{error.stage}</dd>
              </div>
            )}
            <div>
              <dt>下一步</dt>
              <dd>
                {error.retryable
                  ? `重试当前问题${
                      error.retryAfterSeconds
                        ? `，建议等待 ${error.retryAfterSeconds} 秒`
                        : ""
                    }`
                  : "检查查询内容或服务配置"}
              </dd>
            </div>
          </dl>
          {error.retryable && (
            <button type="button" onClick={() => void search()}>
              重试本次查询
            </button>
          )}
        </section>
      )}

      {response && (
        <section className="results-section result-first" id="results">
          <header className="results-first-heading">
            <div>
              <p className="section-index">RESULTS / DECISION DESK</p>
              <h2>
                {response.results.length > 0
                  ? `找到 ${response.results.length} 篇可筛选论文`
                  : "本次没有匹配论文"}
              </h2>
              <p>
                先判断哪些论文值得读；检索过程与技术指标已移至页面底部。
              </p>
            </div>
            <button
              type="button"
              className="export-button"
              disabled={filteredPapers.length === 0}
              onClick={exportResults}
            >
              导出当前结果
              <span aria-hidden="true">↓</span>
            </button>
          </header>

          <div className="result-vitals" aria-label="结果摘要">
            <article>
              <span>当前显示</span>
              <strong>{filteredPapers.length}</strong>
              <small>共 {response.results.length} 篇</small>
            </article>
            <article>
              <span>高度相关</span>
              <strong>{totalHighRelevance}</strong>
              <small>透明相关阈值</small>
            </article>
            <article>
              <span>开放获取</span>
              <strong>{openAccessCount}</strong>
              <small>可直接访问全文</small>
            </article>
            <article>
              <span>本次耗时</span>
              <strong>{(response.stats.elapsedMs / 1000).toFixed(1)}s</strong>
              <small>{response.provider}</small>
            </article>
          </div>

          {(response.warning || response.status === "degraded") && (
            <div className="message warning-message result-warning">
              <strong>当前结果为降级检索。</strong>{" "}
              {response.warning ||
                "部分数据源不可用，仅展示已成功返回的真实论文。"}
              <span> 请求 ID：{response.requestId}</span>
            </div>
          )}

          <div className="filter-console" aria-label="结果筛选与排序">
            <div className="filter-console-heading">
              <div>
                <span>FILTER / SORT</span>
                <b>结果筛选</b>
                {activeFilterCount > 0 && <small>{activeFilterCount} 项已启用</small>}
              </div>
              {activeFilterCount > 0 && (
                <button
                  type="button"
                  onClick={() => setFilters(DEFAULT_FILTERS)}
                >
                  清除筛选
                </button>
              )}
            </div>

            <div className="filter-fields">
              <label>
                <span>排序</span>
                <select
                  value={filters.sort}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      sort: event.target.value as SortMode,
                    }))
                  }
                >
                  <option value="relevance">综合相关度</option>
                  <option value="year">最新年份</option>
                  <option value="citations">引用数</option>
                </select>
              </label>
              <label>
                <span>年份</span>
                <select
                  value={filters.year}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      year: event.target.value,
                    }))
                  }
                >
                  <option value="all">全部年份</option>
                  {years.map((year) => (
                    <option key={year} value={year}>
                      {year}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>相关级别</span>
                <select
                  value={filters.level}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      level: event.target.value,
                    }))
                  }
                >
                  <option value="all">全部级别</option>
                  <option value="高度相关">高度相关</option>
                  <option value="部分相关">部分相关</option>
                  <option value="探索性">探索性</option>
                </select>
              </label>
              <label>
                <span>数据源</span>
                <select
                  value={filters.source}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      source: event.target.value,
                    }))
                  }
                >
                  <option value="all">全部数据源</option>
                  {sources.map((source) => (
                    <option key={source} value={source}>
                      {source}
                    </option>
                  ))}
                </select>
              </label>
              <label className="oa-filter">
                <input
                  type="checkbox"
                  checked={filters.openAccessOnly}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      openAccessOnly: event.target.checked,
                    }))
                  }
                />
                <i aria-hidden="true" />
                <span>仅开放获取</span>
              </label>
            </div>

            {topics.length > 0 && (
              <div className="topic-filter">
                <span>主题</span>
                <button
                  type="button"
                  className={filters.topic === "all" ? "active" : ""}
                  aria-pressed={filters.topic === "all"}
                  onClick={() =>
                    setFilters((current) => ({ ...current, topic: "all" }))
                  }
                >
                  全部
                  <small>{response.results.length}</small>
                </button>
                {topics.map((topic) => (
                  <button
                    type="button"
                    key={topic.label}
                    className={filters.topic === topic.label ? "active" : ""}
                    aria-pressed={filters.topic === topic.label}
                    onClick={() =>
                      setFilters((current) => ({
                        ...current,
                        topic:
                          current.topic === topic.label ? "all" : topic.label,
                      }))
                    }
                  >
                    {topic.label}
                    <small>{topic.count}</small>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="query-suggestions" aria-label="查询优化建议">
            <span>快速调整</span>
            {response.plan.yearFrom && (
              <button
                type="button"
                onClick={() => applyQuerySuggestion(removeYearConstraint(query))}
              >
                放宽年份
              </button>
            )}
            {(response.plan.researchTopic ||
              response.plan.mustHave.length > 0) && (
              <button
                type="button"
                onClick={() =>
                  applyQuerySuggestion(
                    [
                      response.plan.researchTopic,
                      ...(response.plan.methods ?? []).slice(0, 2),
                    ]
                      .filter(Boolean)
                      .join(" ") || response.plan.normalizedQuery,
                  )
                }
              >
                只保留核心主题
              </button>
            )}
            {response.plan.optimizedQueries?.[0] && (
              <button
                type="button"
                onClick={() =>
                  applyQuerySuggestion(response.plan.optimizedQueries?.[0] ?? query)
                }
              >
                使用优化英文查询
              </button>
            )}
            {response.results.some((paper) => paper.openAccess) && (
              <button
                type="button"
                className={filters.openAccessOnly ? "active" : ""}
                onClick={() =>
                  setFilters((current) => ({
                    ...current,
                    openAccessOnly: !current.openAccessOnly,
                  }))
                }
              >
                {filters.openAccessOnly ? "显示全部访问状态" : "只看开放获取"}
              </button>
            )}
            {response.results.some((paper) => paper.level === "探索性") && (
              <button
                type="button"
                onClick={() =>
                  setFilters((current) => ({ ...current, level: "all" }))
                }
              >
                扩大到探索性结果
              </button>
            )}
          </div>

          {response.results.length === 0 ? (
            <div className="decision-empty">
              <span>0 RESULTS</span>
              <h3>约束可能过窄，先调整查询再运行</h3>
              <p>
                可放宽年份、减少必选术语，或使用系统生成的英文查询。
                上方建议会先填入查询栏，由你确认后再重新检索。
              </p>
            </div>
          ) : filteredPapers.length === 0 ? (
            <div className="decision-empty">
              <span>FILTERED TO ZERO</span>
              <h3>当前筛选组合没有论文</h3>
              <p>清除部分筛选即可恢复结果，不需要重新调用检索服务。</p>
              <button
                type="button"
                onClick={() => setFilters(DEFAULT_FILTERS)}
              >
                清除全部筛选
              </button>
            </div>
          ) : (
            <div className="paper-list" aria-live="polite">
              <div className="paper-list-heading">
                <span>
                  显示 {filteredPapers.length} / {response.results.length}
                </span>
                <p>选择 2–4 篇论文可在底部打开横向对比。</p>
              </div>
              {filteredPapers.map((paper) => (
                <PaperResultCard
                  key={paper.id}
                  paper={paper}
                  expanded={expandedPaper === paper.id}
                  bookmarked={savedIds.has(paper.id)}
                  compared={comparedIds.has(paper.id)}
                  compareDisabled={
                    !comparedIds.has(paper.id) && comparedPapers.length >= 4
                  }
                  onToggleExpanded={() =>
                    setExpandedPaper((current) =>
                      current === paper.id ? null : paper.id,
                    )
                  }
                  onToggleBookmark={() => toggleBookmark(paper)}
                  onToggleCompare={() => toggleCompare(paper)}
                  onQuickAction={(action) =>
                    void handleQuickAction(paper, action)
                  }
                />
              ))}
            </div>
          )}

          <RetrievalDetails response={response} />
        </section>
      )}

      <footer className="site-footer">
        <Brand />
        <p>
          论文来自真实学术数据源。收藏、查询历史与对比列表仅保存在当前浏览器。
        </p>
      </footer>

      <PaperComparison
        papers={comparedPapers}
        open={comparisonOpen}
        onOpen={() => setComparisonOpen(true)}
        onClose={() => setComparisonOpen(false)}
        onRemove={(paperId) =>
          setComparedPapers((current) =>
            current.filter((paper) => paper.id !== paperId),
          )
        }
        onClear={() => {
          setComparedPapers([]);
          setComparisonOpen(false);
        }}
      />

      <ResearchLibraryDrawer
        open={libraryOpen}
        history={history}
        savedPapers={savedPapers}
        comparedIds={comparedIds}
        compareFull={comparedPapers.length >= 4}
        onClose={() => setLibraryOpen(false)}
        onRerun={(nextQuery) => {
          setLibraryOpen(false);
          void search(nextQuery);
        }}
        onClearHistory={clearHistory}
        onRemoveSaved={toggleBookmark}
        onToggleCompare={toggleCompare}
      />

      {toast && (
        <div className="toast" role="status" aria-live="polite">
          <i aria-hidden="true">✓</i>
          {toast}
        </div>
      )}
    </main>
  );
}
