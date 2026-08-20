[简体中文](INTEGRATION.md) | [English](INTEGRATION.en.md)

# Using in Sync with Your Development Harness (INTEGRATION)

> The three things for wiring AIQE into your existing project: how to lay out the directories, how to hook up CI, and how to manage baselines.
> Plus the sync mode with the development harness and a complete "five-step model-swap evaluation flow".

---

## 1. Sync Mode with the Development Harness

AIQE is positioned as quality evaluation used **in sync with the development flow**: scoring is not a one-off audit before release, but a layer of quality signal that the development harness (build/CI/local development scripts) automatically carries at every stage.

```
Development harness (every build / every change)
        │
        ├─ Code-level regression: pytest (asserts "the code is not broken")
        └─ Model-level regression: AIQE scoring (asserts "model/product behavior has not degraded")
              │
              ├─ Case set → execute → deterministic scoring
              ├─ Compare against baseline → regression verdict (new/pass/degraded/regression)
              └─ Result as a quality-gate signal:
                   · Gate mode: block on regression (suited to deterministic mock / stable backends)
                   · Report mode: verdict goes into the report artifact for human judgment (suited to flaky real-device environments)
```

Key implementation points:

- **Trigger points**: run the relevant cases on every code change (decision per the decision table in section 3 of `docs/methodology/testing-layers.md`), and run the full case set on every model/config change.
- **Signal form**: scores and regression results serve as quality-gate signals — either hard blocking (CI fails on regression) or soft notification (into the report for human judgment). The latter is the default recommendation; real-device results fluctuate a lot, and a hard gate easily becomes noise.
- **Division of labor with pytest**: pytest manages the code and AIQE manages model behavior; the two coexist in the same harness (see the directory conventions in section 2).

---

## 2. Directory Conventions for Coexisting with pytest

AIQE is not a replacement for pytest; each covers its own part:

| Layer | Tool | What it covers | When it runs |
|---|---|---|---|
| Code-level regression | pytest | Unit/branch/contract/integration tests, asserting "the code is not broken" | Every commit, every CI run |
| Model-level regression | AIQE scoring | Case set + deterministic scoring + baseline comparison, asserting "the model has not degraded" | Model swap / prompt tuning / before release |

**Directory conventions** (this repository is the example):

```
src/AIQE/          # Framework product code
tests/             # pytest contract tests (testpaths=["tests"], examples are not collected)
examples/          # Runnable scripts: quick_score / ollama_backend / regression_compare
docs/              # Methodology docs (testing-layers.md, this file)
```

- `examples/` is outside pytest's collection scope (`testpaths = ["tests"]` in `pyproject.toml`); it holds "smoke scripts executable by humans/CI", not unit tests.
- Your project's existing pytest test directory needs no modification at all: AIQE runs in **script mode** (`python examples/quick_score.py`), and scoring results are produced as JSON report artifacts, never entering pytest's assertion domain.
- If you want scoring results to enter pytest (e.g. "fail the CI when regression is found"), the recommended approach: call the example scripts with `subprocess.run` from pytest and use the exit code/report JSON as the assertion basis, rather than importing AIQE inside the pytest process and chaining the pipeline — this keeps the two lifecycles decoupled so a failure on either side is easy to locate.
- Reports and baselines land in `~/.AIQE/results/` by default, separate from the code repository; switch to explicit paths when archiving with the repository (see section 3).

## 3. CI Snippet (GitHub Actions)

The mock backend has zero dependencies and zero network; a standard GitHub Actions runner can run the full pipeline (no GPU needed):

```yaml
# .github/workflows/aiqe-eval.yml
name: aiqe-eval

on:
  push:
    branches: [master, main]
  pull_request:

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install (AIQE zero runtime dependencies + pytest)
        run: |
          python -m pip install --upgrade pip
          pip install -e . pytest

      - name: Code-level regression (pytest contract tests)
        run: python -m pytest -q

      - name: Model-level regression — quick scoring (mock, 30 s)
        run: python examples/quick_score.py

      - name: Model-level regression — compare two runs (baseline write + regression verdict)
        run: python examples/regression_compare.py --degrade

      - name: Archive evaluation reports
        uses: actions/upload-artifact@v4
        with:
          name: aiqe-reports
          path: |
            AIQE-report.json
            examples/.regression-demo/*.json
          if-no-files-found: ignore
```

Key points:

- **Use only the mock in CI**: `examples/ollama_backend.py` requires a local model — that is real-device evaluation, and putting it in CI introduces instability and cost. Do real-device evaluation locally or on a runner that has the model, following the five-step flow in section 5.
- **Baseline initialization**: when you first wire up CI, the first scoring run marks all cases as `new` (nothing historical to compare against), which is normal; after one successful run, archive the report and manually pick one as the baseline (see section 4).
- **Turning regression into a gate is optional**: the default policy is report-into-artifact with human judgment (mock results under deterministic scoring are stable, so a gate can be enabled with confidence; real-device results fluctuate a lot, so direct blocking is not recommended).

## 4. Baseline Management SOP

### Where to put baselines

| Scenario | Location | Notes |
|---|---|---|
| Solo local | `~/.AIQE/results/baseline.json` | Default path of RegressionAnalyzer, no configuration needed |
| Team/CI archival | Shared storage outside the repo (or CI artifacts) | Archive with names like `AIQE-report-<model>-<date>.json`; manually pick a stable version as the baseline |
| Example/demo | Explicit paths in scripts (e.g. `examples/.regression-demo/`) | Does not pollute the official baseline |

The baseline file has two readable formats (both parsed by `regression.py`):

1. Top-level dict: `{"simple_chat": 1.0, "long_translation": 0.8, ...}`
2. Nested EvaluationReport structure (`{"test_plan_id": ..., "cases": [{"case_id": ..., "judge": {"score": ...}}]}`) — **use a report JSON from a scoring run directly as the baseline**, the most common case, which retains the prompt and the scoring details.

### When to update the baseline

| Scenario | Update? | Notes |
|---|---|---|
| Case-set definition changes (add/remove/modify cases) | Update | The cases changed; old and new scores are not comparable, so the baseline must be rebuilt |
| Scorer rule changes (judge logic) | Update | The metric itself changed; before updating, re-run all historical cases and confirm the old and new score trends are consistent |
| New model major version passes and runs stably | Update | After N consecutive regression-free runs with the new model, set the new scores as the new baseline |
| Baseline stale (cases unverified for a long time) | Update | Recommended cadence (e.g. every 30 days): re-run once with the current configuration to refresh the baseline |
| Scores dropped | **Never** update | Updating the baseline when scores drop = cheating on the metric; investigate first (section 4, step 3) |

One iron rule: **baseline updates must be independent of any single scoring run** — what each run automatically writes is the "current report"; the baseline is a "reference version" picked by a human or a scheduled job. If a script/CI is written to "take the current scores as the baseline right after a run", regression detection will never report a regression again.

## 5. The Five-Step Model-Swap Evaluation Flow

Turn "let's try a different model" from a gut decision into a process — every model swap (version/quantization/backend) goes through these five steps, about 5 minutes in total (30 seconds with mock; on real hardware it depends on the model):

```
Score → Compare → Check regressions → Record → Decide
```

1. **Score**: run the full case set with the new model (standard + extended + boundary, 18 cases). Real backend: `OLLAMA_MODEL=<new model> python examples/ollama_backend.py`; offline validation pipeline: `python examples/regression_compare.py --degrade`.
2. **Compare**: compare against the baseline (RegressionAnalyzer outputs the four states new/pass/degraded/regression plus delta).
3. **Check regressions**: for each regression/degraded case, open the report JSON and inspect the scoring details (keyword hit rate/length/format scores) — is it that the keywords did not cover it (a case problem), or that the model behavior genuinely got worse (a model problem)? Compare the raw responses in the two reports.
4. **Record**: archive the report JSON with the model and date in the filename (`AIQE-report-<model>-<date>.json`), and append a one-line conclusion.
5. **Decide**:

| Verdict | Action |
|---|---|
| All pass | Can switch. Update the baseline (section 3) and put it into use |
| ≤2 degraded (slight drops) | Low risk: manually spot-check the raw responses of the affected cases, then it can be released |
| A regression appears | Reject or roll back; if you must switch, tune the prompt specifically and retest first |
| All new (no baseline) | Observation period: record scores first; set a baseline after it runs stably |

## 6. Positioning and Evolution of This Repository

- **Independent release**: AIQE is an independently distributed Apache-2.0 reference implementation (v0.1.0), released publicly and evolved independently, with no dependency on any unreleased codebase.
- **Open protocol**: `AIQE/protocol.py` defines the single backend integration contract (the Backend Protocol). Any backend that satisfies the protocol (MLX / Ollama / llama.cpp / in-house / mock) can be injected into `ExecutionRunner`, guaranteed by the contract tests in `tests/test_backends.py`.
- **Forking and modification**: this repository may be forked/modified under Apache-2.0, including changing the scoring rules and the case set. Derived repositories should note the source in the README or LICENSE and list their changes relative to AIQE in a prominent place — so the community can trace the origin and evolution of the scoring rules and avoid the silent drift where "the scorer was changed and nobody knew".
- **Positioning**: AIQE keeps only the evaluation chain "cases → execute → deterministic scoring → regression → report" — it is a carrier of the methodology and a reusable evaluation framework, not the runtime of any specific product.

## 7. Frequently Asked Questions

- **What is the project identifier in reports**: `AIQE` (the `_PROJECT` constant in `reporter.py`; older versions emitted lowercase `aiqe` — the current code is authoritative).
- **Baseline file corrupted/wrong format**: if `_load_baseline` fails to parse, it returns None and all cases are treated as `new`; nothing crashes — just fix the file and re-run.
- **Ollama model not installed / service not running**: `examples/ollama_backend.py` prints a Chinese repair guide (`ollama pull <model>` / start the service) and exits, without crashing midway; use the mock backend in CI scenarios.
- **Slow scoring / insufficient memory on real hardware**: in a local inference environment, first confirm available memory before running the full set; performance data (tok/s) only goes into the report, with no automatic gating.
