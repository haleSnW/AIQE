# quick_score.py —— 30 秒快速跑分示例
#
# 用法：python examples/quick_score.py
#
# 流程：mock 后端（确定性，无需模型/网络）
#   → ExecutionRunner 执行 4 个标准用例
#   → OutputJudge 确定性评分
#   → RegressionAnalyzer 对比基线（首次跑 → status="new"）
#   → EvaluationReport 输出 JSON 报告 + 控制台条形图摘要

import sys
from pathlib import Path

# 允许直接以脚本方式运行（不依赖安装）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from AIQE.backends.mock import MockEvalBackend
from AIQE.cases.test_cases import get_test_cases
from AIQE.judge import OutputJudge
from AIQE.regression import RegressionAnalyzer
from AIQE.reporter import EvaluationReport
from AIQE.runner import ExecutionRunner


def main() -> None:
    # 1. mock 后端：确定性响应，零模型零网络
    backend = MockEvalBackend(model_id="quick-score-mock")
    backend.setup()
    try:
        # 2. 组装流水线
        runner = ExecutionRunner(backend)
        judge = OutputJudge()
        analyzer = RegressionAnalyzer()          # 默认基线目录 ~/.AIQE/results
        report = EvaluationReport(test_plan_id="quick-score")

        # 3. 执行 → 评分 → 回归 → 聚合
        for case in get_test_cases():
            exec_result = runner.run(case)
            judge_result = judge.judge(case, exec_result)
            regression_result = analyzer.analyze(case.id, judge_result.score)
            report.add_case(case, exec_result, judge_result, regression_result)

        # 4. 落盘报告 + 控制台摘要
        out = Path("AIQE-report.json")
        report.to_json(path=out)
        print(f"报告已写入: {out.resolve()}")

        # 5. 控制台条形图摘要
        report.print_summary()

        # 6. 摘要速览
        summary = report._compute_summary()
        print(f"通过 {summary['passed']}/{summary['total']}"
              f" · 回归 {len(summary['regressions'])} 个\n")
        print("（这是 mock 后端的演示分数；接入真实模型时替换为满足")
        print(" AIQE.protocol.Backend 的后端实例即可，流水线零改动。）")
    finally:
        backend.teardown()


if __name__ == "__main__":
    main()
