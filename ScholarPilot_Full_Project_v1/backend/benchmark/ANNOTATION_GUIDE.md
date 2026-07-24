# ScholarPilot v0.6 标注规范

当前 `evaluation_queries.json` 是流程回归数据，不是可信比赛验证集。任何 F1
结论必须先通过本规范的人工审计。

每条查询必须满足：

1. 至少一篇相关论文有可复现的 DOI、arXiv ID、OpenAlex ID 或 Semantic Scholar
   ID；本地昵称不能作为唯一标识。
2. `relevant_papers` 中的一项代表一篇论文，多个 ID 只作为同一实体的别名。
3. 论文年份、venue、方法和排除项不得与查询硬约束冲突。
4. `notes` 记录相关性依据和核验来源，不记录 API Key、令牌或受版权限制的全文。
5. 标注完成后由第二位复核者抽检；争议项进入难例集，不直接作为确定标签。
6. 数据固定为 `development` 与 `holdout` 两个 split。开发集可调参；配置冻结后，
   保留集只运行一次。

推荐记录格式：

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

冻结门槛：至少 30 条、至少 3 个学科、每条至少一篇可复现论文，数据审计中
`non_resolvable_identifier` 和 `year_constraint_conflict` 均为 0。
