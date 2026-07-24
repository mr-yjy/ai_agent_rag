# 研索智航 ScholarPilot - Python 后端

## 架构概览 (v0.3)

```
用户查询 → [QueryAnalyzer] → [SearchAgent] → [LLMRanker + Counterfactual] → 结构化结果
              ↓                    ↓                       ↓
         RefChain多步推理    双源并行检索            混合排序+反事实验证
         规则回退            OpenAlex + S2            约束核验+分数调整
```

### 四层 Agent 架构

| 层 | 组件 | 功能 | 参考论文 |
|------|------|------|---------|
| **分析层** | `QueryAnalyzer` | RefChain 4步推理、约束层次化、多角度子查询 | SPAR RefChain (Shi et al., 2025) |
| **搜索层** | `SearchAgent` | 双源并行检索(OA+S2)、相关性过滤、引文扩展、迭代精化 | PaSa Crawler+Selector (He et al., 2025) |
| **排序层** | `LLMRanker` | 启发式粗排 + LLM 5维精排 + MMR多样性 | Cross-Encoder范式 |
| **验证层** | `CounterfactualVerifier` | 约束验证 + 反事实对比 + 分数惩罚 | Counterfactual reasoning |

## 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少配置：

```ini
# 前端服务端 -> Python 的内部鉴权令牌，至少32字符
BACKEND_PROXY_TOKEN=
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173

# LLM 配置 (DeepSeek 示例)
LLM_API_KEY=sk-your-key-here
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro
LLM_THINKING_MODE=disabled
LLM_REASONING_EFFORT=high
LLM_JSON_MODE=true

# 学术搜索 API
# OpenAlex Key 强烈建议配置；匿名共享配额可能产生数小时的 HTTP 429。
OPENALEX_API_KEY=your-openalex-key
OPENALEX_MAILTO=your-email@example.com
# Semantic Scholar 可匿名使用，但比赛批量检索也建议配置 Key。
SEMANTIC_SCHOLAR_API_KEY=optional-key

# 搜索策略
MAX_SEARCH_ROUNDS=3
MAX_TOTAL_PAPERS=100
ENABLE_CITATION_EXPANSION=true
```

生产环境必须轮换任何曾进入 Git 历史的 Key，并按
[`../docs/PRODUCTION_SECURITY.md`](../docs/PRODUCTION_SECURITY.md)
配置唯一 live 代理链路。未配置有效 `BACKEND_PROXY_TOKEN` 时，搜索接口会
安全关闭并拒绝请求。

DeepSeek V4 Pro 的官方参数、思考模式、价格、代码改动和安全配置说明见
[`../docs/DEEPSEEK_V4_PRO_INTEGRATION_2026-07-23.md`](../docs/DEEPSEEK_V4_PRO_INTEGRATION_2026-07-23.md)。

如果健康接口中出现：

```json
{
  "academicSources": {
    "openalex": {"apiKeyConfigured": false},
    "semanticScholar": {"apiKeyConfigured": false}
  }
}
```

说明两个学术接口都在匿名模式运行。DeepSeek Key 只负责查询理解和排序，
不能代替 OpenAlex/Semantic Scholar Key。OpenAlex 返回长时间
`Retry-After` 时，应填写 `OPENALEX_API_KEY` 并重启后端，而不是连续重试。

### 2. 启动服务

```bash
# 零依赖启动 (演示模式)
python run.py

# FastAPI 启动 (全功能)
pip install openai uvicorn fastapi
uvicorn scholarpilot.fastapi_app:app --reload --port 8000
```

### 3. 运行评测

```bash
# 35条查询演示评测
python run_evaluation.py --mode demo

# 实时检索评测
python run_evaluation.py --mode live --verbose

# 导出结果
python run_evaluation.py --mode demo --export results.csv
```

## 模块说明

### query_analyzer.py — RefChain 查询分析引擎

**参考**: SPAR (Shi et al., 2025) RefChain query decomposition

核心类 `QueryAnalyzer`:
- `analyze(query)` → `AnalyzedQuery`: 完整分析流程
  - Step 1: LLM RefChain 4步推理（约束提取→层次化→子查询→优化）
  - Step 2: 规则回退（LLM不可用时）
  - Step 3: 结果合并与sub-query fallback
- 约束层次化: must_have（必须满足）/ preferred（优先满足）/ exclude（排除）
- 子查询含metadata: rationale（生成理由）、perspective（角度）、priority（优先级）
- 中→英学术术语自动转换

### search_agent.py — 双源迭代搜索代理

**参考**: PaSa (He et al., 2025) Crawler+Selector

核心类 `SearchAgent`:
- `search(analyzed_query)` → `SearchResult`:
  - Round 1: 双源初始检索（OpenAlex + Semantic Scholar）
  - Round 2: 引文扩展（从高相关种子论文）
  - Round 3+: LLM查询精化迭代
  - 每轮经 RelevanceFilter 过滤
- `RelevanceFilter`: LLM+关键词双重过滤（PaSa Selector）
- `CitationExpander`: 引文图探索

### semantic_scholar.py — Semantic Scholar API Provider

**新增模块**，提供第二数据源:
- 标题/摘要搜索 + 相关性排序
- TLDR摘要自动补充
- 速率限制（有key: 100rps, 无key: 1rps）
- 内存缓存（TTL 600s）

### counterfactual.py — 反事实验证引擎

**新增模块**，核心创新点:
- 约束验证：LLM逐条验证论文是否满足查询约束，提取证据
- 反事实生成：修改关键约束（如"query decomposition"→"text summarization"）
- 反事实对比：判断约束改变后相关性是否显著下降（≥20分）
- 分数惩罚：非判别性论文降分（最多30%），调整相关级别
- 成本控制：仅对Top-10论文执行

### llm_ranker.py — LLM 混合排序引擎

- Stage 1: 启发式粗排（Token重叠 + 约束覆盖 + 权威 + 时效 + 开放获取）
- Stage 2: LLM 5维精排（topic_match / method_match / domain_match / novelty / authority）
- Stage 3: MMR 多样性重排

### evaluation.py — 跨学科评测管线

核心类 `Evaluator`:
- 35条查询 × 5学科（CS / 生物医学 / 化学材料 / 金融经济 / 安全密码学）
- 指标: Precision / Recall / F1（Macro + Micro）
- 分层报告: 每个学科独立统计
- CSV导出

### llm_client.py — 统一 LLM 客户端

支持 OpenAI 兼容的任何 LLM 提供商:
- DeepSeek / Qwen / OpenAI / 本地模型
- openai 包优先，urllib回退（零依赖）
- Token 估算

## 新增/修改的文件 (v0.3)

| 文件 | 状态 | 说明 |
|------|------|------|
| `scholarpilot/query_analyzer.py` | 重写 | RefChain 多步推理、约束层次化、SubQueryInfo |
| `scholarpilot/search_agent.py` | 修改 | 双源检索（OA+S2）、并行搜索+去重 |
| `scholarpilot/semantic_scholar.py` | 新增 | S2 API Provider、速率限制、TLDR |
| `scholarpilot/counterfactual.py` | 新增 | 反事实验证、约束核验、分数惩罚 |
| `scholarpilot/service.py` | 修改 | 集成CounterfactualVerifier (Step 4.5) |
| `scholarpilot/evaluation.py` | 修改 | DisciplineReport、5学科分层报告 |
| `scholarpilot/data/evaluation_queries.json` | 扩展 | 10条→35条、5学科全覆盖 |

## 许可证

MIT License
