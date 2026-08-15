"""AIQE runner + judge + reporter + regression —— 镜像契约测试

镜像说明：本文件是 上游项目 仓库 tests/unit/test_ai_eval_runner.py 的镜像导出版。
断言语义逐字照抄（成功/异常分支、评分 DAG、回归判定、报告字段、trace_id/
payload_hash），仅作两处适配：
  1. import 来源从 上游项目 内部模块改为 AIQE 包；
  2. 基线文件改用 pytest tmp_path（原版写 /tmp 固定路径，语义相同）；
  3. 依赖 上游项目 基础设施的两个测试（retry 装饰器 / circuit breaker 熔断）
     不属于 AIQE 参考实现范围，不迁移（见文件末尾注释）。

pytest 收集时会对 TestCase 类发出 PytestCollectionWarning，已在 pyproject.toml
中通过 filterwarnings 忽略（不影响测试结果）。
"""
import warnings
warnings.filterwarnings("ignore", message=".*cannot collect test class.*")
import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock

from AIQE.schema import TestCase, ScoreBreakdown
from AIQE.runner import ExecutionRunner, ExecutionResult, compute_payload_hash
from AIQE.judge import OutputJudge, JudgeResult
from AIQE.regression import RegressionAnalyzer, RegressionResult
from AIQE.reporter import EvaluationReport, _VERSION
from AIQE.protocol import GenerateResult, BackendType


# ═══════════════════════════════════════════
# ExecutionRunner
# ═══════════════════════════════════════════

def _make_mock_backend(text: str = "hello", tokens: int = 3, error: str | None = None):
    """工厂：创建带 generate_sync 的 mock backend。"""
    mock = MagicMock()
    mock.backend_type = BackendType.MLX
    mock.profile.return_value = MagicMock(model_id="mock-mlx")
    if error:
        mock.generate_sync.side_effect = RuntimeError(error)
    else:
        mock.generate_sync.return_value = GenerateResult(
            text=text, tokens_generated=tokens, elapsed_sec=0.5, tok_per_sec=6.0, thinking=""
        )
    return mock


def test_execution_runner_successful():
    mock = _make_mock_backend(text="你好，我是 AI 助手")
    runner = ExecutionRunner(mock)
    case = TestCase(id="t1", category="chat", prompt="hi", max_tokens=64)
    result = runner.run(case)
    assert result.success is True
    assert result.response == "你好，我是 AI 助手"
    assert result.tokens_generated == 3
    assert result.error is None
    mock.generate_sync.assert_called_once()


def test_execution_runner_runtime_error():
    mock = _make_mock_backend(error="模型未加载")
    runner = ExecutionRunner(mock)
    case = TestCase(id="t2", category="chat", prompt="hi", max_tokens=64)
    result = runner.run(case)
    assert result.success is False
    assert result.error == "模型未加载"
    assert result.response == ""


def test_execution_runner_unexpected_exception():
    mock = MagicMock()
    mock.backend_type = BackendType.OLLAMA
    mock.profile.return_value = None
    mock.generate_sync.side_effect = ValueError("连接被拒绝")
    runner = ExecutionRunner(mock)
    case = TestCase(id="t3", category="chat", prompt="hi", max_tokens=64)
    result = runner.run(case)
    assert result.success is False
    assert result.error.startswith("execution_error:")


def test_execution_runner_batch_order_preserved():
    mock = _make_mock_backend(text="ok", tokens=1)
    runner = ExecutionRunner(mock)
    cases = [TestCase(id=f"b{i}", category="chat", prompt="x") for i in range(3)]
    results = runner.run_batch(cases)
    assert [r.case_id for r in results] == ["b0", "b1", "b2"]
    assert mock.generate_sync.call_count == 3


def test_execution_runner_empty_response():
    mock = _make_mock_backend(text="", tokens=0)
    runner = ExecutionRunner(mock)
    case = TestCase(id="empty", category="chat", prompt="hi", max_tokens=64)
    result = runner.run(case)
    assert result.success is True
    assert result.response == ""


# ═══════════════════════════════════════════
# OutputJudge
# ═══════════════════════════════════════════

def _make_result(response: str, tokens: int = 1, backend: str = "mock"):
    return ExecutionResult(
        case_id="t1", category="chat", prompt="hi", response=response,
        tokens_generated=tokens, elapsed_sec=0.1, tok_per_sec=10.0,
        backend=backend, model_id="mock",
    )


def test_judge_empty_response():
    judge = OutputJudge()
    case = TestCase(id="t1", category="chat", prompt="hi", expected_keywords=["hello"])
    result = _make_result("", tokens=0)
    jr = judge.judge(case, result)
    assert jr.score == 0.0
    assert jr.passed is False
    assert jr.checks["empty_response"] is True
    assert "响应为空" in jr.reasons


def test_judge_keyword_full_match():
    judge = OutputJudge()
    case = TestCase(id="t1", category="chat", prompt="hi",
                    expected_keywords=["hello", "world"], min_length=5)
    result = _make_result("hello world")
    jr = judge.judge(case, result)
    assert jr.score == 1.0
    assert jr.passed is True
    assert jr.checks["keywords_match"] is True


def test_judge_keyword_partial_match():
    judge = OutputJudge()
    case = TestCase(id="t1", category="chat", prompt="hi",
                    expected_keywords=["hello", "world"], min_length=5)
    result = _make_result("hello there")
    jr = judge.judge(case, result)
    assert jr.score == 0.5   # 1/2 keywords
    assert jr.passed is True  # 0.5 ≥ threshold


def test_judge_keyword_no_match():
    judge = OutputJudge()
    case = TestCase(id="t1", category="chat", prompt="hi",
                    expected_keywords=["hello", "world"], min_length=5)
    result = _make_result("completely unrelated text here")
    jr = judge.judge(case, result)
    assert jr.score == 0.0
    assert jr.passed is False


def test_judge_length_penalty():
    judge = OutputJudge()
    case = TestCase(id="t1", category="chat", prompt="hi",
                    expected_keywords=["hello"], min_length=50)
    result = _make_result("hello hi")  # keyword hit, but only 8 chars < 50
    jr = judge.judge(case, result)
    assert jr.score == 0.5   # keyword=1.0 × 0.5 length penalty
    assert jr.checks["length_ok"] is False


def test_judge_no_keywords_defaults_full():
    judge = OutputJudge()
    case = TestCase(id="t1", category="chat", prompt="hi", expected_keywords=[])
    result = _make_result("any response at all")
    jr = judge.judge(case, result)
    assert jr.score == 1.0
    assert jr.passed is True


def test_judge_format_json():
    judge = OutputJudge()
    case = TestCase(id="j1", category="json_output", prompt="json",
                    expected_keywords=[], min_length=5)
    result = _make_result('{"name": "AI"}')
    jr = judge.judge(case, result)
    assert jr.checks["format_ok"] is True
    assert jr.metrics["format_score"] == 1.0


def test_judge_format_json_invalid():
    judge = OutputJudge()
    case = TestCase(id="j1", category="json_output", prompt="json",
                    expected_keywords=[], min_length=5)
    result = _make_result("not json at all")
    jr = judge.judge(case, result)
    assert jr.checks["format_ok"] is False
    assert jr.metrics["format_score"] == 0.0


def test_judge_format_coding():
    judge = OutputJudge()
    case = TestCase(id="c1", category="coding_task", prompt="code",
                    expected_keywords=[], min_length=5)
    result = _make_result("def quick_sort(arr):\n    return arr")
    jr = judge.judge(case, result)
    assert jr.checks["format_ok"] is True


def test_judge_respects_scoring_relevance_cap():
    judge = OutputJudge()
    case = TestCase(id="t1", category="chat", prompt="hi",
                    expected_keywords=["hello"], min_length=5,
                    scoring=ScoreBreakdown(relevance=0.6))
    result = _make_result("hello world")
    jr = judge.judge(case, result)
    assert jr.score <= 0.6   # capped by relevance


# ═══════════════════════════════════════════
# RegressionAnalyzer
# ═══════════════════════════════════════════

def test_regression_no_baseline(tmp_path: Path):
    analyzer = RegressionAnalyzer(storage_path=tmp_path)
    r = analyzer.analyze("t1", 0.8)
    assert r.status == "new"
    assert r.delta == 0.0
    assert r.baseline_score is None


def test_regression_pass(tmp_path: Path):
    baseline = tmp_path / "base.json"
    baseline.write_text(json.dumps({"t1": 0.5}))
    analyzer = RegressionAnalyzer(storage_path=tmp_path)
    r = analyzer.analyze("t1", 0.8, baseline_path=baseline)
    assert r.status == "pass"
    assert abs(r.delta - 0.3) < 0.01


def test_regression_detected(tmp_path: Path):
    baseline = tmp_path / "base2.json"
    baseline.write_text(json.dumps({"t1": 0.8}))
    analyzer = RegressionAnalyzer(storage_path=tmp_path)
    r = analyzer.analyze("t1", 0.6, baseline_path=baseline)
    assert r.status == "regression"
    assert abs(r.delta - (-0.2)) < 0.01


def test_regression_degraded(tmp_path: Path):
    baseline = tmp_path / "base3.json"
    baseline.write_text(json.dumps({"t1": 0.7}))
    analyzer = RegressionAnalyzer(storage_path=tmp_path)
    r = analyzer.analyze("t1", 0.6, baseline_path=baseline)
    assert r.status == "degraded"  # -0.1 > -0.15 threshold


def test_regression_new_case_in_known_baseline(tmp_path: Path):
    baseline = tmp_path / "base4.json"
    baseline.write_text(json.dumps({"t1": 0.8, "t2": 0.6}))
    analyzer = RegressionAnalyzer(storage_path=tmp_path)
    r = analyzer.analyze("t99", 0.5, baseline_path=baseline)
    assert r.status == "new"  # t99 not in baseline


def test_regression_loads_report_format_baseline(tmp_path: Path):
    """基线支持 EvaluationReport 嵌套格式（{"cases": [...]}）。"""
    baseline = tmp_path / "report_base.json"
    baseline.write_text(json.dumps({
        "cases": [
            {"case_id": "t1", "judge": {"score": 0.9}},
            {"case_id": "t2", "judge": {"score": 0.4}},
        ]
    }))
    analyzer = RegressionAnalyzer(storage_path=tmp_path)
    r = analyzer.analyze("t1", 0.8, baseline_path=baseline)
    assert r.status == "degraded"
    assert r.baseline_score == 0.9


# ═══════════════════════════════════════════
# EvaluationReport
# ═══════════════════════════════════════════

def _make_judge(score: float, passed: bool) -> JudgeResult:
    return JudgeResult(score=score, breakdown=ScoreBreakdown(), passed=passed,
                       checks={"empty_response": False, "keywords_match": True},
                       reasons=["ok"])


def _make_regression(status: str, delta: float) -> RegressionResult:
    return RegressionResult(case_id="t1", status=status, delta=delta,
                            baseline_score=0.5, current_score=0.8)


def test_report_to_json():
    report = EvaluationReport(test_plan_id="plan-001")
    case = TestCase(id="simple_chat", category="chat", prompt="hi")
    exec_result = _make_result("hello")
    jr = _make_judge(1.0, True)
    report.add_case(case, exec_result, jr)
    json_str = report.to_json()
    parsed = json.loads(json_str)
    assert parsed["project"] == "AIQE"
    assert parsed["version"] == _VERSION
    assert len(parsed["cases"]) == 1
    assert parsed["cases"][0]["case_id"] == "simple_chat"
    assert parsed["summary"]["passed"] == 1
    assert parsed["summary"]["total"] == 1


def test_report_to_json_with_regression():
    report = EvaluationReport(test_plan_id="plan-002")
    case = TestCase(id="coding_task", category="coding_task", prompt="code")
    exec_result = _make_result("def foo(): return 1")
    jr = _make_judge(0.3, False)
    rr = _make_regression("regression", -0.2)
    report.add_case(case, exec_result, jr, regression_result=rr)
    parsed = json.loads(report.to_json())
    assert parsed["cases"][0]["regression"]["status"] == "regression"
    assert "coding_task" in parsed["summary"]["regressions"]


def test_report_to_json_file_write(tmp_path: Path):
    report = EvaluationReport(test_plan_id="plan-003")
    case = TestCase(id="t1", category="chat", prompt="hi")
    report.add_case(case, _make_result("hi"), _make_judge(0.9, True))
    out = tmp_path / "report.json"
    report.to_json(path=out)
    assert out.exists()
    parsed = json.loads(out.read_text())
    assert parsed["summary"]["total"] == 1


def test_report_print_summary(capsys: pytest.CaptureFixture):
    report = EvaluationReport(test_plan_id="plan-004")
    report.add_case(TestCase(id="simple_chat", category="chat", prompt="hi"),
                    _make_result("hello"), _make_judge(0.8, True))
    report.add_case(TestCase(id="coding_task", category="coding_task", prompt="code"),
                    _make_result("def f(): pass"), _make_judge(0.3, False))
    report.print_summary()
    captured = capsys.readouterr()
    assert "AIQE Evaluation Report" in captured.out
    assert "simple_chat" in captured.out
    assert "coding_task" in captured.out
    assert "1/2 passed" in captured.out


def test_report_summary_counts():
    report = EvaluationReport(test_plan_id="plan-005")
    report.add_case(TestCase(id="a", category="chat", prompt="x"),
                    _make_result("ok"), _make_judge(0.9, True))
    report.add_case(TestCase(id="b", category="chat", prompt="x"),
                    _make_result("ok"), _make_judge(0.7, True))
    report.add_case(TestCase(id="c", category="chat", prompt="x"),
                    _make_result(""), _make_judge(0.0, False))
    summary = report._compute_summary()
    assert summary["passed"] == 2
    assert summary["total"] == 3
    assert summary["regressions"] == []


# ═══════════════════════════════════════════
# B4: 异常路径测试
# ═══════════════════════════════════════════

def test_execution_runner_timeout_error():
    """注入 TimeoutError → ExecutionResult.error 含 execution_error + timeout。

    【真实代码路径】runner.py run() 的 except Exception 分支
    （TimeoutError 是 OSError 子类，不走 RuntimeError 分支）。
    """
    mock = _make_mock_backend(error="timeout")
    mock.generate_sync.side_effect = TimeoutError("request timed out")
    runner = ExecutionRunner(mock)
    case = TestCase(id="t-timeout", category="chat", prompt="hi")
    result = runner.run(case)
    assert result.success is False
    assert "execution_error" in result.error
    assert "timed out" in result.error
    assert result.response == ""


def test_execution_runner_connection_error():
    """后端不可用（ConnectionError）→ 错误信息保留原因，不崩溃。"""
    mock = _make_mock_backend(error="refused")
    mock.generate_sync.side_effect = ConnectionError("连接被拒绝")
    runner = ExecutionRunner(mock)
    case = TestCase(id="t-conn", category="chat", prompt="hi")
    result = runner.run(case)
    assert result.success is False
    assert "连接被拒绝" in result.error


def test_execution_runner_malformed_result():
    """后端返回空 GenerateResult（形似成功但内容缺失）→ 不崩溃，交由 judge 判 0 分。

    【真实代码路径】runner.py run() 成功分支——response 为空字符串不是异常，
    OutputJudge 的 empty_response 检查负责给 0 分（judge.py）。
    """
    mock = MagicMock()
    mock.backend_type = BackendType.MLX
    mock.profile.return_value = MagicMock(model_id="mock-mlx")
    mock.generate_sync.return_value = GenerateResult(
        text="", tokens_generated=0, elapsed_sec=0.1, tok_per_sec=0.0, thinking=""
    )
    runner = ExecutionRunner(mock)
    case = TestCase(id="t-malformed", category="chat", prompt="hi")
    result = runner.run(case)
    assert result.success is True  # 执行层不判错
    assert result.response == ""


# 未迁移的两项（上游项目 内部基础设施，不属于 AIQE 参考实现范围）：
#   test_execution_runner_with_retry_decorator —— 依赖 上游项目 的 retry_manager
#   test_execution_runner_circuit_breaker_opens —— 依赖 上游项目 的 circuit_breaker
# 这两项验证的是 上游项目 基础设施与 ExecutionRunner 的集成，而非 AIQE 框架自身；
# AIQE 侧的对应保障是「任意满足 Backend Protocol 的后端都可注入」的
# 镜像契约测试（见 test_backends.py）。


# ═══════════════════════════════════════════
# A2: trace_id + payload_hash
# ═══════════════════════════════════════════

def test_execution_result_has_trace_id():
    """每次执行自动生成 trace_id（8 位 hex）。"""
    mock = _make_mock_backend(text="hello")
    runner = ExecutionRunner(mock)
    result = runner.run(TestCase(id="t-trace", category="chat", prompt="hi"))
    assert result.trace_id, "trace_id 不应为空"
    assert len(result.trace_id) == 8


def test_execution_result_trace_id_unique():
    """两次执行 trace_id 不同。"""
    mock = _make_mock_backend(text="hello")
    runner = ExecutionRunner(mock)
    case = TestCase(id="t-trace2", category="chat", prompt="hi")
    r1 = runner.run(case)
    r2 = runner.run(case)
    assert r1.trace_id != r2.trace_id


def test_execution_result_payload_hash_consistent():
    """同一响应文本的 payload_hash 稳定（MD5 前 16 位）。"""
    assert compute_payload_hash("hello") == compute_payload_hash("hello")
    assert compute_payload_hash("hello") != compute_payload_hash("world")
    assert len(compute_payload_hash("hello")) == 16


def test_execution_runner_computes_payload_hash():
    """run() 成功路径自动填充 payload_hash = hash(response)。"""
    mock = _make_mock_backend(text="你好，我是 AI 助手")
    runner = ExecutionRunner(mock)
    result = runner.run(TestCase(id="t-hash", category="chat", prompt="hi"))
    assert result.payload_hash == compute_payload_hash("你好，我是 AI 助手")


def test_execution_runner_error_path_hash_empty():
    """错误路径 response 为空 → payload_hash 为空字符串。"""
    mock = _make_mock_backend(error="模型未加载")
    runner = ExecutionRunner(mock)
    result = runner.run(TestCase(id="t-hash-err", category="chat", prompt="hi"))
    assert result.payload_hash == ""


def test_report_includes_trace_and_hash():
    """报告 JSON 的 execution 段包含 trace_id + payload_hash。"""
    report = EvaluationReport(test_plan_id="plan-trace")
    case = TestCase(id="t-trace3", category="chat", prompt="hi")
    exec_result = _make_result("hello")
    jr = _make_judge(1.0, True)
    report.add_case(case, exec_result, jr)
    parsed = json.loads(report.to_json())
    exec_seg = parsed["cases"][0]["execution"]
    assert "trace_id" in exec_seg
    assert "payload_hash" in exec_seg
