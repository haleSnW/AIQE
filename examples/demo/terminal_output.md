# AIQE Real Terminal Output

> 以下两份输出是 **真实执行捕获**（2026-08-21，AIQE v0.1.0，mock 后端，
> 全程离线）：一次 `quick_score.py`，一次 `regression_compare.py --degrade`。
> 逐字节来自实际运行的 stdout——没有编辑、没有模拟。
>
> The two blocks below are **verbatim captures of real runs** (2026-08-21,
> AIQE v0.1.0, mock backend, fully offline): one `quick_score.py`, one
> `regression_compare.py --degrade`. They are the unedited stdout of the
> actual scripts.

## Run 1 — `python examples/quick_score.py` (first run on a clean machine)

```text
报告已写入: /path/to/aiqe/examples/demo/AIQE-report.json

════════════════════════════════════════════════
  AIQE Evaluation Report
  AIQE v0.1.0 · 2026-08-21T12:35:39.314659+00:00
════════════════════════════════════════════════

  simple_chat          ██████████  1.00  ✓
  long_translation     ███████░░░  0.67  ✓
  json_output          ██████████  1.00  ✓
  coding_task          █████████░  0.90  ✓

  Summary: 4/4 passed
════════════════════════════════════════════════

通过 4/4 · 回归 0 个

（这是 mock 后端的演示分数；接入真实模型时替换为满足
 AIQE.protocol.Backend 的后端实例即可，流水线零改动。）
```

## Run 2 — `python examples/regression_compare.py --degrade` (shift-left closed loop)

Round 1 (healthy mock backend) — this report becomes the baseline:

```text
══ 第一轮跑分（正常 mock 后端）—— 本轮报告即基线 ══
报告已写入: /path/to/aiqe/examples/.regression-demo/baseline.json

════════════════════════════════════════════════
  AIQE Evaluation Report
  AIQE v0.1.0 · 2026-08-21T12:36:03.429037+00:00
════════════════════════════════════════════════

  simple_chat          ██████████  1.00  ✓
  long_translation     ███████░░░  0.67  ✓
  json_output          ██████████  1.00  ✓
  coding_task          █████████░  0.90  ✓

  Summary: 4/4 passed
════════════════════════════════════════════════

基线已写入: /path/to/aiqe/examples/.regression-demo/baseline.json
```

Round 2 (`--degrade` simulates a model version that got worse — responses
truncated) — AIQE detects the regression on every case:

```text
══ 第二轮跑分（--degrade：模拟换版后变差的模型）══
报告已写入: /path/to/aiqe/examples/.regression-demo/run2-report.json

════════════════════════════════════════════════
  AIQE Evaluation Report
  AIQE v0.1.0 · 2026-08-21T12:36:03.433700+00:00
════════════════════════════════════════════════

  simple_chat          █████░░░░░  0.50  ✓
  long_translation     ░░░░░░░░░░  0.00  ✗
  json_output          ░░░░░░░░░░  0.00  ✗
  coding_task          ██░░░░░░░░  0.17  ✗

  Summary: 1/4 passed · 4 regressions
════════════════════════════════════════════════


────────────────────────────────────────────────────────
  回归结论
────────────────────────────────────────────────────────
  case_id                 基线      当前    delta  状态
────────────────────────────────────────────────────────
  simple_chat           1.00    0.50    -0.50  regression
  long_translation      0.67    0.00    -0.67  regression
  json_output           1.00    0.00    -1.00  regression
  coding_task           0.90    0.17    -0.73  regression
────────────────────────────────────────────────────────
  决策建议：存在 regression——建议拒绝发布或回退到基线版本，
            并对照两个报告逐用例排查差异原因（关键词命中/长度/格式）。
────────────────────────────────────────────────────────
  提示：真实换模型评估时，把两轮 run_round() 的 backend 换成
        不同的真实后端（如 ollama 两个模型），此结论逻辑完全复用。
```

---

## Notes

- **Provenance**: captures taken on 2026-08-21 with AIQE v0.1.0, mock backend
  only, no network access. Reproduce with the commands in
  [`README.md`](README.md).
- **What differs between runs**: `generated_at` timestamps and absolute output
  paths (here shown as `/path/to/aiqe/...`). Scores, verdicts and bars are
  deterministic — the mock backend always produces the same responses.
- **What depends on prior runs**: on the first run there is no baseline, so
  every case's regression status is `new` (visible in
  [`sample_report.json`](sample_report.json)). Re-running against an existing
  baseline yields `degraded` with `delta 0.00` — that is threshold semantics,
  not a real regression.
