# 研索智航 ScholarPilot

面向复杂科研问题的论文搜索与推荐系统。系统把自然语言查询转换为结构化约束，
通过 OpenAlex 与 Semantic Scholar 检索论文，并在统一时间和调用预算内完成过滤、
排序、证据说明与结果展示。

当前版本：**v0.6.0 Release Candidate**。代码功能已经完成本地自动化验证，但评测
数据、Git 历史凭据清理和 staging/production 验收尚未满足正式发布条件。

项目代码位于 [`ScholarPilot_Full_Project_v1/`](ScholarPilot_Full_Project_v1/)。
本文件是仓库唯一的 README；其余说明按主题放在项目的 `docs/` 目录。

## 当前能力

- LLM 查询分析失败时可回退到规则规划器；
- 最多 3 条初始子查询，OpenAlex 与 Semantic Scholar 双源并行召回；
- DOI、学术图谱 ID 与规范化标题融合，记录来源和检索路线；
- 预算允许时执行引文扩展、后续检索、Top-32 Selector、Top-12 LLM 精排和最多
  4 篇边界候选的反事实核验；
- 50 秒 Python 请求总预算、55 秒前端代理边界、取消传播、有界重试和预算感知早停；
- 透明排序、证据质量、来源一致性、MMR 去重惩罚、关系图、聚类、时间线和 CSV 导出；
- v1.0 查询、成功响应和错误响应 Schema，以及请求级调用、Token、阶段耗时和配置哈希；
- 所有论文结果均来自真实学术数据源；上游失败时返回结构化错误。

系统的真实数据流和降级语义见
[`ARCHITECTURE.md`](ScholarPilot_Full_Project_v1/docs/ARCHITECTURE.md)。

## 快速开始

要求 Node.js 22.13 或更高版本、Python 3.10 或更高版本。

安装前端依赖并复制环境变量模板：

```powershell
cd ScholarPilot_Full_Project_v1
npm install
Copy-Item .env.example .env.local
Copy-Item backend\.env.example backend\.env
```

在两份文件中填写**相同且不少于 32 字节**的 `BACKEND_PROXY_TOKEN`。在
`backend/.env` 中配置 `LLM_API_KEY`、`OPENALEX_API_KEY`；Semantic Scholar Key
可选但建议配置。真实凭据不得提交到 Git。

终端一：

```powershell
cd ScholarPilot_Full_Project_v1\backend
python run.py
```

终端二：

```powershell
cd ScholarPilot_Full_Project_v1
npx.cmd vite
```

默认地址：

- Web：<http://127.0.0.1:5173>
- Python 健康检查：<http://127.0.0.1:8000/api/health>
- Web 健康检查：<http://127.0.0.1:5173/api/health>

如需 FastAPI 适配器：

```powershell
cd ScholarPilot_Full_Project_v1\backend
python -m pip install -r requirements-fastapi.txt
python -m uvicorn scholarpilot.fastapi_app:app --host 127.0.0.1 --port 8000
```

完整变量说明见
[`CONFIGURATION.md`](ScholarPilot_Full_Project_v1/docs/CONFIGURATION.md)。

## API

浏览器只调用同源的 `POST /api/search`。请求体：

```json
{
  "query": "寻找 2024 年以后使用引文扩展的学术检索智能体论文",
  "limit": 10
}
```

`query` 长度为 6–800 个字符，`limit` 为 1–50。接口只执行真实学术检索，
不接受模式切换字段。
成功响应状态为 `success`、`degraded` 或 `no_results`；失败使用结构化
`error` 对象并携带 `requestId`。

机器可读契约位于
[`docs/schemas/`](ScholarPilot_Full_Project_v1/docs/schemas/)。

## 验证

在项目目录运行本地验收：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\acceptance-v06.ps1
```

脚本依次执行 Python 测试、TypeScript、ESLint、生产构建、渲染/API 测试、当前
代码树与客户端构建物密钥扫描，并默认扫描完整 Git 历史。报告写入
`outputs/acceptance/acceptance-v06.json`。

评测数据尚未冻结，不能据此声称正式 F1。先运行不访问外部 API 的数据审计：

```powershell
cd backend
python run_evaluation.py --validate-only
```

修复并冻结数据后，`python run_evaluation.py` 使用真实学术数据源执行评测。

评测边界和冻结规范见
[`EVALUATION.md`](ScholarPilot_Full_Project_v1/docs/EVALUATION.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [`ARCHITECTURE.md`](ScholarPilot_Full_Project_v1/docs/ARCHITECTURE.md) | 当前架构、搜索流程、API 和降级语义 |
| [`CONFIGURATION.md`](ScholarPilot_Full_Project_v1/docs/CONFIGURATION.md) | 前后端环境变量和搜索参数 |
| [`DEPLOYMENT.md`](ScholarPilot_Full_Project_v1/docs/DEPLOYMENT.md) | 安全、验收、部署和回滚 |
| [`EVALUATION.md`](ScholarPilot_Full_Project_v1/docs/EVALUATION.md) | 数据标注、指标、实验与可信度边界 |
| [`ROADMAP.md`](ScholarPilot_Full_Project_v1/docs/ROADMAP.md) | 尚未完成的发布门禁和后续工作 |
| [`CHANGELOG.md`](ScholarPilot_Full_Project_v1/CHANGELOG.md) | 版本变更记录 |

判断当前行为时，以源码、测试和上述主题文档为准；历史版本细节只保留在
`CHANGELOG.md`，不再维护 v0.3/v0.4 的独立说明。

## 主要目录

```text
ScholarPilot_Full_Project_v1/
├── app/                     Web 页面、组件和同源 API 路由
├── backend/
│   ├── scholarpilot/        Python 搜索、排序、评测与安全实现
│   ├── benchmark/           数据集 manifest
│   └── tests/               Python 自动化测试
├── docs/                    当前主题文档和 JSON Schema
├── scripts/                 构建、验收和密钥扫描脚本
├── tests/                   前端渲染/API 测试
└── CHANGELOG.md             唯一版本流水
```

## 正式发布前仍需完成

- 撤销曾进入 Git 历史的旧第三方 Key，并经授权清理历史记录；
- 人工修复评测集警告，冻结 development/holdout 数据并完成可信消融；
- 部署可用的 staging Python 与 Web 服务，验证 live 延迟、故障矩阵和 20 并发；
- 全部门禁通过后再将 v0.6.0 RC 标记为正式版本。

详见 [`ROADMAP.md`](ScholarPilot_Full_Project_v1/docs/ROADMAP.md)。
