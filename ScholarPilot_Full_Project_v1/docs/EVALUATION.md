# ScholarPilot 评测与标注

适用版本：v0.6.0 RC

当前结论：评测工具可运行，现有数据只能用于流程回归，不能证明正式 F1。

## 1. 当前数据状态

默认数据：
`backend/scholarpilot/data/evaluation_queries.json`

对应 manifest：
`backend/benchmark/dataset-manifest-v0.6.json`

截至 2026-07-25：

- 查询数：35；
- 覆盖 5 个学科；
- manifest 状态：`annotation_required`；
- development 与 holdout 均未冻结；
- 审计结果：0 error、58 warning、8 info；
- demo 回归 Macro F1：0.1061。

0 error 只表示文件可被评测程序读取。58 个 warning 包含不可复现标识符和年份约束
冲突，因此该 F1 只能证明流程可运行，不能用于声称算法质量、比赛效果或 v0.6 提升。
demo 的毫秒级延迟也不能替代真实网络条件下的 live 延迟。

## 2. 可复现论文实体

每个相关论文实体必须至少有一个可公开复现的标识：

- DOI；
- arXiv ID；
- OpenAlex ID；
- Semantic Scholar Paper ID。

本地昵称（例如 `pasa-2025`）不能作为唯一标识。同一论文的多个 ID 是别名，不能
计为多篇 ground truth。标题只用于辅助核验，不能代替稳定 ID。

当前加载器兼容旧字段：

```json
{
  "id": "q001",
  "query": "复杂科研查询",
  "discipline": "computer_science",
  "relevant_paper_ids": ["doi:10.xxxx/xxxx", "openalex:W123"],
  "relevant_titles": ["Canonical paper title"],
  "notes": "标注依据"
}
```

冻结数据应迁移到实体分组格式：

```json
{
  "id": "q001",
  "query": "复杂科研查询",
  "discipline": "computer_science",
  "split": "development",
  "relevant_papers": [
    {
      "ids": ["doi:10.xxxx/xxxx", "openalex:W123"],
      "titles": ["Canonical paper title"]
    }
  ],
  "notes": "标题、摘要或元数据中的可复核标注依据"
}
```

## 3. 标注规范

每条查询必须满足：

1. 至少一篇相关论文有可复现 ID；
2. `relevant_papers` 的一项只代表一篇论文，别名放在同一 `ids` 数组；
3. 论文年份、venue、方法和排除项不得与查询硬约束冲突；
4. `notes` 记录相关性依据与核验来源，不记录 API Key、令牌或受版权限制的全文；
5. 一位标注者完成后，由第二位复核者抽检；
6. 争议项进入难例集，不直接作为确定标签；
7. 数据分为 `development` 和 `holdout`；开发集可调参，配置冻结后 holdout 只运行
   一次；
8. 数据或标签发生变化时更新 manifest 版本、状态和变更说明。

冻结门槛：

- 至少 30 条查询；
- 至少 3 个学科；
- 每条至少一篇可复现论文；
- `non_resolvable_identifier` 为 0；
- `year_constraint_conflict` 为 0；
- development/holdout 划分已写入数据并在 manifest 标记为 frozen。

## 4. 运行数据审计

```powershell
cd backend
python run_evaluation.py --validate-only
```

审计检查别名、标识符、标题、年份约束、重复实体与 split。只要仍有发布阻塞类
warning，就不能冻结 manifest。

## 5. 运行评测

Demo 回归：

```powershell
cd backend
python run_evaluation.py --mode demo `
  --experiment v06-demo-regression `
  --json-output ..\outputs\evaluation\v06-demo-regression.json
```

冻结 development 集上的 live 实验：

```powershell
cd backend
python run_evaluation.py --mode live `
  --split development `
  --limit 20 `
  --seed 20260724 `
  --experiment v06-live-default `
  --json-output ..\outputs\evaluation\v06-live-default.json
```

可用 `--data` 指定数据文件，`--export` 同时导出 CSV，`--verbose` 显示逐查询结果。
未指定 `--json-output` 时，报告写入项目 `outputs/evaluation/`。

## 6. 指标与输出

评测器输出：

- Precision@10、Precision@20；
- Recall@20、Recall@50；
- F1@20；
- Macro/Micro Precision、Recall、F1；
- 按学科分项指标；
- P50/P95 延迟；
- API/LLM 调用、请求尝试、Token 和失败分类；
- 逐查询预测、命中实体和错误；
- 模型版本、随机种子、实验名、配置快照和 `configHash`。

基本定义：

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 × Precision × Recall / (Precision + Recall)
```

匹配在论文实体层完成：DOI、OpenAlex、Semantic Scholar、arXiv 和规范化标题别名
折叠后再计算，避免同一论文因跨源 ID 不同被重复计数。

## 7. 可信实验协议

1. 先修复并冻结数据，不在同一轮同时改标签和算法；
2. 记录 Git 提交、模型、环境、搜索参数、排序权重、随机种子与 `configHash`；
3. 对相同开发集、配置和缓存状态至少运行两次；
4. 消融时一次只改变一个模块或一组明确参数；
5. 报告失败、空结果和降级请求，不能只统计成功样本；
6. live 报告保存最慢查询、阶段耗时、P50/P95、API/Token 和上游状态；
7. holdout 只在配置冻结后运行一次，不用其结果继续调参；
8. 不把 OpenAlex 返回条数当作 Recall，不允许生成或补写不存在的 DOI、作者和标题。

v0.6 正式验收还需要可信 live P50 ≤ 20 秒、P95 ≤ 45 秒，以及冻结集上的质量与
成本对比。达到时间门槛不能替代 F1/Recall 证明，反之亦然。
