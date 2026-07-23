# 研索智航 ScholarPilot

面向“科研场景下复杂学术查询的智能论文搜索与推荐”赛题的可运行
MVP。它把自然语言科研问题转为结构化约束和多个子查询，再完成候选
论文召回、去重、透明排序、证据提取和运行成本统计。

## 当前版本能做什么

- 输入中文或英文的复杂科研检索问题；
- 识别年份、主题、方法、偏好和排除条件；
- 自动生成不超过 3 条并行英文子查询；
- 使用内置学术数据完成稳定演示；
- 通过服务端调用 OpenAlex 获取真实论文元数据；
- 按相关性、约束、被引、时效和开放获取进行透明排序；
- 为每篇论文提供命中证据和评分明细；
- 记录候选数、API 调用数、估算 Token 和端到端延迟；
- 实时接口失败时自动降级到内置数据。

## 当前版本没有假装实现什么

以下能力已经进入总体设计，但尚未进入 MVP 代码：

- 向量 Embedding 召回；
- Cross-Encoder 精排；
- 引文网络的第二轮迭代搜索；
- 反事实约束核验；
- 基于收益的自适应停止；
- 有人工标注的 F1 自动评测；
- 大模型结构化查询规划。

这些内容是后续迭代任务，而不是当前 Demo 的虚假宣传。

## 本地运行

要求 Node.js 22.13 或更高版本。

```bash
npm ci
npm run dev
```

启动后打开终端提示的本地地址。

## 可选环境变量

复制 `.env.example` 为 `.env.local`：

```bash
cp .env.example .env.local
```

然后填入免费的 OpenAlex API Key：

```text
OPENALEX_API_KEY=your_key_here
```

没有 Key 也可以使用内置演示模式；OpenAlex 是否允许匿名调用取决于其
当前 API 策略和额度。

## 验证

```bash
npm run lint
npm test
```

`npm test` 会先执行生产构建，再验证生成的 Worker 能返回有效页面。

## 主要目录

```text
app/
  api/search/route.ts       搜索 API
  lib/search.ts             查询规划、OpenAlex 映射、排序
  lib/demo-data.ts          稳定演示数据
  lib/types.ts              核心数据结构
  page.tsx                  交互页面
  globals.css               产品视觉系统
docs/
  项目设计文档.md            完整工程设计与接口
  参赛项目计划书.md          时间表、里程碑与交付
  PROJECT_PLAN.md           技术方案
  NEXT_STEPS.md             后续 Codex 迭代清单
backend/
  README.md                 Python 后端运行教程
  run.py                    零依赖启动入口
  scholarpilot/             查询、Provider、排序、服务
  tests/                    Python 单元和接口测试
```

## 独立 Python 后端

```bash
cd backend
python run.py
```

无需安装第三方包即可启动。需要 FastAPI 和 Swagger 时，请参考
`backend/README.md`。

## 迭代原则

每增加一个“创新模块”，都必须保留关闭该模块的开关，并在同一验证集上
进行消融实验。只有同时满足以下条件，模块才应进入比赛主分支：

1. F1 或 Precision/Recall 中至少一项有可重复提升；
2. 对延迟、API 调用和 Token 的增加可解释；
3. 在不同学科查询上没有明显退化；
4. 结果可以通过日志和固定随机种子复现。
