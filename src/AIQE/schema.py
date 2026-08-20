# AIQE/schema.py —— 数据模型与 Runner 接口
#
# 纯标准库实现：dataclass 数据模型（ScoreBreakdown / TestCase /
# EvaluationResult）+ ModelRunner 执行器接口（LocalRunner 本地确定性 /
# OllamaRunner HTTP 接入）。
# 零第三方运行时依赖。

from __future__ import annotations
import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ScoreBreakdown:
    """单个维度的评分 + 置信度。"""
    relevance: float = 1.0       # 是否回答了问题
    correctness: float = 1.0     # 答案是否正确
    completeness: float = 1.0    # 是否覆盖所有要点
    formatting: float = 1.0      # 是否符合输出格式
    confidence: float = 1.0      # 评估者自信度（用于加权）

    def weighted_score(self) -> float:
        """加权平均，confidence 作为权重因子。"""
        weights = [1.0] * 4  # 四个维度等权重
        total = sum(s * w for s, w in zip([self.relevance, self.correctness,
                                            self.completeness, self.formatting], weights))
        conf = self.confidence
        return total / sum(weights) * conf

    def model_dump(self) -> dict[str, float]:
        """兼容原 pydantic 版 model_dump() 调用方式。"""
        return {
            "relevance": self.relevance,
            "correctness": self.correctness,
            "completeness": self.completeness,
            "formatting": self.formatting,
            "confidence": self.confidence,
        }


@dataclass
class TestCase:
    """单个评估用例。

    示例：
        TestCase(
            id="simple_chat",
            category="chat",
            prompt="你好，请介绍一下你自己。",
            expected_keywords=["你好", "AI"],
            max_tokens=200,
            scoring=ScoreBreakdown(),
        )
    """
    id: str
    category: str
    prompt: str
    expected_keywords: list[str] = field(default_factory=list)
    min_length: int = 10
    max_tokens: int = 512
    scoring: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    description: str = ""


@dataclass
class EvaluationResult:
    """单次评估的结果。"""
    case_id: str
    category: str
    prompt: str
    response: str
    score: float                         # 0.0 ~ 1.0
    breakdown: ScoreBreakdown
    latency_sec: float
    tokens_generated: int
    backend: str
    model_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "prompt": self.prompt,
            "response": self.response,
            "score": self.score,
            "latency_sec": self.latency_sec,
            "tokens_generated": self.tokens_generated,
            "backend": self.backend,
            "model_id": self.model_id,
            "timestamp": self.timestamp,
            "breakdown": self.breakdown.model_dump(),
        }


class ModelRunner(abc.ABC):
    """评估执行器接口 — 所有 runner 必须实现此接口。"""

    name: str = "unknown"

    @abc.abstractmethod
    def run(self, case: TestCase) -> EvaluationResult:
        """运行单个用例，返回评估结果。"""
        ...

    @abc.abstractmethod
    def run_batch(self, cases: list[TestCase]) -> list[EvaluationResult]:
        """批量运行。"""
        ...


class LocalRunner(ModelRunner):
    """本地默认确定性执行器（无网络）。

    固定返回包含用例 id 的确定性响应，用于测试框架自检与离线演示；
    也可通过 backend 参数注入任意满足 AIQE.protocol.Backend 的对象，
    让执行路径复用真实后端。使用 unittest.mock.Mock 时可直接注入 mock 后端。
    """

    name = "local"

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend

    def run(self, case: TestCase) -> EvaluationResult:
        from AIQE.protocol import GenerateResult
        # 默认：返回固定响应用于测试框架本身
        mock_result = GenerateResult(
            text=f"这是针对 {case.id} 的模拟回答，包含关键词。",
            tokens_generated=case.max_tokens // 4,
            elapsed_sec=0.1,
            tok_per_sec=10.0,
            thinking="",
        )
        # 如果提供了自定义 backend，优先使用其返回结果
        if self._backend is not None:
            backend_result = self._backend.generate_sync(case.prompt)
            if hasattr(backend_result, 'text'):
                mock_result = backend_result
        return EvaluationResult(
            case_id=case.id,
            category=case.category,
            prompt=case.prompt,
            response=mock_result.text,
            score=1.0,  # mock 默认满分
            breakdown=case.scoring,
            latency_sec=mock_result.elapsed_sec,
            tokens_generated=mock_result.tokens_generated,
            backend="local",
            model_id="mock",
        )

    def run_batch(self, cases: list[TestCase]) -> list[EvaluationResult]:
        return [self.run(c) for c in cases]


class OllamaRunner(ModelRunner):
    """Ollama HTTP API 执行器（需要本地 Ollama 服务运行）。

    使用标准库 urllib 实现 HTTP 调用（零第三方依赖）。
    """

    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3") -> None:
        self.base_url = base_url
        self.model = model

    def run(self, case: TestCase) -> EvaluationResult:
        import json
        import urllib.request

        # 使用 /api/chat（messages 格式），与生产代码保持一致；
        # 对 thinking 模型也能拿到正式回答（/api/generate 会返回空内容）。
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": case.prompt}],
            "stream": False,
            "options": {"num_predict": case.max_tokens},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text: str = data.get("message", {}).get("content", "")
        return EvaluationResult(
            case_id=case.id,
            category=case.category,
            prompt=case.prompt,
            response=text,
            score=self._score_with_keywords(text, case.expected_keywords),
            breakdown=case.scoring,
            latency_sec=data.get("total_duration", 0) / 1e9,
            tokens_generated=data.get("eval_count", 0),
            backend="ollama",
            model_id=self.model,
        )

    def run_batch(self, cases: list[TestCase]) -> list[EvaluationResult]:
        return [self.run(c) for c in cases]

    @staticmethod
    def _score_with_keywords(text: str, keywords: list[str]) -> float:
        if not keywords:
            return 1.0
        hits = sum(1 for kw in keywords if kw in text)
        return hits / len(keywords)
