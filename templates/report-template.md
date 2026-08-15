# AIQE 评估报告：<test_plan_id>

> 本模板为五段式标准报告。占位符 `<...>` 在生成时替换；「生成方式」标注
> 每段数据来源（见 docs/methodology/report-generation.md）。
> 报告里不得留空占位符——留空的段落要么填写，要么删除并注明原因。

## 一、执行摘要

- 生成时间：`<generated_at>`（生成方式：报告 JSON 顶层字段）
- 项目 / 版本：`<project>` / `<version>`
- 后端 / 模型：`<backend>` / `<model_id>`
- 汇总：**`<passed>`/`<total>` passed**，回归 `<regression_count>` 个
- 未评估（NOT_ASSESSED）：`<not_assessed_list 或 无>`（error / gated 未跑
  的用例必须在此列出——跳过 ≠ 通过）
- 结论：`<PASS / WARN / FAIL / MANUAL_REVIEW / NOT_ASSESSED>`
  （判定规则见 docs/methodology/process-management.md 第 3 节）

## 二、用例明细表

| 用例 | 类别 | 分数 | 通过 | 回归状态 (delta) | 主要丢分原因 |
|---|---|---|---|---|---|
| `<case_id>` | `<category>` | `<score>` | `<通过/失败>` | `<status> (+delta)` | `<judge.reasons 摘要>` |
| ... | | | | | |

（生成方式：报告 JSON `cases[]` 的 `judge.score / passed / reasons` 与
`regression.status / delta`。）

## 三、回归结论

- `<case_id>`：基线 `<baseline_score>` → 当前 `<current_score>`，
  delta `<+delta>`，状态 `<status>`
- 排查指引：打开 `execution.response` 对比两份报告的原文；对照
  `judge.checks`（empty_response / length_ok / keywords_match /
  format_ok）定位丢分维度。
- 结论：`<本次变更是否引入回归的结论>`

## 四、性能数据

| 用例 | tokens | 耗时 (s) | tok/s |
|---|---|---|---|
| `<case_id>` | `<tokens_generated>` | `<elapsed_sec>` | `<tok_per_sec>` |

（生成方式：报告 JSON `execution` 段。说明：本地推理 tok/s 波动大，
性能数据只做人工参考，不做自动门禁。）

## 五、决策建议

- 门禁判定：`<PASS 可发布 / WARN 观察期发布+抽检 / FAIL 禁止发布 /
  MANUAL_REVIEW 回填结论 / NOT_ASSESSED 补跑>`
- 理由：`<一句话理由，引用关键用例与状态>`
- 后续动作：`<更新基线 / 修复重跑 / 人工抽检项 / 下一轮复查点>`
- 审查人 / 日期：`<reviewer> / <date>`

---

## 附：占位符速查（生成时删除本节）

| 占位符 | 数据来源 |
|---|---|
| `<test_plan_id>` `<generated_at>` `<project>` `<version>` | 报告 JSON 顶层 |
| `<backend>` `<model_id>` | `execution.backend / model_id`（首个用例） |
| `<passed>` `<total>` `<regression_count>` | `summary` |
| `<not_assessed_list>` | `execution.error` 非空的用例 id |
| `<case_id>` `<category>` `<score>` `<status>` `<delta>` | `cases[]` |
| `<baseline_score>` `<current_score>` | `regression` 段 |
| `<tokens_generated>` `<elapsed_sec>` `<tok_per_sec>` | `execution` 段 |
| `<reviewer>` `<date>` | 人工填写 |
