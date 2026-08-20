# AIQE/judge.py —— OutputJudge：确定性评分器
#
# 评分维度：关键词匹配 / 长度检查 / 格式校验。
# 不调用外部 LLM，不引入新依赖。
#
# 评分规则（v0.1.0）：
#   - 空响应 → 0 分（强制零分）
#   - 长度不足 → 关键词分 × 0.5
#   - 格式校验（json_output / coding_task）真实计入综合分：
#     格式分 < 1.0 时按格式分打折（完全错误 → 0 分，部分结构 → 折半）
#   - 综合分不超过 case.scoring.relevance 上限

from __future__ import annotations

import json
import re
from typing import Any

from AIQE.runner import ExecutionResult
from AIQE.schema import ScoreBreakdown, TestCase


class JudgeResult:
    """单个用例的评分结果。

    score: 0.0 ~ 1.0，0.5 为通过阈值
    checks: 各子项是否通过
    reasons: 人工可读的说明列表
    """
    def __init__(
        self,
        *,
        score: float,
        breakdown: ScoreBreakdown,
        passed: bool,
        checks: dict[str, bool],
        reasons: list[str] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self.score = score
        self.breakdown = breakdown
        self.passed = passed
        self.checks = checks
        self.reasons = reasons or []
        self.metrics = metrics or {}

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "passed": self.passed,
            "breakdown": self.breakdown.model_dump(),
            "checks": self.checks,
            "reasons": self.reasons,
            "metrics": self.metrics,
        }


class OutputJudge:
    """确定性评分器：对 ExecutionResult 做关键词 / 长度 / 格式校验。

    评分 DAG（各检查独立，乘法叠加）：
      1. empty_response   → score = 0.0（强制零分）
      2. keyword_check    → hits / total（核心分数）
      3. length_check     → 响应太短 × 0.5
      4. format_check     → JSON / 代码块检测，真实计入综合分：
                           格式分 < 1.0 时按格式分打折
                           （chat / translation 类恒为 1.0，不受影响）

    最终 score 不超过 case.scoring.relevance（尊重 per-case 评分上限）。
    """

    def judge(self, case: TestCase, result: ExecutionResult) -> JudgeResult:
        """执行全部检查，返回 JudgeResult。"""
        checks: dict[str, bool] = {}
        reasons: list[str] = []
        metrics: dict[str, Any] = {}

        # ── 1. 空响应（强制零分）─────────────────────────────
        if not result.response or not result.response.strip():
            checks["empty_response"] = True
            reasons.append("响应为空")
            return JudgeResult(
                score=0.0,
                breakdown=case.scoring,
                passed=False,
                checks=checks,
                reasons=reasons,
                metrics=metrics,
            )
        checks["empty_response"] = False

        # ── 2. 长度检查 ──────────────────────────────────────
        resp_len = len(result.response.strip())
        if resp_len < case.min_length:
            checks["length_ok"] = False
            reasons.append(f"响应过短（{resp_len} 字符 < {case.min_length} 要求）")
        else:
            checks["length_ok"] = True
        metrics["response_length"] = resp_len

        # ── 3. 关键词匹配（核心分数）──────────────────────────
        keywords = case.expected_keywords
        if keywords:
            hits = sum(1 for kw in keywords if kw in result.response)
            keyword_score = hits / len(keywords)
            checks["keywords_match"] = keyword_score >= 0.5
            reasons.append(f"关键词命中 {hits}/{len(keywords)}（{keyword_score:.0%}）")
        else:
            keyword_score = 1.0
            checks["keywords_match"] = True
            reasons.append("无关键词要求，默认满分")
        metrics["keyword_hits"] = sum(1 for kw in keywords if kw in result.response)
        metrics["keyword_total"] = len(keywords)

        # ── 4. 格式检查（真实计入综合分）────────────────────
        fmt_score = self._check_format(result.response, case.category)
        checks["format_ok"] = fmt_score >= 0.5
        metrics["format_score"] = fmt_score
        if fmt_score < 1.0:
            reasons.append(f"格式校验未通过（格式分 {fmt_score:.0%}）")

        # ── 综合评分 ─────────────────────────────────────────
        # 基础分 = 关键词命中率；
        # 长度不达标 × 0.5；
        # 格式分 < 1.0（仅 json_output / coding_task 会触发）按格式分打折：
        #   完全错误的格式（如要求 JSON 却输出纯文本）→ 0 分；
        #   部分结构（如含花括号但解析失败）→ 折半。
        # chat / translation 类格式分恒为 1.0，不受影响。
        score = keyword_score
        if not checks["length_ok"]:
            score *= 0.5
        score *= fmt_score

        # 尊重 per-case scoring 上限
        max_score = case.scoring.relevance
        score = min(score, max_score)

        score = round(score, 4)
        passed = score >= 0.5

        return JudgeResult(
            score=score,
            breakdown=case.scoring,
            passed=passed,
            checks=checks,
            reasons=reasons,
            metrics=metrics,
        )

    @staticmethod
    def _check_format(text: str, category: str) -> float:
        """格式检查：按类别检测常见结构。"""
        text_stripped = text.strip()

        if category == "json_output":
            try:
                json.loads(text_stripped)
                return 1.0
            except (json.JSONDecodeError, ValueError):
                # 检测是否包含 JSON 基本结构
                if re.search(r'[\{\[]', text_stripped) and re.search(r'[\}\]]', text_stripped):
                    return 0.5
                return 0.0

        if category == "coding_task":
            # 检测代码块标记或常见函数定义
            has_code_block = "```" in text_stripped or "def " in text_stripped or "function " in text_stripped
            has_indent = bool(re.search(r"\n\s{2,}", text_stripped))
            if has_code_block or (has_indent and "return" in text_stripped.lower()):
                return 1.0
            if has_indent or "def " in text_stripped:
                return 0.5
            return 0.0

        # chat / translation 等：不做强格式检查
        return 1.0
