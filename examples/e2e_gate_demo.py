"""E2E 质量门禁演示：AI healer 把测试修绿了，能不能放行？

一条命令复现六个场景（零网络、零第三方依赖、不需要浏览器）：

    python examples/e2e_gate_demo.py            # 输出到系统临时目录
    python examples/e2e_gate_demo.py --out ~/aiqe-e2e-demo

输入是 examples/e2e_gate/ 下手写的公开样例：Playwright JSON 报告 + healer diff。
输出：每个场景的门禁判定 JSON / Markdown、AIQE 结果契约文档，以及一个离线看板。
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from AIQE.contract import DataClassification, SourceType
from AIQE.dashboard import _find_git_root, write_dashboard
from AIQE.e2e_gate import run_gate, to_markdown, to_result_document

HERE = Path(__file__).resolve().parent / "e2e_gate"

#: (场景, 报告, 基线, diff, 讲给人听的一句话)
SCENARIOS = (
    ("01-baseline", "01-baseline.json", None, None,
     "基线：6 个用例全绿"),
    ("02-red", "02-candidate-red.json", "01-baseline.json", None,
     "新版本：确认页断言失败 + 优惠券定位器超时"),
    ("03-heal-honest", "03-healed-honest.json", "01-baseline.json", "patch-honest.diff",
     "诚实 healer：只修了定位器；确认页是产品缺陷，照样拦下"),
    ("04-heal-cheating", "04-healed-cheating.json", "01-baseline.json", "patch-cheating.diff",
     "取巧 healer：删断言 + 换宽松匹配，Playwright 全绿——门禁仍然拦下"),
    ("05-product-fixed", "05-product-fixed.json", "01-baseline.json", "patch-honest.diff",
     "开发修了产品缺陷 + 诚实 healer：放行"),
    ("06-flaky", "06-flaky.json", "01-baseline.json", None,
     "重试才通过：不阻断也不自动放行，交给人看"),
)


def generate(output: Path) -> dict[str, str]:
    output = output.expanduser().resolve()
    if _find_git_root(output) is not None:
        raise ValueError("演示输出目录必须位于 Git 工作树之外")
    runs_dir = output / "runs"
    gate_dir = output / "gate"
    runs_dir.mkdir(parents=True, exist_ok=True)
    gate_dir.mkdir(parents=True, exist_ok=True)

    verdicts: dict[str, str] = {}
    print(f"{'场景':<18}{'Playwright':<14}{'门禁':<10}原因码")
    for index, (name, report, baseline, patch, story) in enumerate(SCENARIOS, start=1):
        evaluated_at = f"2026-11-{10 + index:02d}T08:00:00+00:00"
        result = run_gate(
            HERE / report,
            baseline=HERE / baseline if baseline else None,
            patch=HERE / patch if patch else None,
            evaluated_at=evaluated_at,
        )
        counts = result.counts()
        playwright = "全绿" if counts["failed"] == 0 else f"{counts['failed']} 失败"
        codes = ", ".join(sorted({f.code for f in result.findings})) or "—"
        print(f"{name:<18}{playwright:<14}{result.verdict.value:<10}{codes}")
        print(f"{'':<18}↳ {story}")

        (gate_dir / f"{name}.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (gate_dir / f"{name}.md").write_text(to_markdown(result), encoding="utf-8")
        document = to_result_document(
            result,
            run_id=f"e2e-demo-{name}",
            suite_id="aiqe-e2e-demo",
            sut_id=f"build-{100 + index}",
            # 样例是手写的公开数据，可公开；真实项目保持默认 internal
            data_classification=DataClassification.PUBLIC_SYNTHETIC,
            notes=story,
        )
        (runs_dir / f"{name}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        verdicts[name] = result.verdict.value

    target, payload = write_dashboard(
        [runs_dir], output / "index.html", generated_at=f"2026-11-{10 + len(SCENARIOS):02d}T08:00:00+00:00",
        allowed_source_types={SourceType.SYNTHETIC, SourceType.LOCAL_TEST},
    )
    assert payload["totals"]["unreadable_count"] == 0
    print(f"\n判定 JSON / Markdown：{gate_dir}")
    print(f"看板：{target}")
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "aiqe-e2e-gate-demo")
    args = parser.parse_args()
    verdicts = generate(args.out)
    expected = {"01-baseline": "PASS", "02-red": "BLOCK", "03-heal-honest": "BLOCK",
                "04-heal-cheating": "BLOCK", "05-product-fixed": "PASS", "06-flaky": "ESCALATE"}
    if verdicts != expected:
        print(f"演示结果与预期不符：{verdicts}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
