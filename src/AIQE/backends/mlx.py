# AIQE/backends/mlx.py —— MLX 评估后端骨架
#
# 真实 MLX 推理的评估后端。仅在 MLX_EVAL_LIVE=1 时由工厂创建。
#
# 【当前状态：骨架（skeleton）】
#   - 类结构完整，满足 EvaluationBackend + Backend Protocol
#   - setup() 直接报 ImportError 并给出接入指引（不在 import 时加载 MLX，
#     避免无 MLX 环境下 import 失败）
#   - 不下载模型（MLX_EVAL_LIVE=1 时由用户保证模型已就绪）
#   - 真实推理需要使用者自行安装 mlx-lm，并提供满足 AIQE.protocol.Backend
#     的适配层（本骨架的委托逻辑与错误路径保持完整，接口契约不变）

from __future__ import annotations

import logging
from typing import Iterator

from AIQE.protocol import (
    BackendType,
    GenerateOptions,
    GenerateResult,
    ModelProfile,
)

logger = logging.getLogger(__name__)


class MlxEvalBackend:
    """MLX 评估后端（骨架）。

    【使用条件】
      仅当环境变量 MLX_EVAL_LIVE=1 时由工厂创建。
      使用前需确保：
        1. mlx-lm 已安装（pip install mlx-lm）
        2. 模型权重已下载到本地缓存
        3. 内存充足

    【骨架行为】
      - setup() 报 ImportError 并给出接入指引（本骨架未内置 MLX 适配层，
        需要使用者自行注入满足 AIQE.protocol.Backend 的实例）
      - generate_sync() 委托给内部适配层实例
      - 未 setup 就调用 generate_sync() -> RuntimeError("模型未加载")
    """

    name = "mlx"

    def __init__(self, model_id: str = "ornith-1.0-9b-mlx", quant: str = "q4") -> None:
        self._model_id = model_id
        self._quant = quant
        self._mlx_backend = None      # 使用者注入的满足 AIQE.protocol.Backend 的实例
        self._profile: ModelProfile | None = None
        self._setup_done = False

    # ── 评估生命周期 ─────────────────────────────────────
    def setup(self) -> None:
        """加载 MLX 模型（幂等）。

        【行为】直接报 ImportError 并给出接入指引——
        真实 MLX 推理需要使用者：
          1. pip install mlx-lm
          2. 自行实现/注入满足 AIQE.protocol.Backend 的 MLX 适配层
             （委托路径：self._mlx_backend）
        """
        if self._setup_done:
            return

        raise ImportError(
            "AIQE 参考实现未内置 MLX 后端适配层（mlx-lm）。\n"
            "接入指引：pip install mlx-lm 后，自行实现满足 "
            "AIQE.protocol.Backend 的适配层并赋值给 backend._mlx_backend，"
            "再调用 setup()。"
        )

    def teardown(self) -> None:
        """卸载模型，释放统一内存（安全，未 setup 也不抛）。"""
        if self._mlx_backend is not None:
            try:
                self._mlx_backend.unload()
            except Exception as e:
                logger.warning("[mlx-eval] unload 失败（已忽略）: %s", e)
        self._mlx_backend = None
        self._profile = None
        self._setup_done = False

    @property
    def model_id(self) -> str:
        return self._model_id

    # ── Backend Protocol 实现（委托给内部适配层）──
    @property
    def backend_type(self) -> BackendType:
        return BackendType.MLX

    def is_loaded(self) -> bool:
        if self._mlx_backend is None:
            return False
        return self._mlx_backend.is_loaded()

    def profile(self) -> ModelProfile | None:
        return self._profile

    def load(self, model_id: str, quant: str = "q4") -> ModelProfile:
        """兼容 Backend.load()。"""
        self._model_id = model_id
        self._quant = quant
        self.teardown()
        self.setup()
        return self._profile  # type: ignore[return-value]

    def unload(self) -> None:
        self.teardown()

    def generate(
        self, prompt: str, opts: GenerateOptions | None = None
    ) -> Iterator[str]:
        """流式生成：委托给内部适配层 generate()。"""
        if not self.is_loaded():
            raise RuntimeError("模型未加载，请先调用 setup()")
        yield from self._mlx_backend.generate(prompt, opts)  # type: ignore[union-attr]

    def generate_sync(
        self, prompt: str, opts: GenerateOptions | None = None
    ) -> GenerateResult:
        """非流式生成：委托给内部适配层 generate_sync()。"""
        if not self.is_loaded():
            raise RuntimeError("模型未加载，请先调用 setup()")
        return self._mlx_backend.generate_sync(prompt, opts)  # type: ignore[union-attr]
