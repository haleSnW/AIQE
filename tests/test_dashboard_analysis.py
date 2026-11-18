"""Multidimensional dashboard aggregation uses explicit, testable semantics."""

from AIQE.dashboard_analysis import build_analysis_payload


def make_run(run_id, *, model="model-a", passed=0, failed=0, error=0, skipped=0,
             output_tokens=None, precision="measured"):
    count = passed + failed + error + skipped
    metrics = {}
    if output_tokens is not None:
        metrics["output_tokens"] = {
            "metric_value": output_tokens,
            "metric_unit": "tokens",
            "status": "ok",
            "precision": precision,
        }
    return {
        "run_id": run_id,
        "dataset_id": "dataset-a",
        "dataset_version": "1",
        "judge_id": "judge-a",
        "judge_version": "1",
        "model_id": model,
        "backend_id": "backend-a",
        "source_type": "synthetic",
        "data_classification": "public_synthetic",
        "case_count": count,
        "case_status_counts": {
            "passed": passed,
            "failed": failed,
            "error": error,
            "skipped": skipped,
        },
        "metrics": metrics,
    }


def test_pivot_rates_use_each_groups_case_execution_denominator():
    runs = [
        make_run("small", passed=1, failed=1),
        make_run("large", model="model-b", passed=9, failed=1, error=2, skipped=1),
    ]

    payload = build_analysis_payload(runs)
    rows = {row["key"]: row for row in payload["dimensions"]["model"]["rows"]}

    assert rows["model-a"]["case_pass_rate"] == 0.5
    assert rows["model-a"]["execution_success_rate"] == 1.0
    assert rows["model-b"]["case_pass_rate"] == 9 / 13
    assert rows["model-b"]["execution_success_rate"] == 11 / 13
    assert payload["case_status_totals"] == {
        "passed": 10,
        "failed": 2,
        "error": 2,
        "skipped": 1,
        "total": 15,
    }


def test_same_dimension_combines_counts_before_computing_ratios():
    runs = [
        make_run("small", passed=1, failed=1),
        make_run("large", passed=8, failed=2),
    ]

    row = build_analysis_payload(runs)["dimensions"]["model"]["rows"][0]

    assert row["case_pass_rate"] == 9 / 12
    assert row["case_pass_rate"] != (0.5 + 0.8) / 2
    assert row["run_count"] == 2
    assert row["case_execution_count"] == 12


def test_token_scale_separates_estimated_measured_and_missing_runs():
    runs = [
        make_run("measured", output_tokens=100, precision="measured"),
        make_run("estimated", output_tokens=40, precision="estimated"),
        make_run("missing"),
    ]

    scale = build_analysis_payload(runs)["scale"]

    assert scale["run_count"] == 3
    assert scale["case_execution_count"] == 0
    assert scale["output_tokens"] == {
        "measured": {"value": 100, "run_count": 1},
        "estimated": {"value": 40, "run_count": 1},
        "missing_run_count": 1,
    }


def test_all_supported_dimensions_share_the_same_additive_projection():
    payload = build_analysis_payload([make_run("run-a", passed=1)])

    assert set(payload["dimensions"]) == {
        "dataset", "judge", "model", "backend", "source", "classification",
    }
    assert payload["dimensions"]["dataset"]["rows"][0]["key"] == "dataset-a@1"
    assert payload["dimensions"]["judge"]["rows"][0]["key"] == "judge-a@1"
    assert payload["dimensions"]["backend"]["rows"][0]["key"] == "backend-a"
    assert payload["dimensions"]["source"]["rows"][0]["key"] == "synthetic"
    assert payload["dimensions"]["classification"]["rows"][0]["key"] == "public_synthetic"


def test_zero_case_group_has_null_rates_and_explicit_capability_gaps():
    payload = build_analysis_payload([make_run("empty")])
    row = payload["dimensions"]["model"]["rows"][0]

    assert row["case_pass_rate"] is None
    assert row["execution_success_rate"] is None
    assert payload["capabilities"] == [
        {
            "id": "hallucination",
            "status": "unavailable",
            "label": "模型幻觉",
            "reason": "当前结果契约没有已持久化的事实性或幻觉评估；通过率与评分不能替代幻觉率。",
        },
        {
            "id": "flame_graph",
            "status": "unavailable",
            "label": "调用耗时火焰图",
            "reason": "当前只有整次执行耗时，没有 span 父子关系与起止时间，无法还原调用栈。",
        },
    ]


def test_metric_coverage_counts_only_numeric_ok_or_partial_records():
    first = make_run("first", output_tokens=10)
    second = make_run("second")
    second["metrics"]["judge_score"] = {
        "metric_value": None,
        "metric_unit": "score",
        "status": "missing",
        "precision": "not_applicable",
    }
    second["metrics"]["execution_error_count"] = {
        "metric_value": 0,
        "metric_unit": "count",
        "status": "ok",
        "precision": "measured",
    }

    coverage = build_analysis_payload([first, second])["scale"]["metric_coverage"]

    assert coverage == {"available": 2, "total": 3, "ratio": 2 / 3}
