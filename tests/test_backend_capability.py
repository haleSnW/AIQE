"""AIQE 后端可用性（Backend Capability）契约测试

覆盖：
- 后端可用（mock setup 完成）→ generate_sync 正常返回
- 后端不可用（未 setup）   → 明确抛 RuntimeError，不返回空结果
- 后端不可用（MLX 骨架无适配层）→ 明确抛 ImportError，不假装成功
- 工厂默认路径永远产出可用的确定性后端（不 silent fail）

错误契约（§8.3）：所有不可用状态都必须显式暴露，禁止返回
None / 空结果 / fake success。
"""
import warnings
warnings.filterwarnings("ignore", message=".*cannot collect test class.*")

import pytest
from unittest.mock import MagicMock

from AIQE.backends.factory import create_eval_backend
from AIQE.backends.mock import MockEvalBackend
from AIQE.backends.mlx import MlxEvalBackend
from AIQE.protocol import GenerateResult
from AIQE.runner import ExecutionRunner
from AIQE.schema import TestCase


# ── 后端可用（available）──────────────────────────────────

def test_backend_available_after_setup():
    """可用后端：setup 后 generate_sync 返回非空确定性结果。"""
    backend = MockEvalBackend()
    backend.setup()
    result = backend.generate_sync("hi")
    assert result.text, "可用后端的响应不应为空"
    assert result.tokens_generated > 0


def test_backend_available_is_loaded():
    """可用状态显式可查：is_loaded() True、profile 非 None。"""
    backend = MockEvalBackend()
    backend.setup()
    assert backend.is_loaded() is True
    assert backend.profile() is not None


def test_factory_default_backend_fully_usable():
    """工厂默认路径（无 MLX_EVAL_LIVE）产出可直接 setup 并生成的后端。"""
    backend = create_eval_backend()
    assert isinstance(backend, MockEvalBackend)
    backend.setup()
    result = backend.generate_sync("hello")
    assert result.text != ""


# ── 后端不可用（unavailable）──────────────────────────────

def test_backend_unavailable_before_setup_raises():
    """不可用后端：未 setup 调用 generate_sync 必须抛 RuntimeError（不 silent fail）。"""
    backend = MockEvalBackend()
    with pytest.raises(RuntimeError, match="模型未加载"):
        backend.generate_sync("hi")


def test_backend_unavailable_is_loaded_false():
    """不可用状态显式可查：is_loaded() False、profile None。"""
    backend = MockEvalBackend()
    assert backend.is_loaded() is False
    assert backend.profile() is None


def test_mlx_backend_unavailable_without_adapter_raises_import_error():
    """MLX 骨架无适配层：setup() 必须抛 ImportError 并指引 mlx-lm（不假装可用）。"""
    backend = MlxEvalBackend()
    with pytest.raises(ImportError) as exc_info:
        backend.setup()
    assert "mlx" in str(exc_info.value).lower()


# ── 不可用状态在流水线中的显式传播 ────────────────────────

def test_unavailable_backend_through_runner_is_explicit_error():
    """执行器遇到不可用后端 → ExecutionResult.error 非空、response 为空、
    success=False（错误显式传播，不是 fake success）。"""
    backend = MockEvalBackend()  # 未 setup → generate_sync 抛 RuntimeError
    runner = ExecutionRunner(backend)
    result = runner.run(TestCase(id="t", category="chat", prompt="hi"))
    assert result.success is False
    assert result.error  # 错误信息非空
    assert result.response == ""


def test_backend_returning_none_does_not_silently_pass():
    """后端返回 None（形似成功但无内容）→ 执行器必须显式报错，不传 None 下去。"""
    broken = MagicMock()
    broken.backend_type = MagicMock(value="mock")
    broken.profile.return_value = None
    broken.generate_sync.return_value = None  # 坏后端：返回 None
    runner = ExecutionRunner(broken)
    result = runner.run(TestCase(id="t", category="chat", prompt="hi"))
    assert result.success is False
    assert result.error is not None
    assert "execution_error" in result.error
    assert result.response == ""
