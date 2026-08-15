# test-script-template.py —— AIQE 测试脚本骨架模板
#
# 【使用方法】复制本文件到你的项目，按注释标注的「自定义点」修改后直接运行：
#   python test-script-template.py
#
# 本骨架完成一条最小可用跑分流水线：
#   3 个自定义用例 → ExecutionRunner 执行 → OutputJudge 评分
#   → EvaluationReport 控制台摘要 + JSON 落盘
# （回归对比不是骨架必备项：需要时取消第 6 步注释即可）
#
# 零第三方依赖（AIQE 本身零运行时依赖，HTTP 走标准库）。

import sys
from pathlib import Path

# ── 自定义点 1：AIQE 包路径 ─────────────────────────────
# 若 AIQE 已 pip install，可删除以下三行；否则指向仓库 src/ 目录
# （本模板位于 templates/ 子目录，所以向上两级到仓库根）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from AIQE.cases.test_cases import get_test_cases  # 可选：内置标准用例集
from AIQE.judge import OutputJudge
from AIQE.regression import RegressionAnalyzer    # 可选：回归对比用
from AIQE.reporter import EvaluationReport
from AIQE.runner import ExecutionRunner
from AIQE.schema import TestCase, ScoreBreakdown


def build_cases() -> list[TestCase]:
    """── 自定义点 2：你的用例集 ──────────────────────────
    字段填写规则见 templates/test-case-template.md；
    也可直接返回 get_test_cases() 使用内置 4 个标准用例。
    以下 3 个用例只是示例：按你的验收标准改写。
    """
    return [
        TestCase(
            id="chat_greeting",
            category="chat",                       # 复用既有类别，勿自造
            prompt="你好，请用一句话介绍你自己。",
            expected_keywords=["你好", "AI"],
            min_length=10,
            max_tokens=128,
            scoring=ScoreBreakdown(relevance=1.0, confidence=1.0),
            description="示例：基础对话",
        ),
        TestCase(
            id="json_listing",
            category="json_output",                # 触发 judge 的 JSON 格式分支
            prompt='以JSON格式输出：{"name": "AI", "type": "assistant"}',
            expected_keywords=['"', "{", "}"],     # 与 mock 响应匹配；真机可用语义关键词
            min_length=10,
            max_tokens=128,
            description="示例：结构化输出",
        ),
        TestCase(
            id="code_fix",
            category="coding_task",                # 触发 judge 的代码格式分支
            prompt="写一个 Python 快速排序函数，函数名为 quick_sort。",
            expected_keywords=["def", "quick_sort", "return"],
            min_length=30,
            max_tokens=256,
            description="示例：代码生成",
        ),
    ]


def main() -> None:
    # ── 自定义点 3：后端选择 ─────────────────────────────
    # 默认 mock（确定性、零依赖、离线可跑）。注意：mock 只对内置用例
    # 场景（json/排序/翻译）有针对性响应——换成真实后端时，任意用例
    # 都会得到真实输出。接真实后端：注入满足 AIQE.protocol.Backend 的
    # 实例即可，例如 ollama 示例里的 OllamaEvalBackend
    # （见 examples/ollama_backend.py）。
    from AIQE.backends.mock import MockEvalBackend
    backend = MockEvalBackend(model_id="template-eval")
    backend.setup()

    # ── 自定义点 4：报告标识与落盘路径 ───────────────────
    report_id = "template-run"
    out_path = Path("AIQE-report-template.json")   # 已 gitignore 的命名模式

    try:
        runner = ExecutionRunner(backend)
        judge = OutputJudge()
        analyzer = RegressionAnalyzer()            # 基线目录 ~/.AIQE/results
        report = EvaluationReport(test_plan_id=report_id)

        # ── 自定义点 5：用例来源（内置标准集 or 自定义集）──
        cases = build_cases()

        for case in cases:
            exec_result = runner.run(case)
            judge_result = judge.judge(case, exec_result)
            # 第 6 步（回归对比）需要 analyzer：
            regression_result = analyzer.analyze(case.id, judge_result.score)
            report.add_case(case, exec_result, judge_result, regression_result)

        report.to_json(path=out_path)
        print(f"报告已写入: {out_path.resolve()}")
        report.print_summary()
    finally:
        backend.teardown()


if __name__ == "__main__":
    main()
