# ScholarPilot 接入 DeepSeek V4 Pro

日期：2026-07-23

## 1. 官方参数核验

本次只依据 DeepSeek 官方文档接入：

- 快速开始：<https://api-docs.deepseek.com/zh-cn/>
- V4 发布公告：<https://api-docs.deepseek.com/zh-cn/news/news260424>
- 模型与价格：<https://api-docs.deepseek.com/zh-cn/quick_start/pricing>
- 思考模式：<https://api-docs.deepseek.com/zh-cn/guides/thinking_mode>
- JSON Output：<https://api-docs.deepseek.com/zh-cn/guides/json_mode>

截至 2026-07-23，官方信息如下：

| 项目 | 官方值 |
|---|---|
| OpenAI格式 Base URL | `https://api.deepseek.com` |
| 对话接口 | `POST /chat/completions` |
| 模型ID | `deepseek-v4-pro` |
| 发布状态 | 2026-04-24 发布的 DeepSeek-V4 预览版 |
| 上下文长度 | 1M |
| 最大输出 | 384K |
| JSON Output | 支持 |
| Tool Calls | 支持 |
| 思考模式 | 支持，官方默认开启 |
| 思考强度 | `high` 或 `max` |
| 并发限制 | 500 |

官方同时说明，`deepseek-chat` 与 `deepseek-reasoner` 将在北京时间
2026-07-24 23:59 弃用。因此项目不再使用 `deepseek-chat` 作为默认模型。

官方在该日期列出的 V4 Pro 价格（人民币/百万Token）：

- 输入缓存命中：0.025元；
- 输入缓存未命中：3元；
- 输出：6元。

价格会变化，正式提交前应重新核对官方页面。

## 2. 项目采用的默认策略

```ini
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro
LLM_THINKING_MODE=disabled
LLM_REASONING_EFFORT=high
LLM_JSON_MODE=true
LLM_TEMPERATURE=0
LLM_MAX_TOKENS=4096
LLM_TIMEOUT=60
```

虽然官方默认开启思考模式，ScholarPilot 默认显式关闭，原因是：

1. 查询解析、Selector和重排都需要短JSON，而不是长推理过程；
2. 非思考模式可以使用`temperature=0`，便于重复实验；
3. 减少输出Token和端到端延时，符合比赛20%的效率指标；
4. 反事实核验已有独立触发阈值，不需要所有候选都执行长推理。

这不是认定非思考模式一定更好。正式实验必须比较：

- V4 Pro非思考；
- V4 Pro思考`high`；
- V4 Pro思考`max`。

模型开启思考模式时，客户端会按官方要求：

- 发送`{"thinking":{"type":"enabled"}}`；
- 发送`reasoning_effort=high/max`；
- 不发送无效的`temperature`参数；
- 只使用最终`content`，不保存或展示`reasoning_content`。

## 3. 代码改动

### `backend/scholarpilot/config.py`

- 默认模型从`deepseek-chat`升级为`deepseek-v4-pro`；
- Base URL从`https://api.deepseek.com/v1`改为官方值；
- 自动加载被Git忽略的`backend/.env`；
- 同时接受`LLM_API_KEY`和官方名称`DEEPSEEK_API_KEY`；
- 新增思考模式、推理强度、JSON、超时和重试配置。

环境变量优先于`.env`，不会被本地文件覆盖。

### `backend/scholarpilot/llm_client.py`

- SDK和零依赖urllib路径都支持V4参数；
- 结构化任务自动发送`response_format={"type":"json_object"}`；
- 批量Selector和批量重排统一输出`{"items":[...]}`，并兼容读取旧数组格式；
- 思考模式开启时不再发送temperature；
- 只对408、425、429、5xx、超时和连接错误进行一次有界重试；
- API尝试次数独立于逻辑LLM调用次数统计；
- 错误消息清理Bearer Token、API Key和Token参数；
- 不把SDK失败再次交给urllib重发，避免双倍扣费。

### `backend/scholarpilot/service.py`

搜索响应新增安全模型元数据：

```json
{
  "model": {
    "configured": false,
    "model": "deepseek-v4-pro",
    "thinkingMode": "disabled",
    "reasoningEffort": "high",
    "jsonMode": true
  }
}
```

`configured`只表示是否存在密钥，不返回密钥内容。统计新增
`stats.llmRequestAttempts`。

### 服务健康接口

`GET /api/health`返回同样的安全模型元数据，方便检查后端是否加载了正确配置。

### 测试与模板

- 新增`backend/.env.example`；
- 新增V4默认配置测试；
- 新增思考/非思考请求载荷测试；
- 新增官方URL和JSON Output请求测试；
- 健康接口测试确保不会返回API Key。

## 4. 用户需要完成的唯一秘密配置

不要把API Key发送到聊天、代码或文档。

在本机复制：

```powershell
cd C:\Users\27555\Desktop\agent_rag\ai_agent_rag\ScholarPilot_Full_Project_v1\backend
Copy-Item .env.example .env
```

然后由用户本人编辑`backend/.env`：

```ini
LLM_API_KEY=这里填写DeepSeek平台生成的真实Key
```

`.gitignore`已经忽略`.env`和`.env.*`，但保留`.env.example`。

## 5. 配置验证

重启后访问：

```text
http://127.0.0.1:8001/api/health
```

预期：

```json
{
  "llm": {
    "configured": true,
    "model": "deepseek-v4-pro",
    "thinkingMode": "disabled",
    "reasoningEffort": "high",
    "jsonMode": true
  }
}
```

健康接口通过只证明配置被加载。还应执行一条实时搜索并确认：

- `stats.llmCalls > 0`；
- `stats.llmRequestAttempts >= stats.llmCalls`；
- `stats.tokenEstimate > 0`；
- 查询计划包含LLM解析出的结构化约束；
- 日志和响应中没有API Key。

## 6. 推荐消融

在相同候选快照和相同查询集上比较：

| 实验 | 思考模式 | 强度 | 目的 |
|---|---|---|---|
| V4-P0 | disabled | — | 效率基线 |
| V4-P1 | enabled | high | 判断一般推理是否提高F1 |
| V4-P2 | enabled | max | 判断最大推理是否值得额外成本 |

每组报告Macro F1@20、Recall@20、API调用、LLM调用、Token、P50/P95延时。
只有F1增益稳定且效率代价可接受时，才应把思考模式用于完整流水线。
