# AIQE —— 测试左移（Shift-Left）AI 评估框架参考实现
"""
公共导出：
- TestCase: 单个评估用例
- EvaluationResult: 评估结果
- ScoreBreakdown: 多维度评分
- ModelRunner: 执行器接口
- LocalRunner, OllamaRunner: 具体实现（本地确定性 / Ollama HTTP）

镜像说明（协议副本说明）：本包是 上游项目 仓库内 framework/ai_eval/ 模块集合的
独立导出版，公开 API 同构；Backend Protocol 以 AIQE/protocol.py 单文件镜像
副本提供（协议副本说明：原 上游项目 模块路径为 framework/models/backend.py）。
"""
from AIQE.schema import TestCase, EvaluationResult, ScoreBreakdown
from AIQE.schema import ModelRunner, LocalRunner, OllamaRunner
from AIQE.runner import ExecutionRunner, ExecutionResult
from AIQE.judge import OutputJudge, JudgeResult
from AIQE.regression import RegressionAnalyzer, RegressionResult
from AIQE.reporter import EvaluationReport

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
    "EvaluationReport",
]
