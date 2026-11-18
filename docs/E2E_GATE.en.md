# E2E Quality Gate: AI-healed tests must not turn green silently

[简体中文](E2E_GATE.md) | [English](E2E_GATE.en.md)

`AIQE.e2e_gate` is a **deterministic release verdict** that runs after Playwright. It answers one question:

> The tests are green. Can this change be released automatically?

Playwright's Test Agents (planner / generator / healer) can now generate and auto-repair E2E tests with AI.
The new risk is a healer that turns red into green by deleting assertions, loosening matchers or adding `skip`.
CI only looks at the exit code, so it cannot see that.
AIQE does not reimplement those agents. It adds only the verdict layer: AI runs and repairs tests, rules decide, and people handle the exceptions.

## 1. See it in one command

```bash
PYTHONPATH=src python examples/e2e_gate_demo.py --out /tmp/aiqe-e2e-demo
```

| Scenario | Playwright | Gate | Reason |
|---|---|---|---|
| Baseline | all green | PASS | — |
| New build | 2 failed | BLOCK | `NEW_FAILURE` ×2 |
| Honest healer: only fixes a locator | 1 failed | BLOCK | `NEW_FAILURE`: the remaining failure is a product bug, and it is still blocked |
| **Cheating healer: removes an assertion and loosens a matcher** | **all green** | **BLOCK** | `ASSERTION_REMOVED`, `MATCHER_LOOSENED` |
| Product bug fixed + honest healer | all green | PASS | — |
| Passes only on retry | all green | ESCALATE | `FLAKY` |

Inputs live in [`examples/e2e_gate/`](../examples/e2e_gate/): hand-written public Playwright JSON reports and healer diffs.
For each scenario the demo writes the gate JSON, a Markdown summary and an AIQE result-contract document, plus an offline dashboard.
In the dashboard trend, the cheating run shows 83.3%, not 100%: the weakened case counts as "not judged", not as a pass.

## 2. Use it on your project

```bash
PLAYWRIGHT_JSON_OUTPUT_FILE=pw-report.json npx playwright test --reporter=json
git diff "$HEALER_BASE" "$HEALER_HEAD" > e2e.diff

python -m AIQE.e2e_gate \
  --report pw-report.json \
  --baseline last-green/pw-report.json \
  --patch e2e.diff \
  --out aiqe-gate.json --markdown summary.md \
  --result-out aiqe-run.json --sut-id "$GIT_SHA"
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | PASS |
| 1 | BLOCK |
| 2 | ESCALATE (a human decides) |
| 3 | The input could not be parsed (fails closed) |

Set `HEALER_BASE` and `HEALER_HEAD` to the trusted commits immediately before and after the test repair.
Omit `--baseline` and `--patch` to check the current report alone.
The workflow example also checks Playwright's native exit status. Its public summary contains only the verdict and exit code. Keep raw reports, test names, and paths in an access-controlled environment.
For a full GitHub Actions example, see [`examples/ci/playwright-e2e-gate.yml`](../examples/ci/playwright-e2e-gate.yml).

## 3. Reason codes

Severities live in `AIQE.e2e_gate.SEVERITY`. They are not configurable in v0.1, so a single line of config cannot switch the guard off.

| Code | Severity | Trigger |
|---|---|---|
| `UNEXPECTED_FAILURE` / `NEW_FAILURE` / `PERSISTENT_FAILURE` | BLOCK | A test failed (no baseline / passed in the baseline / also failed in the baseline) |
| `FLAKY` | ESCALATE | The test passed only after a retry |
| `EXPECTED_FAILURE_MARKED` | ESCALATE | `test.fail()` makes a failure count as expected |
| `SKIP_ADDED` / `TEST_REMOVED` | ESCALATE | A test that ran in the baseline is now skipped / gone |
| `EVIDENCE_EMPTY` / `REPORT_ERRORS` | BLOCK | The report is empty or all tests were skipped / the report has top-level errors |
| `TRACE_MISSING` | ESCALATE | A failed test has no trace attached |
| `BASELINE_INCOMPARABLE` | ESCALATE | The project set differs from the baseline |
| `ASSERTION_REMOVED` | BLOCK | Net fewer `expect(` / `assert` (code that was commented out counts as removed) |
| `MATCHER_LOOSENED` | BLOCK | Fewer strict matchers, plus new loose ones (`toBeVisible()`, `toBeTruthy()`, `/.*/`…) |
| `ASSERTION_SWALLOWED` | BLOCK | New `.catch(() => {})`, `except: pass` |
| `TEST_DISABLED` | BLOCK | New `skip` / `fixme` / `fail` / `only`, `xit`, `@pytest.mark.skip` |
| `SCOPE_VIOLATION` | BLOCK | The fix changed files outside the allowed test paths |
| `TIMEOUT_INFLATED` / `FORCE_ACTION` | ESCALATE | A larger timeout or `test.slow()` / new `force: true` |

Diff findings that carry a line number are attributed to the nearest enclosing spec.
When a BLOCK-level finding is attributed to a case, that case is projected as "not judged" rather than passed.

## 4. Boundaries

- **No model calls, no browser driving, no Playwright dependency.** The gate reads only the report and the diff, using the standard library. The same input always gives the same verdict.
- **The result contract stores reason codes, never messages.** Error text, stdout and attachment paths stay out of `aiqe.result`.
- **The source type is `local_test` and the classification defaults to `internal`.** The dashboard needs `--allow-source local_test` to read these runs.
- **These are rules, not proofs.** PASS means "no risk signal found", not "quality proven". Attributing a finding to a test by line number is also an approximation: the gate does not parse TS/JS.

- Use matching Playwright projects and test filters for the baseline and candidate. This version requires unique case identities within a project and may reject reports from `--repeat-each`.
