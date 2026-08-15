# AIQE/cases/test_cases.py —— 标准评估用例（独立版）
#
# 预定义的评估用例，覆盖 chat / translation / structured / coding 四类场景。
# 镜像说明（协议副本说明）：本模块是 上游项目 仓库内
# framework/ai_eval/cases/test_cases.py 的独立导出版，用例内容逐字一致。
from __future__ import annotations

from AIQE.schema import ScoreBreakdown, TestCase


def get_test_cases() -> list[TestCase]:
    """返回标准评估用例列表。"""
    return [
        TestCase(
            id="simple_chat",
            category="chat",
            prompt="你好，请用一句话介绍你自己。",
            expected_keywords=["你好", "AI"],
            min_length=10,
            max_tokens=128,
            description="基础对话：模型应使用中文自我介绍",
        ),
        TestCase(
            id="long_translation",
            category="translation",
            prompt=(
                "请将以下中文翻译为英文：\n"
                "人工智能是计算机科学的一个分支，它企图了解智能的实质，"
                "并生产出一种新的能以人类智能相似的方式做出反应的智能机器。"
            ),
            expected_keywords=["artificial", "intelligence", "computer"],
            min_length=20,
            max_tokens=256,
            description="长文本翻译：检测关键词覆盖度",
        ),
        TestCase(
            id="json_output",
            category="json_output",
            prompt='以JSON格式输出一行：{"name": "AI", "type": "assistant"}',
            expected_keywords=['"', "{", "}"],
            min_length=10,
            max_tokens=128,
            scoring=ScoreBreakdown(relevance=1.0, correctness=1.0, formatting=1.0, confidence=1.0),
            description="结构化输出：验证 JSON 格式合法性",
        ),
        TestCase(
            id="coding_task",
            category="coding_task",
            prompt="写一个Python快速排序函数，函数名为 quick_sort",
            expected_keywords=["def", "quick_sort", "return"],
            min_length=30,
            max_tokens=256,
            scoring=ScoreBreakdown(relevance=0.9, correctness=0.9, completeness=0.8, formatting=0.9, confidence=0.95),
            description="代码生成：检测函数定义与返回语句",
        ),
    ]
