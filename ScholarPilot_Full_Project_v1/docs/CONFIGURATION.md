# ScholarPilot 配置说明

适用版本：v0.6.0 RC

真实凭据只应存在于未跟踪的运行时环境或本地 `.env` 文件。不要把 Key、令牌、
真实域名或生产配置提交到 Git。

## 1. 配置文件与加载规则

- Web：复制项目根目录 `.env.example` 为 `.env.local`；
- Python：复制 `backend/.env.example` 为 `backend/.env`；
- Python 启动时读取 `backend/.env`，但不会覆盖进程中已经设置的环境变量；
- staging/production 应由部署平台注入变量，不应上传 `.env`；
- `BACKEND_PROXY_TOKEN` 必须在 Web 和对应 Python 环境中一致。

最小真实检索配置：

```ini
# Web .env.local
PYTHON_BACKEND_URL=http://127.0.0.1:8000
BACKEND_PROXY_TOKEN=<至少32字节随机值>
```

```ini
# backend/.env
BACKEND_PROXY_TOKEN=<与Web相同>
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
LLM_API_KEY=<LLM凭据>
OPENALEX_API_KEY=<OpenAlex凭据>
SEMANTIC_SCHOLAR_API_KEY=<可选但建议配置>
```

## 2. Web 服务端变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PYTHON_BACKEND_URL` | `http://127.0.0.1:8000` | Python 后端基地址 |
| `BACKEND_PROXY_TOKEN` | 空 | 搜索代理令牌；少于 32 个字符时 Web 安全拒绝请求 |

这两个变量都是服务端变量。禁止添加 `NEXT_PUBLIC_` 前缀，禁止通过 Vite `define`
写入客户端包。

## 3. Python 安全与容量

| 变量 | 代码默认值 | 说明 |
| --- | --- | --- |
| `BACKEND_PROXY_TOKEN` | 空 | Bearer 代理令牌；未配置时搜索接口返回 503 |
| `CORS_ALLOWED_ORIGINS` | 两个本地 5173 Origin | 逗号分隔的精确 Origin；不支持 `*` |
| `RATE_LIMIT_REQUESTS` | `30` | 每个身份在窗口内最多请求数 |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | 固定窗口秒数 |
| `MAX_CONCURRENT_SEARCHES` | `4` | 单进程同时执行的搜索数 |

开发、staging 与 production 必须使用不同代理令牌。多 Python 实例不能依赖当前
内存限流来实现全局限制，需接入 Redis 或平台级限流。

## 4. LLM

Python 使用 OpenAI-compatible Chat Completions 接口。默认提供商配置指向
DeepSeek，但可替换为兼容服务。

| 变量 | 代码默认值 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 空 | LLM 凭据；兼容旧变量 `DEEPSEEK_API_KEY` |
| `LLM_BASE_URL` | `https://api.deepseek.com` | API 基地址，末尾 `/` 会被移除 |
| `LLM_MODEL` | `deepseek-v4-pro` | 模型标识 |
| `LLM_THINKING_MODE` | `disabled` | `enabled` 或 `disabled` |
| `LLM_REASONING_EFFORT` | `high` | `high` 或 `max` |
| `LLM_JSON_MODE` | `true` | 请求 JSON 输出模式 |
| `LLM_TEMPERATURE` | `0` | 生成温度 |
| `LLM_MAX_TOKENS` | `4096` | 单次最大输出 Token，最小 128 |
| `LLM_TIMEOUT` | `60` | 单次请求上限；模板设为 8 秒，且仍受共享阶段/总预算约束 |
| `LLM_MAX_RETRIES` | `1` | 可重试失败次数，限制为 0–3 |
| `LLM_RETRY_BACKOFF` | `0.75` | 初始退避秒数 |

安装 `openai` 包时优先使用 SDK；未安装时使用标准库 `urllib`。两种传输不会在一次
失败调用中串联重试，避免双倍成本。

没有可用 LLM Key 时，查询分析、过滤和排序会使用规则路径。该行为不代表真实
论文源也可用；学术 API Key 与 LLM Key 用途不同。

## 5. 学术数据源

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPENALEX_API_KEY` | 空 | OpenAlex Key；匿名共享配额可能被限流 |
| `OPENALEX_MAILTO` | 空 | OpenAlex polite-pool 联系邮箱 |
| `SEMANTIC_SCHOLAR_API_KEY` | 空 | Semantic Scholar Key；空值时使用匿名接口 |
| `MAX_RESULTS_PER_QUERY` | `25` | 每个学术查询请求的最大结果数 |
| `REQUEST_TIMEOUT` | `15` | 单个学术请求期望上限；还会被阶段和总预算截断 |

`GET /api/health` 只报告是否配置和熔断状态，不返回凭据，也不会主动消耗第三方
API 配额。

## 6. 搜索预算与策略

| 变量 | 默认值 | 约束或作用 |
| --- | ---: | --- |
| `MAX_SEARCH_ROUNDS` | 3 | 限制为 1–3 |
| `MAX_API_CALLS_PER_ROUND` | 5 | 限制为 1–10 |
| `MAX_TOTAL_API_CALLS` | 10 | 限制为 1–10 |
| `MAX_TOTAL_PAPERS` | 100 | 限制为 20–500 |
| `MIN_PAPERS_FOR_ITERATION` | 3 | 进入后续迭代所需的最少已有论文数 |
| `INITIAL_SUBQUERY_LIMIT` | 3 | 限制为 1–3 |
| `DESIRED_CANDIDATE_COUNT` | 20 | 候选充足判断，最小 5 |
| `ENABLE_CITATION_EXPANSION` | `true` | 是否允许预算感知引文扩展 |
| `MAX_CITATION_HOPS` | 1 | 配置限制为 0–1；当前流程只做单轮反向扩展 |
| `CITATION_EXPANSION_PER_PAPER` | 5 | 每个种子的扩展数量 |
| `RELEVANCE_THRESHOLD_HIGH` | 0.62 | 高相关过滤阈值 |
| `RELEVANCE_THRESHOLD_PARTIAL` | 0.42 | 部分相关过滤阈值 |
| `SELECTOR_BATCH_SIZE` | 8 | LLM Selector 每批数量，最小 2 |
| `SELECTOR_MAX_PAPERS` | 32 | Selector 最多处理数量，最小 4 |
| `LLM_RERANK_TOP_K` | 12 | LLM 精排候选数 |
| `COUNTERFACTUAL_MAX_PAPERS` | 4 | 反事实核验最大候选数；0 可关闭 |
| `COUNTERFACTUAL_BOUNDARY_MARGIN` | 8.0 | 阈值边界范围 |
| `MIN_NEW_PAPERS_TO_CONTINUE` | 2 | 新论文少于此值时早停 |
| `SEARCH_TIMEOUT_SECONDS` | 50 | Python 总预算，代码强制不超过 50 秒 |
| `OPTIONAL_STEP_MIN_REMAINING_SECONDS` | 2 | 可选步骤启动所需最少剩余时间 |
| `CACHE_TTL_SECONDS` | 600 | 内存缓存 TTL |

Web 代理的 55 秒边界写在 `app/api/search/route.ts`，不是环境变量。

## 7. 透明排序

规则排序权重会在运行时按总和归一化：

| 变量 | 默认值 |
| --- | ---: |
| `RANK_WEIGHT_RELEVANCE` | 0.45 |
| `RANK_WEIGHT_CONSTRAINTS` | 0.23 |
| `RANK_WEIGHT_EVIDENCE` | 0.10 |
| `RANK_WEIGHT_AUTHORITY` | 0.08 |
| `RANK_WEIGHT_RECENCY` | 0.07 |
| `RANK_WEIGHT_SOURCE_CONSISTENCY` | 0.04 |
| `RANK_WEIGHT_OPENNESS` | 0.03 |
| `MMR_DUPLICATE_PENALTY` | 8 |

所有权重均截断到非负值。修改权重进行实验时，应记录 `--experiment`、随机种子、
代码提交和响应中的 `configHash`；不要用 holdout 集调参。

## 8. 配置排查

1. 访问 Python `/api/health`，确认 `ready=true`；
2. 检查 `security.proxyTokenConfigured` 和 CORS Origin；
3. 检查 `academicSources` 中两个数据源的 Key 与熔断状态；
4. 检查 LLM 模型和是否已配置；
5. 搜索返回 401 时核对两端代理令牌，返回 429 时查看 `Retry-After`；
6. 修改 `backend/.env` 后重启 Python；配置在进程启动时加载。

生产要求、密钥历史处理和发布步骤见 [`DEPLOYMENT.md`](DEPLOYMENT.md)。
