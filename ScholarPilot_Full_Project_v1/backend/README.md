# ScholarPilot Python 后端

这是“研索智航”可独立运行、可修改、可测试的 Python 后端。核心实现只
使用 Python 标准库，因此不需要安装第三方包即可启动。

## 1. 环境

- Python 3.11 或更高版本；
- 实时检索需要能够访问 OpenAlex；
- OpenAlex API Key 可选，内置演示模式完全不需要网络。

## 2. 零依赖启动

进入 `backend` 目录：

```bash
python run.py
```

默认地址：

```text
http://127.0.0.1:8000
```

指定监听地址和端口：

```bash
python run.py --host 0.0.0.0 --port 8000
```

## 3. FastAPI 方式

如果希望获得 Swagger 接口文档：

```bash
python -m venv .venv
```

Windows：

```bash
.venv\Scripts\activate
pip install -r requirements-fastapi.txt
uvicorn scholarpilot.fastapi_app:app --reload --port 8000
```

Linux/macOS：

```bash
source .venv/bin/activate
pip install -r requirements-fastapi.txt
uvicorn scholarpilot.fastapi_app:app --reload --port 8000
```

Swagger：

```text
http://127.0.0.1:8000/docs
```

## 4. 接口

### 健康检查

```http
GET /api/health
```

### 论文搜索

```http
POST /api/search
Content-Type: application/json
```

请求：

```json
{
  "query": "寻找2024—2026年使用查询分解进行学术检索的LLM Agent论文",
  "mode": "demo",
  "limit": 10
}
```

`mode`：

- `demo`：使用内置数据，结果稳定，不需要网络；
- `live`：调用 OpenAlex；失败时会明确降级到演示数据。

命令行测试：

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"寻找2024年以后使用查询分解进行学术检索的LLM Agent论文\",\"mode\":\"demo\",\"limit\":5}"
```

## 5. OpenAlex API Key

复制示例配置：

```bash
cp .env.example .env
```

运行前配置环境变量，不要把 Key 写入源码。

Windows PowerShell：

```powershell
$env:OPENALEX_API_KEY="your_key"
python run.py
```

Linux/macOS：

```bash
export OPENALEX_API_KEY="your_key"
python run.py
```

## 6. 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖：

- 查询年份、方法、偏好和排除条件解析；
- 排序结果、分数和证据；
- 实际启动本地 HTTP 服务；
- `/api/health`；
- `POST /api/search`。

## 7. 源码结构

```text
backend/
├── run.py
├── requirements-fastapi.txt
├── scholarpilot/
│   ├── models.py       数据模型和 API 序列化
│   ├── planner.py      查询规范化、约束和子查询
│   ├── providers.py    演示数据与 OpenAlex
│   ├── ranking.py      五维打分、证据、MMR 去重
│   ├── service.py      完整搜索编排和降级
│   ├── server.py       零依赖 HTTP API
│   ├── fastapi_app.py  FastAPI 适配入口
│   └── data/
│       └── demo_papers.json
└── tests/
```

## 8. 前端连接

当前网页内置 `/api/search`。如果要让网页改用 Python 后端，可将前端
请求从：

```typescript
fetch("/api/search", ...)
```

改为：

```typescript
fetch("http://127.0.0.1:8000/api/search", ...)
```

生产环境中应通过反向代理保持同域名，例如将 `/api/*` 转发到 Python
服务，避免写死地址。

## 9. 下一步修改顺序

1. 建立 30 条人工标注查询；
2. 实现 Precision、Recall、F1 离线评测；
3. 增加 Embedding 召回，保留当前算法作为 Baseline；
4. 增加 Cross-Encoder 精排；
5. 增加引文扩展和预算停止；
6. 增加反事实证据核验。

