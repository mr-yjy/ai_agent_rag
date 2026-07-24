# ScholarPilot v0.4 实时检索可靠性修复记录

日期：2026-07-23

## 1. 问题与最终结论

页面曾显示：

> 实时接口暂时不可用 (No papers found)，已自动切换到内置数据。

原问题不是单一故障，而是三个问题叠加：

1. `SearchAgent._execute_search_round()` 吞掉了提供方异常，外层只能看到
   `No papers found`；
2. 规则规划会把较长英文查询整句交给 OpenAlex。复杂全文查询容易超时，
   超时后的立即重试又可能触发 HTTP 429；
3. 最初用于常驻 8001 的提升权限后台进程与普通执行上下文具有不同的公网出口。
   前者对 OpenAlex 持续收到 429，后者可以正常获得 HTTP 200。

最终运行方式把 8001 放在已验证可联网的会话持久运行时中。旧的 8000 服务未停止。

## 2. 代码改动位置

### 2.1 紧凑多路线查询

文件：`backend/scholarpilot/planner.py`

新增 `_compact_keyword_routes()`。对于超过 5 个有效词的英文查询，不再优先发送整句，
而是生成三类最多 4–5 个词的路线：

- 桥接路线：前两个方法词 + 后三个任务/领域词；
- 方法路线：前四个词；
- 范围路线：后四个词。

例如：

```text
原查询:
vision transformer self-supervised learning medical image segmentation

桥接:
vision transformer medical image segmentation

方法:
vision transformer self-supervised learning

范围:
learning medical image segmentation
```

这样做同时改善两件事：

- 降低 OpenAlex 复杂全文查询的超时概率；
- 让不同子查询覆盖“方法”和“应用任务”，提升召回的多样性。

### 2.2 OpenAlex 有界重试和部分成功保留

文件：`backend/scholarpilot/providers.py`

改动：

- `ProviderError` 新增 `api_calls`、`cache_hits`、`retryable`；
- OpenAlex 只对 408、425、429、5xx、超时和网络异常重试；
- 400、401、403、404 等确定性错误不重试；
- 默认最多重试 1 次，并采用短指数退避；
- 每次真实 HTTP 尝试都进入 API 调用统计；
- 同批多个子查询中，单条失败不再丢弃先前成功论文；
- 只有整批都没有论文时才将该数据源判定为失败。

这属于可靠性工程改造，不宣称来自某篇论文。

### 2.3 Semantic Scholar 限流信息保真

文件：`backend/scholarpilot/semantic_scholar.py`

改动：

- HTTP 429 明确标记为可重试错误；
- 60 秒熔断期间不产生新的 HTTP 请求，`apiCalls=0`；
- 保留批内部分成功结果；
- 不再把真实 429 覆盖成笼统的“no usable papers”。

### 2.4 提供方错误贯穿搜索轨迹

文件：`backend/scholarpilot/search_agent.py`

新增并传递：

- `SearchRound.provider_errors`；
- `SearchResult.provider_errors`；
- `RoundResult.provider_errors`。

每条错误包含：

```json
{
  "provider": "SemanticScholar",
  "errorType": "ProviderError",
  "message": "Semantic Scholar rate limit circuit is open",
  "apiCalls": 0,
  "retryable": true
}
```

错误消息会限制长度并清理 `api_key`、`x-api-key`、`token` 等参数，避免把凭据写入
API 响应或日志。

### 2.5 API 降级信息和真实提供方名称

文件：`backend/scholarpilot/service.py`

响应新增：

- `providerErrors`：机器可读错误；
- `degradationReasons`：去重后的降级原因；
- 每轮 `stats.searchRounds[].providerErrors`。

只要 OpenAlex 仍返回论文，Semantic Scholar 429 不会再触发 demo 回退。
`provider` 也根据论文实际 `sources` 生成：只有 OpenAlex 成功时返回
`OpenAlex 实时学术检索`，不再错误声称两个数据源都成功。

### 2.6 可刷新的服务日志和版本

文件：

- `backend/scholarpilot/server.py`
- `backend/scholarpilot/fastapi_app.py`
- `backend/scholarpilot/__init__.py`

改动：

- 服务版本统一为 `0.4.0`；
- 启动消息和访问日志立即刷新；
- 未处理异常写入带堆栈的后端日志；
- `/api/health` 返回真实包版本。

## 3. 与参考论文方法的对应关系

本轮不是照搬论文代码，而是把论文思想改造成可控的工程实现。

| 参考方法 | 本轮如何使用 | 代码位置 | 与原论文的差异 |
|---|---|---|---|
| SPAR 的 RefChain / 查询分解与演化 | 把长查询拆成桥接、方法、范围三条短路线 | `planner.py::_compact_keyword_routes` | 当前无 LLM 时用确定性规则，成本为 0 Token；有 LLM 时仍可由现有 QueryAnalyzer 生成更精细路线 |
| PaSa 的 Crawler + Selector 分工 | Crawler 侧保留各数据源和各子查询的部分成功候选，再交给现有 RelevanceFilter Selector | `providers.py::search`、`search_agent.py::_execute_search_round` | 未使用 PaSa 的强化学习权重；选择器仍是规则召回安全过滤 + 可选批量 LLM |
| Ai2 Paper Finder 的多索引检索思想 | 一个数据源限流时保留另一个数据源结果，并记录真实来源 | `search_agent.py`、`service.py` | 未实现其多臂老虎机采样；当前仍使用预算确定的并行双源路由 |

这些改动对比赛指标的预期影响：

- F1/Recall：多路线检索减少整句查询漏召回；部分失败不丢弃成功候选；
- 精确率：候选仍经过现有 Selector 和综合排序，不直接展示全部召回；
- 效率：规则拆分不消耗 LLM Token；错误重试有次数上限并计入 API 成本；
- 结构化得分：提供方错误和每轮轨迹均为结构化字段。

## 4. 实测对照

同一复杂查询：

```text
vision transformer self-supervised learning medical image segmentation
```

修复前：

- `mode=demo`
- `candidateCount=0`
- 最终原因只能显示 `No papers found`

修复后（8001 直连）：

- `mode=live`
- `candidateCount=95`
- `deduplicatedCount=80`
- `results=5`
- `apiCalls=5`
- `elapsedMs=10170`
- Semantic Scholar 429 被记录，但 OpenAlex 结果正常返回

前端端到端查询：

```text
diffusion models for protein structure generation and design
```

结果：

- `http://127.0.0.1:5173/api/search`
- `mode=live`
- `candidateCount=97`
- `deduplicatedCount=56`
- `results=10`
- `apiCalls=4`
- Top-1：`De novo design of protein structure and function with RFdiffusion`

## 5. 回归验证

- Python 后端单元测试：14/14；
- TypeScript：`npx tsc --noEmit` 通过；
- ESLint：通过；
- Vite 生产构建：通过；
- 前端渲染测试：2/2。

新增测试：

- 长英文查询生成紧凑路线；
- 一个提供方失败时另一个提供方仍返回论文；
- 错误类型、调用次数和 `retryable` 可见。

## 6. 当前限制与下一步

1. 当前没有配置 `SEMANTIC_SCHOLAR_API_KEY`，匿名接口容易 HTTP 429；
2. OpenAlex 仍建议配置正式 API Key，避免比赛批量评测时共享出口限流；
3. 本次在线查询只证明链路和检索合理性，不等价于公开/隐藏测试集 F1 提升；
4. 下一轮应在真实标注开发集上比较：
   - 整句查询；
   - 紧凑三路线；
   - LLM RefChain；
   - 三路线 + 引文扩展；
5. 应分别报告 F1@20、Recall@20、平均 API 调用、P95 延时和 Token。

## 7. 2026-07-23 第二次限流修复：长 Retry-After 熔断

### 7.1 现场根因

DeepSeek V4 Pro 配置完成后，端到端查询出现：

```text
OpenAlex: OpenAlex request failed with HTTP 429
SemanticScholar: Semantic Scholar rate limit circuit is open
```

对 OpenAlex 发送一条只返回 1 篇论文的最小只读请求后，服务端返回：

```text
HTTP 429
Retry-After: 33036
```

`33036` 秒约为 9.2 小时，因此这不是普通的瞬时并发抖动，而是当前匿名
共享出口的配额窗口已经耗尽。当前 `/api/health` 同时确认：

```json
{
  "llm": {
    "configured": true,
    "model": "deepseek-v4-pro"
  },
  "academicSources": {
    "openalex": {"apiKeyConfigured": false},
    "semanticScholar": {
      "enabled": true,
      "apiKeyConfigured": false
    }
  }
}
```

这也说明两种 Key 的职责不同：

- `LLM_API_KEY`：DeepSeek 查询分析、Selector、重排和反事实验证；
- `OPENALEX_API_KEY`：OpenAlex 实时论文元数据检索；
- `SEMANTIC_SCHOLAR_API_KEY`：Semantic Scholar 实时论文检索。

DeepSeek 调用正常不代表匿名学术接口一定仍有可用配额。

### 7.2 旧实现的问题

文件：`backend/scholarpilot/providers.py`

旧 `_retry_delay()` 会把服务端任何 `Retry-After` 强行截断到最多 2 秒。
当服务端明确要求等待数小时，代码仍在 2 秒后重试，并继续处理后续子查询。
一次搜索因而产生：

- OpenAlex：3 个子查询 × 2 次尝试 = 6 次必败请求；
- Semantic Scholar：1 次请求；
- 总计：7 次学术 API 调用；
- 最终仍然回退到 demo。

这会同时恶化比赛的 API 调用次数、端到端延时和共享配额压力。

### 7.3 本轮代码改动

#### `backend/scholarpilot/providers.py`

1. `ProviderError` 新增结构化字段：
   - `status_code`；
   - `retry_after_seconds`；
   - `user_action`。
2. OpenAlex 完整解析 `Retry-After`，不再把数小时等待错误截断为 2 秒。
3. 新增 `max_retry_wait_seconds=3`：
   - 短暂抖动可做一次有界重试；
   - 超过 3 秒立即打开熔断器，不阻塞用户数小时。
4. OpenAlex 熔断期间直接失败，不再产生新的网络请求。
5. 同一轮中一旦收到 HTTP 429，立即停止其余 OpenAlex 子查询。
6. 匿名 OpenAlex 请求采用 1.05 秒最小间隔；带 Key 时采用 0.12 秒间隔，
   防止突发请求触发秒级限流。
7. 支持可选 `OPENALEX_MAILTO`，并统一发送 `Accept: application/json`。

#### `backend/scholarpilot/semantic_scholar.py`

1. Semantic Scholar 同样解析服务端 `Retry-After`，不再固定假设 60 秒；
2. 429 和熔断错误携带结构化状态、剩余等待时间与恢复操作；
3. 收到 429 后立即停止其余子查询。

#### `backend/scholarpilot/search_agent.py`

`providerErrors` 现在会安全返回：

```json
{
  "provider": "OpenAlex",
  "statusCode": 429,
  "apiCalls": 1,
  "retryAfterSeconds": 32496,
  "retryable": true,
  "userAction": "Add a free OpenAlex API key to backend/.env as OPENALEX_API_KEY, then restart the backend."
}
```

不返回请求头，也不会暴露任何 Key。

#### `backend/scholarpilot/service.py`、`server.py`、`fastapi_app.py`

- `/api/health` 新增安全字段 `academicSources`；
- 搜索响应新增去重后的 `recoveryActions`；
- 前端可以直接展示恢复方法，而不必根据英文错误字符串猜测。

#### 配置和测试

- 恢复并补全 `backend/.env.example`；
- 新增 `backend/tests/test_provider_rate_limits.py`；
- HTTP 健康检查测试覆盖 `academicSources`；
- 后端测试从 19 项增加到 22 项，当前为 22/22 通过。

### 7.4 修复后真实对照

查询：

```text
Find 2024 papers on LLM agents for academic paper retrieval using query decomposition
```

本机修复后结果：

- DeepSeek：成功调用 1 次，约 1280 tokens；
- OpenAlex：1 次请求后按长 `Retry-After` 熔断；
- Semantic Scholar：1 次请求后熔断；
- 学术 API 总调用：2 次，而不是修复前的 7 次；
- 错误结构包含两个数据源各自的恢复操作；
- 因当前两个匿名配额都不可用，本次仍回退 demo，这是外部配额状态，
  不是 DeepSeek 或检索代码异常。

### 7.5 恢复实时论文检索

推荐做法：

1. 在 OpenAlex 官方账户中申请/查看 API Key；
2. 只在本机 `backend/.env` 填写：

   ```ini
   OPENALEX_API_KEY=你的真实OpenAlexKey
   OPENALEX_MAILTO=你的联系邮箱
   ```

3. 不要把 Key 发到聊天，也不要提交 `.env`；
4. 重启 8001 后端；
5. 检查 `/api/health` 中
   `academicSources.openalex.apiKeyConfigured=true`；
6. 再跑实时查询，目标是 `mode=live` 且 `candidateCount>0`。

如果暂时不配置 Key，只能等待 OpenAlex 响应中的剩余秒数归零。连续点击搜索
不会缩短等待时间，反而会继续消耗 DeepSeek Token；本轮熔断逻辑已经避免
OpenAlex 侧的重复网络请求。

## 8. 2026-07-24 OpenAlex Key 接入后的端到端修复

### 8.1 Key 验证

用户在 `backend/.env` 配置 OpenAlex Key 后，安全检查确认：

```json
{
  "openAlexKeyInFile": true,
  "runningOpenAlexConfigured": true,
  "llmConfigured": true,
  "model": "deepseek-v4-pro"
}
```

使用相同 Key 发出的最小请求返回 HTTP 200 和 1 条论文，证明 Key 有效。
检查和日志均未输出 Key 内容。

### 8.2 LLM 检索式与 OpenAlex 语法不兼容

DeepSeek 曾生成：

```text
("large language model" OR LLM) AND agent* AND
("scholarly document retrieval" OR "academic paper retrieval")
AND "query decomposition"
```

逐条语法探测证明：

- 引号、`AND`、`OR`、括号：OpenAlex 返回 HTTP 200；
- `agent*`：OpenAlex 返回 HTTP 400。

因此问题不是 Key，而是 Lucene 风格通配符不被 OpenAlex `search` 参数接受。

代码改动：

- `query_analyzer.py`：在两套查询分析 Prompt 中明确禁止 `*` 和 `?`；
- `providers.py::_sanitize_search_query()`：在网络边界删除 `*`、`?` 和控制
  字符，同时保留引号、Boolean 操作符和括号；
- 搜索式最长限制为 500 字符；
- 新增测试，验证 `agent*`、`retrieval?` 会被转换，AND/OR 仍保留。

这采用了“双层防御”：

1. Prompt 层降低模型生成非法语法的概率；
2. Provider 层保证即使模型偶发违规，也不会把非法查询发送给 OpenAlex。

### 8.3 精确检索过严与 Selector 全删

语法修复后，OpenAlex 已能返回 10 篇候选，但系统仍曾回退 demo。诊断发现：

1. 首轮使用 `optimized_queries or sub_queries`，只要存在精确 Boolean 查询，
   更宽的召回查询就完全不会进入 API 预算；
2. Selector 对摘要稀疏的 10 篇候选全部判为不相关；
3. `SearchService` 看到过滤后列表为空，将其误认为实时接口不可用。

代码改动：

- `SearchAgent._initial_query_routes()` 交错排列精确路线和宽召回路线：

  ```text
  precise-1 → broad-1 → precise-2 → broad-2
  ```

  因此前 3 个 OpenAlex 预算不再全部被严格 Boolean 查询占据。

- `RelevanceFilter.filter_papers()` 增加召回安全阀：
  - 先执行词法证据过滤；
  - 再执行批量 LLM Selector；
  - 如果 LLM 把具有词法证据的候选全部删除，保留词法 Top-3 作为探索集；
  - 最终仍由混合排序和相关性等级区分高相关、部分相关和探索性结果。

这不是无条件保留 API 原始结果。只有通过词法阈值的候选才能进入安全阀，
因此能避免“Selector 一票否决导致 Recall=0”，同时控制噪声。

### 8.4 测试隔离修复

Provider 构造函数原来使用：

```python
api_key or os.getenv(...)
```

测试显式传入空字符串时仍会读取本机真实 Key。现改为只有参数为 `None` 才读取
环境变量，保证匿名限流测试不会意外使用开发者凭据。

新增测试覆盖：

- OpenAlex 不支持的通配符清理；
- 精确与宽召回路线交错；
- Selector 全拒绝时保留 3 条有词法证据的探索候选；
- 显式空 Key 不回退读取本机 Key。

后端回归测试最终为 25/25 通过。

### 8.5 最终真实验证

查询：

```text
Find 2024 papers on LLM agents for academic paper retrieval using query decomposition
```

最终结果：

- `mode=live`；
- `provider=OpenAlex 实时学术检索`；
- OpenAlex 候选数：26；
- 最终结果数：1；
- 学术 API 调用：4；
- DeepSeek 调用：3；
- Token 估算：4190；
- Top-1：`Understanding the planning of LLM agents: A survey`；
- 年份：2024；
- 来源：`openalex`；
- 相关等级：高度相关；
- 综合分数：70.8；
- 没有 demo 回退，也没有 warning。

Semantic Scholar 因未配置 Key 仍返回 HTTP 429，但被作为结构化的局部降级记录，
不影响 OpenAlex 实时检索结果。

## 9. 2026-07-24 禁止 live 结果被 demo 数据污染

### 9.1 问题

用户随后看到：

```text
实时接口暂时不可用
(SemanticScholar: Semantic Scholar rate limit circuit is open;
retry after about 30s)，已自动切换到内置数据。
```

后端日志中同一时间只有 Semantic Scholar 限流，没有 OpenAlex 错误。这说明
OpenAlex 请求已经成功，但其候选在相关性过滤后为空。旧 `SearchService` 对
`papers=[]` 直接抛出 `No papers found`，再无条件读取 demo 数据，并把唯一可见的
Semantic Scholar 局部错误拼进“接口不可用”提示。

该行为有三个问题：

1. 把“没有候选通过过滤”误报成“实时接口不可用”；
2. live 结果混入与用户查询无关的内置论文，直接损害自动评测 Precision/F1；
3. Semantic Scholar 的局部降级掩盖了 OpenAlex 已成功这一事实。

### 9.2 live 模式语义修复

文件：`backend/scholarpilot/service.py`

新规则：

- `mode=demo`：明确使用内置演示数据；
- `mode=live` 且有真实论文：返回真实论文；
- `mode=live` 且 API 返回候选但过滤为空：返回 live 空列表和准确提示；
- `mode=live` 且外部请求失败：返回 live 空列表和结构化错误；
- live 请求在任何情况下都不再自动替换为 demo 论文。

候选过滤为空时的提示改为：

```text
实时接口已返回 N 篇候选，但没有论文通过当前相关性过滤；未使用内置数据。
```

这使自动评测获得可解释的空预测，而不是一组无关 demo 假阳性。

### 9.3 跨语言相关性过滤

旧搜索阶段使用 `AnalyzedQuery.original_query` 做词法过滤。中文查询检索到的
OpenAlex 标题与摘要通常是英文，直接比较会导致重合率接近零。

新增 `SearchAgent._relevance_query()`：

- 英文查询优先使用规范化查询；
- 检测到中文原查询时，优先选择 QueryAnalyzer 生成的第一条纯英文子查询；
- 初始检索、迭代检索和引文扩展统一使用该相关性查询；
- 如果没有英文路线，再安全回退到规范化查询或原查询。

### 9.4 Semantic Scholar 熔断不再重复调度

`SemanticScholarProvider` 新增 `circuit_open` 状态。每轮创建 Provider jobs
之前，`SearchAgent` 会检查该状态：

- 第一次真实 429 仍被记录；
- 熔断窗口内后续轮次不再创建 Semantic Scholar job；
- API 预算转给仍可用的 OpenAlex；
- 不再重复输出多条 `circuit is open` 错误。

### 9.5 回归测试与真实验证

新增测试：

- live 空结果绝不替换 demo 论文；
- 中文原查询使用英文子查询做相关性过滤；
- Semantic Scholar 熔断打开时不再调度。

后端测试最终为 28/28 通过。

中文复杂查询验证：

```text
查找2024年使用查询分解进行学术论文检索的大语言模型智能体论文
```

结果：

- `mode=live`；
- `provider=OpenAlex 实时学术检索`；
- 候选数 149；
- 最终结果 5；
- `containsDemo=false`；
- `warning=null`。

最终版本英文指定论文冒烟验证：

```text
Find the 2024 paper titled
Understanding the planning of LLM agents: A survey
```

结果：

- `mode=live`；
- Top-1 标题精确命中；
- 候选数 60；
- `containsDemo=false`；
- Semantic Scholar 真实 429 只记录 1 次；
- `circuit is open` 重复记录 0 次；
- `warning=null`。
