# 研索智航 ScholarPilot

**华为企业赛题三 · 科研场景下复杂学术查询的智能论文搜索与推荐**

> 基于 LLM Agent 的端到端学术论文智能搜索系统，支持查询理解、多源检索、迭代搜索、引文扩展、反事实验证排序与结构化展示。

当前版本：**v0.4（可信评测与预算感知检索）**。本轮新增跨源论文实体融合、
布尔 Query Contract、硬 API 预算、批量 LLM 级联、真实 Token 计量和 benchmark
审计。详细变更与论文方法对应关系见
[`docs/ITERATION_V0.4_2026-07-23.md`](docs/ITERATION_V0.4_2026-07-23.md)。

> 评测说明：内置 35 条数据目前仍含不可复现 ID 和年份冲突，只适合流程回归，
> 不应把 demo F1 当作比赛效果。运行 `python run_evaluation.py --validate-only`
> 可查看完整审计结果。

---

## 🚀 公网访问

**当前公网 URL**: `https://large-views-clean.loca.lt`

> 首次访问需要点击 "Click to Continue" 按钮（localtunnel 的反滥用机制）

---

## 项目简介

本系统面向科研工作者的复杂学术检索需求，构建了一个 **LLM Agent 驱动的智能论文搜索系统**。用户只需用自然语言描述研究问题，系统即可自动完成：

1. **查询理解** — RefChain 多步推理 + 多维约束解析 + 子查询分解
2. **多源检索** — OpenAlex + Semantic Scholar 双源召回 + 自动去重
3. **迭代搜索** — 多轮搜索 + 引文扩展 + LLM 查询精化
4. **智能排序** — 启发式粗排 + LLM 精排 + 反事实验证 + MMR 多样性
5. **结果展示** — 关系图 / 聚类 / 时间线 / 评分分解 / CSV 导出

## 系统架构 (v0.3)

```
                   用户查询 (自然语言)
                          ↓
  ┌─ [QueryAnalyzer]  RefChain 多步推理 (SPAR 2025) ──────┐
  │  Step1: 约束提取 → Step2: 约束层次化                    │
  │  Step3: 多角度子查询 → Step4: 检索式优化                 │
  │  降级: 规则回退 (planner.py)                            │
  └───────────────────────────────────────────────────────┘
                          ↓
  ┌─ [SearchAgent]  双源迭代搜索代理 ──────────────────────┐
  │  OpenAlex + Semantic Scholar 双源并行检索               │
  │  引文扩展 → RelevanceFilter 过滤 → 查询精化              │
  │  预算控制: Max API Calls / Max Papers / 收敛停止        │
  └───────────────────────────────────────────────────────┘
                          ↓
  ┌─ [LLMRanker + CounterfactualVerifier]  混合排序 ───────┐
  │  阶段1: 启发式粗排 (Token重叠 + 权威 + 时效)             │
  │  阶段2: LLM 精排 Top-15 (语义级5维评估)                 │
  │  阶段3: 反事实验证 (约束满足 + 反事实对比)               │
  │  阶段4: MMR 多样性重排                                  │
  └───────────────────────────────────────────────────────┘
                          ↓
  ┌─ [Frontend]  结构化结果展示 ───────────────────────────┐
  │  论文关系图 / 搜索轮次时间线 / 研究主题聚类              │
  │  LLM 分析详情 / 评分分解 + 证据句 / Metrics 面板        │
  │  CSV 导出 / 结果审计                                    │
  └───────────────────────────────────────────────────────┘
```

## 核心创新点

| 创新点 | 实现 | 参考来源 |
|--------|------|---------|
| **RefChain 多步查询推理** | 4步链式推理：约束提取→层次化→子查询生成→检索优化 | SPAR RefChain (Shi et al., 2025) |
| **双源并行检索** | OpenAlex + Semantic Scholar 并行搜索，自动去重合并 | PaSa multi-index (He et al., 2025) |
| **反事实验证排序** | 约束验证 + 反事实对比 + 分数惩罚机制 | Counterfactual reasoning |
| **LLM 查询分析** | 用 LLM 替换规则引擎，识别多维约束并分解子查询 | SPAR (Shi et al., 2025) |
| **迭代搜索策略** | 多轮检索 + 引文扩展 + LLM 查询精化，自适应调整 | PaSa Crawler-Selector (He et al., 2025) |
| **混合排序** | 启发式粗排 + LLM 精排 + MMR 多样性 | Cross-Encoder + DSP (Khattab et al., 2022) |
| **分级成本控制** | LLM 仅用于 Top-15 精排 + 缓存 + 收敛停止 + 反事实仅Top-10 | - |
| **跨学科评测** | 35条查询 × 5学科，分层报告 | - |

## 比赛要求覆盖

| 比赛要求 | 实现方案 | 核心模块 |
|---------|---------|---------|
| 查询理解与分解 | RefChain 4步推理 + 多维约束 + 层次化 must/preferred/exclude | `query_analyzer.py` |
| 子查询分解 | 多角度生成（主题/方法/混合/扩展），每条含 rationale | `QueryAnalyzer._llm_analysis()` |
| 查询改写与扩展 | 中→英学术术语映射 + OpenAlex/S2 优化检索式 | `_generate_optimized_queries()` |
| 自主搜索策略 | 双源并行搜索 → 过滤 → 引文扩展 → 迭代精化 | `search_agent.py` |
| 搜索结果过滤 | LLM + 关键词双重过滤 (PaSa Selector) | `RelevanceFilter` |
| 迭代式检索 | 多轮 + 引文扩展 + LLM 查询精化 | `SearchAgent` |
| 论文综合排序 | 粗排 → LLM 精排 → 反事实验证 → MMR | `llm_ranker.py` + `counterfactual.py` |
| 结构化展示 | 关系图 / 列表 / 时间线 / 聚类 / 评分分解 / CSV导出 | 前端组件 |
| F1 评测 | 宏/微平均 + 5学科分层报告 + CSV导出 | `evaluation.py` |
| 效率监控 | API调用 + Token + 延迟追踪 | `SearchStats` |
| 成本控制 | 分级LLM调用 + 缓存 + 收敛停止 | `SearchStrategyConfig` |
| 双源API | OpenAlex + Semantic Scholar | `providers.py` + `semantic_scholar.py` |
| 多种LLM | DeepSeek/Qwen/OpenAI/本地 (OpenAI兼容) | `llm_client.py` |

## 快速开始

### 1. 前端 (演示模式，无需 API Key)

```bash
cd ScholarPilot_Full_Project_v1
npm install
npx vite
```

访问 http://localhost:5173

### 2. Python 后端 (全功能)

```bash
cd backend

# 配置环境变量 (DeepSeek 示例)
cp .env.example .env
# 编辑 .env: 填入 LLM_API_KEY 和 OPENALEX_API_KEY
# 两类 Key 用途不同：前者调用 DeepSeek，后者检索实时论文。

# 零依赖启动 (演示模式)
python run.py

# 或安装依赖后启动 (推荐)
pip install openai
python run.py
```

### 3. 评测

```bash
cd backend
python run_evaluation.py --mode demo          # 内置数据 (35条查询)
python run_evaluation.py --mode live --verbose # 实时检索
python run_evaluation.py --mode demo --export results.csv
```

评测报告将显示：
- 总体 Macro/Micro F1, Precision, Recall
- 5个学科分层指标（CS / 生物医学 / 化学材料 / 金融经济 / 安全密码学）
- API调用次数、Token估算、平均延迟

### 4. 公网部署

```bash
# 方案1: localtunnel (临时)
npx localtunnel --port 5173

# 方案2: Cloudflare Workers (永久)
npx wrangler login
npm run build
npx wrangler deploy

# 方案3: Cloudflare Pages
npx wrangler pages deploy dist
```

## v0.3 新增/修改的文件清单 (2026-07-23)

### 新文件

| 文件 | 说明 | 参考论文 |
|------|------|---------|
| `backend/scholarpilot/semantic_scholar.py` | Semantic Scholar API 第二数据源（双源检索提升召回率） | PaSa multi-index |
| `backend/scholarpilot/counterfactual.py` | 反事实验证排序引擎（约束验证+反事实对比+分数惩罚） | 创新点三 |
| `app/components/PaperRelationGraph.tsx` | 论文关系图可视化（主题/引用/时间线三种视图） | 比赛要求 |

### 修改文件

| 文件 | 改动 | 参考论文 |
|------|------|---------|
| `backend/scholarpilot/query_analyzer.py` | **RefChain 多步推理**: 4步链式推理提示词, 约束层次化(must/preferred/exclude含rationale), 子查询含多角度metadata, SubQueryInfo数据结构 | SPAR RefChain |
| `backend/scholarpilot/search_agent.py` | **双源检索**: 集成Semantic Scholar, `_execute_search_round`并行调用双源+去重合并, 构造函数新增dual_source参数 | - |
| `backend/scholarpilot/service.py` | **反事实验证集成**: 在排序步骤后新增Step 4.5反事实核验, 导入CounterfactualVerifier | - |
| `backend/scholarpilot/evaluation.py` | **跨学科评测**: 新增discipline字段, DisciplineReport数据类, 5学科分层报告, TestQuery支持discipline | - |
| `backend/scholarpilot/data/evaluation_queries.json` | **35条评测查询**: 覆盖CS(13)/生物医学(7)/化学材料(5)/金融经济(5)/安全密码学(5), 含ground truth标注 | - |
| `app/page.tsx` | **关系图+导出**: 集成PaperRelationGraph, 新增exportResults() CSV导出函数, 导出按钮 | - |
| `app/components/PaperRelationGraph.tsx` | 新增论文关系图组件 | - |
| `app/globals.css` | 新增export-button样式 | - |
| `vite.config.ts` | 新增公网访问allowedHosts (.loca.lt) | - |

## 改动详情与论文方法对应

### 1. RefChain 多步查询推理 (`query_analyzer.py`)

**参考**: SPAR (Shi et al., 2025) — RefChain query decomposition

**改动位置**: `query_analyzer.py` 第 85-242 行

**改动内容**:
- 新增 `REFCHAIN_SYSTEM_PROMPT`: 引导LLM进行4步链式推理
  - Step 1: 约束提取 (Constraints Extraction) — 识别所有维度的约束条件
  - Step 2: 约束层次化 (Constraint Hierarchy) — 区分must_have/preferred/exclude
  - Step 3: 子查询生成 (Sub-query Generation) — 多角度生成含rationale的子查询
  - Step 4: 查询优化 (Query Optimization) — 学术API优化
- 新增 `SubQueryInfo` 数据类: 记录每个子查询的rationale、perspective、priority
- `AnalyzedQuery` 新增字段: `sub_query_details`, `secondary_intents`, `needs_multi_turn`, `search_strategy`, `evolution_notes`
- 新增 `_normalize_constraint_terms()`: 兼容新旧两种约束格式（纯字符串 vs {term, reason}对象）
- 新增 `_normalize_sub_queries()`: 兼容新旧子查询格式
- `_merge_results()` 重写：支持对象数组格式的约束合并、子查询metadata提取
- `_generate_fallback_subqueries()` 增强: 多角度回退生成（主题/方法/混合）
- `_generate_optimized_queries()` 增强: 4种策略生成优化查询

### 2. 双源检索 (`search_agent.py` + `semantic_scholar.py`)

**参考**: PaSa (He et al., 2025) — 多索引检索策略

**改动位置**:
- `semantic_scholar.py`: 全新文件，200+行
- `search_agent.py` 第 260-290, 422-495 行

**改动内容**:
- `SemanticScholarProvider`: 完整的S2 API封装
  - 标题/摘要搜索 + 相关性排序
  - TLDR摘要自动补充
  - 速率限制（有key: 100rps, 无key: 1rps）
  - 内存缓存（TTL 600s）
- `SearchAgent.__init__()`: 新增 `semantic_scholar_provider` 和 `use_dual_source` 参数
- `_execute_search_round()`: 并行调用OpenAlex + Semantic Scholar，DOI/ID/标题三级去重

### 3. 反事实验证排序 (`counterfactual.py`)

**参考**: 创新点三 — 反事实约束核验

**改动位置**: `counterfactual.py` 全新文件，300+行

**改动内容**:
- `CounterfactualVerifier`: 完整的反事实验证引擎
  - Step 1: 约束验证 — 对每篇论文逐条验证must_have约束，提取证据
  - Step 2: 反事实生成 — 替换关键约束（如"query decomposition"→"text summarization"）
  - Step 3: 反事实对比 — 判断约束改变后相关性是否显著下降
  - Step 4: 分数调整 — 对非判别性论文施加惩罚（最多30%），重新定级
- 集成到 `service.py` 搜索流程的 Step 4.5
- 成本控制：仅对Top-10论文执行（每次查询约10-20次LLM调用）

### 4. 跨学科评测 (`evaluation.py` + `evaluation_queries.json`)

**改动位置**:
- `evaluation_queries.json`: 10→35条查询
- `evaluation.py`: 新增 `DisciplineReport`, `TestQuery.discipline`

**改动内容**:
- 35条查询覆盖5个学科：CS(13)、生物医学(7)、化学材料(5)、金融经济(5)、安全密码学(5)
- 评测报告自动按学科分层统计
- 每条查询含ground truth相关论文ID和标题

### 5. 前端增强 (`page.tsx` + `PaperRelationGraph.tsx`)

**改动位置**:
- `PaperRelationGraph.tsx`: 全新文件
- `page.tsx`: 新增 `exportResults()` 函数、关系图集成、导出按钮

**改动内容**:
- **论文关系图**: SVG圆形布局，三种视图模式
  - 主题关联：共享概念≥2的论文连线
  - 引用关系：基于参考文献的引文网络
  - 时间线：相邻年份论文连线
- **CSV导出**: 一键导出所有结果（排名/标题/作者/年份/发表源/引用数/评分/级别/证据/DOI/URL）
- 点击节点查看论文详情

## 参考论文

- **[PaSa]** He et al., "PaSa: An LLM Agent for Comprehensive Academic Paper Search", ACL 2025
- **[SPAR]** Shi et al., "SPAR: Scholar Paper Retrieval with LLM-based Agents", arXiv 2025
- **[DSP]** Khattab et al., "Demonstrate-Search-Predict", arXiv 2022
- **[GritLM]** Muennighoff et al., "GritLM: Generalist Representational Instruction Tuning", ICML 2024
- **[LitSearch]** Ajith et al., "LitSearch: A Retrieval Benchmark for Scientific Literature Search", EMNLP 2024
- **[AstaBench]** Feldman et al., "AstaBench: Rigorous Benchmarking of AI Agents", arXiv 2025

## 目录结构

```
ScholarPilot_Full_Project_v1/
├── app/                              TypeScript 前端
│   ├── api/search/route.ts           API路由 (支持Python后端代理)
│   ├── api/health/route.ts           健康检查
│   ├── components/
│   │   ├── LLMAnalysisPanel.tsx       LLM查询分析面板
│   │   ├── PaperRelationGraph.tsx     论文关系图 ★新增
│   │   ├── SearchRoundsTimeline.tsx   搜索轮次时间线
│   │   └── TopicClusters.tsx          研究主题聚类
│   ├── lib/
│   │   ├── search.ts                 前端搜索引擎
│   │   ├── types.ts                  类型定义
│   │   └── demo-data.ts              Demo数据
│   ├── page.tsx                      主页面
│   └── globals.css                   全局样式
├── backend/                          独立 Python 后端
│   ├── scholarpilot/
│   │   ├── config.py                 配置管理
│   │   ├── counterfactual.py         反事实验证 ★新增
│   │   ├── evaluation.py             评测管线 (跨学科) ★修改
│   │   ├── fastapi_app.py            FastAPI入口
│   │   ├── llm_client.py             LLM客户端
│   │   ├── llm_ranker.py             LLM精排引擎
│   │   ├── models.py                 数据模型
│   │   ├── planner.py                规则查询规划器
│   │   ├── providers.py              OpenAlex Provider
│   │   ├── query_analyzer.py         RefChain查询分析 ★重写
│   │   ├── ranking.py                启发式排序
│   │   ├── search_agent.py           迭代搜索代理 (双源) ★修改
│   │   ├── semantic_scholar.py       S2 API Provider ★新增
│   │   ├── server.py                 HTTP服务
│   │   ├── service.py                搜索服务编排 ★修改
│   │   └── data/
│   │       ├── demo_papers.json      Demo数据
│   │       └── evaluation_queries.json 35条评测查询 ★扩展
│   ├── tests/
│   └── run_evaluation.py             评测CLI
├── docs/                             项目文档
├── vite.config.ts                    Vite配置
└── README.md                         项目文档 ★更新
```
