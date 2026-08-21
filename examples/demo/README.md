# AIQE Demo — What a Real Run Looks Like

> 这里没有模拟数字：以下报告与控制台输出来自 AIQE v0.1.0 在 mock 后端上的
> **真实执行**（确定性响应、零模型、零网络）。照下面的命令，任何人都能
> 在自己的机器上复现同一份结果。

**No simulated numbers here.** The report and terminal captures in this
directory were produced by *actually running* AIQE v0.1.0 on the built-in
deterministic mock backend — no model, no network, no fake benchmark data.
You can reproduce them on your own machine in under a minute.

| File | What it is |
|---|---|
| [`sample_report.json`](sample_report.json) | The real JSON report written by one run of `examples/quick_score.py` |
| [`terminal_output.md`](terminal_output.md) | The real terminal output of two runs: `quick_score.py` and `regression_compare.py --degrade` |

---

## How AIQE actually runs (one pipeline, five stages)

```
test cases → ExecutionRunner(Backend) → OutputJudge → RegressionAnalyzer → EvaluationReport
```

1. **用例集 / Test cases** — `src/AIQE/cases/test_cases.py`: 4 standard cases
   (chat / translation / JSON output / coding task), each with a prompt and
   expected keywords, length and format criteria.
2. **执行 / Execution** — `src/AIQE/runner.py` runs each case against a
   `Backend` through the Backend Protocol (`src/AIQE/protocol.py`). The demo
   uses `MockEvalBackend`, which returns deterministic responses — the same
   prompt always gets the same output.
3. **评分 / Scoring** — `src/AIQE/judge.py` scores each response with
   deterministic rules only: keyword hits, length checks, format validation.
   No LLM judge, no API calls — identical input always yields identical scores.
4. **回归 / Regression** — `src/AIQE/regression.py` compares the score against
   the historical baseline. First run → `status: "new"` (baseline established).
   A drop larger than **0.15** is flagged `regression` and blocks release.
5. **报告 / Report** — `src/AIQE/reporter.py` writes the JSON report and
   prints the console bar-chart summary.

## Reproduce it yourself

```bash
python3 -m venv .venv
.venv/bin/pip install -e . pytest

# Run 1 — quick score (writes a report, prints summary)
.venv/bin/python examples/quick_score.py

# Run 2 — regression closed loop (baseline → degraded model → regression verdict)
.venv/bin/python examples/regression_compare.py --degrade
```

The run takes seconds. The full test suite behind it: `pytest -q` (111 tests).

## Reading `sample_report.json`

Per case, the report records three layers:

- **`execution`** — the raw response, tokens generated, elapsed time,
  backend, `trace_id` and a `payload_hash` (integrity check: the same
  response always hashes to the same value).
- **`judge`** — the score (0–1), pass/fail, per-dimension breakdown
  (relevance / correctness / completeness / formatting / confidence),
  and the concrete `checks` + `metrics` the score came from
  (e.g. `keyword_hits: 2/3`).
- **`regression`** — the verdict against the baseline
  (`new` / `pass` / `degraded` / `regression`) with the delta.

Everything is deterministic and explainable — that is the point: the score is
not a vibe, it is a reproducible number you can put in CI.

## What the regression demo proves

`terminal_output.md` section 2 shows the shift-left closed loop:

1. Round 1 (healthy mock) runs 4/4 passing — this report becomes the baseline.
2. Round 2 simulates a model swap that went wrong (responses truncated).
3. All 4 cases drop below the 0.15 threshold → 4 `regression` verdicts →
   the framework's decision: **refuse release or roll back**.

That is the whole idea of AIQE: a quality regression is caught *before*
deployment, by a deterministic score, not by user complaints after release.

## Notes on what is environment-dependent

- `generated_at` timestamps and absolute output paths differ between runs —
  scores and verdicts do not (mock backend is deterministic).
- On a machine where AIQE baselines already exist in `~/.AIQE/results`,
  `regression.status` may read `degraded` (delta 0.00) instead of `new`.
- `"backend": "mlx"` in the report reflects the mock backend simulating the
  MLX evaluation path — see `src/AIQE/backends/mock.py`.

## Beyond the demo

- **Real models**: `examples/ollama_backend.py` plugs a local Ollama model
  into the same pipeline — the pipeline code is unchanged, only the backend.
- **Full framework**: methodology docs in `docs/methodology/`, templates in
  `templates/`, test suite in `tests/` (111 contract tests).
- **Your own backend**: implement `AIQE.protocol.Backend`
  (`generate_sync` / `generate` / `backend_type` / `profile`) and inject it.
