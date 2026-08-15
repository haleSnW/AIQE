# 测试报告生成（Report Generation）

> 报告是流程的「出口」：机器读 JSON、人读控制台摘要、团队读归档文档。
> 本文档解释报告链路、字段语义，并给出扩展 Markdown 报告的完整示例。

---

## 1. 报告链路

```
EvaluationReport（聚合）
   │
   ├─ to_json(path)   → JSON 文件（机器消费 / 基线复用 / 归档）
   ├─ print_summary() → 控制台条形图（人快速扫一眼）
   └─ 自定义扩展      → Markdown / 看板 / 邮件（团队消费，见第 3 节）
```

三段数据始终同源：`add_case()` 一次收集，三种输出各自渲染，字段不
重复维护。

## 2. 报告字段逐项解释

### 顶层

| 字段 | 含义 | 消费方 |
|---|---|---|
| `test_plan_id` | 本次跑分计划标识（如 `ollama-<模型名>`） | 归档检索 |
| `generated_at` | UTC 生成时间 | 归档排序 |
| `project` | 项目标识（本仓库为 `AIQE`） | 多项目数据区分 |
| `version` | 框架版本 | 数据可比性（不同版本报告谨慎互比） |
| `cases` | 用例明细数组（见下） | 主要消费方 |
| `summary` | 汇总（passed/total/regressions） | 门禁判定（见 process-management.md 五状态） |

### cases[] 内每个用例

| 字段 | 含义 | 怎么读 |
|---|---|---|
| `case_id` / `category` / `prompt` | 用例标识/类别/输入 | 溯源 |
| `execution.response` | 模型原始输出 | 回归排查时对比两份报告的原文 |
| `execution.tokens_generated` / `elapsed_sec` / `tok_per_sec` | 生成量/耗时/速度 | 性能数据（不做自动门禁，进报告人工看） |
| `execution.backend` / `model_id` | 后端与模型标识 | 跨模型对比 |
| `execution.error` | 执行错误（非 None 表示失败） | **error 非 None 时 score 无效**，按 NOT_ASSESSED 处理 |
| `execution.trace_id` / `payload_hash` | 追踪号 / 响应哈希 | 关联同一次执行、校验输出完整性 |
| `judge.score` / `passed` | 分数（0~1）/ 通过（≥0.5） | 核心指标 |
| `judge.breakdown` | 各维度上限（relevance/correctness/…） | 参考，不参与计算 |
| `judge.checks` | 各检查项布尔（empty_response/length_ok/keywords_match/format_ok） | 定位丢分原因 |
| `judge.reasons` | 中文可读原因列表 | 人工阅读 |
| `judge.metrics` | 数值指标（response_length/keyword_hits/format_score） | 量化分析 |
| `regression.status` / `delta` / `baseline_score` / `current_score` | 回归状态 / 差值 / 基线分 / 当前分 | 门禁判定（见 process-management.md） |

**读报告的顺序建议**：summary 扫全局 → regressions 列表看哪些用例退化 →
点开退化用例看 `judge.checks` 与 `judge.reasons` 定位丢分维度 →
对照 `execution.response` 看模型实际输出。

## 3. 自定义报告：Markdown 扩展示例

`EvaluationReport` 不内置 Markdown 输出（保持最小核心），但 `to_json()`
的返回串 + `_compute_summary()` 已给出全部数据，扩展渲染只需几行：

```python
# render_markdown.py —— 把 AIQE 报告渲染为 Markdown（可直接复制改造）
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

def render_markdown(report_json: dict) -> str:
    """把 to_json() 返回的 dict 渲染为五段式 Markdown（模板见
    templates/report-template.md）。"""
    s = report_json["summary"]
    lines = [
        f"# AIQE 评估报告：{report_json['test_plan_id']}",
        "",
        f"- 生成时间：{report_json['generated_at']}",
        f"- 项目：{report_json['project']} v{report_json['version']}",
        f"- 汇总：{s['passed']}/{s['total']} passed"
        + (f"，回归 {len(s['regressions'])} 个" if s["regressions"] else ""),
        "",
        "## 用例明细",
        "",
        "| 用例 | 分数 | 状态 | 回归 | 主要丢分原因 |",
        "|---|---|---|---|---|",
    ]
    for c in report_json["cases"]:
        j = c["judge"]
        r = c.get("regression", {})
        # 从 reasons 里挑出非「满分」的原因，便于快速定位
        bad = [x for x in j.get("reasons", []) if "满分" not in x and "命中" not in x]
        lines.append(
            f"| {c['case_id']} | {j['score']:.2f} | {'通过' if j['passed'] else '失败'} "
            f"| {r.get('status', '-')} ({r.get('delta', 0.0):+.2f}) "
            f"| {('；'.join(bad))[:60] or '-'} |"
        )
    if s["regressions"]:
        lines += ["", "## 回归结论", ""]
        lines += [f"- {cid} 出现回归" for cid in s["regressions"]]
    lines += ["", "## 决策建议", "",
              "- 按 process-management.md 第 3 节门禁规则判定后填写。"]
    return "\n".join(lines)


if __name__ == "__main__":
    # 用法：python render_markdown.py <报告.json>
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(render_markdown(data))
```

**扩展原则**：自定义渲染只**读** EvaluationReport 的输出（JSON），不
改框架代码；渲染逻辑放你自己的项目里，避免与上游框架漂移。

## 4. 报告质量检查清单

- [ ] 报告含 `execution` / `judge` / `regression` 三段完整字段
- [ ] error 非 None 的用例在摘要里明确标出（不能混入 passed 统计）
- [ ] 控制台摘要与 JSON 数据一致（同一数据源渲染）
- [ ] 归档命名含 模型/日期（如 `AIQE-report-<模型>-<日期>.json`）
- [ ] 含真实输入输出的报告不进 git，共享前按 test-data-management.md 脱敏
