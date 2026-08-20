# AIQE — A Shift-Left AI Quality Evaluation Framework (Reference Implementation)

> Score before you ship. Catch model quality regressions with deterministic scoring, before release.

[简体中文](README.md) | [English](README.en.md)

AIQE is a reference implementation of a quality evaluation framework for **LLM
and agent development, and AI product development**: **test cases → execution
(Backend Protocol) → deterministic scoring → regression comparison → JSON
report**. It is designed to be used **alongside your development harness** —
scoring and regression checks run with every build/change, not as a post-hoc
audit. **Product-shape agnostic**: whether you evaluate a system/OS, a model,
an algorithm, an APK or a Web product, the same "case → score → regression"
pipeline applies.

- Pure standard library — zero runtime dependencies; the only dev dependency is pytest
- Built-in mock backend: deterministic responses, no model, no network, report in 30 seconds
- Plug in any inference backend (MLX / Ollama / llama.cpp / your own) through the Backend Protocol
- Independently distributed reference implementation (Apache-2.0): complete code, all tests green — use it, fork it, adapt it

> **⚠️ Release status**: currently **v0.1.0 Alpha** reference implementation.
> The core pipeline (execution → scoring → regression → reporting) is complete
> and test-covered; real inference backends are "example / skeleton" level —
> see the [Backend Support Matrix](#backend-support-matrix) below.

---

## Table of Contents

1. [Backend Support Matrix](#backend-support-matrix)
2. [The Shift-Left Idea: Why Score Before Generating](#2-the-shift-left-idea-why-score-before-generating)
3. [Who It's For: AIQE by Product Shape](#3-who-its-for-aiqe-by-product-shape)
4. [Quick Start: Mock Backend, Report in 30 Seconds](#4-quick-start-mock-backend-report-in-30-seconds)
5. [Repository Structure](#5-repository-structure)
6. [Methodology Docs: Layers, Process, Collaboration, Triggers](#6-methodology-docs-layers-process-collaboration-triggers)
7. [Using AIQE with Your Dev Harness: pytest, CI, Baselines, Model Swap](#7-using-aiqe-with-your-dev-harness-pytest-ci-baselines-model-swap)
8. [Examples: Ollama Integration and Regression Comparison](#8-examples-ollama-integration-and-regression-comparison)
9. [Test Trigger Strategy: Four Tiers × Auto/Manual](#9-test-trigger-strategy-four-tiers--automanual)
10. [Templates and Companion Skills](#10-templates-and-companion-skills)
11. [License](#11-license)
12. [Donation and Support (last section)](#12-donation-and-support)

---

## Backend Support Matrix

**Read this first**: AIQE's evaluation pipeline knows nothing about concrete
backends — it only depends on the `AIQE.protocol.Backend` contract. The table
below shows the **real status** of each backend in this repository (v0.1.0),
so you won't assume everything works out of the box:

| Backend | Status | Ready out of the box? | Notes |
|---|---|---|---|
| **Mock Backend** (default) | **Built-in** | ✅ Yes | `backends/mock.py` — deterministic responses, zero dependencies, no network. Use it for CI and offline demos |
| **Ollama Adapter** | **Example Adapter** | 🟡 Experimental | `examples/ollama_backend.py` is an integration example; requires a local Ollama service and model. Assemble it yourself following the example |
| **MLX Backend** | **Skeleton Adapter** | 🟠 Requires Integration | `backends/mlx.py` is a skeleton: complete structure, but `setup()` explicitly raises `ImportError` — install mlx-lm yourself and inject an adapter satisfying the Backend Protocol |
| **llama.cpp** | **Protocol Compatible** | 🟠 External Adapter Required | No implementation in this repo; implement `AIQE.protocol.Backend` (`generate_sync` / `generate` / `backend_type` / `profile`) and inject it — zero pipeline changes |

The full contract for integrating a real model is in
[AIQE/protocol.py](src/AIQE/protocol.py); the integration example is in
[examples/ollama_backend.py](examples/ollama_backend.py).

---

## 2. The Shift-Left Idea: Why Score Before Generating

Traditional quality assurance for AI applications is **reactive**: after a model
goes live you rely on user feedback, manual spot checks, and postmortems. The
problems:

- **Feedback loop too long**: a degradation can take days or weeks to be noticed;
- **No attribution**: was it the prompt? A model version bump? A longer context? Reactive feedback can't say;
- **No baseline**: without numbers there is no "regression" — just gut feeling.

**Shift-Left testing** pushes quality assurance to the **front of the generation
pipeline**: before a model is integrated into a product, run it through a fixed
set of scoreable tasks. Every version, every prompt change, every new model —
run the same exam, get the same scores, and compare against the previous run.

```
              Shift-Left: score before generating
  ┌──────────────────────────────────────────────────────┐
  │  Test Cases (TestCase)                                │
  │   ├─ chat / translation / json_output / coding_task   │
  │   └─ boundary / adversarial / long-context extras     │
  │                                                       │
  │  ExecutionRunner        ← inject any Backend          │
  │  OutputJudge            ← deterministic: keyword/length/format │
  │  RegressionAnalyzer     ← compare against baseline     │
  │  EvaluationReport       ← JSON + console summary       │
  └──────────────────────────────────────────────────────┘
                           ↓
            score drop → block release / trigger investigation
```

Three key design choices make "scoring" something you can do locally, every day,
during development:

1. **Deterministic scoring, no LLM judge**: OutputJudge only performs
   reproducible checks — keyword hits, length checks, format validation (plus
   optional JSON/code-structure detection). The same response always gets the
   same score — so scores can feed baselines and regression analysis.
2. **Cases are assets**: the case sets (including 8 boundary scenarios:
   oversized inputs, adversarial prompts, conflicting instructions, numeric
   precision, etc.) encode your product expectations. Swap a model → run the
   case set first, instead of shipping first.
3. **Baselines are a hard gate**: RegressionAnalyzer compares current scores
   against historical baselines; a drop beyond 0.15 is flagged as a regression.
   With no baseline file, cases are automatically marked `new`, so first-time
   integrations aren't penalized.

> One-liner: **Shift-left testing = turning "is the model good enough" from
> gut feeling into scores, and moving "when do we detect degradation" from
> post-release to pre-release.**

---

## 3. Who It's For: AIQE by Product Shape

AIQE's pipeline is product-shape agnostic — "case → score → regression" works
for any AI product; the difference is only **what your cases encode**:

| What you evaluate | How to use AIQE |
|---|---|
| System/OS (incl. agent runtime) | Agent decision-path evaluation: encode "was the decision correct" as cases (expected keywords/format/length); scores are decision-quality regression |
| Model (large / on-device) | Scoring and swap regression: full case set against baseline; the five-step flow (see §7) decides keep vs. swap |
| Algorithm (RAG/routing/ranking/post-processing) | Deterministic-output regression: same input must produce same-quality output; score change is an alert |
| APK/Web product | Product-function cases (incl. UI output assertions): encode acceptance criteria as cases, pass the exam before release |
| Generic (any AI feature) | CI gate alongside your dev harness: auto-run relevant cases on every build/change; scores and regression results are quality signals |

The relative value of the 12 test layers differs by product shape — see the
"适用产品形态 / product shapes" column in the overview table of
[docs/methodology/testing-layers.md](docs/methodology/testing-layers.md).

---

## 4. Quick Start: Mock Backend, Report in 30 Seconds

No model, no network required. The default mock backend returns deterministic
responses based on prompt content (JSON / code / translation / Chinese chat),
so the whole pipeline completes in under 30 seconds:

```bash
# Install (a dedicated virtualenv is recommended)
python3 -m venv .venv
.venv/bin/pip install -e . pytest

# Run the scoring example (4 standard cases → scoring → regression → report)
.venv/bin/python examples/quick_score.py
```

Example output (excerpt):

```
  AIQE Evaluation Report
  AIQE v0.1.0 · 2026-08-15T...
════════════════════════════════════════════
  simple_chat         █████████░  0.90  ✓
  long_translation    ██████████  1.00  ✓
  json_output         ██████████  1.00  ✓
  coding_task         █████████░  0.90  ✓

  Summary: 4/4 passed
════════════════════════════════════════════
```

Run the full test suite:

```bash
.venv/bin/python -m pytest -q
```

To plug in a real model: implement or inject an object satisfying
`AIQE.protocol.Backend` (`generate_sync` / `generate` / `backend_type` /
`profile`, etc.) — zero pipeline changes:

```python
from AIQE.backends.mock import MockEvalBackend
from AIQE.runner import ExecutionRunner

backend = MockEvalBackend()          # swap in your real backend instance
backend.setup()
runner = ExecutionRunner(backend)    # downstream judge/regression/reporter unchanged
```

---

## 5. Repository Structure

```
src/AIQE/
├── protocol.py        # Backend Protocol: BackendType / ModelProfile /
│                      #   GenerateOptions / GenerateResult / Backend / default impl
├── schema.py          # Data models: TestCase / ScoreBreakdown / EvaluationResult
│                      #   + ModelRunner / LocalRunner (local deterministic) / OllamaRunner
├── runner.py          # ExecutionRunner: run case → ExecutionResult
│                      #   (with trace_id / payload_hash integrity checks)
├── judge.py           # OutputJudge: deterministic scoring (keyword/length/format;
│                      #   format score genuinely counts toward the total)
├── regression.py      # RegressionAnalyzer: compare against baseline, detect regression
├── reporter.py        # EvaluationReport: JSON report + console bar-chart summary
├── backends/
│   ├── base.py        #   EvaluationBackend Protocol (Backend superset + setup/teardown)
│   ├── mock.py        #   MockEvalBackend: deterministic mock (default, Built-in)
│   ├── mlx.py         #   MlxEvalBackend: real-MLX inference skeleton (adapter needed)
│   └── factory.py     #   create_eval_backend(): switches on MLX_EVAL_LIVE env var
└── cases/
    ├── test_cases.py      # 4 standard cases (chat/translation/json/coding)
    ├── extended_cases.py  # 6 extended cases (Chinese scenarios)
    └── boundary_cases.py  # 8 boundary cases (long input/adversarial/conflict/precision…)
tests/                       # contract tests (111, all green with `pytest -q`)
examples/
    quick_score.py           # 30-second quick scoring example (mock)
    ollama_backend.py        # real-model integration example (ollama)
    regression_compare.py    # two-run regression comparison demo (mock, offline)
docs/
    methodology/                 # methodology docs (layers/process/collab/requirements/data/report/triggers)
    INTEGRATION.md               # using AIQE with your dev harness
templates/
    test-case-template.md        # TestCase field-by-field guide
    test-script-template.py      # runnable script skeleton (3 cases + scoring pipeline)
    report-template.md           # five-section report template
skills/
    testing-agent/               # testing-agent discipline skill
    aiqe-testing/                # four-tier manual trigger skill
```

Data flow: `TestCase → ExecutionRunner(Backend) → ExecutionResult → OutputJudge
→ JudgeResult → [RegressionAnalyzer] → EvaluationReport → JSON`

> **More than code: methodology doc index**
>
> - [docs/methodology/testing-layers.md](docs/methodology/testing-layers.md)
>   — twelve-layer test framework: per-layer "what to test / where / what not to build" + shift-left layering principles
> - [docs/methodology/process-management.md](docs/methodology/process-management.md)
>   — full quality-process lifecycle + gate states (PASS/WARN/FAIL/MANUAL_REVIEW/NOT_ASSESSED) + release decision rules
> - [docs/methodology/multi-agent-testing.md](docs/methodology/multi-agent-testing.md)
>   — four-role model for multi-agent testing + task-brief template + reusable testing skill
> - [docs/methodology/requirement-analysis.md](docs/methodology/requirement-analysis.md)
>   — requirement → acceptance criteria → test cases (with a complete example)
> - [docs/methodology/test-data-management.md](docs/methodology/test-data-management.md)
>   — case sets / baselines / reports management + baseline in git + privacy redaction
> - [docs/methodology/report-generation.md](docs/methodology/report-generation.md)
>   — report pipeline and field explanations + extended Markdown example
> - [docs/methodology/test-trigger-strategy.md](docs/methodology/test-trigger-strategy.md)
>   — four test tiers (smoke/full/regression/acceptance) × auto/manual trigger matrix
> - [docs/INTEGRATION.md](docs/INTEGRATION.md)
>   — using AIQE with your dev harness: pytest coexistence, CI, baseline SOP, five-step model swap
> - [templates/](templates/) — case template / runnable script skeleton / five-section report template
> - [skills/](skills/) — testing-agent discipline skill + four-tier manual trigger skill
> - [examples/](examples/) — runnable examples: quick mock scoring / real ollama integration /
>   two-run regression comparison (see §8)

---

## 6. Methodology Docs: Layers, Process, Collaboration, Triggers

All methodology docs live in `docs/methodology/`, covering the full chain of
"what to test → how to set standards → who does what → when to trigger → where
data lives → how to report":

| Doc | Content | Entry point |
|---|---|---|
| [testing-layers.md](docs/methodology/testing-layers.md) | twelve-layer test framework (layering / shift-left / decision table / don't build your own infra) | "what to test" |
| [process-management.md](docs/methodology/process-management.md) | full quality-process lifecycle + gate states (PASS/WARN/FAIL/MANUAL_REVIEW/NOT_ASSESSED) + release rules | "how to judge" |
| [requirement-analysis.md](docs/methodology/requirement-analysis.md) | requirement → testable acceptance criteria → test cases (complete example) | "what standard" |
| [multi-agent-testing.md](docs/methodology/multi-agent-testing.md) | four-role model + task-brief template + reusable testing skill | "who does it" |
| [test-trigger-strategy.md](docs/methodology/test-trigger-strategy.md) | four tiers (smoke/full/regression/acceptance) × auto/manual trigger matrix | "when to run" |
| [test-data-management.md](docs/methodology/test-data-management.md) | case set / baseline / report management, baseline in git, privacy redaction | "where data lives" |
| [report-generation.md](docs/methodology/report-generation.md) | report pipeline, field-by-field explanations + extended Markdown example | "how to report" |

Integration guidance (pytest coexistence / CI / baseline SOP / five-step model
swap) is in §7.

## 7. Using AIQE with Your Dev Harness: pytest, CI, Baselines, Model Swap

[docs/INTEGRATION.md](docs/INTEGRATION.md) answers "how do I wire AIQE into my
project": the sync pattern with your dev harness (auto-score on every
build/change, results as quality-gate signals), directory conventions for
coexisting with pytest, a GitHub Actions CI snippet, the baseline-management
SOP (where baselines live / when to update / when updates are forbidden), and
the five-step model-swap flow (score → compare → check regression → record →
decide).

This repo ships `.github/workflows/test.yml`: anyone who clones it gets a single
CI run validating AIQE on Python 3.10 / 3.11 / 3.12 (install + full test suite).

## 8. Examples: Ollama Integration and Regression Comparison

| Example | Purpose | Run |
|---|---|---|
| [examples/quick_score.py](examples/quick_score.py) | 30-second quick scoring (mock, zero deps) | `python examples/quick_score.py` |
| [examples/ollama_backend.py](examples/ollama_backend.py) | score against a real local ollama model (with Chinese hints when the model isn't ready) | `ollama pull llama3.2` first, then `python examples/ollama_backend.py` |
| [examples/regression_compare.py](examples/regression_compare.py) | two-run regression comparison: generate baseline → re-run with changed params → regression verdict (mock, offline-capable) | `python examples/regression_compare.py --degrade` |

## 9. Test Trigger Strategy: Four Tiers × Auto/Manual

[docs/methodology/test-trigger-strategy.md](docs/methodology/test-trigger-strategy.md)
defines four test tiers (smoke / full / regression / acceptance) mapped onto
the 12 layers, auto-trigger mount points (harness hooks
SessionStart/PreToolUse/Stop/SessionEnd and CI push/PR/schedule/release), the
"changed X → auto-run tier Y" decision table, and the four scenarios that must
be triggered manually, with the matching commands (see
[skills/aiqe-testing/](skills/aiqe-testing/SKILL.md): /aiqe-smoke, /aiqe-full,
/aiqe-regression, /aiqe-acceptance).

## 10. Templates and Companion Skills

- [templates/test-case-template.md](templates/test-case-template.md)
  — field-by-field TestCase guide + good/bad case comparison
- [templates/test-script-template.py](templates/test-script-template.py)
  — copy-and-run script skeleton (3 cases + runner + judge + report, with customization points annotated)
- [templates/report-template.md](templates/report-template.md)
  — five-section report template (executive summary / case details / regression verdict / performance data / recommendations)
- [skills/testing-agent/SKILL.md](skills/testing-agent/SKILL.md)
  — testing-agent work discipline (red→green, acceptance commands, no self-verifying busywork, boundary declarations)
- [skills/aiqe-testing/SKILL.md](skills/aiqe-testing/SKILL.md)
  — four-tier manual trigger command mapping

---

## 11. License

This project is licensed under the **Apache License 2.0** (full text in
[LICENSE](LICENSE)). Why this license:

| Aspect | Notes |
|---|---|
| Commercial use, closed-source forks allowed | Use the framework in commercial products; forks may stay closed-source |
| Patent grant | Apache-2.0 includes a patent grant clause, friendly for evaluation frameworks |
| Retention obligations | Redistributions must keep copyright notices, the license file, and note modifications |
| No warranty | Reference implementation — no express or implied warranty (standard Apache-2.0 terms) |

**Attribution and modification norms**:

- **Forking: please note the source**: derived repositories should state in
  their README or LICENSE: "derived from AIQE
  (https://github.com/haleSnW/AIQE)"
- **Modified releases must declare differences**: list your changes
  prominently (e.g., at the top of your README) — so the community can trace
  where scoring rules come from and how they evolved, and there is no silent
  drift from "someone changed the judge and nobody knew"
- **Independent distribution**: AIQE is an independently distributed reference
  implementation; the Apache-2.0 license covers everything in this repository.
  Commercial use (including closed source) needs no additional authorization

---

## 12. Donation and Support

AIQE is a fully open-source, free-to-use project. If you find it useful,
consider supporting its development and maintenance. Every contribution is
accounted for and published in the repository's release notes; funds are used
for exactly three things:

| Purpose | Notes |
|---|---|
| Real inference validation | Compute cost of running the full case set on real hardware (Apple Silicon / MLX / Ollama) |
| Case set expansion | Building and manually calibrating new scenario cases |
| Maintenance and docs | Framework maintenance, CI, documentation and translations |

<div align="center">

<img src="docs/donate_alipay.png" alt="Alipay QR code" width="240">

**Alipay QR code**

</div>

Whatever the amount — thank you for supporting open source. ❤️
