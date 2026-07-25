"use client";

import { useMemo, useState } from "react";
import type { RankedPaper } from "../lib/types";

interface Props {
  papers: RankedPaper[];
}

type ViewMode = "topic" | "citation" | "timeline";

interface GraphNode {
  id: string;
  label: string;
  score: number;
  level: string;
  year: number;
  rank: number;
}

interface GraphEdge {
  source: string;
  target: string;
  weight: number;
}

interface PositionedNode extends GraphNode {
  x: number;
  y: number;
}

const LEVEL_COLORS: Record<string, string> = {
  "高度相关": "#087f73",
  "部分相关": "#b97716",
  "探索性": "#69777d",
};

function circlePosition(index: number, total: number) {
  const angle = (index / Math.max(total, 1)) * Math.PI * 2 - Math.PI / 2;
  return {
    x: 400 + Math.cos(angle) * 138,
    y: 192 + Math.sin(angle) * 138,
  };
}

export default function PaperRelationGraph({ papers }: Props) {
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("topic");

  const graphData = useMemo(() => {
    const nodes: GraphNode[] = papers.map((paper) => ({
      id: paper.id,
      label:
        paper.title.length > 34
          ? `${paper.title.slice(0, 32)}…`
          : paper.title,
      score: paper.score,
      level: paper.level,
      year: paper.year,
      rank: paper.rank,
    }));
    const edges: GraphEdge[] = [];

    if (viewMode === "topic") {
      for (let left = 0; left < papers.length; left += 1) {
        for (let right = left + 1; right < papers.length; right += 1) {
          const sharedConcepts = papers[left].concepts.filter((concept) =>
            papers[right].concepts.includes(concept),
          );
          if (sharedConcepts.length >= 2) {
            edges.push({
              source: papers[left].id,
              target: papers[right].id,
              weight: sharedConcepts.length,
            });
          }
        }
      }
    }

    if (viewMode === "citation") {
      for (let left = 0; left < papers.length; left += 1) {
        for (let right = left + 1; right < papers.length; right += 1) {
          const leftCitesRight = papers[left].referencedWorks.some(
            (reference) =>
              papers[right].id.includes(reference) ||
              reference.includes(papers[right].id),
          );
          const rightCitesLeft = papers[right].referencedWorks.some(
            (reference) =>
              papers[left].id.includes(reference) ||
              reference.includes(papers[left].id),
          );
          if (leftCitesRight || rightCitesLeft) {
            edges.push({
              source: papers[left].id,
              target: papers[right].id,
              weight: 1,
            });
          }
        }
      }
    }

    const positionedNodes: PositionedNode[] =
      viewMode === "timeline"
        ? buildTimelineNodes(nodes)
        : nodes.map((node, index) => ({
            ...node,
            ...circlePosition(index, nodes.length),
          }));

    const years = papers.map((paper) => paper.year);
    let minYear = Math.min(...years);
    let maxYear = Math.max(...years);
    if (minYear === maxYear) {
      minYear -= 1;
      maxYear += 1;
    }

    return {
      nodes,
      edges,
      positionedNodes,
      yearRange: { min: minYear, max: maxYear },
    };
  }, [papers, viewMode]);

  if (papers.length === 0) return null;

  const selectedPaper = papers.find((paper) => paper.id === selectedNode);

  function selectNode(nodeId: string) {
    setSelectedNode((current) => (current === nodeId ? null : nodeId));
  }

  const yearTicks = (() => {
    if (viewMode !== "timeline") return [];
    const span = graphData.yearRange.max - graphData.yearRange.min;
    const step = span > 36 ? 5 : span > 14 ? 2 : 1;
    const ticks: number[] = [];
    for (
      let year = graphData.yearRange.min;
      year <= graphData.yearRange.max;
      year += step
    ) {
      ticks.push(year);
    }
    if (ticks.at(-1) !== graphData.yearRange.max) {
      ticks.push(graphData.yearRange.max);
    }
    return ticks;
  })();

  return (
    <article className="relation-graph">
      <div className="graph-header">
        <div>
          <span className="section-index">MAP / RELATIONS</span>
          <h3>论文关系坐标</h3>
        </div>
        <div className="graph-controls">
          <div className="view-toggle" role="group" aria-label="关系图模式">
            {(["topic", "citation", "timeline"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                className={viewMode === mode ? "active" : ""}
                aria-pressed={viewMode === mode}
                onClick={() => {
                  setViewMode(mode);
                  setSelectedNode(null);
                }}
              >
                {mode === "topic"
                  ? "主题关联"
                  : mode === "citation"
                    ? "引用关系"
                    : "发表时间"}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div
        className={`graph-container ${
          viewMode === "timeline" ? "graph-container--timeline" : ""
        }`}
      >
        <svg
          viewBox="0 0 800 380"
          className="graph-svg"
          role="img"
          aria-label={
            viewMode === "timeline"
              ? "论文按发表年份排列的时间坐标图"
              : "论文之间的主题或引用关系图"
          }
        >
          <defs>
            <linearGradient id="axis-gradient" x1="0" x2="1">
              <stop offset="0" stopColor="#3157c8" />
              <stop offset="1" stopColor="#008c95" />
            </linearGradient>
            <filter
              id="selected-shadow"
              x="-60%"
              y="-60%"
              width="220%"
              height="220%"
            >
              <feDropShadow
                dx="0"
                dy="4"
                stdDeviation="5"
                floodColor="#10242d"
                floodOpacity="0.22"
              />
            </filter>
          </defs>

          {viewMode === "timeline" ? (
            <>
              <line
                x1="72"
                y1="300"
                x2="728"
                y2="300"
                stroke="url(#axis-gradient)"
                strokeWidth="3"
              />
              {yearTicks.map((year) => {
                const span =
                  graphData.yearRange.max - graphData.yearRange.min || 1;
                const x =
                  72 +
                  ((year - graphData.yearRange.min) / span) * (728 - 72);
                return (
                  <g key={year}>
                    <line
                      x1={x}
                      y1="44"
                      x2={x}
                      y2="306"
                      className="graph-guide"
                    />
                    <text x={x} y="330" className="graph-year">
                      {year}
                    </text>
                  </g>
                );
              })}
            </>
          ) : (
            <>
              <line x1="400" y1="24" x2="400" y2="356" className="graph-axis" />
              <line x1="224" y1="192" x2="576" y2="192" className="graph-axis" />
              <circle cx="400" cy="192" r="74" className="graph-core" />
              <text x="400" y="187" className="graph-core-label">
                SCHOLARPILOT
              </text>
              <text x="400" y="204" className="graph-core-note">
                {viewMode === "topic" ? "SHARED CONCEPTS" : "CITATION LINKS"}
              </text>
            </>
          )}

          {viewMode !== "timeline" &&
            graphData.edges.map((edge, index) => {
              const source = graphData.positionedNodes.find(
                (node) => node.id === edge.source,
              );
              const target = graphData.positionedNodes.find(
                (node) => node.id === edge.target,
              );
              if (!source || !target) return null;

              return (
                <line
                  key={`${edge.source}-${edge.target}-${index}`}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  className="graph-edge"
                  strokeWidth={Math.min(edge.weight, 3)}
                />
              );
            })}

          {graphData.positionedNodes.map((node) => {
            const selected = selectedNode === node.id;
            const color = LEVEL_COLORS[node.level] || LEVEL_COLORS["探索性"];
            const radius = selected ? 22 : 17;

            return (
              <g
                key={node.id}
                className={`graph-node ${selected ? "selected" : ""}`}
                role="button"
                tabIndex={0}
                aria-label={`第 ${node.rank} 名，${node.label}，${Math.round(
                  node.score,
                )} 分`}
                aria-pressed={selected}
                onClick={() => selectNode(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectNode(node.id);
                  }
                }}
              >
                {viewMode === "timeline" && (
                  <line
                    x1={node.x}
                    y1={node.y + radius}
                    x2={node.x}
                    y2="296"
                    className="graph-drop"
                  />
                )}
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={radius + 5}
                  fill="none"
                  stroke={color}
                  strokeWidth="2"
                  opacity={selected ? 0.72 : 0.28}
                  strokeDasharray={`${(node.score / 100) * 138} 138`}
                  transform={`rotate(-90 ${node.x} ${node.y})`}
                />
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={radius}
                  fill={color}
                  filter={selected ? "url(#selected-shadow)" : undefined}
                />
                <text x={node.x} y={node.y + 1} className="graph-rank">
                  {node.rank}
                </text>
                <text
                  x={node.x}
                  y={node.y - radius - 11}
                  className="graph-node-label"
                >
                  {node.label.length > 22
                    ? `${node.label.slice(0, 20)}…`
                    : node.label}
                </text>
              </g>
            );
          })}
        </svg>

        <div className="graph-legend">
          <span>
            <i style={{ background: LEVEL_COLORS["高度相关"] }} /> 高度相关
          </span>
          <span>
            <i style={{ background: LEVEL_COLORS["部分相关"] }} /> 部分相关
          </span>
          <span>
            <i style={{ background: LEVEL_COLORS["探索性"] }} /> 探索性
          </span>
          <span className="legend-note">
            {viewMode === "topic"
              ? "连线表示至少两个共享研究主题"
              : viewMode === "citation"
                ? "连线表示结果集合内可确认的引用关系"
                : "横轴为发表年份，圆内数字为排序名次"}
          </span>
        </div>

        {viewMode !== "timeline" && graphData.edges.length === 0 && (
          <p className="graph-empty-note">
            当前结果集合中没有可确认的
            {viewMode === "topic" ? "强主题关联" : "直接引用边"}；论文节点仍可逐一查看。
          </p>
        )}
      </div>

      {selectedPaper && (
        <div className="graph-detail">
          <strong>RANK {selectedPaper.rank.toString().padStart(2, "0")}</strong>
          <a href={selectedPaper.url} target="_blank" rel="noreferrer">
            {selectedPaper.title}
          </a>
          <span>
            {Math.round(selectedPaper.score)} / 100 · {selectedPaper.level}
          </span>
        </div>
      )}
    </article>
  );
}

function buildTimelineNodes(nodes: GraphNode[]): PositionedNode[] {
  const years = nodes.map((node) => node.year);
  let minYear = Math.min(...years);
  let maxYear = Math.max(...years);
  if (minYear === maxYear) {
    minYear -= 1;
    maxYear += 1;
  }
  const span = maxYear - minYear || 1;
  const stacks = new Map<number, number>();
  const groupSizes = new Map<number, number>();
  for (const node of nodes) {
    groupSizes.set(node.year, (groupSizes.get(node.year) ?? 0) + 1);
  }

  return [...nodes]
    .sort((left, right) => left.year - right.year || left.rank - right.rank)
    .map((node) => {
      const stack = stacks.get(node.year) ?? 0;
      stacks.set(node.year, stack + 1);
      const groupSize = groupSizes.get(node.year) ?? 1;
      const baseX = 72 + ((node.year - minYear) / span) * (728 - 72);
      const spread = groupSize === 1 ? 0 : stack / (groupSize - 1);
      return {
        ...node,
        x: baseX,
        y: groupSize === 1 ? 118 : 58 + spread * 196,
      };
    });
}
