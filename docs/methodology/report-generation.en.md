[简体中文](report-generation.md) | [English](report-generation.en.md)

# Test Report Generation

> The report is the "exit" of the process: machines read JSON, humans read the console summary, and teams read the
> archived documents. This document explains the report pipeline and field semantics, and provides a complete
> example of extending Markdown reports.

---

## 1. Report Pipeline

```
EvaluationReport (aggregation)
   │
   ├─ to_json(path)   → JSON file (machine-consumed / baseline reuse / archiving)
   ├─ print_summary() → console bar chart (quick human scan)
   └─ custom extensions → Markdown / dashboard / email (team consumption, see Section 3)
```

The three parts of data always share a single source: `add_case()` collects once, the three outputs each render
from it, and no fields are maintained redundantly.

## 2. Report Fields Explained One by One

### Top level

| Field | Meaning | Consumer |
|---|---|---|
| `test_plan_id` | Identifier of this scoring plan (e.g. `ollama-<model-name>`) | Archive retrieval |
| `generated_at` | UTC generation time | Archive sorting |
| `project` | Project identifier (`AIQE` for this repository) | Distinguishing data across projects |
| `version` | Framework version | Data comparability (compare reports across versions with caution) |
| `cases` | Array of test case details (see below) | Primary consumer |
| `summary` | Summary (passed/total/regressions) | Gate decisions (see the five states in process-management.md) |

### Each test case in cases[]

| Field | Meaning | How to read |
|---|---|---|
| `case_id` / `category` / `prompt` | Test case identifier/category/input | Traceability |
| `execution.response` | Raw model output | Compare the raw text of two reports when troubleshooting regressions |
| `execution.tokens_generated` / `elapsed_sec` / `tok_per_sec` | Tokens generated / elapsed time / speed | Performance data (no automatic gating; included in the report for human review) |
| `execution.backend` / `model_id` | Backend and model identifier | Cross-model comparison |
| `execution.error` | Execution error (non-None means failure) | **When error is not None, score is invalid**; treat as NOT_ASSESSED |
| `execution.trace_id` / `payload_hash` | Trace ID / response hash | Link to the same execution; verify output integrity |
| `judge.score` / `passed` | Score (0~1) / passed (≥0.5) | Core metrics |
| `judge.breakdown` | Per-dimension upper bounds (relevance/correctness/…) | Reference only; not part of the computation |
| `judge.checks` | Per-check booleans (empty_response/length_ok/keywords_match/format_ok) | Locate where points were lost |
| `judge.reasons` | Human-readable list of reasons | For human reading |
| `judge.metrics` | Numeric metrics (response_length/keyword_hits/format_score) | Quantitative analysis |
| `regression.status` / `delta` / `baseline_score` / `current_score` | Regression status / delta / baseline score / current score | Gate decisions (see process-management.md) |

**Suggested reading order**: scan the summary for the big picture → check the regressions list for which test
cases regressed → open the regressed test cases and look at `judge.checks` and `judge.reasons` to locate the
dimensions where points were lost → cross-reference `execution.response` to see the model's actual output.

## 3. Custom Reports: Markdown Extension Example

`EvaluationReport` does not ship built-in Markdown output (keeping the core minimal), but the string returned by
`to_json()` plus `_compute_summary()` already provide all the data; extended rendering needs only a few lines:

```python
# render_markdown.py —— renders an AIQE report to Markdown (copy and adapt freely)
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

def render_markdown(report_json: dict) -> str:
    """Render the dict returned by to_json() as five-section Markdown
    (see the template in templates/report-template.md)."""
    s = report_json["summary"]
    lines = [
        f"# AIQE Evaluation Report: {report_json['test_plan_id']}",
        "",
        f"- generated at: {report_json['generated_at']}",
        f"- project: {report_json['project']} v{report_json['version']}",
        f"- summary: {s['passed']}/{s['total']} passed"
        + (f", {len(s['regressions'])} regression(s)" if s["regressions"] else ""),
        "",
        "## Case details",
        "",
        "| Case | Score | Status | Regression | Main reason for lost points |",
        "|---|---|---|---|---|",
    ]
    for c in report_json["cases"]:
        j = c["judge"]
        r = c.get("regression", {})
        # pick reasons other than "full marks" for quick triage
        bad = [x for x in j.get("reasons", []) if "满分" not in x and "命中" not in x]
        lines.append(
            f"| {c['case_id']} | {j['score']:.2f} | {'passed' if j['passed'] else 'failed'} "
            f"| {r.get('status', '-')} ({r.get('delta', 0.0):+.2f}) "
            f"| {('；'.join(bad))[:60] or '-'} |"
        )
    if s["regressions"]:
        lines += ["", "## Regression verdict", ""]
        lines += [f"- {cid} has a regression" for cid in s["regressions"]]
    lines += ["", "## Recommendation", "",
              "- fill in per the gate rules in Section 3 of process-management.md."]
    return "\n".join(lines)


if __name__ == "__main__":
    # usage: python render_markdown.py <report.json>
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(render_markdown(data))
```

**Extension principle**: custom rendering only **reads** EvaluationReport's output (JSON) and does not modify
framework code; keep the rendering logic in your own project to avoid drifting from the upstream framework.

## 4. Report Quality Checklist

- [ ] The report contains the complete three-part fields `execution` / `judge` / `regression`
- [ ] Test cases with error not None are explicitly flagged in the summary (must not be mixed into the passed statistics)
- [ ] The console summary and the JSON data are consistent (rendered from the same data source)
- [ ] Archive naming includes model/date (e.g. `AIQE-report-<model>-<date>.json`)
- [ ] Reports containing real inputs and outputs do not enter git; sanitize per test-data-management.md before sharing
