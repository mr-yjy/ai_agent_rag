# ScholarPilot 生产安全链路

## 1. 上线硬门槛

以下条件必须全部满足：

1. 在 DeepSeek 控制台撤销曾进入 Git 的旧 Key，并创建新 Key；
2. 在 OpenAlex 控制台撤销曾进入 Git 的旧 Key，并创建新 Key；
3. Python 与前端服务端使用同一个、每个环境独立的
   `BACKEND_PROXY_TOKEN`，长度至少 32 个字符；
4. `CORS_ALLOWED_ORIGINS` 只包含实际前端域名，不使用 `*`；
5. 当前工作树密钥扫描为零；
6. 如果要求“完整 Git 历史扫描为零”，完成历史重写、团队重新克隆和远端强推。

删除文件中的 Key 不能让已公开的 Key 恢复安全，必须先在提供商控制台撤销。

## 2. 唯一生产调用链

```text
浏览器
  -> 同源 /api/search
  -> 前端服务端读取 BACKEND_PROXY_TOKEN
  -> Authorization: Bearer <token>
  -> Python /api/search
  -> OpenAlex / Semantic Scholar / LLM
```

TypeScript 只保留 demo 排序，不再连接任何学术 live API。Python 上游失败时，
前端返回 HTTP 502，不回退 demo。

## 3. Python 环境变量

复制 `backend/.env.example` 为 `backend/.env`，至少填写：

```ini
BACKEND_PROXY_TOKEN=
CORS_ALLOWED_ORIGINS=https://your-frontend.example
LLM_API_KEY=
OPENALEX_API_KEY=
SEMANTIC_SCHOLAR_API_KEY=
```

建议通过密码管理器生成至少 32 字节的随机代理令牌。开发、测试和生产环境使用
不同令牌。

## 4. 前端服务端环境变量

前端运行时只需要：

```ini
PYTHON_BACKEND_URL=https://your-python-backend.example
BACKEND_PROXY_TOKEN=
```

`BACKEND_PROXY_TOKEN` 只能存在于服务端运行时环境，禁止使用 `NEXT_PUBLIC_` 或
在 Vite `define` 中内联。

## 5. 限流与并发

Python 后端同时应用：

- IP 固定窗口限流；
- 前端代理传入的匿名用户哈希限流；
- 全局非阻塞并发信号量。

相关环境变量：

```ini
RATE_LIMIT_REQUESTS=30
RATE_LIMIT_WINDOW_SECONDS=60
MAX_CONCURRENT_SEARCHES=4
```

单机内存限流适用于当前单实例 Python 服务。如果扩展到多个实例，应将限流状态
迁移到 Redis、Cloudflare Rate Limiting 或同类共享存储。

## 6. 健康检查

前端 `/api/health` 只代理 Python `/api/health`。响应包含：

- 真实 Python adapter 与版本；
- `ready`；
- LLM 模型和配置状态；
- OpenAlex、Semantic Scholar 的配置与熔断状态；
- 鉴权、CORS、限流和当前并发状态。

健康检查不会主动消耗第三方 API 配额。

## 7. 安全扫描

扫描当前跟踪文件：

```bash
npm run security:scan
```

扫描当前文件和完整 Git 历史：

```bash
npm run security:scan:history
```

扫描器只输出提交、路径和规则，不输出密钥内容。历史扫描仍有命中时，旧 Key
必须保持撤销状态。历史重写属于破坏性协作操作，需要先冻结推送、备份仓库并通知
所有协作者重新克隆。
