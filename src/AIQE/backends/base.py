# AIQE/backends/base.py —— 评估后端抽象层（独立版）
#
# 位于 ExecutionRunner 与具体推理后端（MLX/Ollama/llama.cpp/remote）之间。
# 职责：
#   1. 提供评估生命周期管理（setup/teardown）
#   2. 屏蔽具体后端实现细节，ExecutionRunner 只依赖此抽象
#   3. 支持通过环境变量切换 mock / live 模式
#
# 设计约束：
#   - EvaluationBackend 必须满足 AIQE.protocol.Backend Protocol
#     （generate_sync / backend_type / profile / is_loaded），这样 ExecutionRunner
#     无需任何改动即可直接使用。
#   - 新增的 setup/teardown/name/model_id 是评估专用扩展，不污染 Backend Protocol。
#
# 镜像说明（协议副本说明）：上游项目 仓库内对应原模块为
# framework/ai_eval/backends/base.py，仅 import 来源由 上游项目 侧
# framework/models/backend.py 改为本地 AIQE/protocol.py（协议副本说明）。

from __future__ import annotations

from typing import Protocol, runtime_checkable

from AIQE.protocol import BackendType, GenerateOptions, GenerateResult, ModelProfile


@runtime_checkable
class EvaluationBackend(Protocol):
    """评估后端抽象层协议。

    【与 Backend Protocol 的关系】
      EvaluationBackend 是 Backend 的超集：包含 Backend 的全部方法
      （generate_sync / backend_type / profile / is_loaded / load / unload / generate）
      外加评估生命周期方法（setup / teardown / name / model_id）。

      这样 ExecutionRunner 可以把 EvaluationBackend 当普通 Backend 用，
      无需感知它是 mock 还是真实 MLX。

    【生命周期】
      create_eval_backend()  ← 工厂创建实例（不加载模型）
        ↓
      setup()                ← 加载模型 / 初始化资源
        ↓
      ExecutionRunner.run()  ← 多次调用 generate_sync()
        ↓
      teardown()             ← 卸载模型 / 释放资源

    【实现要求】
      - setup() 必须幂等：重复调用不重复加载
      - teardown() 必须安全：未 setup 时调用不抛异常
      - generate_sync() 在未 setup 时抛 RuntimeError("模型未加载")
    """

    # ── 评估生命周期扩展 ──────────────────────────────────
    @property
    def name(self) -> str:
        """后端名称：mock / mlx / ollama / llamacpp。用于报告标识。"""
        ...

    @property
    def model_id(self) -> str:
        """当前模型标识。setup 前可能返回占位值。"""
        ...

    def setup(self) -> None:
        """评估前初始化：加载模型、预热缓存等。幂等。"""
        ...

    def teardown(self) -> None:
        """评估后清理：卸载模型、释放内存。安全（未 setup 也不抛）。"""
        ...

    # ── Backend Protocol 方法（ExecutionRunner 依赖这些）──
    @property
    def backend_type(self) -> BackendType:
        ...

    def is_loaded(self) -> bool:
        ...

    def profile(self) -> ModelProfile | None:
        ...

    def generate_sync(
        self, prompt: str, opts: GenerateOptions | None = None
    ) -> GenerateResult:
        ...
