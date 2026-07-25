import type { RankedPaper } from "./types";

export type PaperExportKind = "bibtex" | "ris";

export interface SearchHistoryEntry {
  id: string;
  query: string;
  searchedAt: string;
  resultCount: number;
  requestId: string;
  status: string;
}

export interface TopicOption {
  label: string;
  count: number;
}

function compactWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function citationAuthors(paper: RankedPaper): string {
  if (paper.authors.length === 0) return "作者信息暂缺";
  if (paper.authors.length <= 3) return paper.authors.join(", ");
  return `${paper.authors.slice(0, 3).join(", ")} 等`;
}

function citationKey(paper: RankedPaper): string {
  const leadAuthor = paper.authors[0]?.split(/\s+/).at(-1) || "paper";
  const titleWord =
    paper.title
      .replace(/[^\p{L}\p{N}\s]/gu, "")
      .split(/\s+/)
      .find(Boolean) || "study";
  return `${leadAuthor}${paper.year}${titleWord}`
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}]/gu, "");
}

function escapeBibtex(value: string): string {
  return value
    .replace(/\\/g, "\\textbackslash{}")
    .replace(/([{}%&_#$])/g, "\\$1");
}

export function formatCitation(paper: RankedPaper): string {
  const doi = paper.doi ? ` https://doi.org/${paper.doi}` : "";
  return compactWhitespace(
    `${citationAuthors(paper)}. (${paper.year}). ${paper.title}. ${
      paper.venue || "发表源暂缺"
    }.${doi}`,
  );
}

export function formatBibtex(paper: RankedPaper): string {
  const fields = [
    `  title = {${escapeBibtex(paper.title)}}`,
    `  author = {${escapeBibtex(paper.authors.join(" and "))}}`,
    `  year = {${paper.year}}`,
    `  journal = {${escapeBibtex(paper.venue || "")}}`,
    paper.doi ? `  doi = {${escapeBibtex(paper.doi)}}` : "",
    paper.url ? `  url = {${escapeBibtex(paper.url)}}` : "",
  ].filter(Boolean);

  return `@article{${citationKey(paper)},\n${fields.join(",\n")}\n}`;
}

export function formatRis(paper: RankedPaper): string {
  const authors = paper.authors.map((author) => `AU  - ${author}`);
  return [
    "TY  - JOUR",
    `TI  - ${paper.title}`,
    ...authors,
    `PY  - ${paper.year}`,
    `JO  - ${paper.venue || ""}`,
    paper.doi ? `DO  - ${paper.doi}` : "",
    paper.url ? `UR  - ${paper.url}` : "",
    "ER  -",
  ]
    .filter(Boolean)
    .join("\n");
}

export function downloadText(
  filename: string,
  content: string,
  mime = "text/plain;charset=utf-8",
): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function copyText(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
    return;
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }
}

export function getTopicOptions(papers: RankedPaper[]): TopicOption[] {
  const topics = new Map<string, { label: string; count: number }>();

  papers.forEach((paper) => {
    paper.concepts.forEach((concept) => {
      const label = compactWhitespace(concept);
      if (!label) return;
      const key = label.toLocaleLowerCase();
      const current = topics.get(key);
      topics.set(key, {
        label: current?.label ?? label,
        count: (current?.count ?? 0) + 1,
      });
    });
  });

  return Array.from(topics.values())
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label))
    .slice(0, 10);
}

export function removeYearConstraint(query: string): string {
  const cleaned = query
    .replace(
      /(?:19|20)\d{2}\s*(?:年)?\s*[—–\-至到]\s*(?:19|20)\d{2}\s*年?/g,
      "",
    )
    .replace(/(?:19|20)\d{2}\s*年(?:以后|之后|以来|前|后)?/g, "")
    .replace(/\s{2,}/g, " ")
    .replace(/^[，、；：\s]+|[，、；：\s]+$/g, "")
    .trim();

  return cleaned || query;
}

export function safeFilename(paper: RankedPaper, extension: string): string {
  const base = paper.title
    .normalize("NFKC")
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, "")
    .replace(/\s+/g, "-")
    .slice(0, 72);
  return `${base || "scholarpilot-paper"}.${extension}`;
}
