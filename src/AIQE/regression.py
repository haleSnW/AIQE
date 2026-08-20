# AIQE/regression.py —— RegressionAnalyzer：对比历史基线，检测性能回归
#
# 基线文件：<storage_path>/baseline.json，格式见 EvaluationReport。
# 判定规则与阈值：
#   - 无基线文件            → status="new", delta=0.0
#   - score 提升             → status="pass"
#   - score 下降 > 0.15      → status="regression"
#   - score 下降 ≤ 0.15      → status="degraded"

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

RegressionStatus = Literal["pass", "degraded", "regression", "new"]


class RegressionResult:
    """单次回归分析结果。"""
    def __init__(
        self,
        *,
        case_id: str,
        status: RegressionStatus,
        delta: float,
        baseline_score: float | None,
        current_score: float,
    ) -> None:
        self.case_id = case_id
        self.status = status
        self.delta = delta        # current - baseline；正=改善，负=退化
        self.baseline_score = baseline_score
        self.current_score = current_score

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "delta": round(self.delta, 4),
            "baseline_score": self.baseline_score,
            "current_score": round(self.current_score, 4),
        }


class RegressionAnalyzer:
    """对比当前结果与历史基线，判断是否发生性能回归。

    【判定规则】
      - 无基线文件            → status="new", delta=0.0
      - score 提升             → status="pass"
      - score 下降 > 0.15      → status="regression"
      - score 下降 ≤ 0.15      → status="degraded"
    """

    DEGRADATION_THRESHOLD = 0.15

    def __init__(self, storage_path: str | Path = "~/.AIQE/results") -> None:
        self._storage_path = Path(storage_path).expanduser()

    def analyze(
        self,
        case_id: str,
        current_score: float,
        baseline_path: Path | None = None,
    ) -> RegressionResult:
        """分析单个用例的回归状态。

        【参数】
          case_id         : 用例标识
          current_score   : 当前评分（0.0 ~ 1.0）
          baseline_path   : 基线 JSON 文件路径；None 使用默认 <storage_path>/baseline.json

        【返回】
          RegressionResult
        """
        path = baseline_path or (self._storage_path / "baseline.json")
        baseline = self._load_baseline(path)

        if baseline is None:
            return RegressionResult(
                case_id=case_id,
                status="new",
                delta=0.0,
                baseline_score=None,
                current_score=current_score,
            )

        base_score = baseline.get(case_id)
        if base_score is None:
            return RegressionResult(
                case_id=case_id,
                status="new",
                delta=0.0,
                baseline_score=None,
                current_score=current_score,
            )

        delta = current_score - base_score

        if delta > 0:
            status: RegressionStatus = "pass"
        elif delta < -self.DEGRADATION_THRESHOLD:
            status = "regression"
        else:
            status = "degraded"

        return RegressionResult(
            case_id=case_id,
            status=status,
            delta=delta,
            baseline_score=base_score,
            current_score=current_score,
        )

    def _load_baseline(self, path: Path) -> dict[str, float] | None:
        """加载基线 JSON；文件不存在或格式错误时返回 None。"""
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 支持两种格式：顶层 dict{case_id: score} 或 EvaluationReport 嵌套结构
            if isinstance(data, dict) and "cases" in data:
                return {c["case_id"]: c.get("judge", {}).get("score", 0.0) for c in data["cases"]}
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, (int, float))}
            return None
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load baseline from %s: %s", path, e)
            return None
