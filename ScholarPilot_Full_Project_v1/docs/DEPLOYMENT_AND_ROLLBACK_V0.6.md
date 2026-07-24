# ScholarPilot v0.6 部署与回滚手册

## 当前状态

本文件定义可执行的发布流程，但不代表已经上线。当前 `.openai/hosting.json` 指向的
Sites 项目不可用，且尚无已确认的公网 Python 后端，因此 staging 和 production
均未完成。多实例生产部署还必须先选择 Redis 或平台级共享限流。

## 推荐拓扑

```text
Browser
  -> HTTPS frontend /api/search
  -> Bearer BACKEND_PROXY_TOKEN
  -> HTTPS Python backend
  -> DeepSeek / OpenAlex / Semantic Scholar
```

浏览器构建物不得包含代理令牌或第三方 Key。`BACKEND_PROXY_TOKEN` 只能存在于
前端服务端运行时和 Python 后端运行时。

## 环境变量

前端服务端：

```text
PYTHON_BACKEND_URL=https://python-staging.example
BACKEND_PROXY_TOKEN=<每个环境独立、至少32字节>
```

Python 后端：

```text
BACKEND_PROXY_TOKEN=<与对应前端相同>
CORS_ALLOWED_ORIGINS=https://frontend-staging.example
RATE_LIMIT_REQUESTS=30
RATE_LIMIT_WINDOW_SECONDS=60
MAX_CONCURRENT_SEARCHES=4
LLM_API_KEY=<secret>
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro
OPENALEX_API_KEY=<secret>
OPENALEX_MAILTO=<contact>
SEMANTIC_SCHOLAR_API_KEY=<secret-or-empty>
SEARCH_TIMEOUT_SECONDS=50
MAX_TOTAL_API_CALLS=10
```

完整非敏感默认值见根目录和 `backend/.env.example`。staging 与 production
必须使用不同的代理令牌及第三方 Key。

## 发布前门禁

1. 在服务商控制台确认历史泄露 Key 已撤销。
2. 经仓库所有者授权完成历史清理，并确认当前树与完整历史扫描均为 0。
3. 冻结开发集、保留集、配置哈希和版本提交；确认 F1/Recall/成本门槛通过。
4. 执行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\acceptance-v06.ps1
   ```

5. 报告必须为 `passed`；`dist/client` 中不得出现任何服务端凭据。

## Staging 部署与验收

1. 先部署单实例 Python 后端，注入 staging secrets。
2. 访问 Python `/api/health`，确认版本为 0.6.0、`ready=true`，且不显示 Key。
3. 部署前端服务端，配置 Python HTTPS URL 和 staging 代理令牌。
4. 将前端精确 Origin 写入 Python CORS 白名单。
5. 验证 401、CORS 拒绝、真实空结果、单源降级、全源 502、55 秒总超时和主动取消。
6. 执行 20 并发测试，确认唯一 requestId、指标隔离、429/Retry-After、活动并发归零。
7. 运行冻结开发集两次并保存 P50/P95、API、LLM、Token 和逐查询输出。

## Production 发布

1. 保存 staging 已通过的 Git 提交、构建版本、配置哈希和验收报告。
2. 使用全新的 production secrets，部署与 staging 相同的不可变版本。
3. 若使用多个 Python 实例，先接入 Redis/平台共享限流；否则保持单实例。
4. 执行 production health、401、CORS、live 成功、上游失败、20 并发和客户端
   构建物扫描。
5. 记录 production URL、部署版本、时间和操作者，不记录 secret 值。

## 回滚

回滚触发条件包括错误率、P95、401/CORS、demo/live 隔离、密钥扫描或指标隔离任一
门禁失效。

1. 停止继续发布和配置变更。
2. 将前端和 Python 同时切回上一个已验收的不可变版本；不要只回滚一侧的 Schema。
3. 恢复上一版本的非敏感配置快照。若疑似凭据泄露，立即轮换，不复用旧 secret。
4. 执行 health、未授权 401、后端不可达 502、当前树与客户端构建物扫描。
5. 保留故障版本的脱敏日志、requestId、配置哈希和验收报告用于复盘。
6. 若历史重写后有人推回旧分支，冻结推送并要求重新克隆，避免旧 Key 再进入历史。

