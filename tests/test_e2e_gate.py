"""AIQE E2E 质量门禁测试。

覆盖三件事：
  1. Playwright JSON 报告解析只取结果字段，结构不符就失败关闭；
  2. 判定规则（基线比较 + healer diff 守卫）是确定性的，原因码稳定；
  3. 投影后的文档能被同一份结果契约与看板读回，且不夹带错误消息正文。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from AIQE import e2e_gate as g
from AIQE.contract import CaseStatus, DataClassification, SourceType, validate_run
from AIQE.dashboard import load_runs

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "e2e_gate"
FIXED_AT = "2026-11-12T00:00:00+00:00"


# ── 报告构造器 ─────────────────────────────────────────────────

def _result(status="passed", retry=0, message=None, trace=True, duration=1000):
    item = {"status": status, "duration": duration, "retry": retry, "errors": [], "attachments": []}
    if message:
        item["errors"] = [{"message": message}]
    if trace and status != "passed":
        item["attachments"] = [{"name": "trace", "contentType": "application/zip", "path": "t.zip"}]
    return item


def _test(outcome="expected", results=None, expected="passed", annotations=(), project="chromium"):
    return {
        "projectName": project,
        "expectedStatus": expected,
        "annotations": [{"type": a} for a in annotations],
        "status": outcome,
        "results": results if results is not None else [_result()],
    }


def _report(specs, errors=(), file="a.spec.ts", describe="suite"):
    """specs: {title: test-dict 或 test-dict 列表}"""
    spec_items = []
    for title, tests in specs.items():
        tests = tests if isinstance(tests, list) else [tests]
        spec_items.append({"title": title, "file": file, "tests": tests})
    return {
        "config": {"version": "1.56.1"},
        "suites": [{"title": file, "file": file, "specs": [],
                    "suites": [{"title": describe, "file": file, "specs": spec_items}]}],
        "errors": list(errors),
        "stats": {"startTime": "2026-11-12T00:00:00.000Z"},
    }


def _gate(report, baseline=None, patch=None, **kwargs):
    cases, facts = g.parse_playwright_report(report)
    base_cases = base_facts = None
    if baseline is not None:
        base_cases, base_facts = g.parse_playwright_report(baseline)
    return g.evaluate(cases, facts, baseline_cases=base_cases, baseline_facts=base_facts,
                      patch_text=patch, evaluated_at=FIXED_AT, **kwargs)


def _codes(result):
    return sorted(f.code for f in result.findings)


# ════════════════════════════════════════════════════════════════
#  1. 解析
# ════════════════════════════════════════════════════════════════

def test_parse_builds_stable_case_ids_and_kinds():
    report = _report({
        "ok": _test(),
        "assert": _test("unexpected", [_result("failed", message="expect(locator).toHaveText failed")]),
        "timeout": _test("unexpected", [_result("timedOut", message="Test timeout of 30000ms exceeded")]),
        "crash": _test("unexpected", [_result("failed", message="browserType.launch: Target closed")]),
        "flaky": _test("flaky", [_result("failed", message="x"), _result("passed", retry=1)]),
    })
    cases, facts = g.parse_playwright_report(report)
    by_title = {c.title.split(" › ")[-1]: c for c in cases}
    assert by_title["ok"].case_id == "chromium › a.spec.ts › suite › ok"
    assert by_title["assert"].failure_kind == "ASSERTION"
    assert by_title["timeout"].failure_kind == "TIMEOUT"
    assert by_title["crash"].failure_kind == "RUNTIME"
    assert by_title["flaky"].attempts == 2 and by_title["flaky"].failure_kind is None
    assert facts["projects"] == ["chromium"]


def test_same_spec_in_two_projects_is_two_cases():
    report = _report({"t": [_test(project="chromium"), _test(project="webkit")]})
    cases, facts = g.parse_playwright_report(report)
    assert len(cases) == 2
    assert facts["projects"] == ["chromium", "webkit"]


@pytest.mark.parametrize("document", [[], {}, {"suites": "x"}, {"suites": [1]}])
def test_non_report_fails_closed(document):
    with pytest.raises(g.GateInputError):
        g.parse_playwright_report(document)


def test_duplicate_case_id_fails_closed():
    report = _report({"t": [_test(), _test()]})
    with pytest.raises(g.GateInputError):
        g.parse_playwright_report(report)


def test_unreadable_report_fails_closed(tmp_path):
    bad = tmp_path / "r.json"
    bad.write_bytes(b"\xff\xfe not json")
    with pytest.raises(g.GateInputError):
        g.load_playwright_report(bad)


# ════════════════════════════════════════════════════════════════
#  2. 报告与基线规则
# ════════════════════════════════════════════════════════════════

def test_all_green_passes():
    result = _gate(_report({"a": _test(), "b": _test()}))
    assert result.verdict is g.Verdict.PASS and result.exit_code == 0 and result.findings == []


def test_empty_report_is_never_pass():
    result = _gate(_report({}))
    assert result.verdict is g.Verdict.BLOCK
    assert _codes(result) == [g.EVIDENCE_EMPTY]


def test_top_level_errors_block():
    result = _gate(_report({"a": _test()}, errors=[{"message": "config error"}]))
    assert g.REPORT_ERRORS in _codes(result) and result.verdict is g.Verdict.BLOCK


def test_failure_without_baseline_is_unexpected_failure():
    result = _gate(_report({"a": _test("unexpected", [_result("failed", message="expect(")])}))
    assert _codes(result) == [g.UNEXPECTED_FAILURE]


def test_failure_without_trace_also_escalates_evidence_gap():
    failing = _test("unexpected", [_result("failed", message="expect(", trace=False)])
    result = _gate(_report({"a": failing}))
    assert _codes(result) == [g.TRACE_MISSING, g.UNEXPECTED_FAILURE]
    assert _codes(_gate(_report({"a": failing}), require_trace_on_failure=False)) == [g.UNEXPECTED_FAILURE]


def test_new_vs_persistent_failure_against_baseline():
    fail = _test("unexpected", [_result("failed", message="expect(")])
    baseline = _report({"was_green": _test(), "was_red": fail})
    current = _report({"was_green": fail, "was_red": fail})
    result = _gate(current, baseline)
    by_case = {f.case_id.split(" › ")[-1]: f.code for f in result.findings}
    assert by_case == {"was_green": g.NEW_FAILURE, "was_red": g.PERSISTENT_FAILURE}


def test_fixed_cases_are_reported_in_baseline_summary():
    fail = _test("unexpected", [_result("failed", message="expect(")])
    result = _gate(_report({"a": _test()}), _report({"a": fail}))
    assert result.verdict is g.Verdict.PASS
    assert result.baseline["fixed"] == ["chromium › a.spec.ts › suite › a"]


def test_flaky_escalates():
    flaky = _test("flaky", [_result("failed", message="x"), _result("passed", retry=1)])
    result = _gate(_report({"a": flaky}))
    assert result.verdict is g.Verdict.ESCALATE and result.exit_code == 2
    assert _codes(result) == [g.FLAKY]


def test_removed_and_newly_skipped_tests_escalate():
    baseline = _report({"kept": _test(), "gone": _test(), "skip_me": _test()})
    current = _report({"kept": _test(), "skip_me": _test("skipped", [])})
    result = _gate(current, baseline)
    assert _codes(result) == [g.SKIP_ADDED, g.TEST_REMOVED]
    assert result.verdict is g.Verdict.ESCALATE


def test_test_fail_annotation_is_not_silently_green():
    marked = _test("expected", [_result("failed", message="expect(")], expected="failed", annotations=("fail",))
    result = _gate(_report({"a": marked}))
    assert _codes(result) == [g.EXPECTED_FAILURE_MARKED]
    assert result.counts()["passed"] == 0


def test_project_set_change_makes_baseline_incomparable():
    result = _gate(_report({"a": _test(project="webkit")}), _report({"a": _test(project="chromium")}))
    assert g.BASELINE_INCOMPARABLE in _codes(result)


# ════════════════════════════════════════════════════════════════
#  3. healer diff 守卫
# ════════════════════════════════════════════════════════════════

def _diff(removed=(), added=(), context=(), path="tests/a.spec.ts", start=10):
    body = [f" {line}" for line in context] + [f"-{line}" for line in removed] + [f"+{line}" for line in added]
    old = len(context) + len(removed)
    new = len(context) + len(added)
    return "\n".join([
        f"diff --git a/{path} b/{path}",
        f"--- a/{path}",
        f"+++ b/{path}",
        f"@@ -{start},{old} +{start},{new} @@",
        *body,
    ]) + "\n"


def _patch_codes(text, **kwargs):
    return sorted(f.code for f in g.inspect_patch(text, **kwargs))


def test_honest_locator_fix_has_no_findings():
    text = _diff(removed=["await page.locator('#coupon').fill('X');"],
                 added=["await page.getByLabel('Coupon code').fill('X');"],
                 context=["await expect(total).toHaveText('$90.00');"])
    assert _patch_codes(text) == []


def test_removed_assertion_blocks():
    text = _diff(removed=["await expect(page).toHaveURL(/orders/);"])
    assert _patch_codes(text) == [g.ASSERTION_REMOVED]


def test_commented_out_assertion_counts_as_removed():
    text = _diff(removed=["await expect(status).toHaveText('ok');"],
                 added=["// await expect(status).toHaveText('ok');"])
    assert _patch_codes(text) == [g.ASSERTION_REMOVED]


@pytest.mark.parametrize("loose", [
    "await expect(status).toBeVisible();",
    "await expect(status).toHaveText(/.*/);",
    "expect(count).toBeGreaterThanOrEqual(0);",
    "expect(value).toBeTruthy();",
])
def test_strict_matcher_replaced_by_loose_one_blocks(loose):
    text = _diff(removed=["await expect(status).toHaveText('Order confirmed');"], added=[loose])
    assert _patch_codes(text) == [g.MATCHER_LOOSENED]


def test_swallowed_failure_blocks():
    text = _diff(removed=["await page.click('#buy');"],
                 added=["await page.click('#buy').catch(() => {});"])
    assert _patch_codes(text) == [g.ASSERTION_SWALLOWED]


@pytest.mark.parametrize("marker", [
    "test.skip('flaky on CI', async () => {",
    "test.fixme();",
    "test.describe.skip('checkout', () => {",
    "test.only('focus', async () => {",
    "@pytest.mark.skip(reason='later')",
])
def test_disabling_markers_block(marker):
    assert _patch_codes(_diff(added=[marker])) == [g.TEST_DISABLED]


def test_moving_an_existing_skip_is_not_new():
    text = _diff(removed=["test.skip(isMobile);"], added=["  test.skip(isMobile);"])
    assert _patch_codes(text) == []


def test_force_and_timeout_inflation_escalate():
    text = _diff(removed=["await btn.click({ timeout: 5000 });"],
                 added=["await btn.click({ timeout: 60000, force: true });"])
    assert _patch_codes(text) == [g.FORCE_ACTION, g.TIMEOUT_INFLATED]


def test_new_timeout_only_counts_above_default():
    assert _patch_codes(_diff(added=["await el.waitFor({ timeout: 5000 });"])) == []
    assert _patch_codes(_diff(added=["test.setTimeout(120000);"])) == [g.TIMEOUT_INFLATED]
    assert _patch_codes(_diff(added=["test.slow();"])) == [g.TIMEOUT_INFLATED]


def test_touching_product_code_is_scope_violation():
    text = _diff(removed=["return status;"], added=["return 'Order confirmed';"], path="src/checkout/status.ts")
    assert _patch_codes(text) == [g.SCOPE_VIOLATION]
    assert _patch_codes(text, allowed_paths=("src/*",)) == []


def test_deleting_a_whole_spec_file_counts_removed_assertions():
    text = "\n".join([
        "diff --git a/tests/a.spec.ts b/tests/a.spec.ts",
        "deleted file mode 100644",
        "--- a/tests/a.spec.ts",
        "+++ /dev/null",
        "@@ -1,2 +0,0 @@",
        "-test('a', async () => {",
        "-  await expect(page).toHaveTitle('A');",
    ]) + "\n"
    assert _patch_codes(text) == [g.ASSERTION_REMOVED]


def test_content_line_that_looks_like_header_is_not_a_header():
    # 被删除的内容行恰好以 "-- " 开头时，显示为 "--- "；按 hunk 行数消费就不会误判为文件头
    text = _diff(removed=["-- expect(old).toBe(1)"], added=["-- expect(old).toBe(1)"])
    assert _patch_codes(text) == []


# ════════════════════════════════════════════════════════════════
#  4. 示例场景（与 examples/e2e_gate_demo.py 同一组输入）
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("report,baseline,patch,verdict,codes", [
    ("01-baseline.json", None, None, "PASS", []),
    ("02-candidate-red.json", "01-baseline.json", None, "BLOCK", [g.NEW_FAILURE, g.NEW_FAILURE]),
    ("03-healed-honest.json", "01-baseline.json", "patch-honest.diff", "BLOCK", [g.NEW_FAILURE]),
    ("04-healed-cheating.json", "01-baseline.json", "patch-cheating.diff", "BLOCK",
     [g.ASSERTION_REMOVED, g.MATCHER_LOOSENED]),
    ("05-product-fixed.json", "01-baseline.json", "patch-honest.diff", "PASS", []),
    ("06-flaky.json", "01-baseline.json", None, "ESCALATE", [g.FLAKY]),
])
def test_example_scenarios(report, baseline, patch, verdict, codes):
    result = g.run_gate(
        EXAMPLES / report,
        baseline=EXAMPLES / baseline if baseline else None,
        patch=EXAMPLES / patch if patch else None,
        evaluated_at=FIXED_AT,
    )
    assert result.verdict.value == verdict
    assert _codes(result) == sorted(codes)


def test_cheating_heal_is_all_green_in_playwright_but_blocked():
    result = g.run_gate(EXAMPLES / "04-healed-cheating.json", patch=EXAMPLES / "patch-cheating.diff")
    assert result.counts()["failed"] == 0
    assert result.verdict is g.Verdict.BLOCK


def test_gate_is_deterministic():
    kwargs = dict(baseline=EXAMPLES / "01-baseline.json", patch=EXAMPLES / "patch-cheating.diff",
                  evaluated_at=FIXED_AT)
    first = g.run_gate(EXAMPLES / "04-healed-cheating.json", **kwargs).to_dict()
    second = g.run_gate(EXAMPLES / "04-healed-cheating.json", **kwargs).to_dict()
    assert first == second
    assert set(first["inputs"]) == {"report_sha256", "baseline_sha256", "patch_sha256"}


# ════════════════════════════════════════════════════════════════
#  5. 投影为结果契约
# ════════════════════════════════════════════════════════════════

def _projected(report="02-candidate-red.json", **kwargs):
    result = g.run_gate(EXAMPLES / report, baseline=EXAMPLES / "01-baseline.json", evaluated_at=FIXED_AT)
    return g.to_result_document(result, run_id="e2e-test", **kwargs)


def test_projection_round_trips_through_contract():
    document = _projected()
    run = validate_run(document, allowed_source_types={SourceType.LOCAL_TEST})
    statuses = {c.case_id.split(" › ")[-1]: c.status for c in run.cases}
    assert statuses["shows order confirmation"] is CaseStatus.FAILED   # 断言失败 = 判定失败
    assert statuses["applies coupon"] is CaseStatus.ERROR              # 超时 = 执行异常
    assert statuses["adds item to cart"] is CaseStatus.PASSED
    assert run.metadata.source_type is SourceType.LOCAL_TEST
    assert run.metadata.data_classification is DataClassification.INTERNAL
    assert document["e2e_gate"]["verdict"] == "BLOCK"


def test_projection_is_rejected_by_default_synthetic_only_contract():
    from AIQE.contract import ContractViolation
    with pytest.raises(ContractViolation):
        validate_run(_projected())


def test_projection_carries_codes_not_messages():
    text = json.dumps(_projected(), ensure_ascii=False)
    assert "Payment pending" not in text          # 失败消息正文
    assert "test-results/trace.zip" not in text   # 附件路径
    assert "waiting for locator" not in text
    assert "NEW_FAILURE" in text and "E2E_TIMEOUT" in text


def test_dashboard_reads_projected_runs_only_when_local_test_is_allowed(tmp_path):
    (tmp_path / "run.json").write_text(json.dumps(_projected(data_classification=DataClassification.PUBLIC_SYNTHETIC)))
    loaded, failures = load_runs([tmp_path])
    assert loaded == [] and failures[0].reason_code == "SOURCE_TYPE_NOT_ALLOWED"
    loaded, failures = load_runs([tmp_path], allowed_source_types={SourceType.SYNTHETIC, SourceType.LOCAL_TEST})
    assert failures == [] and len(loaded) == 1


# ════════════════════════════════════════════════════════════════
#  6. 命令行
# ════════════════════════════════════════════════════════════════

def test_cli_exit_codes_and_outputs(tmp_path, capsys):
    out, md, res = tmp_path / "gate.json", tmp_path / "summary.md", tmp_path / "run.json"
    code = g.main([
        "--report", str(EXAMPLES / "04-healed-cheating.json"),
        "--baseline", str(EXAMPLES / "01-baseline.json"),
        "--patch", str(EXAMPLES / "patch-cheating.diff"),
        "--out", str(out), "--markdown", str(md), "--result-out", str(res), "--sut-id", "build-42",
    ])
    assert code == 1
    assert json.loads(out.read_text())["verdict"] == "BLOCK"
    assert "MATCHER_LOOSENED" in md.read_text()
    run = validate_run(json.loads(res.read_text()), allowed_source_types={SourceType.LOCAL_TEST})
    assert run.metadata.model_id == "build-42"
    assert "BLOCK" in capsys.readouterr().out

    assert g.main(["--report", str(EXAMPLES / "01-baseline.json")]) == 0
    assert g.main(["--report", str(EXAMPLES / "06-flaky.json")]) == 2


def test_cli_bad_input_exit_3(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{}")
    assert g.main(["--report", str(bad)]) == 3


# ════════════════════════════════════════════════════════════════
#  7. diff 发现归属到用例
# ════════════════════════════════════════════════════════════════

def test_patch_findings_are_attributed_to_the_enclosing_spec():
    result = g.run_gate(EXAMPLES / "04-healed-cheating.json", patch=EXAMPLES / "patch-cheating.diff")
    owners = {c for f in result.findings for c in f.attributed_cases}
    assert owners == {"chromium › checkout.spec.ts › checkout › shows order confirmation"}


def test_attribution_needs_matching_file_and_line():
    cases, _ = g.parse_playwright_report(json.loads((EXAMPLES / "01-baseline.json").read_text()))
    other_file = g.Finding(g.ASSERTION_REMOVED, g.Verdict.BLOCK, "x", file="tests/other.spec.ts", line=18)
    before_any_spec = g.Finding(g.ASSERTION_REMOVED, g.Verdict.BLOCK, "x", file="tests/checkout.spec.ts", line=2)
    no_line = g.Finding(g.SCOPE_VIOLATION, g.Verdict.BLOCK, "x", file="tests/checkout.spec.ts")
    for item in g.attribute_findings([other_file, before_any_spec, no_line], cases):
        assert item.attributed_cases == ()


def test_weakened_case_is_not_counted_as_passed_on_dashboard():
    result = g.run_gate(EXAMPLES / "04-healed-cheating.json", patch=EXAMPLES / "patch-cheating.diff",
                        evaluated_at=FIXED_AT)
    run = validate_run(g.to_result_document(result, run_id="x"), allowed_source_types={SourceType.LOCAL_TEST})
    statuses = {c.case_id.split(" › ")[-1]: c.status for c in run.cases}
    assert statuses["shows order confirmation"] is CaseStatus.SKIPPED   # 未判定，不算通过
    assert statuses["applies coupon"] is CaseStatus.PASSED             # 诚实修复的用例照常计入
    weakened = next(c for c in run.cases if c.case_id.endswith("shows order confirmation"))
    assert weakened.raw["judge"]["reasons"] == [g.ASSERTION_REMOVED, g.MATCHER_LOOSENED]


def test_all_skipped_has_no_executed_evidence():
    result = _gate(_report({"unavailable": _test("skipped", [], expected="skipped")}))
    assert result.verdict is g.Verdict.BLOCK
    assert g.EVIDENCE_EMPTY in _codes(result)


def test_malformed_nested_suite_fails_closed():
    report = _report({"a": _test()})
    report["suites"][0]["suites"].append(None)
    with pytest.raises(g.GateInputError):
        g.parse_playwright_report(report)


def test_result_summary_counts_only_judged_passes():
    result = g.run_gate(
        EXAMPLES / "04-healed-cheating.json",
        patch=EXAMPLES / "patch-cheating.diff",
    )
    document = g.to_result_document(result, run_id="summary-check")
    assert document["summary"]["passed"] == sum(
        case["judge"]["passed"] is True for case in document["cases"]
    )
