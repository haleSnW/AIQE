[简体中文](test-data-management.md) | [English](test-data-management.en.md)

# Test Data Management

> Test case sets, baselines, and reports are the **three types of assets** of the evaluation system, each with different
> storage, versioning, update, and privacy policies. Mixing them together is the number one source of data management
> incidents.

---

## 1. Three Types of Data and Directory Conventions

| Data type | Content | Recommended location | Commit to git? | Update frequency |
|---|---|---|---|---|
| **Test case set** | TestCase definitions (code) | `src/<pkg>/cases/` in the project (this repository: `src/AIQE/cases/`) | ✅ Committed with the code | Changes with requirements/acceptance criteria (low frequency) |
| **Baseline** | Historical score references (JSON) | `baselines/` in the repository (or `tests/baselines/`) | ✅ Recommended to commit (see Section 2) | Follows the "baseline update SOP" (see Section 3) |
| **Report** | Results of each scoring run (JSON + summary) | Outside the repository (CI artifact / `~/.AIQE/results` / shared storage) | ❌ Not committed by default | Produced on every scoring run (high frequency) |

**Current state in this repository** (for reference):

```
src/AIQE/cases/        # case set (code asset, evolves with versions)
~/.AIQE/results/       # default baseline directory (RegressionAnalyzer default path)
examples/.regression-demo/  # demo-only data (gitignored; demos don't pollute the real baseline)
AIQE-report-*.json     # report artifacts (gitignored)
```

**One red line**: a report is "a snapshot of the results of each run", and a baseline is "a manually selected reference
version" — if the two are mixed in one file, or a script automatically treats the current scores as the baseline,
regression detection becomes ineffective (see the "prohibited updates" scenario in the baseline management SOP in
INTEGRATION.md).

## 2. Committing Baseline JSON to git Version Control

Three reasons for putting baselines in git: traceability (which version set the baseline), diffability (baseline changes
can be reviewed), and reproducibility (checking out a historical version replays the evaluation of that time).

Recommended directory and naming:

```
baselines/
    baseline.json              # currently active baseline (top-level dict or report-nested format parsed by RegressionAnalyzer)
    baseline-2026-08-15.json   # historical snapshot (archived by date, kept per decisions)
```

**Baseline file content specification**:
- Top-level dict format: `{"<case_id>": <score>, ...}`;
- Or the nested EvaluationReport format (`{"test_plan_id":..., "cases":[...]}`,
  reusing a report file directly as the baseline, keeping the prompts and scoring details);
- It is recommended to **include an explanation** in the same commit (what changed and why), such as
  `baselines/CHANGELOG.md` or a commit message — baseline changes, like code changes,
  need an audit trail.

**git operation discipline**:
- Baseline updates and code changes go in the same PR/commit, so that the cause-and-effect of "changing code while
  changing the baseline" can be reviewed;
- It is forbidden to directly overwrite the baseline commit with "the current report at the time of a score drop"
  (cheating mode);
- Report artifacts do not go into git (high-frequency noise); only baselines should be committed.

## 3. Baseline Update SOP

Trigger conditions and actions (echoing Section 4 of INTEGRATION.md):

| Trigger scenario | Action | Allowed? |
|---|---|---|
| Test case set changes (adding/removing/modifying cases) | Rerun the full suite → the new scores become the new baseline | ✅ Required |
| Scorer rule changes | First rerun all historical cases to verify the new and old score trends are consistent → then update the baseline | ✅ Conditional |
| Model upgrade with consistently stable scores | Set the new scores as the new baseline | ✅ Recommended |
| Baseline stale (periodic refresh, e.g., 30 days) | Rerun once with the current configuration to refresh | ✅ Recommended |
| Score drop | Update the baseline | ❌ Forbidden — first investigate the cause of the regression |

**Update process** (five steps):

1. Create a candidate file `baseline-<date>.json` under `baselines/` (the scoring results with the current
   configuration);
2. Diff against the old baseline and explain each difference one by one (which test case went up/down and why);
3. Run a regression comparison of "candidate baseline + current report" to confirm the conclusion is sound;
4. Replace `baseline.json` with the candidate file, and commit it together with the explanation;
5. Archive the old version as a historical snapshot (or rely on git history and delete redundant copies).

## 4. Privacy Notes: Test Case Data Sanitization

Test case sets are **code assets** that are distributed with the repository (open source / internal distribution) —
embedding real data in test cases equals data leakage:

| Risk scenario | Example | Handling |
|---|---|---|
| Test case prompt contains real user messages | "User Zhang* complaining about an order..." | Replace with fictional equivalent samples (keep format characteristics, remove identifiable information) |
| Expected output contains real responses/log excerpts | expected_keywords copied from production logs | Keep only keyword characteristics; do not copy the real output in full |
| Baseline/report contains real inputs and outputs | prompt/response fields in the report JSON | Reports do not go into git; sanitize before archiving to shared storage |
| Accounts/keys/intranet addresses | tokens, domains, IPs appearing in prompts | Always replace with placeholders (`<TOKEN>` / `example.com` / the example CIDR `10.0.0.0/8`) |

**Self-check command** (before committing test case sets/baselines):

```bash
# scan for common sensitive patterns (tokens/private keys/emails/internal IPs), tighten as needed
grep -rniE "(sk-[a-z0-9]{16,}|api[_-]?key|password\s*[:=]|[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|10\.\d+\.\d+\.\d+|192\.168\.)" src/ baselines/ 2>/dev/null || echo "no common sensitive patterns found"
```

**The principle in one sentence**: test case sets and baselines should only contain "fictional equivalent samples"; real
data is only allowed in local reports that are not committed to git, and should be sanitized as needed before archiving.
