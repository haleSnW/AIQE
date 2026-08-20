"""AIQE 格式评分回归测试（P0-1）

验证：format_score 真实计入最终综合分——
相同关键词命中的响应，格式正确必须得分更高，格式错误必须拉低分数。

回归背景（v0.1.0 修复）：早期版本计算了 format_score 但未纳入最终 score，
导致 json_output 类别下「要求 JSON 却输出纯文本」仍可能拿到高分。
本测试锁定修复后的行为：
  - json_output + 合法 JSON    → score 不因格式扣分（format=1.0）
  - json_output + 非法文本    → score 按格式分打折（format=0.0 → 0 分）
  - json_output + 部分结构    → score 折半（format=0.5）
  - chat（无强格式要求）      → 格式分恒为 1.0，不受影响
"""
import warnings
warnings.filterwarnings("ignore", message=".*cannot collect test class.*")

import pytest

from AIQE.judge import OutputJudge
from AIQE.runner import ExecutionResult
from AIQE.schema import TestCase


def _make_result(response: str, category: str = "json_output") -> ExecutionResult:
    return ExecutionResult(
        case_id="fmt", category=category, prompt="x",
        response=response, tokens_generated=1, elapsed_sec=0.1,
        tok_per_sec=1.0, backend="mock", model_id="m",
    )


def _judge(category: str, response: str, keywords: list[str] | None = None) -> tuple[float, float, bool]:
    """返回 (score, format_score, passed)。"""
    judge = OutputJudge()
    case = TestCase(
        id="fmt", category=category, prompt="x",
        expected_keywords=keywords or ["ok"], min_length=5,
    )
    jr = judge.judge(case, _make_result(response, category))
    return jr.score, jr.metrics["format_score"], jr.passed


def test_format_correct_json_keeps_full_score():
    """合法 JSON + 关键词命中 → 满分，格式分 1.0。"""
    score, fmt, passed = _judge("json_output", '{"answer": "ok"}')
    assert fmt == 1.0
    assert score == 1.0
    assert passed is True


def test_format_broken_json_reduces_score_to_zero():
    """非法 JSON（纯文本）+ 关键词命中 → 格式分 0.0，score 归零。

    核心回归：早期版本此场景 score 仍为 1.0（格式分未纳入综合分）。
    """
    score, fmt, passed = _judge("json_output", "plain text with ok inside")
    assert fmt == 0.0
    assert score == 0.0
    assert passed is False


def test_format_partial_json_halves_score():
    """含 JSON 基本结构但解析失败 → 格式分 0.5，score 折半。"""
    score, fmt, passed = _judge("json_output", '{"answer": ok}')
    assert fmt == 0.5
    assert score == 0.5
    assert passed is True  # 0.5 ≥ 通过阈值


def test_format_broken_still_respects_keywords():
    """格式错误与关键词同时影响：无关键词命中且格式错误 → 0 分且 passed=False。"""
    score, fmt, passed = _judge("json_output", "not json, no keywords", keywords=["ok"])
    assert fmt == 0.0
    assert score == 0.0
    assert passed is False


def test_format_broken_score_lower_than_format_ok():
    """相同关键词命中，格式错误分数必须低于格式正确分数（核心断言）。"""
    score_ok, _, _ = _judge("json_output", '{"answer": "ok"}')
    score_broken, _, _ = _judge("json_output", "plain text ok")
    assert score_broken < score_ok


def test_format_check_not_applied_to_chat_category():
    """chat 类别不做强格式检查：格式分恒为 1.0，纯文本不因格式扣分。"""
    score, fmt, passed = _judge("chat", "ok whatever")
    assert fmt == 1.0
    assert score == 1.0
    assert passed is True


def test_format_broken_flagged_in_reasons():
    """格式未通过时 reasons 必须包含可读说明（不 silent fail）。"""
    judge = OutputJudge()
    case = TestCase(id="f", category="json_output", prompt="x",
                    expected_keywords=["ok"], min_length=5)
    jr = judge.judge(case, _make_result("plain text ok"))
    assert any("格式" in r for r in jr.reasons)
