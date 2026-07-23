"use client";

import { useMemo } from "react";
import type { RankedPaper } from "../lib/types";

interface Props {
  papers: RankedPaper[];
}

interface Cluster {
  topic: string;
  papers: RankedPaper[];
  avgScore: number;
}

export default function TopicClusters({ papers }: Props) {
  const clusters = useMemo(() => {
    if (!papers || papers.length === 0) return [];

    // Collect all concepts and assign papers to them
    const topicMap = new Map<string, RankedPaper[]>();
    for (const paper of papers) {
      const topics = paper.concepts.length > 0
        ? paper.concepts.slice(0, 3)
        : ["General"];
      for (const topic of topics) {
        if (!topicMap.has(topic)) topicMap.set(topic, []);
        topicMap.get(topic)!.push(paper);
      }
    }

    // Convert to clusters, sorted by size
    const clusters: Cluster[] = [];
    for (const [topic, topicPapers] of topicMap) {
      if (topicPapers.length < 1) continue;
      clusters.push({
        topic,
        papers: topicPapers,
        avgScore:
          topicPapers.reduce((sum, p) => sum + p.score, 0) /
          topicPapers.length,
      });
    }

    return clusters.sort((a, b) => b.papers.length - a.papers.length).slice(0, 8);
  }, [papers]);

  if (clusters.length === 0) return null;

  const maxCount = Math.max(...clusters.map((c) => c.papers.length), 1);

  return (
    <article className="topic-clusters">
      <div className="clusters-header">
        <span className="section-index">CLUSTER</span>
        <h3>研究主题聚类</h3>
        <span className="clusters-badge">{clusters.length} 个主题</span>
      </div>

      <div className="clusters-grid">
        {clusters.map((cluster) => (
          <div key={cluster.topic} className="cluster-card">
            <div className="cluster-bar">
              <div
                className="cluster-fill"
                style={{
                  width: `${(cluster.papers.length / maxCount) * 100}%`,
                }}
              />
            </div>
            <div className="cluster-info">
              <span className="cluster-topic">{cluster.topic}</span>
              <div className="cluster-meta">
                <span className="cluster-count">
                  {cluster.papers.length} 篇
                </span>
                <span className="cluster-score">
                  {cluster.avgScore.toFixed(0)}分
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <style>{`
        .topic-clusters {
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: 12px;
          padding: 20px;
          margin-bottom: 24px;
        }
        .clusters-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;
        }
        .clusters-header h3 {
          margin: 0;
          font-size: 16px;
        }
        .clusters-badge {
          background: var(--accent);
          color: #fff;
          font-size: 11px;
          font-weight: 600;
          padding: 2px 10px;
          border-radius: 20px;
          margin-left: auto;
        }
        .clusters-grid {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .cluster-card {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .cluster-bar {
          flex: 1;
          height: 32px;
          background: var(--bg);
          border-radius: 8px;
          overflow: hidden;
          max-width: 200px;
        }
        .cluster-fill {
          height: 100%;
          background: linear-gradient(90deg, var(--accent), var(--accent-secondary, var(--accent)));
          border-radius: 8px;
          opacity: 0.7;
          transition: width 0.3s ease;
          min-width: 4px;
        }
        .cluster-info {
          flex: 1;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .cluster-topic {
          font-size: 13px;
          font-weight: 500;
        }
        .cluster-meta {
          display: flex;
          gap: 12px;
          font-size: 12px;
          color: var(--text-secondary);
        }
        .cluster-count {
          min-width: 40px;
        }
        .cluster-score {
          min-width: 36px;
          text-align: right;
        }
      `}</style>
    </article>
  );
}
