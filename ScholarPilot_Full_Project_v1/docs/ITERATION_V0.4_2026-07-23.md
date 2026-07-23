# ScholarPilot v0.4 第一轮可信检索改造记录

日期：2026-07-23

## 1. 本轮目标与结论

本轮没有继续堆叠界面功能，而是先修复会直接影响 F1、效率统计和实验可信度的
基础问题：

1. 同一篇论文在 OpenAlex、Semantic Scholar、DOI、arXiv 中的 ID 不同，旧代码
   会重复计数；
2. 评测集把同一论文的本地 ID 和 arXiv ID 当作两篇论文，Recall 分母错误；
3. `MAX_API_CALLS_PER_ROUND` 只是配置项，旧搜索链路没有执行预算；
4. 旧 LLM Selector 对每篇候选分别调用一次，最坏成本很高；
5. “A 或 B”被当作 A、B 都必须满足；明确年份只获得少量加分，并非硬约束；
6. 搜索轮次已经在后端记录，但没有返回给前端；
7. Semantic Scholar 发生 HTTP 429 后仍会继续尝试其他子查询。

本轮完成后：

- 后端单元测试从 5 项增加到 12 项，全部通过；
- Python 全量编译通过；
- 无 LLM 的实时冒烟查询成功返回 5 篇论文；
- 35 条 demo 的宏平均 F1 从 0.0826 变为 0.1061，但该变化主要是评测口径修复，
  **不能作为算法涨点对外宣传**；
- 开发集审计结果为 0 error、58 warning、8 info，证明现有 35 条数据只能用于流程
  回归，尚不能作为比赛验证集。

## 2. 论文方法如何使用

用户本轮消息中没有可读取的单独论文附件，因此以下方法来自赛题正文列出的 PaSa、
SPAR 等参考工作。收到具体论文 PDF 后，还需要继续做逐节对照。

### 2.1 PaSa：Crawler + Selector

参考思想：Crawler 扩大候选覆盖，Selector 在候选进入排序前过滤噪声。

本轮落点：

- `backend/scholarpilot/search_agent.py`
  - `SearchAgent._execute_search_round()`：OpenAlex 与 Semantic Scholar 独立检索，
    并发执行后统一合并；
  - `RelevanceFilter`：从逐篇 LLM 判断改成“低成本词法粗筛 + 批量 LLM
    Selector”；
  - `CitationExpander`：只从满足分数阈值且确实含参考文献的种子论文做一次批量
    后向引文扩展；
  - 所有检索路线受每轮和总 API 预算限制。

与论文方法的差异：

- 当前没有使用 PaSa 的强化学习 Crawler/Selector；
- Selector 仍是启发式 + LLM-as-judge，而非训练后的专用模型；
- 当前只实现后向参考文献扩展，没有实现被引论文的前向扩展。

### 2.2 SPAR：RefChain 查询分解与查询演化

参考思想：先明确约束，再生成互补子查询，并根据已找到的论文做查漏补缺。

本轮落点：

- `backend/scholarpilot/planner.py`
  - 新增相对年份解析：`after 2024`、`since 2022`、`2024 年以后`、`近 3 年`；
  - 新增布尔约束组：组内 OR、组间 AND；
  - 新增面向学术 API 的同义词扩展，例如：
    `academic paper search → scientific literature search / paper retrieval /
    paper finding`；
- `backend/scholarpilot/query_analyzer.py`
  - `AnalyzedQuery.constraint_groups` 保存规则基线中的布尔 Query Contract；
- `backend/scholarpilot/search_agent.py`
  - 初始多路查询后，LLM 可根据当前结果生成 gap-driven refinement query；
  - 新增 `marginal_yield_below_threshold` 和 `api_budget_exhausted` 停止原因。

与论文方法的差异：

- 目前没有训练 RefChain；
- 没有把每条演化路径的预期收益做成可学习策略；
- LLM 不可用时依靠确定性术语映射和模板扩展。

### 2.3 多索引/多源召回

参考思想：不同学术索引的覆盖范围不同，多源召回提高 Recall，再做统一实体融合。

本轮落点：

- 新增 `backend/scholarpilot/identity.py`；
- DOI 统一为小写裸 DOI，例如
  `https://doi.org/10.1234/ABC → 10.1234/abc`；
- arXiv ID 去除版本号；
- 无共同 ID 时使用保守的规范化标题匹配；
- 重复记录不是简单丢弃，而是融合更长摘要、作者、概念、参考文献、开放获取状态、
  引用数以及 `sources`、`retrieval_routes`。

这一步对应多索引方案中容易被忽略的 Candidate Store。没有统一实体层，多源检索会
虚增候选数、降低 Precision，并让评测结果失真。

### 2.4 级联精排与成本控制

参考思想：先便宜后昂贵，只把小规模候选交给 LLM。

本轮落点：

- `RelevanceFilter`：
  - 先对规范化后的中英文术语做词法粗筛；
  - 最多判断 32 篇；
  - 每批默认 8 篇；
- `LLMRanker`：
  - 只精排粗排 Top-12；
  - 每批最多 8 篇，不再逐篇调用；
- `CounterfactualVerifier`：
  - 不再处理固定 Top-10；
  - 只处理距离 62/42 分类阈值不超过 8 分的边界候选；
  - 最多 4 篇，每篇最多两次调用；
  - 降权后重新排序并重写 rank。

按上限估算，旧链路可能出现约 100 次 Selector + 15 次精排 + 20 次反事实调用。
新链路对应上限约为 4 批 Selector + 2 批精排 + 8 次边界核验，再加查询分析与
查询演化。此处是静态上限比较，仍需在真实 LLM 配置下记录实测 Token 和调用数。

## 3. 代码级变更

### 3.1 统一论文实体

文件：`backend/scholarpilot/identity.py`

关键函数：

- `normalize_doi()`：统一 DOI；
- `normalize_arxiv_id()`：统一 arXiv ID；
- `normalize_title()`：NFKC、大小写、标点和空白规范化；
- `canonical_paper_key()`：DOI > arXiv > 标题；
- `merge_papers()`：融合多源元数据；
- `upsert_paper()`：插入或合并候选。

调用位置：

- `providers.py`；
- `semantic_scholar.py`；
- `search_agent.py`；
- `evaluation.py`。

### 3.2 Query Contract

文件：`backend/scholarpilot/models.py`

`QueryPlan` 新增：

```json
{
  "constraintGroups": [
    ["query decomposition", "citation expansion"],
    ["LLM agent"]
  ],
  "methods": [],
  "datasets": [],
  "domains": [],
  "venues": []
}
```

语义是组内任一满足、所有组都满足。`ranking.py::_constraint_coverage()` 使用这一
结构打分。已知年份超出明确时间范围的论文会被硬过滤；年份未知的记录仍保留，避免
误伤 Recall。

### 3.3 预算控制与搜索轨迹

文件：`backend/scholarpilot/config.py`

新增环境变量：

| 环境变量 | 默认值 | 含义 |
| --- | ---: | --- |
| `MAX_TOTAL_API_CALLS` | 12 | 单查询学术 API 总预算 |
| `SELECTOR_BATCH_SIZE` | 8 | Selector 每批论文数 |
| `SELECTOR_MAX_PAPERS` | 32 | Selector 最多处理论文数 |
| `LLM_RERANK_TOP_K` | 12 | LLM 精排候选上限 |
| `COUNTERFACTUAL_MAX_PAPERS` | 4 | 反事实核验论文上限 |
| `COUNTERFACTUAL_BOUNDARY_MARGIN` | 8 | 分类阈值附近的核验窗口 |
| `MIN_NEW_PAPERS_TO_CONTINUE` | 2 | 继续迭代的最小新增候选数 |

`SearchService` 现在返回：

```json
{
  "stats": {
    "apiCalls": 4,
    "llmCalls": 0,
    "candidateCount": 50,
    "deduplicatedCount": 18,
    "tokenEstimate": 0,
    "searchRounds": [
      {
        "roundNumber": 1,
        "strategy": "initial",
        "queriesUsed": [],
        "papersFound": 50,
        "papersAdded": 18,
        "apiCalls": 4,
        "elapsedMs": 1200
      }
    ]
  }
}
```

`candidateCount` 是各数据源内部去重后返回的候选总和（跨源融合前），
`deduplicatedCount` 是统一实体后的候选数，不再把二者写成同一个值。

### 3.4 LLM 调用计量

文件：`backend/scholarpilot/llm_client.py`

- SDK 已安装时，API 失败不再自动换 urllib 重发同一个请求，避免重复扣费；
- 记录调用数、失败数、实际或估算 Token、累计延迟；
- `SearchService` 对请求前后快照做差，返回该次搜索的真实统计；
- demo/无 LLM 时 Token 为 0，而不是根据论文数量伪造 Token。

### 3.5 Semantic Scholar 限流

文件：`backend/scholarpilot/semantic_scholar.py`

- HTTP 429 后打开 60 秒熔断；
- 同一轮不再继续请求剩余子查询；
- 失败调用也计入 API 成本；
- OpenAlex 仍可独立返回结果，S2 失败不导致整条搜索降级到 demo。

## 4. 评测口径修复

旧数据：

```json
{
  "relevant_paper_ids": [
    "pasa-2025",
    "arxiv:2501.10120"
  ],
  "relevant_titles": [
    "PaSa: An LLM Agent for Comprehensive Academic Paper Search"
  ]
}
```

两种 ID 指向同一篇论文，旧评测却把 Recall 分母记为 2。

新推荐格式：

```json
{
  "relevant_papers": [
    {
      "ids": [
        "pasa-2025",
        "arxiv:2501.10120",
        "doi:10.18653/v1/2025.acl-long.572"
      ],
      "titles": [
        "PaSa: An LLM Agent for Comprehensive Academic Paper Search"
      ]
    }
  ]
}
```

`evaluation.py` 兼容旧格式。当 ID 数量恰好是标题数量的两倍时，按并行别名折叠；
新格式应由人工标注直接给出，不依赖推断。

新增命令：

```powershell
cd backend
python run_evaluation.py --validate-only
```

当前结果：

- 0 errors；
- 58 warnings；
- 8 info；
- q003、q011、q021、q031 等存在查询年份与标注年份冲突；
- q008 之后大部分 ID 是无法在 OpenAlex/S2 中复现的占位 ID。

因此当前 demo 指标只能证明代码路径可运行，不能证明检索算法在比赛数据上有效。

## 5. 验证结果

执行：

```powershell
cd backend
python -m compileall -q scholarpilot tests
python -m unittest discover -s tests -v
python run_evaluation.py --mode demo
python run_evaluation.py --validate-only
npx tsc --noEmit
npx eslint . --ignore-pattern dist --ignore-pattern .next
npx vite build
node --test tests/rendered-html.test.mjs
```

结果：

- compileall：通过；
- 单元测试：12/12 通过；
- demo 宏 F1：0.1061；
- demo micro F1：0.1068；
- benchmark audit：0 error / 58 warning / 8 info；
- TypeScript 类型检查：通过；
- ESLint：0 error，0 warning；
- Vite 生产构建：通过；
- 前端渲染测试：2/2 通过；
- 实时冒烟查询：OpenAlex 正常返回，S2 无 Key 时遇到 429 后由熔断器停止，
  不影响 OpenAlex 结果。

## 6. 下一轮优先级

1. 把 35 条开发集改为真实 DOI/arXiv/OpenAlex ID，并由两位标注者复核时间约束；
2. 导入 PaSa/RealScholarQuery 或 AstaBench paper-finding 的正式开发切分；
3. 保存每条查询的原始 API 响应，建立可重复的离线检索实验；
4. 实现 B0/B1/B2/Full 消融配置，而不是一次启用全部模块；
5. 在可靠验证集上比较 BM25、Embedding、Cross-Encoder，并只保留能稳定提高
   F1 的模块；
6. 增加前向被引论文扩展和基于新增高相关论文数的停止策略；
7. 收到用户所指的具体论文文件后，补充“论文章节—算法—代码—实验”四列对照表。
