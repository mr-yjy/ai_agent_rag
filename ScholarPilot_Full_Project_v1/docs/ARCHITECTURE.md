# ScholarPilot 当前架构

适用版本：v0.6.0 RC

更新时间：2026-07-25

本文只描述当前源码已经实现的行为。未来设想统一记录在
[`ROADMAP.md`](ROADMAP.md)，历史变化统一记录在
[`../CHANGELOG.md`](../CHANGELOG.md)。

## 1. 系统边界

ScholarPilot 包含两个运行时：

```text
Browser
  └─> Web /api/search
        └─> Bearer BACKEND_PROXY_TOKEN
              └─> Python /api/search
                    ├─> OpenAlex
                    ├─> Semantic Scholar
                    └─> OpenAI-compatible LLM
```

- 浏览器不直接访问学术 API 或 LLM，也不能获得代理令牌与第三方 Key。
- Web 只负责校验、身份散列、超时和 Python 代理，不实现第二套检索算法。
- 所有论文结果来自真实学术数据源；上游失败时返回结构化错误。
- Web 与 Python 都提供 `GET /api/health`；Web 健康接口只代理 Python 的真实状态。

## 2. 真实搜索流程

一次请求使用唯一 `requestId` 和同一个单调时钟截止时间。

1. **鉴权和容量控制**
   - Python 校验 `Authorization: Bearer <BACKEND_PROXY_TOKEN>`；
   - 按用户/IP 固定窗口限流；
   - 使用全局非阻塞信号量限制并发；
   - 浏览器取消会传播给 Python 的后续步骤。
2. **查询理解**
   - `QueryAnalyzer` 尝试通过 LLM 提取主题、方法、数据集、时间、发表源、
     must/preferred/exclude、布尔约束组与检索偏好；
   - LLM 不可用、低置信或输出异常时，`planner.py` 生成规则 Query Contract；
   - 初始子查询最多 3 条。
3. **多源召回**
   - `SearchAgent` 并行调用 OpenAlex 和 Semantic Scholar；
   - 先按 DOI/学术图谱 ID，再按规范化标题融合论文实体；
   - 每篇论文记录 `sources` 和 `retrievalRoutes`；
   - 默认总学术 API 调用不超过 10 次、总候选不超过 100 篇。
4. **过滤和迭代**
   - `RelevanceFilter` 最多检查 32 篇候选，按 8 篇一批调用 LLM；
   - LLM Selector 超时或失败时使用词法筛选，不让整个搜索请求失败；
   - 仅当候选缺口、剩余预算和预期收益允许时执行一次反向引文扩展及后续精化；
   - 新增候选不足、候选已充足、API 或时间预算耗尽时早停。
5. **排序和验证**
   - 先应用年份、排除项和约束组等硬条件；
   - 规则排序综合相关性、约束覆盖、证据质量、权威性、时效性、跨源一致性和开放性；
   - 对重复论文施加 MMR 惩罚；
   - LLM 已配置且预算允许时，对 Top-12 进行 LLM 精排；
   - 最多选择 4 篇阈值附近候选执行反事实核验；
   - 可选 LLM 阶段超时或失败时保留已有规则排序。
6. **响应组装**
   - 返回 Query Contract、论文、证据、来源状态、检索轮次和请求级指标；
   - 指标包含 API/LLM 调用、Token、缓存、阶段耗时、停止原因、剩余预算和配置哈希。

## 3. 时间、重试与缓存

Python 默认总预算为 50 秒，Web 代理在 55 秒终止，预留响应组装与网络传输时间。
所有步骤共享总预算，单步实际可用时间不会超过阶段上限或剩余总预算。

| 阶段 | 默认上限 |
| --- | ---: |
| 鉴权/排队 | 1 秒 |
| 查询理解 | 8 秒 |
| 子查询生成 | 2 秒 |
| OpenAlex / Semantic Scholar | 各 15 秒 |
| 候选融合 | 5 秒 |
| LLM Selector | 6 秒 |
| 引文扩展 | 10 秒 |
| 迭代查询生成 | 4 秒 |
| LLM 精排 | 8 秒 |
| 反事实核验 | 4 秒 |
| 响应组装 | 2 秒 |

仅对 429、可重试 5xx 和网络瞬断执行有界重试。若 `Retry-After` 或退避将耗尽
剩余预算，立即停止。查询分析、学术 API、Selector、精排和反事实结果使用线程
安全 TTL 内存缓存，默认 600 秒。

这些缓存和限流状态都在单个 Python 进程内；多实例部署需要共享存储或平台能力。

## 4. API 契约

### 请求

`POST /api/search`

```json
{
  "query": "长度为 6 到 800 个字符的科研问题",
  "limit": 10
}
```

`limit` 范围为 1–50。除此之外的字段会被拒绝。Web 路由会把代理令牌、
`X-Request-ID` 和匿名用户标识
传给 Python。

### 成功响应

所有非错误响应使用 `schemaVersion: "1.0"`，并至少包含：

- `requestId`；
- `status`：`success`、`degraded` 或 `no_results`；
- `provider`；
- `queryPlan`/`plan`；
- `results`；
- `sourceStatus`；
- `stats`。

`degraded` 表示仍返回真实论文，但至少一个真实数据源失败或部分失败。
`no_results` 表示真实数据源成功返回空集合，或候选均未通过过滤；它不是后端故障。

### 错误响应

错误体统一为：

```json
{
  "error": {
    "code": "stable_error_code",
    "message": "可读说明",
    "requestId": "request-id",
    "retryable": true,
    "retryAfterSeconds": 0,
    "stage": "optional-stage"
  }
}
```

典型 HTTP 状态包括 400（请求不合法）、401（代理鉴权失败）、429（限流或并发
已满）、499（前端观察到客户端取消）、502（上游或 Python 不可达）和
503（Python 未配置代理令牌）。

完整 Schema：

- [`query-contract-v1.schema.json`](schemas/query-contract-v1.schema.json)
- [`search-response-v1.schema.json`](schemas/search-response-v1.schema.json)
- [`error-response-v1.schema.json`](schemas/error-response-v1.schema.json)

## 5. 主要模块

| 模块 | 职责 |
| --- | --- |
| `app/page.tsx` | 搜索交互、状态处理和结果展示 |
| `app/api/search/route.ts` | 请求校验、身份散列、超时与 Python 代理 |
| `app/lib/types.ts` | 前端共享 API 类型 |
| `backend/scholarpilot/service.py` | 请求编排、降级语义和响应组装 |
| `budget.py` | 截止时间、阶段计时和取消 |
| `query_analyzer.py` / `planner.py` | LLM 查询理解与规则回退 |
| `search_agent.py` | 多源召回、过滤、引文扩展、迭代和早停 |
| `providers.py` / `semantic_scholar.py` | 学术 API、缓存、重试和熔断 |
| `identity.py` | 跨源论文实体归一和融合 |
| `ranking.py` / `llm_ranker.py` | 透明规则排序与 LLM 精排 |
| `counterfactual.py` | 边界候选约束与反事实核验 |
| `causal_trust.py` | t0/t1/t2、Panel、CCI、可靠性门、诊断、恢复与 Trace |
| `security.py` | 代理鉴权、CORS、限流和并发控制 |
| `evaluation.py` | 数据审计、指标和可复现实验输出 |
| `calibration_metrics.py` | ECE、Brier、选择性回答和干预/恢复离线指标 |

## 6. 当前没有实现的能力

以下内容不是 v0.6 当前能力，不能在介绍或评测中写成“已完成”：

- Embedding 向量召回；
- BM25 索引服务；
- Cross-Encoder 精排；
- 学习型预算停止策略；
- Redis/平台级共享限流；
- 已冻结且可证明质量提升的比赛评测集；
- 已通过验收的 staging 或 production 部署。

## 7. CausalTrust / When-to-Trust 控制层

排序完成且存在至少 3 篇论文、个人 LLM Key 可用、剩余预算不少于配置门槛时，
`service.py` 把排序论文转换为带稳定论文 ID 的证据池，并调用独立
`causal_trust.py`：

1. t0 正常生成一个结构化核心结论；
2. t1 在不改变证据池的前提下假设证据质量有问题并重新判断；
3. t2 在不改变证据池的前提下假设理解或推理有问题并重新判断；
4. 规范化表面不同但含义相同的候选；
5. 一次 Panel 调用分别从三种干预视角给所有候选评分；
6. Python 归一化评分，计算平均支持度、跨干预极差和 CCI；
7. 可靠性门选择接受、证据恢复、推理恢复或拒答；
8. 恢复最多一次，之后重新校准；仍未通过则拒答。

证据恢复最多使用总学术 API 预算中的剩余调用，并且只改变校准证据，不重写原始
论文列表和排序。任何校准失败、超时、取消、无 Key 或证据不足都只让
`reliability` 标记为 `skipped`/`failed`，不会把真实论文检索变成失败。响应 Trace
保存证据 ID、t0/t1/t2、Panel、CCI 和决策，不保存凭据。

完整设计和字段见 [`CAUSAL_TRUST.md`](CAUSAL_TRUST.md)。
