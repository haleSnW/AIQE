# AIQE —— 测试左移（Shift-Left）AI 评估框架参考实现
"""
公共导出：
- TestCase: 单个评估用例
- EvaluationResult: 评估结果
- ScoreBreakdown: 多维度评分
- ModelRunner: 执行器接口
- LocalRunner, OllamaRunner: 具体实现（本地确定性 / Ollama HTTP）
"""
from AIQE.schema import TestCase, EvaluationResult, ScoreBreakdown
from AIQE.schema import ModelRunner, LocalRunner, OllamaRunner
from AIQE.runner import ExecutionRunner, ExecutionResult
from AIQE.judge import OutputJudge, JudgeResult
from AIQE.regression import RegressionAnalyzer, RegressionResult, classify_delta
from AIQE.reporter import EvaluationReport

# 统一结果数据契约（v0.1）—— 验证 + 指标聚合 + 运行级回归对比
from AIQE.contract import (
    SCHEMA_VERSION,
    METRICS_VERSION,
    CaseStatus,
    ContractViolation,
    DataClassification,
    EvaluationMetadata,
    EvaluationRun,
    MetricPrecision,
    MetricRecord,
    MetricStatus,
    SourceType,
    build_run,
    compute_run_metrics,
    load_run,
    validate_run,
)
from AIQE.comparison import RegressionComparison, compare_runs
from AIQE.synthetic import GENERATOR_ID, write_fixtures

# AIQE 框架版本（参考实现 v0.1）
__version__ = "0.1.0"

__all__ = [
    "TestCase",
    "EvaluationResult",
    "ScoreBreakdown",
    "ModelRunner",
    "LocalRunner",
    "OllamaRunner",
    "ExecutionRunner",
    "ExecutionResult",
    "OutputJudge",
    "JudgeResult",
    "RegressionAnalyzer",
    "RegressionResult",
    "classify_delta",
    "EvaluationReport",
    # ── 结果契约 ──
    "SCHEMA_VERSION",
    "METRICS_VERSION",
    "ContractViolation",
    "SourceType",
    "DataClassification",
    "CaseStatus",
    "MetricStatus",
    "MetricPrecision",
    "EvaluationMetadata",
    "MetricRecord",
    "EvaluationRun",
    "validate_run",
    "build_run",
    "load_run",
    "compute_run_metrics",
    "RegressionComparison",
    "compare_runs",
    "GENERATOR_ID",
    "write_fixtures",
]
