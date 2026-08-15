# regression_compare.py —— 两次跑分对比回归演示（mock 后端，可离线）
#
# 用途：演示「测试左移」最核心的闭环——生成基线 JSON → 改参数再跑 →
#       输出回归结论。全程 mock 后端，无需模型、无需网络。
#
# 【先做什么再跑】
#   直接运行即可（两种模式）：
#     python examples/regression_compare.py           # 相同后端跑两次：应无回归
#     python examples/regression_compare.py --degrade # 第二次用「变差」的后端：应报回归
#
#   输出三份内容：
#     1. 第一次跑分报告（同时作为基线 baseline.json 落盘）
#     2. 第二次跑分报告
#     3. 回归结论表 + 决策建议
#
# 【改参数再跑 的对应关系】
#   实际换模型评估时，「第一次」是你的当前模型，「第二次」是你想换的
#   模型——把脚本里两次 run() 的 backend 换成两个真实后端（如
#   OllamaEvalBackend 配不同 OLLAMA_MODEL）即可，流水线零改动。
#   本示例用 --degrade 模拟「换版后变差的模型」：把响应截断到前 12 个
#   字符，关键词丢失 + 长度不足，分数必然下降。
#
# 零第三方依赖。基线/报告只写在 examples/.regression-demo/ 本地目录，
# 不污染 ~/.AIQE 正式基线。

import argparse
import sys
from pathlib import Path

# 允许直接以脚本方式运行（不依赖安装）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from AIQE.backends.mock import MockEvalBackend  # noqa: E402
from AIQE.cases.test_cases import get_test_cases  # noqa: E402
from AIQE.judge import OutputJudge  # noqa: E402
from AIQE.protocol import GenerateOptions, GenerateResult  # noqa: E402
from AIQE.regression import RegressionAnalyzer  # noqa: E402
from AIQE.reporter import EvaluationReport  # noqa: E402
from AIQE.runner import ExecutionRunner  # noqa: E402

# 示例数据目录（已 gitignore）：run1 报告即基线，run2 报告留档
DEMO_DIR = Path(__file__).resolve().parent / ".regression-demo"
BASELINE_PATH = DEMO_DIR / "baseline.json"


class DegradedMockBackend(MockEvalBackend):
    """模拟「换版后变差」的后端：把确定性响应截断到前 12 个字符。

    截断导致：关键词命中率下降（大部分关键词落在 12 字符之外）+
    响应长度不足（触发 judge 的长度惩罚 ×0.5）——分数必然下降，
    从而演示回归检测。其余行为（setup/teardown/profile）继承 mock。
    """

    name = "mock-degraded"

    def generate_sync(
        self, prompt: str, opts: GenerateOptions | None = None
    ) -> GenerateResult:
        if not self.is_loaded():
            raise RuntimeError("模型未加载，请先调用 setup()")
        result = super().generate_sync(prompt, opts)
        truncated = result.text[:12]
        return GenerateResult(
            text=truncated,
            tokens_generated=max(1, len(truncated) // 2),
            elapsed_sec=result.elapsed_sec,
            tok_per_sec=result.tok_per_sec,
            thinking="",
        )


def run_round(backend, report_path: Path) -> list[dict]:
    """跑一轮完整流水线：执行 → 评分 → 回归 → 报告落盘。返回用例级结论。"""
    runner = ExecutionRunner(backend)
    judge = OutputJudge()
    analyzer = RegressionAnalyzer(storage_path=str(DEMO_DIR))
    report = EvaluationReport(test_plan_id="regression-compare")
    rows: list[dict] = []

    for case in get_test_cases():
        exec_result = runner.run(case)
        judge_result = judge.judge(case, exec_result)
        regression_result = analyzer.analyze(case.id, judge_result.score)
        report.add_case(case, exec_result, judge_result, regression_result)
        rows.append({
            "case_id": case.id,
            "score": judge_result.score,
            "status": regression_result.status,
            "delta": regression_result.delta,
            "baseline": regression_result.baseline_score,
        })

    report.to_json(path=report_path)
    print(f"报告已写入: {report_path.resolve()}")
    report.print_summary()
    return rows


def print_conclusion(rows: list[dict], degraded: bool) -> None:
    """输出回归结论表 + 决策建议。"""
    sep = "─" * 56
    print(f"\n{sep}")
    print("  回归结论")
    print(sep)
    print(f"  {'case_id':<18}{'基线':>8}{'当前':>8}{'delta':>9}  状态")
    print(sep)
    for r in rows:
        base = f"{r['baseline']:.2f}" if r["baseline"] is not None else "  -"
        print(f"  {r['case_id']:<18}{base:>8}{r['score']:>8.2f}"
              f"{r['delta']:>+9.2f}  {r['status']}")

    statuses = {r["status"] for r in rows}
    print(sep)
    if "regression" in statuses:
        print("  决策建议：存在 regression——建议拒绝发布或回退到基线版本，")
        print("            并对照两个报告逐用例排查差异原因（关键词命中/长度/格式）。")
    elif "degraded" in statuses and degraded is False:
        # 相同后端两次跑分：delta=0 也标 degraded 是框架语义（只有提升才标 pass）
        print("  决策建议：所有用例与基线持平（delta=0.00 标 degraded 是阈值语义，")
        print("            实际无退化）——相同后端重复跑分结果可复现。")
    else:
        print("  决策建议：无回归（degraded 仅指轻微下降 ≤0.15，可人工抽检后放行）。")
    print(sep)
    print("  提示：真实换模型评估时，把两轮 run_round() 的 backend 换成")
    print("        不同的真实后端（如 ollama 两个模型），此结论逻辑完全复用。")


def main() -> None:
    parser = argparse.ArgumentParser(description="AIQE 两次跑分回归对比演示（mock，离线）")
    parser.add_argument("--degrade", action="store_true",
                        help="第二轮用「变差」的 mock 后端，演示回归检测")
    args = parser.parse_args()

    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    # ── 第一轮：正常 mock → 生成基线 ──────────────────────
    print("══ 第一轮跑分（正常 mock 后端）—— 本轮报告即基线 ══")
    backend1 = MockEvalBackend(model_id="regression-demo-v1")
    backend1.setup()
    rows1 = run_round(backend1, BASELINE_PATH)  # 直接以 baseline.json 落盘
    backend1.teardown()
    # 基线就位后，第一轮的 regression 结果自然全部是 new（无历史可比）
    print(f"基线已写入: {BASELINE_PATH.resolve()}")

    # ── 第二轮：同后端 或 --degrade 变差后端 ───────────────
    if args.degrade:
        print("\n══ 第二轮跑分（--degrade：模拟换版后变差的模型）══")
        backend2 = DegradedMockBackend(model_id="regression-demo-v2-degraded")
    else:
        print("\n══ 第二轮跑分（相同 mock 后端，验证可复现）══")
        backend2 = MockEvalBackend(model_id="regression-demo-v2")
    backend2.setup()
    rows2 = run_round(backend2, DEMO_DIR / "run2-report.json")
    backend2.teardown()

    # ── 回归结论 ───────────────────────────────────────────
    print_conclusion(rows2, degraded=args.degrade)


if __name__ == "__main__":
    main()
