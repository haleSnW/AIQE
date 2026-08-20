[简体中文](process-management.md) | [English](process-management.en.md)

# AIQE Quality Process Management

> AI quality evaluation is not a single command; it is a **process**: from requirements to decisions, every stage has
> explicit entry and exit criteria. This document defines the full lifecycle, the five-state quality gate vocabulary,
> and the release decision rules — all generalized, independent of any specific product form.

---

## 1. Full Lifecycle: Seven Stages

```
Requirements → Case design → Execution → Scoring → Regression → Report → Decision
      │            │            │          │         │           │        │
      │            │            │          │         │           │        └─ release / rollback / iterate / observe
      │            │            │          │         │           └─ conclusions for humans, JSON for machines
      │            │            │          │         └─ compare vs baseline → new/pass/degraded/regression
      │            │            │          └─ deterministic scoring (keyword/length/format)
      │            │            └─ backend execution (mock offline / real machine online)
      │            └─ cases are the spec: encode expectations as TestCase
      └─ start: testable acceptance criteria (see requirement-analysis.md)
```

Entry and exit criteria for each stage:

| Stage | Input (entry) | Output (exit) | Completion criteria |
|---|---|---|---|
| Requirements | Vague requirements / change requests | Testable acceptance criteria | Each criterion can be described in terms of "does the response contain X / is the length ≥ N / is the format valid" (see requirement-analysis.md) |
| Test case design | Acceptance criteria | A set of TestCases | Each acceptance criterion has ≥ 1 test case; test case fields are complete and valid (see templates/test-case-template.md); each test case can run independently and produce a meaningful score |
| Execution | Test case set + backend | List of ExecutionResults | All test cases have been executed; failures are recorded with an error rather than silently skipped; real backends are gated |
| Scoring | ExecutionResult | JudgeResult (score/checks/reasons) | Scoring is deterministic: the same response yields the same score; scoring rules match the test case category (json/coding go through the format branch) |
| Regression | JudgeResult + baseline | RegressionResult (new/pass/degraded/regression) | Baseline existence has been verified; when no baseline exists, mark as new rather than misreporting |
| Reporting | All results | JSON report + console summary + (optional) Markdown | The report contains the three-part execution/scoring/regression fields; traceable (trace_id/payload_hash) |
| Decision | Report | Release / rollback / iterate / observe + baseline update | Determined per the gate rules in Section 3; decision rationale archived with the report |

**Failed-output loopback**: if any stage's output fails to qualify, the process falls back to the stage before it
and does not continue downstream with the substandard artifact — for example, if the scoring rules change, loop back
to test case design (re-run the full set); the report cannot be produced directly.

## 2. Quality Gate Five-State Vocabulary

All evaluation conclusions converge into five states; inventing your own vocabulary is forbidden (to avoid
descriptions such as "pretty good" or "basically fine" that cannot be compared across people or across time):

| State | Meaning | Trigger conditions (examples) | Handling |
|---|---|---|---|
| **PASS** | All passed | All test cases passed and no regression | Can release/merge; update the baseline per SOP |
| **WARN** | Minor decline, observation period | ≤ 2 test cases degraded (decline ≤ threshold) or a single performance metric slipping | Can release, but requires manual spot-check of the raw responses of the affected test cases; focus on them in the next scoring round |
| **FAIL** | Blocking regression | ≥ 1 test case regression (decline exceeds threshold) or a critical test case FAIL | Release forbidden; roll back or fix, then re-run |
| **MANUAL_REVIEW** | Requires human judgment | Test cases involve subjective quality (translation naturalness/style consistency); or test cases with status new before entering production | Manual spot-check + conclusions filled back into the report (reviewer signature) |
| **NOT_ASSESSED** | Not assessed | Test case skipped (real-machine gated, not run) / execution error / no baseline and not observed | Not counted in the pass rate; reasons for non-assessment explicitly listed in the report |

**Design notes**:
- The five states are **orthogonal**: WARN/FAIL describe "the gap from the baseline," MANUAL_REVIEW describes
  "whether the evidence is sufficient," and NOT_ASSESSED describes "whether it was actually tested" — a single test
  case can be both PASS + MANUAL_REVIEW (the score passes, but the quality is subjective and still needs human review).
- NOT_ASSESSED is the most dangerous slip-through state: skipped ≠ passed. It must be listed separately in the
  report, and the default state of gated test cases is NOT_ASSESSED (preventing "not run yet shown as passed").

## 3. Release Decision Rules

Release decision = gate status + non-assessed situation; both rules are indispensable:

```
Rule 1 (gate): any FAIL status → release forbidden, return to the fix loop
Rule 2 (evidence): any NOT_ASSESSED whose case falls within this change's impact scope
                → must be re-run before release (releasable = "everything run has passed" ≠ "unrun also passes")
```

| Scenario | Decision | Notes |
|---|---|---|
| All PASS, no NOT_ASSESSED | ✅ Release | Standard approval |
| All PASS but with NOT_ASSESSED (gated, not run) | ⚠️ Depends on impact scope | Within scope → run before release; outside scope → record and approve |
| Has WARN (≤ 2 minor declines) | ⚠️ Release with observation period | Manual spot-check + record tracking items, re-check next round |
| Has MANUAL_REVIEW with no conclusion filled back | ⏸ Wait | Do not proceed until the human conclusion is filled back |
| Has FAIL | ⛔ Forbidden | Roll back or fix, re-enter from the "Execution" stage |
| All new (first-time integration, no baseline) | 🔍 Observation period | Not released as an official version; establish the baseline after N stable runs |

## 4. Integration Points with the Development Harness / CI

The AIQE process does not run in isolation; it hooks into the development harness at three trigger points:

```
Dev harness (build / commit / release)
        │
        ├─① every commit (light): mock scoring + related cases
        │     → status into PR checks, FAIL blocks merge
        │
        ├─② nightly/weekly (full): full case set + baseline regression
        │     → reports archived, trends into the quality dashboard
        │
        └─③ pre-release (gate): five-state verdict + MANUAL_REVIEW backfill
              → PASS/WARN approve, FAIL blocks, NOT_ASSESSED re-run
```

| Hook point | What runs | Gate effect | Artifacts |
|---|---|---|---|
| ① Commit level | Relevant test cases (decision table in Section 3 of testing-layers.md) + mock | FAIL blocks merge | Report JSON + PR comment |
| ② Periodic level | Full test case set + real backend (optional) | Trend alerts (WARN accumulation) | Archived reports + trend data |
| ③ Release level | Full set + gated real machine + MANUAL_REVIEW | Five-state decision | Release checklist + archived report |

**A stricter gate is not necessarily better**: level ① uses the deterministic mock (results are stable, so blocking
is safe); level ③'s real-machine results fluctuate greatly, so the default is "report + human judgment"; when a hard
gate is truly needed, enable it only for deterministic backends.
