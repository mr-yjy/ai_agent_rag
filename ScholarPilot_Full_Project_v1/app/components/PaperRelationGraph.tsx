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

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export default function PaperRelationGraph({ papers }: Props) {
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"citation" | "topic" | "timeline">(
    "topic",
  );

  const graphData = useMemo(() => {
    if (!papers || papers.length === 0) return { nodes: [], edges: [] };

    const nodes: GraphNode[] = papers.map((paper, idx) => ({
      id: paper.id,
      label:
        paper.title.length > 40
          ? paper.title.slice(0, 38) + "..."
          : paper.title,
      score: paper.score,
      level: paper.level,
      year: paper.year,
      cluster: idx % 3, // Simple clustering for visualization
    }));

    const edges: GraphEdge[] = [];

    if (viewMode === "topic") {
      // Topic-based edges: papers sharing similar concepts
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
      // Citation-based edges: papers citing each other
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
    } else {
      // Timeline: connect papers by year proximity
      const sorted = [...papers].sort((a, b) => a.year - b.year);
      for (let i = 0; i < sorted.length - 1; i++) {
        if (Math.abs(sorted[i].year - sorted[i + 1].year) <= 1) {
          edges.push({
            source: sorted[i].id,
            target: sorted[i + 1].id,
            weight: 1,
          });
        }
      }
    }

    return { nodes, edges };
  }, [papers, viewMode]);

  if (papers.length === 0) return null;

  const selectedPaper = papers.find((p) => p.id === selectedNode);

  const levelColors: Record<string, string> = {
    "高度相关": "#059669",
    "部分相关": "#d97706",
    "探索性": "#6b7280",
  };

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
                onClick={() => setViewMode(mode)}
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

      <div className="graph-container">
        {/* SVG-based graph visualization */}
        <svg
          viewBox="0 0 800 400"
          className="graph-svg"
          aria-label="论文关系图"
        >
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

            // Circular layout
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
                {/* Score ring */}
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
            <span className="legend-note">连线=相邻年份</span>
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
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: 12px;
          padding: 20px;
          margin-bottom: 24px;
        }
        .graph-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;
          flex-wrap: wrap;
        }
        .graph-header h3 {
          margin: 0;
          font-size: 16px;
        }
        .graph-controls {
          margin-left: auto;
        }
        .view-toggle {
          display: flex;
          gap: 2px;
          background: var(--bg);
          border-radius: 8px;
          padding: 2px;
        }
        .view-toggle button {
          padding: 4px 12px;
          border: none;
          background: none;
          font-size: 12px;
          cursor: pointer;
          border-radius: 6px;
          color: var(--text-secondary);
          font-weight: 500;
        }
        .view-toggle button.active {
          background: var(--accent);
          color: #fff;
        }
        .graph-container {
          position: relative;
        }
        .graph-svg {
          width: 100%;
          height: auto;
          max-height: 420px;
        }
        .graph-legend {
          display: flex;
          gap: 16px;
          margin-top: 12px;
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
          margin-top: 12px;
          padding: 10px 14px;
          background: var(--bg);
          border-radius: 8px;
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
      `}</style>
    </article>
  );
}
