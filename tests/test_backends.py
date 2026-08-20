"""AIQE 评估后端抽象层 —— 契约测试

覆盖：MockEvalBackend 确定性/生命周期、MlxEvalBackend 骨架行为、
create_eval_backend 环境变量切换、ExecutionRunner 集成、全链路端到端。

行为约定（v0.1.0）：
  MlxEvalBackend.setup() 确定性抛 ImportError（本仓库未内置 MLX 适配层），
  因此断言为「必须抛 ImportError 且提示含 mlx」。

pytest 收集时会对 TestCase 类发出 PytestCollectionWarning，已在 pyproject.toml
中通过 filterwarnings 忽略（不影响测试结果）。
"""
import warnings
warnings.filterwarnings("ignore", message=".*cannot collect test class.*")
import json
import os
import pytest
from unittest.mock import MagicMock

from AIQE.backends.base import EvaluationBackend
from AIQE.backends.mock import MockEvalBackend
from AIQE.backends.mlx import MlxEvalBackend
from AIQE.backends.factory import create_eval_backend
from AIQE.runner import ExecutionRunner
from AIQE.schema import TestCase
from AIQE.protocol import Backend, BackendType, GenerateResult, ModelProfile


# ═══════════════════════════════════════════
# MockEvalBackend
# ═══════════════════════════════════════════

def test_mock_backend_satisfies_backend_protocol():
    """MockEvalBackend 必须满足 Backend Protocol（ExecutionRunner 依赖此契约）。"""
    backend = MockEvalBackend()
    backend.setup()
    assert isinstance(backend, Backend), "MockEvalBackend 必须满足 Backend Protocol"
    assert isinstance(backend, EvaluationBackend)


def test_mock_backend_satisfies_evaluation_protocol():
    """MockEvalBackend 满足 EvaluationBackend Protocol。"""
    backend = MockEvalBackend()
    assert isinstance(backend, EvaluationBackend)


def test_mock_backend_not_loaded_before_setup():
    """setup 前未加载。"""
    backend = MockEvalBackend()
    assert backend.is_loaded() is False
    assert backend.profile() is None


def test_mock_backend_setup_loads_profile():
    """setup 后产生 ModelProfile。"""
    backend = MockEvalBackend(model_id="test-mock")
    backend.setup()
    assert backend.is_loaded() is True
    profile = backend.profile()
    assert profile is not None
    assert profile.model_id == "test-mock"
    assert profile.loaded is True


def test_mock_backend_setup_is_idempotent():
    """重复 setup 不重复加载。"""
    backend = MockEvalBackend()
    backend.setup()
    profile1 = backend.profile()
    backend.setup()  # 幂等
    profile2 = backend.profile()
    assert profile1 is profile2


def test_mock_backend_teardown_safe_without_setup():
    """未 setup 就 teardown 不抛异常。"""
    backend = MockEvalBackend()
    backend.teardown()  # 不应抛
    assert backend.is_loaded() is False


def test_mock_backend_teardown_clears_state():
    """teardown 后状态清空。"""
    backend = MockEvalBackend()
    backend.setup()
    backend.teardown()
    assert backend.is_loaded() is False
    assert backend.profile() is None


def test_mock_backend_generate_sync_requires_setup():
    """未 setup 调用 generate_sync -> RuntimeError。"""
    backend = MockEvalBackend()
    with pytest.raises(RuntimeError, match="模型未加载"):
        backend.generate_sync("hi")


def test_mock_backend_deterministic_chat_response():
    """chat 类 prompt 返回包含关键词的确定性响应。"""
    backend = MockEvalBackend()
    backend.setup()
    result = backend.generate_sync("你好，介绍一下你自己")
    assert "你好" in result.text
    assert "AI" in result.text
    assert result.tokens_generated > 0
    assert result.elapsed_sec == 0.1  # 固定值


def test_mock_backend_deterministic_json_response():
    """JSON 类 prompt 返回合法 JSON。"""
    backend = MockEvalBackend()
    backend.setup()
    result = backend.generate_sync("请输出JSON格式")
    parsed = json.loads(result.text)
    assert "name" in parsed


def test_mock_backend_deterministic_code_response():
    """代码类 prompt 返回含 def/return 的代码。"""
    backend = MockEvalBackend()
    backend.setup()
    result = backend.generate_sync("写一个快速排序 sort 函数")
    assert "def quick_sort" in result.text
    assert "return" in result.text


def test_mock_backend_deterministic_translation_response():
    """翻译类 prompt 返回英文。"""
    backend = MockEvalBackend()
    backend.setup()
    result = backend.generate_sync("请翻译以下内容")
    assert "artificial" in result.text.lower() or "intelligence" in result.text.lower()


def test_mock_backend_same_prompt_same_response():
    """确定性：相同 prompt 多次调用返回相同响应。"""
    backend = MockEvalBackend()
    backend.setup()
    r1 = backend.generate_sync("hello")
    r2 = backend.generate_sync("hello")
    assert r1.text == r2.text
    assert r1.tokens_generated == r2.tokens_generated


def test_mock_backend_backend_type():
    """backend_type 返回 MLX（mock 模拟 MLX 路径）。"""
    backend = MockEvalBackend()
    assert backend.backend_type == BackendType.MLX


def test_mock_backend_name():
    assert MockEvalBackend().name == "mock"


# ═══════════════════════════════════════════
# MlxEvalBackend 骨架
# ═══════════════════════════════════════════

def test_mlx_backend_satisfies_protocols():
    """MlxEvalBackend 满足 EvaluationBackend + Backend Protocol。"""
    backend = MlxEvalBackend()
    assert isinstance(backend, EvaluationBackend)
    assert isinstance(backend, Backend)


def test_mlx_backend_not_loaded_before_setup():
    """骨架未 setup 前不加载。"""
    backend = MlxEvalBackend()
    assert backend.is_loaded() is False
    assert backend.profile() is None


def test_mlx_backend_generate_sync_requires_setup():
    """未 setup 调用 generate_sync -> RuntimeError。"""
    backend = MlxEvalBackend()
    with pytest.raises(RuntimeError, match="模型未加载"):
        backend.generate_sync("hi")


def test_mlx_backend_teardown_safe_without_setup():
    """未 setup 就 teardown 不抛。"""
    backend = MlxEvalBackend()
    backend.teardown()  # 不应抛
    assert backend.is_loaded() is False


def test_mlx_backend_setup_raises_without_adapter():
    """setup() 确定性抛 ImportError（未内置 MLX 适配层）。"""
    backend = MlxEvalBackend(model_id="nonexistent-model")
    with pytest.raises(ImportError) as exc_info:
        backend.setup()
    assert "mlx" in str(exc_info.value).lower()


def test_mlx_backend_backend_type():
    assert MlxEvalBackend().backend_type == BackendType.MLX


def test_mlx_backend_name():
    assert MlxEvalBackend().name == "mlx"


def test_mlx_backend_delegates_to_inner_backend():
    """注入适配层后 generate_sync 委托给内部实例（用 mock 验证委托）。"""
    backend = MlxEvalBackend()
    # 注入假内部后端，绕过真实 MLX 加载
    fake_inner = MagicMock()
    fake_inner.is_loaded.return_value = True
    fake_inner.generate_sync.return_value = GenerateResult(
        text="delegated", tokens_generated=9, elapsed_sec=0.1, tok_per_sec=90.0, thinking=""
    )
    backend._mlx_backend = fake_inner
    backend._setup_done = True
    backend._profile = ModelProfile(
        model_id="test", backend=BackendType.MLX, quant="q4", loaded=True
    )

    result = backend.generate_sync("hello")
    assert result.text == "delegated"
    fake_inner.generate_sync.assert_called_once()


# ═══════════════════════════════════════════
# create_eval_backend 工厂
# ═══════════════════════════════════════════

def test_factory_default_returns_mock(monkeypatch):
    """默认（MLX_EVAL_LIVE 未设置）-> MockEvalBackend。"""
    monkeypatch.delenv("MLX_EVAL_LIVE", raising=False)
    backend = create_eval_backend()
    assert isinstance(backend, MockEvalBackend)


def test_factory_false_returns_mock(monkeypatch):
    """MLX_EVAL_LIVE=false -> MockEvalBackend。"""
    monkeypatch.setenv("MLX_EVAL_LIVE", "false")
    assert isinstance(create_eval_backend(), MockEvalBackend)


def test_factory_true_returns_mlx(monkeypatch):
    """MLX_EVAL_LIVE=1 -> MlxEvalBackend。"""
    monkeypatch.setenv("MLX_EVAL_LIVE", "1")
    backend = create_eval_backend(model_id="test-model")
    assert isinstance(backend, MlxEvalBackend)
    assert backend.model_id == "test-model"


def test_factory_yes_returns_mlx(monkeypatch):
    """MLX_EVAL_LIVE=yes -> MlxEvalBackend。"""
    monkeypatch.setenv("MLX_EVAL_LIVE", "yes")
    assert isinstance(create_eval_backend(), MlxEvalBackend)


def test_factory_case_insensitive(monkeypatch):
    """MLX_EVAL_LIVE 不区分大小写。"""
    monkeypatch.setenv("MLX_EVAL_LIVE", "TRUE")
    assert isinstance(create_eval_backend(), MlxEvalBackend)


def test_factory_passes_model_id_to_mock(monkeypatch):
    """工厂把 model_id 透传给 MockEvalBackend。"""
    monkeypatch.delenv("MLX_EVAL_LIVE", raising=False)
    backend = create_eval_backend(model_id="my-mock")
    assert backend.model_id == "my-mock"


# ═══════════════════════════════════════════
# ExecutionRunner 集成（不破坏现有流水线）
# ═══════════════════════════════════════════

def test_execution_runner_works_with_mock_eval_backend():
    """ExecutionRunner 能直接使用 MockEvalBackend（无需改动 runner）。"""
    backend = MockEvalBackend(model_id="integration-test")
    backend.setup()
    runner = ExecutionRunner(backend)
    case = TestCase(id="t1", category="chat", prompt="你好", max_tokens=64)
    result = runner.run(case)
    assert result.success is True
    assert result.response != ""
    assert result.backend == "mlx"
    assert result.model_id == "integration-test"
    backend.teardown()


def test_execution_runner_mock_backend_end_to_end():
    """完整流水线：mock 后端 + 4 个标准用例（runner→judge→reporter）。"""
    from AIQE.cases.test_cases import get_test_cases
    from AIQE.judge import OutputJudge
    from AIQE.reporter import EvaluationReport

    backend = MockEvalBackend()
    backend.setup()
    runner = ExecutionRunner(backend)
    judge = OutputJudge()
    report = EvaluationReport(test_plan_id="backend-integration")

    for case in get_test_cases():
        exec_result = runner.run(case)
        judge_result = judge.judge(case, exec_result)
        report.add_case(case, exec_result, judge_result)

    summary = report._compute_summary()
    assert summary["total"] == 4
    assert summary["passed"] >= 3  # 至少 3 个用例通过（mock 确定性）
    backend.teardown()


def test_full_pipeline_with_regression(tmp_path):
    """全链路：runner→judge→regression→reporter（mock 后端，30 秒内出报告）。

    覆盖验收要求「mock 后端跑通全链路」：每个用例执行→评分→与基线对比
    （无基线 → status="new"）→ 聚合进报告 JSON。
    """
    from AIQE.cases.test_cases import get_test_cases
    from AIQE.judge import OutputJudge
    from AIQE.regression import RegressionAnalyzer
    from AIQE.reporter import EvaluationReport

    backend = MockEvalBackend(model_id="pipeline-mock")
    backend.setup()
    try:
        runner = ExecutionRunner(backend)
        judge = OutputJudge()
        analyzer = RegressionAnalyzer(storage_path=tmp_path)
        report = EvaluationReport(test_plan_id="pipeline-e2e")

        for case in get_test_cases():
            exec_result = runner.run(case)
            judge_result = judge.judge(case, exec_result)
            # 第一次跑：无基线 → status="new"
            regression_result = analyzer.analyze(case.id, judge_result.score)
            report.add_case(case, exec_result, judge_result, regression_result)

        parsed = json.loads(report.to_json())
        assert parsed["test_plan_id"] == "pipeline-e2e"
        assert parsed["summary"]["total"] == 4
        # 每个用例的 execution/judge/regression 三段都在报告里
        for entry in parsed["cases"]:
            assert "execution" in entry and "judge" in entry and "regression" in entry
            assert entry["regression"]["status"] == "new"
            assert entry["execution"]["backend"] == "mlx"
        # 报告可落盘（regression/reporter 全链路的文件侧）
        out = tmp_path / "report.json"
        report.to_json(path=out)
        assert out.exists()
    finally:
        backend.teardown()
