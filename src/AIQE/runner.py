# AIQE/runner.py —— ExecutionRunner（独立版）
#
# 镜像说明（协议副本说明）：本模块是 上游项目 仓库内 framework/ai_eval/runner.py
# 的独立导出版，公开 API 同构。与原版的两处导出差异：
#   1. ExecutionResult 由 pydantic BaseModel → 标准库 dataclass
#   2. 对 上游项目 侧框架 models/backend.py 的引用 → 本地 AIQE/protocol.py
# 其余行为（异常处理分支、trace_id/payload_hash 语义）与 上游项目 侧完全一致。

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from AIQE.schema import TestCase
    from AIQE.protocol import Backend

logger = logging.getLogger(__name__)


def compute_payload_hash(text: str) -> str:
    """计算响应文本的 MD5 哈希（前 16 位 hex）。

    用于输出完整性校验：Input → Runtime → Final Output 各阶段
    可以用同一哈希互相核对，检测静默内容篡改/截断。
    """
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class ExecutionResult:
    """单次后端执行的原始状态（不含评分）。

    由 ExecutionRunner.run() 返回，供 OutputJudge 进一步打分。
    error 字段非 None 时表示执行失败，score/passed 不填。

    【trace_id】每次执行独立生成（uuid4 前 8 位），贯穿执行→评分→
    报告各阶段，便于在 JSON 报告里关联同一次执行的多个记录。
    【payload_hash】response 文本的 MD5 前 16 位，用于完整性校验。
    """
    case_id: str
    category: str
    prompt: str
    response: str
    tokens_generated: int
    elapsed_sec: float
    tok_per_sec: float
    backend: str
    model_id: str
    error: str | None = None
    cache_hit: bool | None = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    payload_hash: str = ""

    @property
    def success(self) -> bool:
        return self.error is None


class ExecutionRunner:
    """通过 Backend Protocol 执行 TestCase 的执行器。

    职责：
      - 调用 backend.generate_sync() 获取原始响应
      - 捕获耗时、token 数、错误状态
      - 返回 ExecutionResult（不含评分，评分由 OutputJudge 负责）

    不依赖具体后端实现（MLX / Ollama / llama.cpp / mock 均可注入）。
    """

    def __init__(self, backend: "Backend") -> None:
        self._backend = backend

    def run(self, case: "TestCase") -> ExecutionResult:
        """执行单个用例，返回 ExecutionResult。

        异常处理：
          - RuntimeError("模型未加载") → 记录警告，返回 error 结果
          - 其他异常 → 记录错误，返回 error 结果
        """
        try:
            from AIQE.protocol import GenerateOptions
            opts = GenerateOptions(max_tokens=case.max_tokens)
            gen_result = self._backend.generate_sync(case.prompt, opts)
            return ExecutionResult(
                case_id=case.id,
                category=case.category,
                prompt=case.prompt,
                response=gen_result.text,
                tokens_generated=gen_result.tokens_generated,
                elapsed_sec=gen_result.elapsed_sec,
                tok_per_sec=gen_result.tok_per_sec,
                backend=self._backend.backend_type.value,
                model_id=self._backend.profile().model_id if self._backend.profile() else "unknown",
                error=None,
                payload_hash=compute_payload_hash(gen_result.text),
            )
        except RuntimeError as e:
            logger.warning("Backend runtime error for case %s: %s", case.id, e)
            return ExecutionResult(
                case_id=case.id,
                category=case.category,
                prompt=case.prompt,
                response="",
                tokens_generated=0,
                elapsed_sec=0.0,
                tok_per_sec=0.0,
                backend=self._backend.backend_type.value,
                model_id=self._backend.profile().model_id if self._backend.profile() else "unknown",
                error=str(e),
            )
        except Exception as e:
            logger.error("Unexpected error running case %s: %s", case.id, e)
            return ExecutionResult(
                case_id=case.id,
                category=case.category,
                prompt=case.prompt,
                response="",
                tokens_generated=0,
                elapsed_sec=0.0,
                tok_per_sec=0.0,
                backend=self._backend.backend_type.value,
                model_id=self._backend.profile().model_id if self._backend.profile() else "unknown",
                error=f"execution_error: {e}",
            )

    def run_batch(self, cases: list["TestCase"]) -> list[ExecutionResult]:
        """顺序执行多个用例，保持输入顺序。"""
        return [self.run(c) for c in cases]
