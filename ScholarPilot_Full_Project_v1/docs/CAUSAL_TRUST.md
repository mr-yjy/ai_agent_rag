# CausalTrust：When-to-Trust 可靠性校准

适用版本：v0.6.0 RC（Unreleased）

本模块把 `when to trust.md` 描述的 Ca2KG 思想迁移到 ScholarPilot，但不照搬知识
图谱部分。Knowledge Path 被替换为真实论文证据，KG Reasoning 被替换为科研
结论生成与推理。原有检索、过滤和排序逻辑保持不变。

## 1. 与旧反事实核验的区别

项目原有 `counterfactual.py` 只处理排序阈值附近的论文：改变一个查询约束，判断
论文相关性是否真正依赖该约束，并在必要时降低论文分数。

新增 `causal_trust.py` 位于检索和排序之后，校准的是“基于这些论文形成的结论是否
值得相信”。两者分别负责论文级排序核验和答案级可靠性校准，不能互相替代。

## 2. 运行流程

```text
Ranked real papers
        ↓
Evidence pool with stable paper IDs
        ↓
t0 baseline ─┬─ t1 evidence-quality intervention
             └─ t2 reasoning-reliability intervention
        ↓
Candidate canonicalization
        ↓
One Panel call, three independent perspectives
        ↓
Python normalization → CE / CEvar / CCI
        ↓
Reliability gate
        ├─ ACCEPT
        ├─ RETRY_RETRIEVAL
        ├─ RETRY_REASONING
        └─ ABSTAIN
```

t1 和 t2 只改变失败假设，不允许在干预生成阶段获取新证据。Panel 在一次 LLM
调用中分别输出 baseline、evidence quality 和 reasoning reliability 三个视角的
0–100 支持度；概率归一化和 CCI 数学计算全部由 Python 完成。

对于候选 `a`：

```text
CE(a)    = mean(score_t0, score_t1, score_t2)
CEvar(a) = max(score) - min(score)
CCI(a)   = CE(a) × (1 - CEvar(a))
```

默认可靠性门：

- CCI ≥ 0.75，且第一名领先第二名至少 0.15：`ACCEPT`；
- 0.50 ≤ CCI，或高分但候选间隔不足：诊断后执行一次恢复；
- CCI < 0.50：`ABSTAIN`。

若只有一个规范化候选，则无需候选间隔。阈值是工程初始值，不是论文规定值，必须
用冻结的开发集调参。

## 3. 故障诊断与恢复

系统比较 baseline 候选在三个 Panel 视角下的支持下降，并结合 t1/t2 是否改变核心
结论：

- evidence-quality 视角下降更大：`RETRY_RETRIEVAL`；
- reasoning-reliability 视角下降更大：`RETRY_REASONING`。

证据恢复最多使用剩余学术 API 预算中的 2 次调用，并把新论文只用于可靠性重新
校准；原始返回论文列表和排序不被恢复流程改写。若没有剩余 API 预算，则从已经
召回的候选池重新选择更宽的证据集合。推理恢复使用相同证据，以更严格的限定词、
实体、数字和证据到结论检查重新运行校准。恢复最多一次；仍未通过时拒答。

## 4. 响应与 Trace

`POST /api/search` 保留全部 v1.0 字段，并增加 `reliability`：

```json
{
  "reliability": {
    "status": "completed",
    "answer": "带必要限定条件的校准后结论",
    "confidence": 0.84,
    "decision": "ACCEPT",
    "diagnosis": {
      "evidenceRisk": 0.07,
      "reasoningRisk": 0.04,
      "recommendedRecovery": "NONE"
    },
    "candidates": [],
    "recovery": {
      "attempted": false,
      "mode": "NONE",
      "attempts": 0,
      "recovered": false
    },
    "trace": {}
  }
}
```

Trace 包含 query ID、证据 ID、每轮 t0/t1/t2 结构化输出、Panel 矩阵、CCI、选择
结果、决策与校准延迟；不复制 API Key，也不保存论文全文。前端显示校准结论、CCI、
证据风险、推理风险和候选摘要。

## 5. 失败安全与兼容性

- 没有个人 LLM Key、论文少于最小证据数或剩余预算不足时，返回
  `status=skipped`、`decision=NOT_RUN`；
- LLM JSON 不合法、校准调用失败或预算耗尽时，返回 `failed`/`skipped`；
- 所有上述情况都不改变原论文结果、状态和排序；
- 只在有足够预算时启动校准，仍受 50 秒 Python 总预算、取消信号和 55 秒 Web
  代理边界约束；
- 功能可整体关闭，也可分别关闭 t1、t2、Panel、CCI、稳定性惩罚和两类恢复，
  以支持消融实验。

## 6. 离线指标

`calibration_metrics.py` 提供 ECE、Brier Score、Accuracy-Coverage 曲线/AUC、
Retry Recovery Rate、Abstain Precision 和 Intervention Flip Rate。正式质量
声明必须基于已冻结、含答案正确性标签的开发/holdout 数据；当前论文检索评测集
尚未提供完整的结论正确性标签，因此不能据本模块单元测试声称校准质量提升。
