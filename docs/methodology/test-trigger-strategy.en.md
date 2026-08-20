[简体中文](test-trigger-strategy.md) | [English](test-trigger-strategy.en.md)

# Test Trigger Strategy

> The layered framework (testing-layers.md) answers "what to test"; this document answers "**when to
> run**": a matrix of four test tiers × automatic/manual triggers. The goal is that every change triggers the
> appropriate tier — neither over-testing (waste) nor under-testing (risk).

---

## 1. Tier Definitions and Scope

The 12 layers of tests are assigned to four tiers, ordered by **speed from fastest to slowest and trigger
frequency from highest to lowest**:

| Tier | Layers included | Magnitude | When triggered | Cost |
|---|---|---|---|---|
| **① Smoke** | Unit + interface (contract) | Seconds | **Every change** (after any code/test case change) | Seconds |
| **② Full** | Integration + functional + black-box | Minutes | **Daily / before merge** | Minutes |
| **③ Regression** | Performance + baseline comparison | Minutes (can be long on real machines) | **When switching models / modifying the scorer / updating the baseline** | Minutes to hours |
| **④ Acceptance** | End-to-end + stability + security + UI + gray-box | Minutes to hours | **Before release / when requirements are complete** | Minutes to hours |

**Relationship between tiers and layers** (12 layers → 4 tiers):

```
① Smoke      unit / interface (contract)
② Full       integration / functional / black-box
③ Regression performance / baseline comparison (regression verdict)
④ Acceptance end-to-end / stability / security / UI / gray-box
```

**Design intent**: a tier is the unit of "trigger," and a layer is the unit of "what to test" — a commit that
"modifies the scorer" triggers tier ③, which internally actually runs "performance comparison + a full re-run of
the test case set" (modifying the scorer requires re-running historical test cases; see the decision table in
testing-layers.md). Which layers each tier runs internally is trimmed by the project per the decision table in
testing-layers.md.

## 2. Automatic Triggers (harness hook / CI)

### 2.1 Development harness hook timing

Using the hook timing of a Claude Code-style harness as an example (the timing names are generic; other harnesses
map them to equivalent timings):

| Hook timing | Which tier it attaches to | Trigger condition | Expected duration |
|---|---|---|---|
| `SessionStart` | Runs no tests; only checks baseline existence | Every session start | Seconds |
| `PreToolUse` (before writing tests/changing test case files) | Runs no tests; outputs a hint about "which tier this change should trigger" | The tool touches the src/tests/cases directory | Seconds |
| `Stop` (after a change is complete) | **① Smoke** | Any code/test case change | Seconds; safe to attach to every stop |
| `SessionEnd` | **② Full** (when accumulated changes for the day ≥ 1) | Accumulated changes exist at session end | Minutes; executes after a prompt |

Key point: **attach Smoke to Stop and Full to SessionEnd** — Smoke is fast enough not to interrupt the workflow,
and Full is placed at the session boundary to avoid repeated runs.

### 2.2 CI timing

| CI event | Which tier it attaches to | Notes |
|---|---|---|
| push / PR (every commit) | ① Smoke | Seconds; fails fast; the deterministic results of the mock backend are safe to block on |
| Before PR merge (required check) | ② Full | Minutes; the report is a PR check item |
| Scheduled (daily/weekly) | ② Full + ③ Regression (baseline trend) | Baseline drift alerts; reports archived |
| Release pipeline | ④ Acceptance | Gated real-machine test cases are enabled in this tier; five-state gate decision |

### 2.3 "Changed X → automatically run tier Y" decision table

| Change | Automatically triggered tier | Rationale |
|---|---|---|
| Change test cases (add/remove/change prompt/change keywords) | ① Smoke + ② Full | Test cases are the spec; changing them requires verifying that the test cases themselves are valid and that scores are discriminative |
| Modify the scorer (judge rules) | ③ Regression + ② Full | The measurement itself changed: first run historical test cases to prove the new and old scores are comparable, then re-run the full set |
| Switch models (version/quantization/backend) | ③ Regression | Full test case set compared against the baseline; five-step process (see Section 5 of INTEGRATION.md) |
| Modify the executor/backend protocol | ① Smoke (contract tests) | Protocol breakage surfaces first at the contract layer |
| Change the report/output format | ① Smoke + ② Full (report assertions) | The output is the contract for downstream consumers |
| Release (tag/release) | ④ Acceptance | All gates + human judgment |
| Docs-only change | No trigger | No code changes |

## 3. Manual Triggers (when manual is required)

The following scenarios **cannot** rely on automatic triggers and must be explicitly initiated by a human:

| Scenario | Why manual is required | Manual action |
|---|---|---|
| Needs a real machine / real model | The automatic trigger environment (CI/sandbox) has no model or limited resources | `/aiqe-acceptance` (includes real-machine test cases) |
| Needs human judgment | Handling WARN, adjudicating MANUAL_REVIEW, canary observation | Human reviews the report + fills back conclusions (five-state vocabulary in process-management.md) |
| Long-running soak / stability | Hours-long; not suitable for attaching to every change | The soak subcommand of `/aiqe-acceptance` |
| Baseline update decision | Involves the judgment of "whether the baseline should be updated" (SOP in test-data-management.md) | Human executes per the five-step process |

The accompanying `skills/aiqe-testing/SKILL.md` provides manual command mappings (/aiqe-smoke, /aiqe-full,
/aiqe-regression, /aiqe-acceptance) — making "manual" a **fixed action** rather than ad-hoc command assembly.

## 4. Four Principles

1. **Automate whenever possible**: any trigger that can be written as a deterministic command goes into hook/CI;
   manual is reserved only for scenarios that "need a real machine / need judgment".
2. **Fast tiers first**: if Smoke does not pass, do not proceed to Full; if Full does not pass, do not proceed to
   Regression — the tiers form a gate chain, not an optional checklist.
3. **Regression always precedes acceptance**: a complete regression comparison is required before acceptance
   (acceptance answers "can we release", regression answers "is anything worse than last time" — without the
   latter, the former is a castle in the air).
4. **Manual tiers must leave a trace**: who, when, what result — after a manual run, archive the output into the
   report/task ticket; a one-line "I ran it manually" is forbidden.
