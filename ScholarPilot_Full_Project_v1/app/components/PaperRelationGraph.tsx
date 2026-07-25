"use client";

import { useMemo, useState } from "react";
import type { RankedPaper } from "../lib/types";

interface Props {
  papers: RankedPaper[];
}

interface GraphNode {
  id: string;
  label: string;
  score: number;
  level: string;
  year: number;
  cluster: number;
}

interface GraphEdge {
  source: string;
  target: string;
  weight: number;
}

interface TimelineNode {
  id: string;
  label: string;
  score: number;
  level: string;
  year: number;
  x: number;
  y: number;
  stackIndex: number;
}

export default function PaperRelationGraph({ papers }: Props) {
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"citation" | "topic" | "timeline">(
    "topic",
  );

  const graphData = useMemo(() => {
    if (!papers || papers.length === 0) return { nodes: [], edges: [], timelineNodes: [], yearRange: { min: 0, max: 0 }, yearTicks: [] };

    const nodes: GraphNode[] = papers.map((paper, idx) => ({
      id: paper.id,
      label:
        paper.title.length > 40
          ? paper.title.slice(0, 38) + "..."
          : paper.title,
      score: paper.score,
      level: paper.level,
      year: paper.year,
      cluster: idx % 3,
    }));

    const edges: GraphEdge[] = [];

    if (viewMode === "topic") {
      for (let i = 0; i < papers.length; i++) {
        for (let j = i + 1; j < papers.length; j++) {
          const sharedConcepts = papers[i].concepts.filter((c) =>
            papers[j].concepts.includes(c),
          );
          if (sharedConcepts.length >= 2) {
            edges.push({
              source: papers[i].id,
              target: papers[j].id,
              weight: sharedConcepts.length,
            });
          }
        }
      }
    } else if (viewMode === "citation") {
      for (let i = 0; i < papers.length; i++) {
        for (let j = i + 1; j < papers.length; j++) {
          const cites = papers[i].referencedWorks.some((ref) =>
            papers[j].id.includes(ref) || ref.includes(papers[j].id),
          );
          if (cites) {
            edges.push({
              source: papers[i].id,
              target: papers[j].id,
              weight: 1,
            });
          }
        }
      }
    }

    // --- Timeline-specific data ---
    let timelineNodes: TimelineNode[] = [];
    let yearRange = { min: 0, max: 0 };
    let yearTicks: number[] = [];

    if (viewMode === "timeline") {
      const sorted = [...papers].sort((a, b) => a.year - b.year);
      let minYear = sorted[0]?.year ?? 2020;
      let maxYear = sorted[sorted.length - 1]?.year ?? 2024;

      // Expand range if all papers are the same year
      if (minYear === maxYear) {
        minYear = minYear - 1;
        maxYear = maxYear + 1;
      }
      // Ensure at least 2 years of span for visual clarity
      if (maxYear - minYear < 1) {
        maxYear = minYear + 2;
      }

      yearRange = { min: minYear, max: maxYear };

      // Build year ticks (every year, but if span > 15, every 2 years)
      const yearSpan = maxYear - minYear;
      const tickInterval = yearSpan > 15 ? 2 : 1;
      const ticks: number[] = [];
      for (let y = minYear; y <= maxYear; y += tickInterval) {
        ticks.push(y);
      }
      yearTicks = ticks;

      // X-axis mapping
      const marginLeft = 70;
      const marginRight = 60;
      const axisStartX = marginLeft;
      const axisEndX = 800 - marginRight;

      const yearToX = (year: number): number => {
        if (yearSpan === 0) return (axisStartX + axisEndX) / 2;
        return (
          axisStartX +
          ((year - minYear) / yearSpan) * (axisEndX - axisStartX)
        );
      };

      // Group papers by year for stacking
      const byYear = new Map<number, typeof sorted>();
      for (const paper of sorted) {
        const list = byYear.get(paper.year) || [];
        list.push(paper);
        byYear.set(paper.year, list);
      }

      // Build timeline nodes with stacking
      const axisY = 310;
      const baseNodeY = 30;
      const stackSpacing = 44;

      timelineNodes = sorted.map((paper) => {
        const sameYearPapers = byYear.get(paper.year)!;
        const stackIndex = sameYearPapers.indexOf(paper);
        // Offset odd stacks to create visual variety
        const yOffset = stackIndex * stackSpacing;

        return {
          id: paper.id,
          label:
            paper.title.length > 25
              ? paper.title.slice(0, 23) + "..."
              : paper.title,
          score: paper.score,
          level: paper.level,
          year: paper.year,
          x: yearToX(paper.year),
          y: baseNodeY + yOffset,
          stackIndex,
        };
      });
    }

    return { nodes, edges, timelineNodes, yearRange, yearTicks };
  }, [papers, viewMode]);

  if (papers.length === 0) return null;

  const selectedPaper = papers.find((p) => p.id === selectedNode);

  const levelColors: Record<string, string> = {
    "高度相关": "#059669",
    "部分相关": "#d97706",
    "探索性": "#6b7280",
  };

  const isTimeline = viewMode === "timeline";

  return (
    <article className="relation-graph">
      <div className="graph-header">
        <span className="section-index">GRAPH</span>
        <h3>论文关系图</h3>
        <div className="graph-controls">
          <div className="view-toggle" role="group" aria-label="关系图模式">
            {(["topic", "citation", "timeline"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                className={viewMode === mode ? "active" : ""}
                onClick={() => {
                  setViewMode(mode);
                  setSelectedNode(null);
                }}
              >
                {mode === "topic"
                  ? "主题关联"
                  : mode === "citation"
                    ? "引用关系"
                    : "时间线"}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className={`graph-container${isTimeline ? " graph-container--timeline" : ""}`}>
        <svg
          viewBox="0 0 800 400"
          className="graph-svg"
          aria-label="论文关系图"
        >
          {isTimeline ? (
            /* ========== TIMELINE VIEW ========== */
            <>
              {/* Background gradient for timeline */}
              <defs>
                <linearGradient id="timelineGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#cbd5e1" />
                  <stop offset="50%" stopColor="#5266df" />
                  <stop offset="100%" stopColor="#3449be" />
                </linearGradient>
                <linearGradient id="timelineGlow" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="rgba(82,102,223,0.06)" />
                  <stop offset="50%" stopColor="rgba(82,102,223,0.12)" />
                  <stop offset="100%" stopColor="rgba(52,73,190,0.08)" />
                </linearGradient>
                {/* Drop shadow filter for nodes */}
                <filter id="nodeShadow" x="-50%" y="-50%" width="200%" height="200%">
                  <feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.15" />
                </filter>
              </defs>

              {/* Subtle timeline backdrop */}
              <rect
                x={60}
                y={10}
                width={690}
                height={300}
                rx={14}
                fill="url(#timelineGlow)"
                opacity={0.6}
              />

              {/* Time axis main bar */}
              <line
                x1={70}
                y1={310}
                x2={740}
                y2={310}
                stroke="url(#timelineGradient)"
                strokeWidth={4}
                strokeLinecap="round"
              />

              {/* Axis endpoint circles */}
              <circle cx={70} cy={310} r={6} fill="#cbd5e1" />
              <circle cx={740} cy={310} r={6} fill="#3449be" />

              {/* Year ticks and labels */}
              {graphData.yearTicks.map((year) => {
                const yearSpan = graphData.yearRange.max - graphData.yearRange.min || 1;
                const x =
                  70 +
                  ((year - graphData.yearRange.min) / yearSpan) * (740 - 70);

                if (x < 60 || x > 750) return null;

                const isRoundYear = year % 5 === 0 || yearSpan <= 3;

                return (
                  <g key={`tick-${year}`}>
                    {/* Tick mark */}
                    <line
                      x1={x}
                      y1={303}
                      x2={x}
                      y2={317}
                      stroke={isRoundYear ? "#5266df" : "#cbd3e3"}
                      strokeWidth={isRoundYear ? 2.5 : 1.5}
                      strokeLinecap="round"
                    />
                    {/* Year label */}
                    <text
                      x={x}
                      y={340}
                      textAnchor="middle"
                      fontSize={isRoundYear ? 13 : 11}
                      fontWeight={isRoundYear ? 700 : 500}
                      fill={isRoundYear ? "#3449be" : "#94a3b8"}
                      fontFamily="system-ui, -apple-system, sans-serif"
                    >
                      {year}
                    </text>
                    {/* Subtle vertical guide line */}
                    <line
                      x1={x}
                      y1={40}
                      x2={x}
                      y2={298}
                      stroke="#e2e8f0"
                      strokeWidth={0.8}
                      strokeDasharray="4 8"
                      opacity={0.7}
                    />
                  </g>
                );
              })}

              {/* Connection lines between nodes in same year group */}
              {graphData.timelineNodes.map((node, i) => {
                // Connect nodes within the same year with a subtle vertical line
                const sameYearSiblings = graphData.timelineNodes.filter(
                  (n) => n.year === node.year && n.id !== node.id && n.stackIndex < node.stackIndex,
                );
                if (sameYearSiblings.length === 0) return null;
                const prevSibling = sameYearSiblings[sameYearSiblings.length - 1];
                return (
                  <line
                    key={`stack-line-${i}`}
                    x1={node.x}
                    y1={prevSibling.y + 12}
                    x2={node.x}
                    y2={node.y - 12}
                    stroke="#e2e8f0"
                    strokeWidth={1.5}
                    strokeDasharray="3 4"
                    opacity={0.5}
                  />
                );
              })}

              {/* Vertical lines connecting nodes to time axis */}
              {graphData.timelineNodes.map((node) => (
                <line
                  key={`drop-${node.id}`}
                  x1={node.x}
                  y1={node.y + 14}
                  x2={node.x}
                  y2={306}
                  stroke={
                    node.level === "高度相关"
                      ? "rgba(5,150,105,0.18)"
                      : node.level === "部分相关"
                        ? "rgba(217,119,6,0.16)"
                        : "rgba(107,114,128,0.12)"
                  }
                  strokeWidth={1}
                  strokeDasharray="2 5"
                />
              ))}

              {/* Paper nodes */}
              {graphData.timelineNodes.map((node) => {
                const isSelected = selectedNode === node.id;
                const baseR = 13;
                const radius = isSelected ? 18 : baseR;
                const color = levelColors[node.level] || "#6b7280";

                return (
                  <g
                    key={node.id}
                    style={{ cursor: "pointer" }}
                    onClick={() =>
                      setSelectedNode(
                        selectedNode === node.id ? null : node.id,
                      )
                    }
                  >
                    {/* Halo glow on selected */}
                    {isSelected && (
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r={radius + 8}
                        fill="none"
                        stroke={color}
                        strokeWidth={1.5}
                        opacity={0.25}
                      />
                    )}

                    {/* Score ring */}
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={radius + 4}
                      fill="none"
                      stroke={color}
                      strokeWidth={2}
                      strokeDasharray={`${(node.score / 100) * Math.PI * 2 * (radius + 4)} ${Math.PI * 2 * (radius + 4)}`}
                      opacity={isSelected ? 0.7 : 0.35}
                      transform={`rotate(-90 ${node.x} ${node.y})`}
                    />

                    {/* Main node circle */}
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={radius}
                      fill={color}
                      opacity={isSelected ? 1 : 0.82}
                      stroke="#fff"
                      strokeWidth={isSelected ? 2.5 : 1.5}
                      filter={isSelected ? "url(#nodeShadow)" : undefined}
                    />

                    {/* Rank number inside node */}
                    <text
                      x={node.x}
                      y={node.y + 1}
                      textAnchor="middle"
                      dominantBaseline="central"
                      fontSize={isSelected ? 11 : 9}
                      fontWeight={700}
                      fill="#fff"
                      fontFamily="system-ui, -apple-system, sans-serif"
                      style={{ pointerEvents: "none" }}
                    >
                      {papers.find((p) => p.id === node.id)?.rank ?? ""}
                    </text>

                    {/* Title label above node */}
                    <text
                      x={node.x}
                      y={node.y - radius - 8}
                      textAnchor="middle"
                      fontSize={10}
                      fill="#475569"
                      fontFamily="system-ui, -apple-system, sans-serif"
                      style={{ pointerEvents: "none" }}
                    >
                      {node.label}
                    </text>
                  </g>
                );
              })}
            </>
          ) : (
            /* ========== TOPIC / CITATION VIEW (circular layout) ========== */
            <>
              {/* Render edges */}
              {graphData.edges.map((edge, i) => {
                const sourceNode = graphData.nodes.find(
                  (n) => n.id === edge.source,
                );
                const targetNode = graphData.nodes.find(
                  (n) => n.id === edge.target,
                );
                if (!sourceNode || !targetNode) return null;
                const si = graphData.nodes.indexOf(sourceNode);
                const ti = graphData.nodes.indexOf(targetNode);
                const totalNodes = graphData.nodes.length;

                const angleS = (si / totalNodes) * Math.PI * 2;
                const angleT = (ti / totalNodes) * Math.PI * 2;
                const cx = 400, cy = 200, radius = 140;
                const x1 = cx + Math.cos(angleS) * radius;
                const y1 = cy + Math.sin(angleS) * radius;
                const x2 = cx + Math.cos(angleT) * radius;
                const y2 = cy + Math.sin(angleT) * radius;

                return (
                  <line
                    key={`edge-${i}`}
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                    stroke="var(--line)"
                    strokeWidth={Math.min(edge.weight, 3)}
                    opacity={0.6}
                  />
                );
              })}

              {/* Render nodes */}
              {graphData.nodes.map((node, idx) => {
                const totalNodes = graphData.nodes.length;
                const angle = (idx / totalNodes) * Math.PI * 2;
                const cx = 400, cy = 200, radius = 140;
                const x = cx + Math.cos(angle) * radius;
                const y = cy + Math.sin(angle) * radius;
                const isSelected = selectedNode === node.id;
                const radius_ = isSelected ? 28 : 20;

                return (
                  <g key={node.id}>
                    <circle
                      cx={x}
                      cy={y}
                      r={radius_}
                      fill={levelColors[node.level] || "#6b7280"}
                      opacity={isSelected ? 1 : 0.7}
                      stroke={isSelected ? "#fff" : "transparent"}
                      strokeWidth={2}
                      style={{ cursor: "pointer", transition: "all 0.2s" }}
                      onClick={() =>
                        setSelectedNode(
                          selectedNode === node.id ? null : node.id,
                        )
                      }
                    />
                    <text
                      x={x}
                      y={y - radius_ - 6}
                      textAnchor="middle"
                      fontSize={10}
                      fill="var(--text-secondary)"
                    >
                      {node.label.length > 20
                        ? node.label.slice(0, 18) + ".."
                        : node.label}
                    </text>
                    <circle
                      cx={x}
                      cy={y}
                      r={radius_ + 3}
                      fill="none"
                      stroke={levelColors[node.level] || "#6b7280"}
                      strokeWidth={2}
                      strokeDasharray={`${(node.score / 100) * Math.PI * 2 * (radius_ + 3)} ${Math.PI * 2 * (radius_ + 3)}`}
                      opacity={0.5}
                      transform={`rotate(-90 ${x} ${y})`}
                    />
                  </g>
                );
              })}
            </>
          )}
        </svg>

        {/* Legend */}
        <div className="graph-legend">
          <span>
            <i style={{ background: "#059669" }} /> 高度相关
          </span>
          <span>
            <i style={{ background: "#d97706" }} /> 部分相关
          </span>
          <span>
            <i style={{ background: "#6b7280" }} /> 探索性
          </span>
          {viewMode === "topic" && (
            <span className="legend-note">连线=共享研究主题 ≥2</span>
          )}
          {viewMode === "citation" && (
            <span className="legend-note">连线=引用关系</span>
          )}
          {viewMode === "timeline" && (
            <span className="legend-note">时间轴按发表年份排列 · 圆内=排名</span>
          )}
        </div>
      </div>

      {/* Selected paper detail */}
      {selectedPaper && (
        <div className="graph-detail">
          <strong>#{selectedPaper.rank}</strong>
          <span>{selectedPaper.title}</span>
          <span className="detail-score">
            {Math.round(selectedPaper.score)}分 · {selectedPaper.level}
          </span>
        </div>
      )}

      <style>{`
        .relation-graph {
          width: min(1320px, calc(100% - 48px));
          margin: 20px auto 0;
          padding: 28px;
          background:
            radial-gradient(circle at 0 0, rgba(18, 165, 148, 0.09), transparent 20rem),
            var(--surface);
          border: 1px solid #dfe5f0;
          border-radius: 26px 26px 26px 9px;
          box-shadow: var(--shadow-soft);
        }
        .graph-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 20px;
          flex-wrap: wrap;
        }
        .graph-header h3 {
          margin: 0;
          font-size: 18px;
          font-weight: 700;
        }
        .graph-controls {
          margin-left: auto;
        }
        .view-toggle {
          display: flex;
          gap: 3px;
          padding: 4px;
          border: 1px solid var(--line);
          border-radius: 999px;
          background: #f4f6fa;
        }
        .view-toggle button {
          padding: 7px 12px;
          border: none;
          background: none;
          font-size: 12px;
          cursor: pointer;
          border-radius: 999px;
          color: var(--text-secondary);
          font-weight: 600;
          transition: all 160ms ease;
        }
        .view-toggle button.active {
          background: linear-gradient(135deg, var(--accent), #6f7fe8);
          color: #fff;
          box-shadow: 0 5px 14px rgba(82, 102, 223, 0.22);
        }
        .graph-container {
          overflow: hidden;
          position: relative;
          border: 1px solid #e2e7f0;
          border-radius: 18px;
          padding: 12px 16px 16px;
          background:
            radial-gradient(circle at 50% 50%, rgba(82, 102, 223, 0.07), transparent 17rem),
            linear-gradient(rgba(82, 102, 223, 0.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(82, 102, 223, 0.035) 1px, transparent 1px),
            #fafbfe;
          background-size: auto, 28px 28px, 28px 28px, auto;
        }
        .graph-container--timeline {
          background:
            linear-gradient(180deg, #f8fafd 0%, #f1f5fb 100%);
        }
        .graph-svg {
          width: 100%;
          height: auto;
          min-height: 330px;
          max-height: 420px;
        }
        .graph-legend {
          display: flex;
          gap: 16px;
          margin-top: 4px;
          border-top: 1px solid #e4e8f0;
          padding-top: 14px;
          font-size: 12px;
          color: var(--text-secondary);
          flex-wrap: wrap;
        }
        .graph-legend i {
          display: inline-block;
          width: 10px;
          height: 10px;
          border-radius: 50%;
          margin-right: 4px;
        }
        .legend-note {
          margin-left: auto;
          font-style: italic;
        }
        .graph-detail {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 14px;
          border: 1px solid rgba(82, 102, 223, 0.12);
          border-radius: 12px;
          padding: 12px 14px;
          background: var(--accent-pale);
          font-size: 13px;
        }
        .graph-detail strong {
          color: var(--accent);
          min-width: 28px;
        }
        .detail-score {
          margin-left: auto;
          color: var(--text-secondary);
          font-size: 12px;
          white-space: nowrap;
        }
        @media (max-width: 760px) {
          .relation-graph {
            width: min(100% - 28px, 1320px);
            padding: 21px 18px;
            border-radius: 22px 22px 22px 8px;
          }
          .graph-header {
            align-items: flex-start;
            flex-direction: column;
          }
          .graph-controls,
          .view-toggle {
            width: 100%;
          }
          .view-toggle button {
            flex: 1;
            padding-inline: 7px;
          }
          .graph-container {
            padding-inline: 6px;
          }
          .graph-svg {
            min-height: 260px;
          }
          .legend-note {
            width: 100%;
            margin-left: 0;
          }
          .graph-detail {
            align-items: flex-start;
            flex-direction: column;
          }
          .detail-score {
            margin-left: 0;
          }
        }
      `}</style>
    </article>
  );
}
