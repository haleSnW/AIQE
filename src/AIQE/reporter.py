# AIQE/reporter.py —— EvaluationReport：聚合用例结果，输出 JSON 报告
# + 控制台条形图摘要。
#
# 报告 JSON 结构：
#   test_plan_id / generated_at / project / version / cases / summary
# 每个 case 含 execution（响应原文、耗时、backend、error、trace_id、
# payload_hash）、judge（评分明细）、可选 regression（回归结论）。

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from AIQE.judge import JudgeResult
from AIQE.regression import RegressionResult
from AIQE.schema import TestCase

logger = logging.getLogger(__name__)

_VERSION = "0.1.0"
_PROJECT = "AIQE"


class EvaluationReport:
    """AIQE 评估报告：聚合多用例结果，支持 JSON 序列化与控制台摘要。"""

    def __init__(self, test_plan_id: str) -> None:
        self.test_plan_id = test_plan_id
        self.generated_at = datetime.now(timezone.utc).isoformat()
        self.cases: list[dict[str, Any]] = []
        self.project = _PROJECT
        self.version = _VERSION

    def add_case(
        self,
        case: TestCase,
        execution_result: Any,   # ExecutionResult
        judge_result: JudgeResult,
        regression_result: RegressionResult | None = None,
    ) -> None:
        """追加一个用例的结果到报告。"""
        entry: dict[str, Any] = {
            "case_id": case.id,
            "category": case.category,
            "prompt": case.prompt,
            "execution": {
                "response": execution_result.response,
                "tokens_generated": execution_result.tokens_generated,
                "elapsed_sec": execution_result.elapsed_sec,
                "tok_per_sec": execution_result.tok_per_sec,
                "backend": execution_result.backend,
                "model_id": execution_result.model_id,
                "error": execution_result.error,
                "trace_id": getattr(execution_result, "trace_id", ""),
                "payload_hash": getattr(execution_result, "payload_hash", ""),
            },
            "judge": judge_result.to_dict(),
        }
        if regression_result is not None:
            entry["regression"] = regression_result.to_dict()
        self.cases.append(entry)

    def to_json(self, path: Path | None = None) -> str:
        """序列化为 JSON 字符串；若 path 非空则同时写入文件。"""
        payload = {
            "test_plan_id": self.test_plan_id,
            "generated_at": self.generated_at,
            "project": self.project,
            "version": self.version,
            "cases": self.cases,
            "summary": self._compute_summary(),
        }
        json_str = json.dumps(payload, ensure_ascii=False, indent=2)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            try:
                tmp.write_text(json_str, encoding="utf-8")
                tmp.replace(path)
            except OSError as e:
                logger.error("Failed to write report to %s: %s", path, e)
        return json_str

    def print_summary(self) -> None:
        """在控制台打印条形图摘要（不写文件）。"""
        summary = self._compute_summary()
        total = summary["total"]
        passed = summary["passed"]
        regressions = summary.get("regressions", [])

        sep = "═" * 48
        print(f"\n{sep}")
        print(f"  AIQE Evaluation Report")
        print(f"  {_PROJECT} v{self.version} · {self.generated_at}")
        print(sep)
        print()

        for case in self.cases:
            cid = case["case_id"]
            score = case["judge"]["score"]
            check_mark = "✓" if case["judge"]["passed"] else "✗"
            bar_len = int(round(score * 10))
            bar = "█" * bar_len + "░" * (10 - bar_len)
            print(f"  {cid:<20} {bar}  {score:.2f}  {check_mark}")

        print()
        print(f"  Summary: {passed}/{total} passed", end="")
        if regressions:
            print(f" · {len(regressions)} regression{'s' if len(regressions) > 1 else ''}")
        else:
            print()
        print(sep + "\n")

    def _compute_summary(self) -> dict[str, Any]:
        total = len(self.cases)
        passed = sum(1 for c in self.cases if c["judge"]["passed"])
        regressions = [
            c["case_id"]
            for c in self.cases
            if c.get("regression", {}).get("status") in ("regression", "degraded")
        ]
        return {
            "passed": passed,
            "total": total,
            "regressions": regressions,
        }
