"""Additive, run-level aggregations for the offline quality dashboard.

This module never scores a case and never invents a metric. It combines only
counts and explicit numerator/denominator pairs from the dashboard run payload.
Non-additive statistics such as p50 latency and unweighted judge-score means are
intentionally absent from pivot aggregates.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


STATUS_KEYS = ("passed", "failed", "error", "skipped")
DIMENSIONS = {
    "dataset": ("数据集", lambda run: run["dataset_id"] + "@" + run["dataset_version"]),
    "judge": ("评分器", lambda run: run["judge_id"] + "@" + run["judge_version"]),
    "model": ("模型", lambda run: run["model_id"]),
    "backend": ("后端", lambda run: run["backend_id"]),
    "source": ("来源", lambda run: run["source_type"]),
    "classification": ("数据分级", lambda run: run["data_classification"]),
}
CAPABILITY_GAPS = [
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


def _empty_token_scale() -> dict[str, Any]:
    return {
        "measured": {"value": 0, "run_count": 0},
        "estimated": {"value": 0, "run_count": 0},
        "missing_run_count": 0,
    }


def _empty_row(key: str, label: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "run_count": 0,
        "case_execution_count": 0,
        "case_status_counts": {status: 0 for status in STATUS_KEYS},
        "case_pass_rate": None,
        "execution_success_rate": None,
        "output_tokens": _empty_token_scale(),
    }


def _add_tokens(target: dict[str, Any], run: dict[str, Any]) -> None:
    record = run["metrics"].get("output_tokens")
    value = record.get("metric_value") if record else None
    precision = record.get("precision") if record else None
    status = record.get("status") if record else None
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and status in {"ok", "partial"}
        and precision in {"measured", "estimated"}
    ):
        target[precision]["value"] += value
        target[precision]["run_count"] += 1
    else:
        target["missing_run_count"] += 1


def _add_run(row: dict[str, Any], run: dict[str, Any]) -> None:
    row["run_count"] += 1
    row["case_execution_count"] += run["case_count"]
    for status in STATUS_KEYS:
        row["case_status_counts"][status] += run["case_status_counts"][status]
    _add_tokens(row["output_tokens"], run)


def _finish_row(row: dict[str, Any]) -> None:
    total = row["case_execution_count"]
    if total:
        counts = row["case_status_counts"]
        row["case_pass_rate"] = counts["passed"] / total
        row["execution_success_rate"] = (total - counts["error"]) / total


def build_analysis_payload(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Build additive multidimensional facts from already validated run payloads."""
    rows: dict[str, dict[str, dict[str, Any]]] = {
        dimension: {} for dimension in DIMENSIONS
    }
    totals = {key: 0 for key in STATUS_KEYS}
    total_cases = 0
    run_count = 0
    metric_available = 0
    metric_total = 0
    token_scale = _empty_token_scale()
    for run in runs:
        run_count += 1
        for dimension, (_, key_of) in DIMENSIONS.items():
            key = key_of(run)
            row = rows[dimension].setdefault(key, _empty_row(key, key))
            _add_run(row, run)
        total_cases += run["case_count"]
        for status in STATUS_KEYS:
            totals[status] += run["case_status_counts"][status]
        _add_tokens(token_scale, run)
        for record in run["metrics"].values():
            metric_total += 1
            value = record.get("metric_value")
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and record.get("status") in {"ok", "partial"}
            ):
                metric_available += 1
    for dimension_rows in rows.values():
        for row in dimension_rows.values():
            _finish_row(row)
    return {
        "analysis_version": "aiqe.dashboard-analysis/0.1.0",
        "dimensions": {
            dimension: {
                "label": label,
                "rows": sorted(rows[dimension].values(), key=lambda row: row["key"]),
            }
            for dimension, (label, _) in DIMENSIONS.items()
        },
        "case_status_totals": {**totals, "total": total_cases},
        "scale": {
            "run_count": run_count,
            "case_execution_count": total_cases,
            "output_tokens": token_scale,
            "metric_coverage": {
                "available": metric_available,
                "total": metric_total,
                "ratio": metric_available / metric_total if metric_total else None,
            },
        },
        "capabilities": [dict(item) for item in CAPABILITY_GAPS],
    }
