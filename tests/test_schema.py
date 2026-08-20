"""AIQE 数据模型与 Runner 的契约测试

覆盖：ScoreBreakdown 加权分与默认值、model_dump 兼容层、
TestCase / EvaluationResult 字段、LocalRunner 本地确定性执行、
OllamaRunner 关键词评分。

pytest 收集时会对 TestCase 类发出 PytestCollectionWarning，已在 pyproject.toml
中通过 filterwarnings 忽略（不影响测试结果）。
"""
import warnings
warnings.filterwarnings("ignore", message=".*cannot collect test class.*")
import pytest
from unittest.mock import MagicMock

from AIQE.schema import (
    TestCase, EvaluationResult, ScoreBreakdown,
    LocalRunner, OllamaRunner,
)


def test_score_breakdown_weighted():
    sb = ScoreBreakdown(relevance=0.8, correctness=0.9, completeness=0.7, formatting=1.0, confidence=0.95)
    # 加权平均 = (0.8+0.9+0.7+1.0)/4 * 0.95 = 0.85 * 0.95 = 0.8075
    assert abs(sb.weighted_score() - 0.8075) < 0.001


def test_score_breakdown_defaults():
    sb = ScoreBreakdown()
    assert sb.relevance == 1.0
    assert sb.confidence == 1.0
    assert sb.weighted_score() == 1.0


def test_score_breakdown_model_dump():
    """model_dump() 兼容原 pydantic 版调用方式（judge/reporter 依赖）。"""
    sb = ScoreBreakdown(relevance=0.6, confidence=0.9)
    d = sb.model_dump()
    assert d["relevance"] == 0.6
    assert d["confidence"] == 0.9
    assert set(d.keys()) == {"relevance", "correctness", "completeness", "formatting", "confidence"}


def test_test_case_creation():
    case = TestCase(
        id="test_case",
        category="chat",
        prompt="hello",
        expected_keywords=["hello"],
        min_length=5,
        max_tokens=100,
    )
    assert case.id == "test_case"
    assert case.expected_keywords == ["hello"]


def test_test_case_defaults():
    """字段默认值（scoring 默认满分、min_length 10）。"""
    case = TestCase(id="t", category="chat", prompt="hi")
    assert case.min_length == 10
    assert case.max_tokens == 512
    assert case.scoring == ScoreBreakdown()


def test_evaluation_result_to_dict():
    result = EvaluationResult(
        case_id="test",
        category="chat",
        prompt="hello",
        response="hi",
        score=0.9,
        breakdown=ScoreBreakdown(),
        latency_sec=0.5,
        tokens_generated=10,
        backend="local",
        model_id="mock",
    )
    d = result.to_dict()
    assert d["case_id"] == "test"
    assert d["score"] == 0.9
    assert "timestamp" in d
    assert d["breakdown"]["confidence"] == 1.0


def test_local_runner_returns_result():
    runner = LocalRunner()
    case = TestCase(id="r1", category="chat", prompt="hi")
    result = runner.run(case)
    assert result.case_id == "r1"
    assert result.backend == "local"
    assert result.score == 1.0  # mock 默认满分


def test_local_runner_batch():
    runner = LocalRunner()
    cases = [
        TestCase(id="b1", category="chat", prompt="hi"),
        TestCase(id="b2", category="chat", prompt="hello"),
    ]
    results = runner.run_batch(cases)
    assert len(results) == 2
    assert results[0].case_id == "b1"
    assert results[1].case_id == "b2"


def test_local_runner_with_mock_backend():
    mock_backend = MagicMock()
    from AIQE.protocol import GenerateResult
    mock_backend.generate_sync.return_value = GenerateResult(
        text="actual response", tokens_generated=5, elapsed_sec=0.2, tok_per_sec=25.0, thinking=""
    )
    runner = LocalRunner(backend=mock_backend)
    case = TestCase(id="m1", category="chat", prompt="hi")
    result = runner.run(case)
    assert result.response == "actual response"
    assert result.tokens_generated == 5
    mock_backend.generate_sync.assert_called_once()


def test_ollama_runner_keyword_scoring():
    assert OllamaRunner._score_with_keywords("hello world", ["hello", "world"]) == 1.0
    assert OllamaRunner._score_with_keywords("hello", ["hello", "world"]) == 0.5
    assert OllamaRunner._score_with_keywords("no match", ["hello", "world"]) == 0.0
    assert OllamaRunner._score_with_keywords("anything", []) == 1.0
