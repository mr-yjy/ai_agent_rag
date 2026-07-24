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
          background:
            radial-gradient(circle at 100% 0%, rgba(18, 165, 148, 0.09), transparent 14rem),
            var(--surface);
          border: 1px solid #dfe5f0;
          border-radius: 22px 22px 22px 8px;
          padding: 23px;
          margin-bottom: 4px;
          box-shadow: var(--shadow-soft);
        }
        .clusters-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;
        }
        .clusters-header h3 {
          margin: 0;
          font-size: 17px;
          font-weight: 700;
        }
        .clusters-badge {
          border: 1px solid rgba(18, 165, 148, 0.16);
          background: #e2f7f2;
          color: #087665;
          font-size: 11px;
          font-weight: 700;
          padding: 5px 10px;
          border-radius: 999px;
          margin-left: auto;
        }
        .clusters-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 9px;
        }
        .cluster-card {
          min-width: 0;
          border: 1px solid #e5e9f1;
          border-radius: 13px;
          padding: 11px;
          display: flex;
          align-items: center;
          gap: 11px;
          background: rgba(250, 251, 254, 0.88);
        }
        .cluster-bar {
          width: 54px;
          height: 7px;
          flex: 0 0 54px;
          background: #e7ebf2;
          border-radius: 999px;
          overflow: hidden;
        }
        .cluster-fill {
          height: 100%;
          background: linear-gradient(90deg, var(--accent), var(--accent-secondary));
          border-radius: 999px;
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
          overflow: hidden;
          color: var(--ink);
          font-size: 13px;
          font-weight: 650;
          text-overflow: ellipsis;
          white-space: nowrap;
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
        @media (max-width: 760px) {
          .topic-clusters {
            padding: 19px 16px;
          }
          .clusters-header {
            align-items: flex-start;
            flex-wrap: wrap;
          }
          .clusters-badge {
            margin-left: 0;
          }
          .clusters-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </article>
  );
}
