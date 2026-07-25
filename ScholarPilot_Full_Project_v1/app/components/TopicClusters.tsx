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

    const topicMap = new Map<string, RankedPaper[]>();
    for (const paper of papers) {
      const topics =
        paper.concepts.length > 0 ? paper.concepts.slice(0, 3) : ["General"];
      for (const topic of topics) {
        if (!topicMap.has(topic)) topicMap.set(topic, []);
        topicMap.get(topic)!.push(paper);
      }
    }

    const grouped: Cluster[] = [];
    for (const [topic, topicPapers] of topicMap) {
      grouped.push({
        topic,
        papers: topicPapers,
        avgScore:
          topicPapers.reduce((sum, paper) => sum + paper.score, 0) /
          topicPapers.length,
      });
    }

    return grouped
      .sort((left, right) => right.papers.length - left.papers.length)
      .slice(0, 8);
  }, [papers]);

  if (clusters.length === 0) return null;

  const maxCount = Math.max(
    ...clusters.map((cluster) => cluster.papers.length),
    1,
  );

  return (
    <article className="topic-clusters">
      <div className="clusters-header">
        <div>
          <span className="section-index">TOPIC / CLUSTERS</span>
          <h3>结果主题分布</h3>
        </div>
        <span className="clusters-badge">{clusters.length} TOPICS</span>
      </div>

      <div className="clusters-grid">
        {clusters.map((cluster, index) => (
          <div key={cluster.topic} className="cluster-card">
            <span className="cluster-index">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div className="cluster-info">
              <span className="cluster-topic">{cluster.topic}</span>
              <div className="cluster-bar" aria-hidden="true">
                <i
                  style={{
                    width: `${(cluster.papers.length / maxCount) * 100}%`,
                  }}
                />
              </div>
            </div>
            <div className="cluster-meta">
              <span>{cluster.papers.length} 篇</span>
              <span>{cluster.avgScore.toFixed(0)} 分</span>
            </div>
          </div>
        ))}
      </div>
    </article>
  );
}
