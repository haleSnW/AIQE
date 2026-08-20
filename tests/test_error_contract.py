"""AIQE 错误契约（Error Contract）测试

错误必须：明确（error 信息非空且可读）、可预测（类型/前缀稳定）、
不 silent fail（禁止 None / empty result / fake success 混入报告）。

覆盖链路：ExecutionRunner 错误 → OutputJudge 不得给假分 →
EvaluationReport 必须携带 error 原文。
"""
import warnings
warnings.filterwarnings("ignore", message=".*cannot collect test class.*")

import json

from AIQE.judge import OutputJudge
from AIQE.reporter import EvaluationReport
from AIQE.runner import ExecutionRunner
from AIQE.schema import TestCase
from AIQE.protocol import GenerateResult
from unittest.mock import MagicMock


def _backend_with_error(exc: Exception) -> MagicMock:
    backend = MagicMock()
    backend.backend_type = MagicMock(value="mock")
    backend.profile.return_value = None
    backend.generate_sync.side_effect = exc
    return backend


def test_error_is_never_none_on_failure():
    """失败路径 error 字段必须是非空字符串（不 silent fail）。"""
    runner = ExecutionRunner(_backend_with_error(RuntimeError("模型未加载")))
    result = runner.run(TestCase(id="t", category="chat", prompt="hi"))
    assert result.error is not None and isinstance(result.error, str) and result.error


def test_error_message_is_predictable_prefix():
    """非预期异常带稳定前缀 execution_error:，原因保留可读。"""
    runner = ExecutionRunner(_backend_with_error(ValueError("连接被拒绝")))
    result = runner.run(TestCase(id="t", category="chat", prompt="hi"))
    assert result.error.startswith("execution_error:")
    assert "连接被拒绝" in result.error


def test_judge_never_fabricates_success_on_failed_execution():
    """执行失败（空响应）→ judge 给 0 分，不因关键词存在而给分。"""
    judge = OutputJudge()
    case = TestCase(id="t", category="chat", prompt="hi",
                    expected_keywords=["hello"], min_length=5)
    result = MagicMock()
    result.response = ""
    result.case_id = "t"
    result.category = "chat"
    result.prompt = "hi"
    result.tokens_generated = 0
    result.elapsed_sec = 0.0
    result.tok_per_sec = 0.0
    result.backend = "mock"
    result.model_id = "m"
    jr = judge.judge(case, result)
    assert jr.score == 0.0
    assert jr.passed is False


def test_report_carries_error_text_not_fake_success():
    """报告 JSON 必须保留执行错误原文（可追溯），而不是假装成功。"""
    report = EvaluationReport(test_plan_id="err-plan")
    case = TestCase(id="t", category="chat", prompt="hi")
    exec_result = MagicMock()
    exec_result.response = ""
    exec_result.tokens_generated = 0
    exec_result.elapsed_sec = 0.0
    exec_result.tok_per_sec = 0.0
    exec_result.backend = "mock"
    exec_result.model_id = "m"
    exec_result.error = "模型未加载"
    exec_result.trace_id = "abc12345"
    exec_result.payload_hash = ""
    judge_result = MagicMock()
    judge_result.to_dict.return_value = {"score": 0.0, "passed": False,
                                         "breakdown": {}, "checks": {},
                                         "reasons": ["响应为空"], "metrics": {}}
    report.add_case(case, exec_result, judge_result)
    parsed = json.loads(report.to_json())
    entry = parsed["cases"][0]
    assert entry["execution"]["error"] == "模型未加载"
    assert entry["judge"]["score"] == 0.0
    assert entry["judge"]["passed"] is False


def test_empty_result_from_backend_is_not_fake_success():
    """后端返回空文本（非异常）→ 执行层不误判成功也不误判失败，
    错误语义交由 judge 的 empty_response 检查显式给 0 分。"""
    backend = MagicMock()
    backend.backend_type = MagicMock(value="mock")
    backend.profile.return_value = None
    backend.generate_sync.return_value = GenerateResult(
        text="", tokens_generated=0, elapsed_sec=0.0, tok_per_sec=0.0, thinking=""
    )
    runner = ExecutionRunner(backend)
    result = runner.run(TestCase(id="t", category="chat", prompt="hi"))
    # 执行层：不抛异常 → success True 但响应为空（可验证状态）
    assert result.success is True
    assert result.response == ""
    # judge 层：空响应 → 显式 0 分 + passed=False（不 silent）
    judge = OutputJudge()
    jr = judge.judge(TestCase(id="t", category="chat", prompt="hi"), result)
    assert jr.score == 0.0
    assert jr.passed is False
    assert jr.checks["empty_response"] is True
