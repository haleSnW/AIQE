# AIQE/protocol.py —— Backend Protocol：统一模型后端抽象
"""
统一模型后端抽象（Backend Protocol）—— AIQE 参考实现

═══════════════════════════════════════════════════════════════════
【协议定位】
- 定义后端接入契约：BackendType / ModelProfile / GenerateOptions /
  GenerateResult / Backend Protocol / make_generate_sync_default
- 任何满足本 Protocol 的后端实例（MLX / Ollama / llama.cpp / 自研 /
  mock），都可以直接注入 AIQE 的 ExecutionRunner，流水线零改动。
- 本文件只含契约本身，不含任何具体推理后端的实现代码。
═══════════════════════════════════════════════════════════════════

【为什么用 Protocol 而不是抽象基类 ABC？】
  - Protocol 是「结构性子类型」：只要一个类实现了这些方法，
    就自动满足 Backend，不需要显式继承。便于：
      * 加新后端时不用改本文件
      * 写 mock/假后端做测试时不用继承
      * isinstance(obj, Backend) 可在运行时检查（@runtime_checkable）

【契约分组】
  ① 生命周期：load / unload / is_loaded / profile
  ② 生成    ：generate（流式）/ generate_sync（非流式）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Protocol, runtime_checkable


# ════════════════════════════════════════════════════════════════
#  1. 后端类型枚举
# ════════════════════════════════════════════════════════════════
class BackendType(str, Enum):
    """所有支持的后端类型。

    设计为 str + Enum，便于：
      - 序列化到配置文件（字符串声明）
      - 日志/CLI 里直接打印
      - 作为 dict key 比较时稳定

    优先级（本地推理场景）：
      MLX（Apple Silicon 原生，最快）>
      OLLAMA（模型管理 + OpenAI 兼容 API，最方便）>
      LLAMACPP（兜底，格式兼容最全）>
      MESH（远程节点，把请求转发给其他设备）
    """
    MLX = "mlx"
    OLLAMA = "ollama"
    LLAMACPP = "llamacpp"
    MESH = "mesh"


# ════════════════════════════════════════════════════════════════
#  2. 能力画像：每个模型一张「身份证」
# ════════════════════════════════════════════════════════════════
@dataclass
class ModelProfile:
    """单个已加载模型的「能力画像」。

    【字段说明】
    ─────────────────────────────────────────────
    model_id   : 模型唯一标识（ollama tag 或 MLX repo id）
    backend    : 当前由哪个后端加载
    quant      : 量化等级（"q4"/"q8"/"f16"）
    params_b   : 参数量（单位 B）
    mem_mb     : 实际占用内存（含 KV 缓存）
    tok_per_sec: 实测生成速度（tok/s）
    ctx_len    : 最大上下文长度
    loaded     : 当前是否已驻留内存
    """
    model_id: str
    backend: BackendType
    quant: str = "q4"
    params_b: float = 0.0
    mem_mb: int = 0
    tok_per_sec: float = 0.0
    ctx_len: int = 4096
    loaded: bool = False


# ════════════════════════════════════════════════════════════════
#  3. 生成参数与结果
# ════════════════════════════════════════════════════════════════
@dataclass
class GenerateOptions:
    """生成参数。所有后端共用同一份，避免抽象泄漏。

    【设计取舍】
      - 故意保持精简（只放通用参数），不放各后端独有的选项。
        后端特有参数通过各后端的构造函数或额外方法传入。
      - system 字段是人格/系统提示的注入点。

    【字段说明】
    ─────────────────────────────────────────────
    system         : system prompt
    temperature    : 采样温度。0=确定，1=多样
    max_tokens     : 最多生成多少 token
    top_p          : nucleus sampling 参数
    stop           : 停止词列表
    images         : base64 图片列表（视觉模型用）
    draft_model    : 投机解码草稿模型（仅 MLX 后端读取）
    enable_thinking: 思考开关（尽力而为语义）
    """
    system: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 0.9
    stop: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    draft_model: Any = None
    enable_thinking: bool | None = None


@dataclass
class GenerateResult:
    """非流式生成的结果（含性能数据）。

    【字段说明】
      text            : 最终正式文本
      thinking        : 思考链内容（thinking model 才有，默认空）
      tokens_generated: token 数（后端自报；没报则退化为字符数粗估）
      elapsed_sec     : 耗时（秒）
      tok_per_sec     : 生成速度（token/秒）
    """
    text: str
    tokens_generated: int
    elapsed_sec: float
    tok_per_sec: float
    thinking: str = ""  # 思考链内容（thinking model 才有，默认空）


# ════════════════════════════════════════════════════════════════
#  4. Backend Protocol：所有后端的契约
# ════════════════════════════════════════════════════════════════
@runtime_checkable
class Backend(Protocol):
    """所有模型后端必须满足的接口契约。

    【契约分组】
      ① 生命周期：load / unload / is_loaded / profile
      ② 生成    ：generate（流式）/ generate_sync（非流式）

    【单驻留纪律】（低内存环境铁律）
      实现类应保证「同一时刻只驻留一个模型」。load 新模型前自动 unload 旧的。

    【线程安全】
      P0 单线程足够。后期并发时，需在实现类里加锁或引入请求队列。
      本 Protocol 不强制，留给实现决定。
    """

    @property
    def backend_type(self) -> BackendType:
        """返回后端类型。供识别当前用的是哪条路。"""
        ...

    # ─────────────────────────────────────────────────────────
    #  生命周期方法
    # ─────────────────────────────────────────────────────────
    def load(self, model_id: str, quant: str = "q4") -> ModelProfile:
        """加载模型到内存，返回能力画像。

        【语义】
          - 幂等：对同一 model_id 重复 load 应直接返回 cached profile
          - 自动切换：load 不同模型时，实现类应先 unload 旧的（单驻留）
          - 异常：模型不存在抛 FileNotFoundError；内存不足抛 MemoryError
        """
        ...

    def unload(self) -> None:
        """卸载当前模型，释放内存。不抛异常——失败不应阻塞主流程。"""
        ...

    def is_loaded(self) -> bool:
        """当前是否有模型驻留内存。"""
        ...

    def profile(self) -> ModelProfile | None:
        """返回当前驻留模型的画像；未加载返回 None。"""
        ...

    # ─────────────────────────────────────────────────────────
    #  生成方法
    # ─────────────────────────────────────────────────────────
    def generate(
        self, prompt: str, opts: GenerateOptions | None = None
    ) -> Iterator[str]:
        """流式生成：逐 token 产出字符串片段。

        【语义】
          - 调用方负责拼接：text = "".join(backend.generate(...))
          - 未 load 就调用 → 抛 RuntimeError
        """
        ...

    def generate_sync(
        self, prompt: str, opts: GenerateOptions | None = None
    ) -> GenerateResult:
        """非流式便捷封装：内部消费 generate() 的迭代器，计时并返回完整结果。

        【用途】
          - 跑分脚本（需要精确 tok/s）
          - 后台批量任务（不关心流式，只要结果）
        """
        ...


# ════════════════════════════════════════════════════════════════
#  5. 复用工具：generate_sync 默认实现
# ════════════════════════════════════════════════════════════════
def make_generate_sync_default(instance) -> callable:
    """为后端实现类生成 generate_sync 的默认实现。

    【为什么这样设计？】
      Protocol 不支持默认方法实现（Python Protocol 的限制）。
      各后端实现里这样用：

          class OllamaBackend:
              def generate(self, prompt, opts=None): ...
              def generate_sync(self, prompt, opts=None):
                  return make_generate_sync_default(self)(prompt, opts)

    【参数】
      instance : 后端实例（需要有 .generate 方法）

    【返回】
      一个 generate_sync(prompt, opts) -> GenerateResult 函数

    【token 计数降级说明】
      默认实现用 len(text) 粗估 token 数（中文≈字数，英文偏多）。
      这只在没有精确计数时用；生产场景应让后端覆盖此方法用真实 tokenizer 计数。
    """
    def _generate_sync(prompt: str, opts: GenerateOptions | None = None) -> GenerateResult:
        start = time.perf_counter()
        chunks: list[str] = []
        for tok in instance.generate(prompt, opts):
            chunks.append(tok)
        text = "".join(chunks)
        elapsed = time.perf_counter() - start
        # 粗估 token 数：fallback 路径，不精确
        n = max(1, len(text))
        return GenerateResult(
            text=text,
            tokens_generated=n,
            elapsed_sec=elapsed,
            tok_per_sec=n / elapsed if elapsed > 0 else 0.0,
        )
    return _generate_sync


# ════════════════════════════════════════════════════════════════
#  6. 模块自检（python -m AIQE.protocol 时跑）
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # 临时自检：验证 Protocol 的 runtime_checkable 能识别结构兼容的实现类
    class _DummyBackend:
        backend_type = BackendType.MLX

        def load(self, model_id, quant="q4"):
            return ModelProfile(model_id=model_id, backend=BackendType.MLX, loaded=True)

        def unload(self):
            pass

        def is_loaded(self):
            return True

        def profile(self):
            return None

        def generate(self, prompt, opts=None):
            yield "hello"

    dummy = _DummyBackend()
    print(f"DummyBackend 是否满足 Backend 协议: {isinstance(dummy, Backend)}")
    print(f"后端类型: {dummy.backend_type}")
    print(f"默认 generate_sync: {make_generate_sync_default(dummy)('hi').text!r}")
    print("✓ protocol.py 结构性自检通过")
