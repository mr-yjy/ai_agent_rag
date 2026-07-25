# ScholarPilot 安全、部署与回滚

适用版本：v0.6.0 RC

当前状态：流程已定义，本地自动化已通过；staging 与 production 尚未完成验收。

## 1. 生产拓扑

```text
Browser
  -> HTTPS Web /api/search
  -> Authorization: Bearer BACKEND_PROXY_TOKEN
  -> HTTPS Python /api/search
  -> DeepSeek-compatible LLM / OpenAlex / Semantic Scholar
```

浏览器构建物不得包含 `BACKEND_PROXY_TOKEN` 或第三方 Key。TypeScript 路由只
代理 Python，不直接调用学术 API，也不维护本地论文结果源。

## 2. 发布硬门槛

以下条件必须全部满足后才能把 v0.6.0 RC 标记为正式版本：

1. 在服务商控制台撤销任何曾进入 Git 历史的 DeepSeek/OpenAlex Key；
2. 经仓库所有者授权后清理完整历史，并通知协作者重新克隆；
3. 当前跟踪树、完整 Git 历史与 `dist/client` 密钥扫描均为 0 命中；
4. 人工核验并冻结 development/holdout 评测集，质量和效率门槛通过；
5. staging 完成鉴权、CORS、故障、超时、取消、20 并发和真实检索复现验收；
6. production 使用 staging 已验收的同一不可变版本和独立 secrets；
7. 多 Python 实例已接入 Redis 或平台级共享限流，否则保持单实例。

当前已知阻塞见 [`ROADMAP.md`](ROADMAP.md)。删除工作树中的 Key 不能让已经暴露的
Key 恢复安全，撤销/轮换必须先在提供商控制台完成。

## 3. 环境隔离

每个环境使用独立的：

- `BACKEND_PROXY_TOKEN`，建议由密码管理器生成至少 32 字节随机值；
- LLM、OpenAlex 与 Semantic Scholar Key；
- 精确的 `CORS_ALLOWED_ORIGINS`；
- 配置快照、验收报告和部署记录。

Web 只需要：

```ini
PYTHON_BACKEND_URL=https://python.example
BACKEND_PROXY_TOKEN=<environment-specific-secret>
```

Python 至少需要：

```ini
BACKEND_PROXY_TOKEN=<与对应Web相同>
CORS_ALLOWED_ORIGINS=https://web.example
# 不配置服务端 LLM Key；用户在网页设置中提供个人 Key
OPENALEX_API_KEY=<secret>
SEMANTIC_SCHOLAR_API_KEY=<secret-or-empty>
```

完整变量见 [`CONFIGURATION.md`](CONFIGURATION.md)。不要使用通配 CORS，不要把服务端
变量命名为 `NEXT_PUBLIC_*`。

## 4. Python 运行方式

标准库适配器：

```powershell
cd backend
python run.py --host 127.0.0.1 --port 8000
```

FastAPI 适配器：

```powershell
cd backend
python -m pip install -r requirements-fastapi.txt
python -m uvicorn scholarpilot.fastapi_app:app --host 0.0.0.0 --port 8000
```

生产环境应由平台进程管理器启动，使用 HTTPS 入口，收集脱敏日志并设置健康探针
`GET /api/health`。健康返回 `ready=true` 才能接收搜索流量。

## 5. 本地发布验收

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\acceptance-v06.ps1
```

验收包含：

1. Python 单元与接口测试；
2. TypeScript 类型检查；
3. ESLint；
4. Vite 生产构建；
5. 渲染/API 测试；
6. 当前跟踪树密钥扫描；
7. `dist/client` 密钥扫描；
8. 完整 Git 历史密钥扫描。

机器报告写入 `outputs/acceptance/acceptance-v06.json`。只有报告为 `passed` 才能
进入 staging。`-SkipHistoryScan` 只适合临时诊断，不能作为发布报告。

可单独运行：

```powershell
npm run security:scan
npm run security:scan:history
node scripts\scan-secrets.mjs --artifact dist\client
```

扫描器只输出规则、提交和路径，不输出凭据内容。

## 6. Staging

1. 部署单实例 Python，注入 staging secrets；
2. 访问 Python `/api/health`，确认版本 `0.6.0`、`ready=true`、活动并发为 0，
   且响应不含 secret；
3. 部署 Web，配置 Python HTTPS URL 和相同代理令牌；
4. 将 Web 的精确 Origin 写入 Python CORS 白名单；
5. 验证成功、降级和真实空结果响应 Schema；
6. 验证无令牌 401、错误 Origin 拒绝、用户/并发 429 与 `Retry-After`；
7. 验证真实空集合、单源降级、全源 502、Python 不可达、55 秒代理超时和主动取消；
8. 运行 20 个 HTTP 并发请求，确认 `requestId` 唯一、指标隔离、请求结束后活动并发
   归零；
9. 对冻结 development 集以相同配置、缓存状态和种子运行两次，保存 P50/P95、
   API/LLM/Token、最慢阶段和逐查询结果；
10. 执行浏览器视觉验收：成功、空结果、降级、超时、限流和后端未就绪。

## 7. Production

1. 固定 staging 已通过的 Git 提交、构建版本、配置哈希和验收报告；
2. 使用全新的 production secrets 部署相同不可变版本；
3. 若扩展到多个 Python 实例，先启用共享限流；否则保持单实例；
4. 重跑 health、401、CORS、真实检索成功、单/全源失败、20 并发和客户端构建物扫描；
5. 记录部署 URL、版本、时间和操作者，不记录 secret 值；
6. 观察错误率、P95、429、上游降级率和活动并发，再逐步放量。

## 8. 回滚

以下任一情况触发回滚：错误率或 P95 超标、401/CORS 异常、结果来源不可追踪、
密钥扫描失败、Schema 不兼容、指标串请求或并发无法归零。

1. 停止放量和配置变更；
2. Web 与 Python 同时切回上一个已验收的不可变版本，避免只回滚一侧导致 Schema
   不兼容；
3. 恢复上一版非敏感配置快照；
4. 如疑似凭据泄露，立即轮换，不复用旧 secret；
5. 重跑 health、未授权 401、后端不可达 502、当前树和客户端构建物扫描；
6. 保存脱敏日志、`requestId`、配置哈希和验收报告用于复盘；
7. 若历史清理后有人推回旧分支，冻结推送并要求重新克隆。
