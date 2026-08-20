# AIQE/backends/mock.py —— 确定性 Mock 评估后端
#
# 默认评估后端（MLX_EVAL_LIVE != "1" 时使用）。
# 不依赖任何外部运行时，返回基于 prompt 内容的确定性响应。
# 用于：单元测试、CI、无 MLX 环境下的评估流水线验证。

from __future__ import annotations

from typing import Iterator

from AIQE.protocol import (
    BackendType,
    GenerateOptions,
    GenerateResult,
    ModelProfile,
)


class MockEvalBackend:
    """确定性 Mock 评估后端。

    【设计原则】
      - 确定性：相同 prompt 永远返回相同响应（无随机、无时间漂移）
      - 自包含：不依赖 mlx_lm / ollama / 网络
      - 满足 Backend Protocol：ExecutionRunner 可直接使用
      - 响应按 prompt 内容分类：让 4 个标准测试用例都能产生有意义评分

    【响应策略】
      prompt 含 "JSON"/"json"   -> 返回合法 JSON
      prompt 含 "排序"/"sort"   -> 返回 quick_sort 代码
      prompt 含 "翻译"/"trans"  -> 返回英文翻译
      其他                       -> 返回中文自我介绍（含"你好"/"AI"关键词）
    """

    name = "mock"

    def __init__(self, model_id: str = "mock-eval-model") -> None:
        self._model_id = model_id
        self._profile: ModelProfile | None = None
        self._setup_done = False

    # ── 评估生命周期 ─────────────────────────────────────
    def setup(self) -> None:
        """初始化 mock 后端（幂等）。创建一个假的 ModelProfile。"""
        if self._setup_done:
            return
        self._profile = ModelProfile(
            model_id=self._model_id,
            backend=BackendType.MLX,  # mock 模拟 MLX 路径
            quant="q4",
            params_b=0.0,
            mem_mb=0,
            tok_per_sec=15.0,  # 固定值，确保确定性
            ctx_len=4096,
            loaded=True,
        )
        self._setup_done = True

    def teardown(self) -> None:
        """清理（安全，未 setup 也不抛）。"""
        self._profile = None
        self._setup_done = False

    @property
    def model_id(self) -> str:
        return self._model_id

    # ── Backend Protocol 实现 ────────────────────────────
    @property
    def backend_type(self) -> BackendType:
        return BackendType.MLX

    def is_loaded(self) -> bool:
        return self._setup_done and self._profile is not None

    def profile(self) -> ModelProfile | None:
        return self._profile

    def load(self, model_id: str, quant: str = "q4") -> ModelProfile:
        """兼容 Backend.load()：设置 model_id 并 setup。"""
        self._model_id = model_id
        self.setup()
        return self._profile  # type: ignore[return-value]

    def unload(self) -> None:
        self.teardown()

    def generate(
        self, prompt: str, opts: GenerateOptions | None = None
    ) -> Iterator[str]:
        """流式生成（mock 按字符切片 yield）。"""
        text = self._generate_response(prompt)
        # 简单按字符切片模拟流式
        for ch in text:
            yield ch

    def generate_sync(
        self, prompt: str, opts: GenerateOptions | None = None
    ) -> GenerateResult:
        """非流式生成：返回确定性响应 + 固定性能数据。"""
        if not self.is_loaded():
            raise RuntimeError("模型未加载，请先调用 setup()")

        text = self._generate_response(prompt)
        # 固定性能数据，确保测试可复现
        tokens = max(1, len(text) // 2)
        return GenerateResult(
            text=text,
            tokens_generated=tokens,
            elapsed_sec=0.1,
            tok_per_sec=15.0,
            thinking="",
        )

    # ── 内部：确定性响应生成 ─────────────────────────────
    @staticmethod
    def _generate_response(prompt: str) -> str:
        """根据 prompt 内容返回确定性响应。"""
        p = prompt.lower()

        if "json" in p:
            return '{"name": "AI", "type": "assistant", "version": "0.1.0"}'

        if "排序" in prompt or "sort" in p or "quick" in p:
            return (
                "def quick_sort(arr):\n"
                "    if len(arr) <= 1:\n"
                "        return arr\n"
                "    pivot = arr[len(arr) // 2]\n"
                "    left = [x for x in arr if x < pivot]\n"
                "    middle = [x for x in arr if x == pivot]\n"
                "    right = [x for x in arr if x > pivot]\n"
                "    return quick_sort(left) + middle + quick_sort(right)\n"
            )

        if "翻译" in prompt or "trans" in p:
            return (
                "Artificial intelligence is a branch of computer science "
                "that aims to understand the essence of intelligence and "
                "produce intelligent machines."
            )

        # 默认：中文自我介绍（命中 simple_chat 的关键词 "你好" / "AI"）
        return "你好！我是一个运行在本地的 AI 助手，使用 MLX 框架提供推理能力。"
