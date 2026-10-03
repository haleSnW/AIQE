# AIQE/comparison.py —— 运行级回归对比（RegressionComparison）
#
# 定位：补齐 RegressionAnalyzer 缺失的**运行级可比性校验**。
#
# 【为什么需要本模块？】
#   RegressionAnalyzer.analyze(case_id, current_score) 只接收用例 id 与分数，
#   完全不校验两次运行是否同源（src/AIQE/regression.py:64-68）。这意味着
#   拿「数据集 v1 的基线」去比「数据集 v2 的结果」也能算出 delta——
#   而那个 delta 没有意义。
#
#   本模块在**不修改** RegressionAnalyzer 公共行为的前提下，
#   在其之上加一层运行级门禁：评估条件不一致时，不产出 delta。
#
# 【阈值语义复用】case 级状态判定复用 regression.classify_delta()，
#   与 RegressionAnalyzer 共享同一份阈值实现，避免两处规则分叉。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from AIQE.contract import (
    EvaluationRun,
    MetricStatus,
    SCHEMA_VERSION,
    _parse_schema_version,
)
from AIQE.regression import DEGRADATION_THRESHOLD, classify_delta

# ════════════════════════════════════════════════════════════════
#  不可比原因码（稳定字符串，供测试与 Dashboard 使用）
# ════════════════════════════════════════════════════════════════

INCOMPARABLE_DATASET_ID = "DATASET_ID_MISMATCH"
INCOMPARABLE_DATASET_VERSION = "DATASET_VERSION_MISMATCH"
INCOMPARABLE_JUDGE_ID = "JUDGE_ID_MISMATCH"
INCOMPARABLE_JUDGE_VERSION = "JUDGE_VERSION_MISMATCH"
INCOMPARABLE_SCHEMA_MAJOR = "SCHEMA_MAJOR_MISMATCH"
INCOMPARABLE_SAME_RUN = "SAME_RUN_ID"

# 软差异：记录下来但不阻断对比（换模型正是回归测试的正当用途）
FLAG_MODEL_CHANGED = "MODEL_CHANGED"
FLAG_BACKEND_CHANGED = "BACKEND_CHANGED"
FLAG_SOURCE_TYPE_CHANGED = "SOURCE_TYPE_CHANGED"
FLAG_CASE_SET_DIFFERS = "CASE_SET_DIFFERS"


@dataclass(frozen=True)
class CaseComparison:
    """单个用例的基线↔候选对比。"""
    case_id: str
    baseline_score: float | None
    candidate_score: float | None
    delta: float | None
    status: str          # pass / degraded / regression / new / removed

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "baseline_score": self.baseline_score,
            "candidate_score": self.candidate_score,
            "delta": None if self.delta is None else round(self.delta, 4),
            "status": self.status,
        }


@dataclass
class RegressionComparison:
    """两次评估运行之间的回归对比结论。

    【核心不变式】comparable=False 时 case_comparisons 必为空列表，
    且 metric_deltas 必为空字典。**不可比时绝不产出 delta**——
    产出再标注「仅供参考」是危险的，因为下游很容易忽略标注。
    """
    baseline_run_id: str
    candidate_run_id: str
    comparable: bool
    incomparable_reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    degradation_threshold: float = DEGRADATION_THRESHOLD
    case_comparisons: list[CaseComparison] = field(default_factory=list)
    metric_deltas: dict[str, float] = field(default_factory=dict)
    baseline_conditions: dict[str, Any] = field(default_factory=dict)
    candidate_conditions: dict[str, Any] = field(default_factory=dict)

    @property
    def regression_count(self) -> int:
        return sum(1 for c in self.case_comparisons if c.status == "regression")

    @property
    def degraded_count(self) -> int:
        return sum(1 for c in self.case_comparisons if c.status == "degraded")

    @property
    def regressed_case_ids(self) -> list[str]:
        return [c.case_id for c in self.case_comparisons if c.status == "regression"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_run_id": self.baseline_run_id,
            "candidate_run_id": self.candidate_run_id,
            "comparable": self.comparable,
            "incomparable_reasons": self.incomparable_reasons,
            "flags": self.flags,
            "degradation_threshold": self.degradation_threshold,
            "baseline_conditions": self.baseline_conditions,
            "candidate_conditions": self.candidate_conditions,
            "case_comparisons": [c.to_dict() for c in self.case_comparisons],
            "metric_deltas": {k: round(v, 6) for k, v in self.metric_deltas.items()},
            "summary": {
                "regression_count": self.regression_count,
                "degraded_count": self.degraded_count,
                "regressed_case_ids": self.regressed_case_ids,
            },
        }


def _conditions(run: EvaluationRun) -> dict[str, Any]:
    """提取用于可比性判定与留证的评估条件快照。"""
    metadata = run.metadata
    return {
        "run_id": metadata.run_id,
        "created_at": metadata.created_at,
        "dataset_id": metadata.dataset_id,
        "dataset_version": metadata.dataset_version,
        "judge_id": metadata.judge_id,
        "judge_version": metadata.judge_version,
        "model_id": metadata.model_id,
        "backend_id": metadata.backend_id,
        "source_type": metadata.source_type.value,
        "data_classification": metadata.data_classification.value,
        "schema_version": run.document.get("schema_version", SCHEMA_VERSION),
    }


def check_comparable(
    baseline: EvaluationRun, candidate: EvaluationRun
) -> tuple[bool, list[str], list[str]]:
    """判定两次运行是否可比较。返回 (comparable, reasons, flags)。

    【硬条件（阻断）—— 测量条件必须一致】
      dataset_id / dataset_version / judge_id / judge_version / schema 主版本

      为什么是这些？它们决定「分数代表什么」：
        - 数据集不同 → 题目不同，分数不可比
        - 数据集版本不同 → 同一数据集的题目可能已增删改
        - 评分器不同/版本不同 → 同一份响应会得到不同分数
        - schema 主版本不同 → 字段语义可能已变

    【软条件（仅记录 flag）—— 被测量的对象可以不同】
      model_id / backend_id / source_type

      为什么换模型不阻断？**换模型正是回归测试的正当用途**：
      「同一套题、同一个评分器，新模型比旧模型好还是差」是有效问题。
      但差异必须被记录，因为跨模型的绝对分数不能横向排名。
    """
    reasons: list[str] = []
    flags: list[str] = []

    if baseline.run_id == candidate.run_id:
        reasons.append(INCOMPARABLE_SAME_RUN)

    base_meta, cand_meta = baseline.metadata, candidate.metadata

    if base_meta.dataset_id != cand_meta.dataset_id:
        reasons.append(INCOMPARABLE_DATASET_ID)
    if base_meta.dataset_version != cand_meta.dataset_version:
        reasons.append(INCOMPARABLE_DATASET_VERSION)
    if base_meta.judge_id != cand_meta.judge_id:
        reasons.append(INCOMPARABLE_JUDGE_ID)
    if base_meta.judge_version != cand_meta.judge_version:
        reasons.append(INCOMPARABLE_JUDGE_VERSION)

    try:
        base_major, _, _ = _parse_schema_version(baseline.document.get("schema_version"))
        cand_major, _, _ = _parse_schema_version(candidate.document.get("schema_version"))
        if base_major != cand_major:
            reasons.append(INCOMPARABLE_SCHEMA_MAJOR)
    except Exception:  # noqa: BLE001 —— 版本不可解析时按不可比处理（失败关闭）
        reasons.append(INCOMPARABLE_SCHEMA_MAJOR)

    if base_meta.model_id != cand_meta.model_id:
        flags.append(FLAG_MODEL_CHANGED)
    if base_meta.backend_id != cand_meta.backend_id:
        flags.append(FLAG_BACKEND_CHANGED)
    if base_meta.source_type != cand_meta.source_type:
        flags.append(FLAG_SOURCE_TYPE_CHANGED)

    base_ids = {c.case_id for c in baseline.cases}
    cand_ids = {c.case_id for c in candidate.cases}
    if base_ids != cand_ids:
        flags.append(FLAG_CASE_SET_DIFFERS)

    return (not reasons), reasons, flags


def compare_runs(baseline: EvaluationRun, candidate: EvaluationRun) -> RegressionComparison:
    """对比两次运行，产出回归结论。

    【不可比时的行为】返回 comparable=False 的结论，case_comparisons 为空、
    metric_deltas 为空。调用方必须显式检查 comparable，不得假设有 delta。
    """
    comparable, reasons, flags = check_comparable(baseline, candidate)

    comparison = RegressionComparison(
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        comparable=comparable,
        incomparable_reasons=reasons,
        flags=flags,
        baseline_conditions=_conditions(baseline),
        candidate_conditions=_conditions(candidate),
    )

    if not comparable:
        return comparison

    base_scores = {c.case_id: c.score for c in baseline.cases}
    cand_scores = {c.case_id: c.score for c in candidate.cases}

    for case_id in sorted(set(base_scores) | set(cand_scores)):
        base_score = base_scores.get(case_id)
        cand_score = cand_scores.get(case_id)

        if base_score is None or cand_score is None:
            # 只在一侧出现，或某一侧缺分数 —— 无法计算 delta
            comparison.case_comparisons.append(CaseComparison(
                case_id=case_id,
                baseline_score=base_score,
                candidate_score=cand_score,
                delta=None,
                status="new" if base_score is None else "removed",
            ))
            continue

        delta = cand_score - base_score
        comparison.case_comparisons.append(CaseComparison(
            case_id=case_id,
            baseline_score=base_score,
            candidate_score=cand_score,
            delta=delta,
            status=classify_delta(delta, DEGRADATION_THRESHOLD),
        ))

    # ── run 级指标 delta ─────────────────────────────────────
    # 只对**两侧都是 OK 状态**的指标计算 delta。任一侧缺失（null）就不产出
    # delta —— 把缺失当 0 参与相减会制造虚假的「巨大改善/退化」。
    for metric_id in sorted({m.metric_id for m in baseline.metrics}):
        base_metric = baseline.metric(metric_id)
        cand_metric = candidate.metric(metric_id)
        if base_metric is None or cand_metric is None:
            continue
        if base_metric.status is not MetricStatus.OK:
            continue
        if cand_metric.status is not MetricStatus.OK:
            continue
        if base_metric.metric_value is None or cand_metric.metric_value is None:
            continue
        if base_metric.metric_version != cand_metric.metric_version:
            continue
        if base_metric.metric_unit != cand_metric.metric_unit:
            continue
        if base_metric.precision is not cand_metric.precision:
            # 估算值与实测值不可相减
            continue
        comparison.metric_deltas[metric_id] = (
            float(cand_metric.metric_value) - float(base_metric.metric_value)
        )

    return comparison
