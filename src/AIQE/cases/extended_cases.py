# AIQE/cases/extended_cases.py —— 扩展评估用例（独立版）
#
# 扩展评估用例，覆盖 6 个中文场景：
# 长文本翻译 / 情感分类(JSON 限定选项) / 摘要压缩 / 代码审查(找 bug) /
# 多轮对话连续性 / 边界输入(全角、emoji、超长单行)。
#
# 镜像说明（协议副本说明）：本模块是 上游项目 仓库内
# framework/ai_eval/cases/extended_cases.py 的独立导出版，用例内容逐字一致。
from __future__ import annotations

from AIQE.schema import TestCase


# 本模块 6 个用例实际使用的类别清单（单一事实来源，测试与用例都引用它）：
# - json_output / coding_task 复用既有类别，保证 judge.py 的特殊格式分支有真实用例覆盖
# - 其余为新引入类别（schema.py 中 category 为自由字符串，无枚举约束）
EXTENDED_CATEGORIES = [
    "translation",
    "json_output",
    "summarization",
    "coding_task",
    "multi_turn",
    "edge_case",
]


def get_extended_cases() -> list[TestCase]:
    """返回 6 个扩展评估用例（中文场景）。"""
    return [
        TestCase(
            id="zh_en_long_translation",
            category="translation",
            prompt=(
                "请将以下中文长文本翻译为英文，保持术语准确、语序自然：\n"
                "机器学习是人工智能的核心分支之一，它通过数据驱动的方式让计算机自动改进算法性能。"
                "深度学习作为机器学习的子领域，利用多层神经网络对海量数据进行特征提取与模式识别，"
                "在图像识别、自然语言处理和语音合成等方向取得了突破性进展。近年来，大语言模型的"
                "出现进一步推动了生成式人工智能的发展，深刻影响了科学研究、内容创作与软件工程等行业。"
            ),
            expected_keywords=["machine", "learning", "artificial", "neural"],
            min_length=50,
            max_tokens=512,
            description="中文到英文长文本翻译：检测术语关键词覆盖度",
        ),
        TestCase(
            id="sentiment_json_output",
            category="json_output",
            prompt=(
                "请判断以下用户评论的情感倾向，只允许输出一个 JSON 对象，格式为 "
                '{"sentiment": "正面" | "负面" | "中性"}，不要输出任何其他内容。\n'
                "评论：等了半小时外卖还没送到，联系客服也一直没人回复，体验太差了。"
            ),
            expected_keywords=['{"sentiment"', '"负面"'],
            min_length=10,
            max_tokens=64,
            description="情感分类：JSON 结构化输出且选项受限（覆盖 judge 的 json_output 特殊分支）",
        ),
        TestCase(
            id="text_summarization",
            category="summarization",
            prompt=(
                "请将以下新闻压缩为一句话摘要（不超过 50 字），保留核心信息：\n"
                "中国科学家团队近日在量子通信领域取得重要突破，成功实现了跨城市距离的"
                "量子密钥分发实验，传输距离达到 1200 公里，刷新了此前的世界纪录。该成果"
                "为未来构建全球量子安全通信网络奠定了技术基础，相关论文已发表于国际顶级期刊。"
            ),
            expected_keywords=["量子", "1200"],
            min_length=10,
            max_tokens=128,
            description="摘要压缩：长文压缩为单句并保留关键数字",
        ),
        TestCase(
            id="code_review_bug",
            category="coding_task",
            prompt=(
                "以下 Python 函数有一个 bug，请找出问题，并用 ``` 代码块给出修复后的完整函数：\n"
                "def average(numbers):\n"
                "    total = sum(numbers)\n"
                "    return total / len(numbers)  # 当 numbers 为空列表时会怎样？"
            ),
            expected_keywords=["def", "ZeroDivisionError", "除零"],
            min_length=30,
            max_tokens=256,
            description="代码审查：定位空列表除零 bug 并给出修复（覆盖 judge 的 coding_task 特殊分支）",
        ),
        TestCase(
            id="multi_turn_continuity",
            category="multi_turn",
            prompt=(
                "以下是一场对话的片段，请作为助手继续回答用户最后的问题：\n"
                "用户：我想了解量子计算的基本原理。\n"
                "助手：量子计算利用量子比特的叠加与纠缠特性，在特定问题上远超经典计算机。\n"
                "用户：你刚才提到的「叠加」，能再具体解释一下吗？\n"
                "助手："
            ),
            expected_keywords=["叠加"],
            min_length=20,
            max_tokens=256,
            description="多轮对话：第二轮提问引用第一轮的概念，验证上下文连续性",
        ),
        TestCase(
            id="edge_case_input",
            category="edge_case",
            prompt=(
                "请忽略输入中的干扰字符（全角符号、表情符号、无意义长串），"
                "直接回答其中的核心问题：\n"
                "Ｈｅｌｌｏ！😀 "
                "这是一段无换行的超长填充文本，用于模拟超长单行输入场景，本身不包含任何问题信息。"
                "这是一段无换行的超长填充文本，用于模拟超长单行输入场景，本身不包含任何问题信息。"
                "这是一段无换行的超长填充文本，用于模拟超长单行输入场景，本身不包含任何问题信息。"
                " 请告诉我中国的首都是哪里。"
            ),
            expected_keywords=["北京"],
            min_length=5,
            max_tokens=128,
            description="边界输入：全角字符/emoji/超长单行混合，验证模型仍能回答核心问题",
        ),
    ]


# 模块级导出：供 CLI / runner / 测试直接引用
ALL_CASES = get_extended_cases()
