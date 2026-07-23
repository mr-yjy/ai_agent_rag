import type { Paper } from "./types";

export const DEMO_PAPERS: Paper[] = [
  {
    id: "pasa-2025",
    title: "PaSa: An LLM Agent for Comprehensive Academic Paper Search",
    abstract:
      "PaSa is a paper search agent that autonomously invokes search tools, reads papers, explores citation links, and selects references for complex scholarly queries. The system separates crawling from paper selection and is optimized with reinforcement learning on synthetic academic queries.",
    year: 2025,
    authors: [
      "Yichen He",
      "Guanhua Huang",
      "Peiyuan Feng",
      "Yuan Lin",
    ],
    venue: "ACL",
    citedByCount: 56,
    url: "https://aclanthology.org/2025.acl-long.572/",
    openAccess: true,
    referencedWorks: ["litsearch-2024", "dsp-2022", "gritlm-2024"],
    concepts: [
      "academic paper search",
      "LLM agent",
      "citation expansion",
      "reinforcement learning",
    ],
  },
  {
    id: "litsearch-2024",
    title:
      "LitSearch: A Retrieval Benchmark for Scientific Literature Search",
    abstract:
      "LitSearch introduces a benchmark for retrieving scientific literature from complex natural-language information needs. It evaluates whether systems can balance precision and recall when relevant papers are not recoverable from a single keyword query.",
    year: 2024,
    authors: ["Anirudh Ajith", "Mengzhou Xia", "Alexis Chevalier"],
    venue: "EMNLP",
    citedByCount: 41,
    url: "https://arxiv.org/abs/2407.18940",
    openAccess: true,
    referencedWorks: ["dsp-2022"],
    concepts: [
      "scientific literature search",
      "retrieval benchmark",
      "precision",
      "recall",
    ],
  },
  {
    id: "asta-2025",
    title:
      "AstaBench: Rigorous Benchmarking of AI Agents with a Scientific Research Suite",
    abstract:
      "AstaBench evaluates agents on a broad suite of scientific research tasks, including literature search, code execution, data analysis, and end-to-end discovery. The framework emphasizes controlled, reproducible evaluation and computational efficiency.",
    year: 2025,
    authors: ["Jonathan Bragg", "Allen Institute for AI"],
    venue: "arXiv",
    citedByCount: 24,
    url: "https://arxiv.org/abs/2510.21652",
    openAccess: true,
    referencedWorks: ["litsearch-2024"],
    concepts: [
      "scientific agent",
      "benchmark",
      "evaluation",
      "efficiency",
    ],
  },
  {
    id: "spar-2025",
    title:
      "SPAR: Scholar Paper Retrieval with LLM-based Agents for Enhanced Academic Search",
    abstract:
      "SPAR decomposes a complex scholarly request into a reference chain and evolves search queries over multiple retrieval rounds. Multiple agents coordinate query generation, evidence inspection, and paper selection.",
    year: 2025,
    authors: ["Xiaoming Shi", "Yiming Li", "Qian Kou"],
    venue: "arXiv",
    citedByCount: 12,
    url: "https://arxiv.org/abs/2507.15245",
    openAccess: true,
    referencedWorks: ["pasa-2025", "litsearch-2024"],
    concepts: [
      "query decomposition",
      "query evolution",
      "multi-agent",
      "academic search",
    ],
  },
  {
    id: "dsp-2022",
    title:
      "Demonstrate-Search-Predict: Composing Retrieval and Language Models for Knowledge-Intensive NLP",
    abstract:
      "The demonstrate-search-predict framework composes language models with retrieval through modular prompting. It generates search queries, retrieves evidence, and predicts answers without requiring a single monolithic model.",
    year: 2022,
    authors: ["Omar Khattab", "Keshav Santhanam", "Xiang Lisa Li"],
    venue: "arXiv",
    citedByCount: 398,
    url: "https://arxiv.org/abs/2212.14024",
    openAccess: true,
    referencedWorks: [],
    concepts: ["retrieval", "query generation", "language model", "RAG"],
  },
  {
    id: "gritlm-2024",
    title: "GritLM: Generalist Representational Instruction Tuning",
    abstract:
      "GritLM unifies text representation and generation in one language model. The work studies instruction tuning for embeddings, retrieval, reranking, and generative tasks, enabling shared representations across retrieval pipelines.",
    year: 2024,
    authors: ["Niklas Muennighoff", "Hongjin Su", "Liang Wang"],
    venue: "ICML",
    citedByCount: 184,
    url: "https://arxiv.org/abs/2402.09906",
    openAccess: true,
    referencedWorks: ["dsp-2022"],
    concepts: ["embedding", "reranking", "instruction tuning", "retrieval"],
  },
  {
    id: "agile-2024",
    title: "AGILE: A Novel Framework of LLM Agents",
    abstract:
      "AGILE studies how language-model agents can plan tool use, refine intermediate decisions, and solve tasks through iterative interaction. Its design provides reusable ideas for search planning and reflective agent loops.",
    year: 2024,
    authors: ["Peiyuan Feng", "Yichen He", "Guanhua Huang"],
    venue: "NeurIPS",
    citedByCount: 29,
    url: "https://arxiv.org/search/?query=AGILE+LLM+Agents&searchtype=all",
    openAccess: true,
    referencedWorks: [],
    concepts: ["LLM agent", "planning", "tool use", "reflection"],
  },
  {
    id: "compositional-gap-2022",
    title: "Measuring and Narrowing the Compositionality Gap in Language Models",
    abstract:
      "This work analyzes failures on compositional questions and introduces a self-ask strategy that decomposes a complex request into follow-up questions. The approach highlights when iterative search and decomposition improve grounded reasoning.",
    year: 2022,
    authors: ["Ofir Press", "Muru Zhang", "Sewon Min"],
    venue: "Findings of EMNLP",
    citedByCount: 721,
    url: "https://arxiv.org/abs/2210.03350",
    openAccess: true,
    referencedWorks: [],
    concepts: ["query decomposition", "self-ask", "reasoning", "search"],
  },
  {
    id: "paperqa-2024",
    title:
      "Language Agents for Answering Questions from Scientific Literature",
    abstract:
      "The system retrieves scientific papers, gathers passages, and constructs answers with traceable citations. It examines agentic literature review workflows and how evidence quality affects scientific question answering.",
    year: 2024,
    authors: ["Michael Skarlinski", "Sam Cox", "Artur Kibbe"],
    venue: "NeurIPS",
    citedByCount: 77,
    url: "https://arxiv.org/search/?query=Language+Agents+for+Answering+Questions+from+Scientific+Literature&searchtype=title",
    openAccess: true,
    referencedWorks: ["dsp-2022"],
    concepts: [
      "scientific question answering",
      "evidence",
      "citation",
      "RAG",
    ],
  },
  {
    id: "domain-rag-2025",
    title:
      "Domain-aligned LLM Framework for Trustworthy Scientific QA via Query Reformulation RAG",
    abstract:
      "A domain-aligned retrieval-augmented generation framework uses query reformulation and evidence filtering to improve trustworthy scientific question answering. The workflow emphasizes domain constraints and grounded output.",
    year: 2025,
    authors: ["D. Lee", "S. Sohn", "B. Lee"],
    venue: "ChemRxiv",
    citedByCount: 7,
    url: "https://chemrxiv.org/",
    openAccess: true,
    referencedWorks: ["dsp-2022", "gritlm-2024"],
    concepts: [
      "query reformulation",
      "RAG",
      "scientific QA",
      "trustworthiness",
    ],
  },
];

