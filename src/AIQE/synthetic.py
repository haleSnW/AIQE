# AIQE/synthetic.py —— 合成样本生成器（受信生成入口）
#
# 【这是本轮唯一的受信数据来源】
#   本模块产出的一切数据都是**人工构造的合成样本**，不含任何真实
#   质量数据、个人数据或来自其他项目的记录。
#
# 【为什么生成器要放在包里，而不是测试里？】
#   content_digest 的验证需要一个**可复现的生成入口**——校验方必须能
#   独立重跑生成器并比对摘要。把入口放在包内，测试、CI、人工复核
#   都能以同一份实现复现，避免「测试里写一套、文档里写一套」的分叉。
#
# 【信任边界（必须诚实声明）】
#   本生成器 + content_digest 能证明：
#     ✓ 文档的结构符合结果契约
#     ✓ 文档由本生成入口产出，且生成后未被改动
#   不能证明：
#     ✗ 文档底层数据在语义上「真的是」合成数据
#
#   掌握生成入口的一方可以把任意数据喂进来并得到合法摘要。
#   因此 source_type="synthetic" 是**声明**，content_digest 是
#   **防篡改证据**，二者都不构成「数据来源真实可信」的证明。
#
#   真实数据接入的控制手段是**独立导入契约的字段白名单**与**授权门禁**
#   （见 docs/architecture/AIQE_MYFRI_IMPORT_CONTRACT_DRAFT.md），
#   不是本模块。本模块的存在**不会**放宽那条路径的任何限制。

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from AIQE.contract import SCHEMA_VERSION, compute_content_digest

GENERATOR_ID = "aiqe.synthetic/0.1.0"
GENERATOR_VERSION = "0.1.0"

#: 固定的生成时间戳 —— 保证 fixtures 可字节级复现。
#: 不用 datetime.now()：那会让每次生成产生不同摘要，无法做漂移检测。
FIXED_CREATED_AT = "2026-09-22T00:00:00+00:00"

DEFAULT_JUDGE_ID = "aiqe.deterministic-judge"
DEFAULT_JUDGE_VERSION = "0.1.0"


# ════════════════════════════════════════════════════════════════
#  构造原语
# ════════════════════════════════════════════════════════════════

def _breakdown(relevance: float = 1.0) -> dict[str, float]:
    return {
        "relevance": relevance,
        "correctness": relevance,
        "completeness": relevance,
        "formatting": 1.0,
        "confidence": 1.0,
    }


def make_case(
    case_id: str,
    category: str,
    prompt: str,
    *,
    response: str,
    tokens_generated: int,
    elapsed_sec: float,
    tok_per_sec: float,
    backend: str,
    model_id: str,
    error: str | None = None,
    score: float = 0.0,
    passed: bool = False,
    checks: dict[str, bool] | None = None,
    reasons: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
    regression: dict[str, Any] | None = None,
    trace_id: str = "synth000",
) -> dict[str, Any]:
    """构造单个用例记录（形状与 EvaluationReport 实际产出一致）。

    【为什么失败用例也要有 judge 块？】
      真实流水线中 judge 一定会跑：ExecutionRunner 在异常路径返回
      response=""，OutputJudge 第一步「空响应 → 强制 0 分」立即命中，
      产出 score=0.0 / passed=False / checks={"empty_response": true}
      / metrics={}（提前 return，不产出 format_score）。
      合成样本必须忠实复现这个形状，否则测不出真实行为。
    """
    case: dict[str, Any] = {
        "case_id": case_id,
        "category": category,
        "prompt": prompt,
        "execution": {
            "response": response,
            "tokens_generated": tokens_generated,
            "elapsed_sec": elapsed_sec,
            "tok_per_sec": tok_per_sec,
            "backend": backend,
            "model_id": model_id,
            "error": error,
            "trace_id": trace_id,
            "payload_hash": _payload_hash(response),
        },
        "judge": {
            "score": score,
            "passed": passed,
            "breakdown": _breakdown(),
            "checks": checks if checks is not None else {},
            "reasons": reasons if reasons is not None else [],
            "metrics": metrics if metrics is not None else {},
        },
    }
    if regression is not None:
        case["regression"] = regression
    return case


def _payload_hash(text: str) -> str:
    """复用 runner.compute_payload_hash 的实现，保持字段语义一致。"""
    from AIQE.runner import compute_payload_hash

    return compute_payload_hash(text)


def make_regression(
    case_id: str,
    *,
    status: str,
    delta: float,
    baseline_score: float | None,
    current_score: float,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": status,
        "delta": delta,
        "baseline_score": baseline_score,
        "current_score": current_score,
    }


def make_document(
    *,
    run_id: str,
    dataset_id: str,
    dataset_version: str,
    model_id: str,
    backend_id: str,
    cases: list[dict[str, Any]],
    judge_id: str = DEFAULT_JUDGE_ID,
    judge_version: str = DEFAULT_JUDGE_VERSION,
    test_plan_id: str = "synthetic-fixture",
    created_at: str = FIXED_CREATED_AT,
    notes: str = "",
) -> dict[str, Any]:
    """构造一份完整的合成结果契约文档（含合法 content_digest）。"""
    document: dict[str, Any] = {
        "test_plan_id": test_plan_id,
        "generated_at": created_at,
        "project": "AIQE",
        "version": "0.1.0",
        "cases": cases,
        "summary": _summary(cases),
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "run_id": run_id,
            "created_at": created_at,
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "judge_id": judge_id,
            "judge_version": judge_version,
            "model_id": model_id,
            "backend_id": backend_id,
            "source_type": "synthetic",
            "data_classification": "public_synthetic",
            "generator": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "content_digest": "",
            "test_plan_id": test_plan_id,
            "notes": notes,
        },
    }
    _reseal(document)
    return document


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """与 EvaluationReport._compute_summary 保持同一口径。"""
    return {
        "passed": sum(1 for c in cases if c.get("judge", {}).get("passed")),
        "total": len(cases),
        "regressions": [
            c["case_id"] for c in cases
            if c.get("regression", {}).get("status") in ("regression", "degraded")
        ],
    }


def _reseal(document: dict[str, Any]) -> None:
    """重算并写入 content_digest（生成器与负样本构造共用）。

    【为什么负样本也要重新封装？】
      为了让「校验失败的原因」唯一。若一份负样本摘要本身就是坏的，
      测试通过就不能证明我们想测的那条规则生效了——
      它可能只是被摘要检查拦下的。
    """
    document["metadata"]["content_digest"] = compute_content_digest(document)


# ════════════════════════════════════════════════════════════════
#  合法样本（Case A–H、L）
# ════════════════════════════════════════════════════════════════

_PROMPT_CHAT = "你好，请用一句话介绍你自己。"
_PROMPT_JSON = '以JSON格式输出一行：{"name": "AI"}'


def _case_ok(case_id: str, *, trace: str, model: str, score: float) -> dict[str, Any]:
    return make_case(
        case_id, "chat", _PROMPT_CHAT,
        response="你好！我是一个合成样本中的 AI 助手。",
        tokens_generated=12, elapsed_sec=0.12, tok_per_sec=100.0,
        backend="mock", model_id=model, score=score, passed=True,
        checks={"empty_response": False, "length_ok": True,
                "keywords_match": True, "format_ok": True},
        reasons=["关键词命中 2/2（100%）"],
        metrics={"response_length": 18, "keyword_hits": 2,
                 "keyword_total": 2, "format_score": 1.0},
        trace_id=trace,
    )


def _case_judge_fail(case_id: str, *, trace: str, model: str, score: float) -> dict[str, Any]:
    return make_case(
        case_id, "chat", _PROMPT_CHAT,
        response="不清楚。",
        tokens_generated=4, elapsed_sec=0.09, tok_per_sec=44.0,
        backend="mock", model_id=model, score=score, passed=False,
        checks={"empty_response": False, "length_ok": False,
                "keywords_match": False, "format_ok": True},
        reasons=["响应过短（4 字符 < 10 要求）", "关键词命中 0/2（0%）"],
        metrics={"response_length": 4, "keyword_hits": 0,
                 "keyword_total": 2, "format_score": 1.0},
        trace_id=trace,
    )


def _case_exec_error(case_id: str, *, trace: str, model: str, error: str) -> dict[str, Any]:
    """执行失败用例：忠实复现 runner 异常分支 + judge 空响应分支。"""
    return make_case(
        case_id, "chat", _PROMPT_CHAT,
        response="", tokens_generated=0, elapsed_sec=0.0, tok_per_sec=0.0,
        backend="mock", model_id=model, error=error,
        score=0.0, passed=False,
        checks={"empty_response": True},
        reasons=["响应为空"],
        metrics={},  # 空响应分支提前 return，不产出 format_score
        trace_id=trace,
    )


def build_valid_runs() -> dict[str, dict[str, Any]]:
    """构造全部合法合成样本。返回 {fixture_name: document}。"""
    runs: dict[str, dict[str, Any]] = {}

    # ── Case A：正常通过 ─────────────────────────────────────
    runs["run_a_normal_pass"] = make_document(
        run_id="synth-run-a",
        dataset_id="aiqe-demo", dataset_version="1.0.0",
        model_id="demo-model-a", backend_id="mock",
        cases=[
            _case_ok("alpha", trace="a0000001", model="demo-model-a", score=0.95),
            _case_ok("beta", trace="a0000002", model="demo-model-a", score=1.0),
        ],
        notes="Case A：执行成功且评分通过",
    )

    # ── Case B：测试失败（执行成功，评分不通过）─────────────
    runs["run_b_case_fail"] = make_document(
        run_id="synth-run-b",
        dataset_id="aiqe-demo", dataset_version="1.0.0",
        model_id="demo-model-a", backend_id="mock",
        cases=[
            _case_ok("alpha", trace="b0000001", model="demo-model-a", score=0.95),
            _case_judge_fail("beta", trace="b0000002", model="demo-model-a", score=0.25),
        ],
        notes="Case B：执行成功但用例不通过（区别于 Case C 的执行异常）",
    )

    # ── Case C：执行异常 ─────────────────────────────────────
    runs["run_c_execution_error"] = make_document(
        run_id="synth-run-c",
        dataset_id="aiqe-demo", dataset_version="1.0.0",
        model_id="demo-model-a", backend_id="mock",
        cases=[
            _case_ok("alpha", trace="c0000001", model="demo-model-a", score=0.95),
            _case_exec_error(
                "beta", trace="c0000002", model="demo-model-a",
                error="execution_error: 模型未加载，请先调用 setup()",
            ),
        ],
        notes="Case C：执行异常，error 非 null，judge 强制 0 分",
    )

    # ── Case D：超时 ─────────────────────────────────────────
    # 注意：本样本**故意**只把超时表达为自由文本 error。
    # 契约层不据此推断 timeout 分类——timeout_count 恒为 UNDEFINED/null。
    runs["run_d_timeout"] = make_document(
        run_id="synth-run-d",
        dataset_id="aiqe-demo", dataset_version="1.0.0",
        model_id="demo-model-a", backend_id="mock",
        cases=[
            _case_exec_error(
                "slow_case", trace="d0000001", model="demo-model-a",
                error="execution_error: request timed out after 60.0s",
            ),
        ],
        notes="Case D：超时。仅以自由文本表达——契约层不产出 timeout_count 数值",
    )

    # ── Case E：指标缺失（合法文档，指标无输入）─────────────
    # 空响应分支提前 return，不产出 judge.metrics.format_score。
    # 契约层必须把它标为 MISSING，而不是当作 0。
    runs["run_e_missing_metric"] = make_document(
        run_id="synth-run-e",
        dataset_id="aiqe-demo", dataset_version="1.0.0",
        model_id="demo-model-a", backend_id="mock",
        cases=[
            make_case(
                "json_case", "json_output", _PROMPT_JSON,
                response="", tokens_generated=0, elapsed_sec=0.05, tok_per_sec=0.0,
                backend="mock", model_id="demo-model-a",
                error=None,  # 执行成功，只是响应为空
                score=0.0, passed=False,
                checks={"empty_response": True},
                reasons=["响应为空"],
                metrics={},  # ← format_score 缺失（不是 0）
                trace_id="e0000001",
            ),
        ],
        notes="Case E：指标缺失。空响应分支不产出 format_score —— 是缺失，不是 0",
    )

    # ── Case G：同一数据集的基线与候选 ──────────────────────
    runs["run_g_baseline"] = make_document(
        run_id="synth-run-g-baseline",
        dataset_id="aiqe-demo", dataset_version="1.0.0",
        model_id="demo-model-a", backend_id="mock",
        cases=[
            {**_case_ok("alpha", trace="g1000001", model="demo-model-a", score=0.80),
             "regression": make_regression("alpha", status="new", delta=0.0,
                                           baseline_score=None, current_score=0.80)},
            {**_case_ok("beta", trace="g1000002", model="demo-model-a", score=0.90),
             "regression": make_regression("beta", status="new", delta=0.0,
                                           baseline_score=None, current_score=0.90)},
        ],
        notes="Case G 基线：同数据集、同评分器、同模型",
    )
    runs["run_g_candidate"] = make_document(
        run_id="synth-run-g-candidate",
        dataset_id="aiqe-demo", dataset_version="1.0.0",
        model_id="demo-model-a", backend_id="mock",
        cases=[
            {**_case_ok("alpha", trace="g2000001", model="demo-model-a", score=0.90),
             "regression": make_regression("alpha", status="pass", delta=0.10,
                                           baseline_score=0.80, current_score=0.90)},
            {**_case_ok("beta", trace="g2000002", model="demo-model-a", score=0.90),
             "regression": make_regression("beta", status="degraded", delta=0.0,
                                           baseline_score=0.90, current_score=0.90)},
        ],
        notes="Case G 候选：与基线同源，无显著退化（beta delta=0 标 degraded 是阈值语义）",
    )

    # ── Case H：有效的回归变化（换模型，测量条件一致）───────
    runs["run_h_candidate"] = make_document(
        run_id="synth-run-h-candidate",
        dataset_id="aiqe-demo", dataset_version="1.0.0",
        model_id="demo-model-b",  # ← 换模型：软差异，不阻断对比
        backend_id="mock",
        cases=[
            {**_case_judge_fail("alpha", trace="h0000001", model="demo-model-b", score=0.40),
             "regression": make_regression("alpha", status="regression", delta=-0.40,
                                           baseline_score=0.80, current_score=0.40)},
            {**_case_ok("beta", trace="h0000002", model="demo-model-b", score=0.70),
             "regression": make_regression("beta", status="regression", delta=-0.20,
                                           baseline_score=0.90, current_score=0.70)},
        ],
        notes="Case H：同数据集同评分器、换模型 → 可比，检出 2 例 regression",
    )

    # ── Case L：不同数据集版本（不可比）──────────────────────
    runs["run_l_dataset_v2"] = make_document(
        run_id="synth-run-l-v2",
        dataset_id="aiqe-demo",
        dataset_version="2.0.0",  # ← 数据集版本不同 → 不可比
        model_id="demo-model-b", backend_id="mock",
        cases=[
            {**_case_judge_fail("alpha", trace="l0000001", model="demo-model-b", score=0.40),
             "regression": make_regression("alpha", status="regression", delta=-0.40,
                                           baseline_score=0.80, current_score=0.40)},
            {**_case_ok("beta", trace="l0000002", model="demo-model-b", score=0.70),
             "regression": make_regression("beta", status="regression", delta=-0.20,
                                           baseline_score=0.90, current_score=0.70)},
        ],
        notes="Case L：数据集版本 v2，与 v1 基线不可比——即使分数形态相同也不得产出 delta",
    )

    # ── 附加边界：空用例集 ───────────────────────────────────
    # 用于压测「缺失值绝不填 0」规则：
    #   比例类指标在空集上无定义 → 必须为 null
    #   计数类指标在空集上是确定的测量结果 → 合法为 0
    runs["run_m_empty_cases"] = make_document(
        run_id="synth-run-m",
        dataset_id="aiqe-demo", dataset_version="1.0.0",
        model_id="demo-model-a", backend_id="mock",
        cases=[],
        notes="附加边界：空用例集。比例指标为 null（无定义），计数指标为 0（确定结果）",
    )

    return runs


# ════════════════════════════════════════════════════════════════
#  非法样本（Case F、I、J、K）
# ════════════════════════════════════════════════════════════════
#
# 【构造原则】每份非法样本都以一份**合法样本**为基底，只注入单一缺陷，
# 然后重算 content_digest。这样校验失败的原因唯一，测试断言才有意义。

def build_invalid_runs() -> dict[str, dict[str, Any]]:
    """构造全部非法合成样本（每份只含单一缺陷）。"""
    invalid: dict[str, dict[str, Any]] = {}

    def _base(run_id: str = "synth-run-invalid") -> dict[str, Any]:
        return make_document(
            run_id=run_id,
            dataset_id="aiqe-demo", dataset_version="1.0.0",
            model_id="demo-model-a", backend_id="mock",
            cases=[_case_ok("alpha", trace="x0000001", model="demo-model-a", score=0.95)],
        )

    # ── Case F：指标非法类型 ─────────────────────────────────
    doc = _base("synth-run-f")
    doc["cases"][0]["judge"]["score"] = "0.95"  # ← 字符串，应为数值
    _reseal(doc)
    invalid["case_f_invalid_metric_type"] = doc

    # ── Case I：Schema 版本不兼容 ────────────────────────────
    doc = _base("synth-run-i")
    doc["schema_version"] = "aiqe.result/1.0.0"  # ← 主版本 1 ≠ 支持的主版本 0
    _reseal(doc)
    invalid["case_i_schema_incompatible"] = doc

    # ── Case J-1：敏感字段（键名命中）────────────────────────
    doc = _base("synth-run-j1")
    doc["metadata"]["api_key"] = "placeholder-value-not-a-real-key"
    _reseal(doc)
    invalid["case_j1_sensitive_key"] = doc

    # ── Case J-2：敏感取值（值模式命中）──────────────────────
    doc = _base("synth-run-j2")
    doc["cases"][0]["execution"]["response"] = "请联系 alice@example.com 获取详情。"
    _reseal(doc)
    invalid["case_j2_sensitive_value"] = doc

    # ── Case K-1：伪造 synthetic，但无 generator ─────────────
    doc = _base("synth-run-k1")
    doc["metadata"]["generator"] = ""
    _reseal(doc)
    invalid["case_k1_no_generator"] = doc

    # ── Case K-2：伪造 synthetic，generator 不在白名单 ───────
    doc = _base("synth-run-k2")
    doc["metadata"]["generator"] = "untrusted.generator/9.9.9"
    _reseal(doc)
    invalid["case_k2_untrusted_generator"] = doc

    # ── Case K-3：摘要不匹配（生成后被改动）──────────────────
    # 关键：**不**重算摘要。改动后摘要失配 = 篡改证据生效。
    doc = _base("synth-run-k3")
    doc["cases"][0]["judge"]["score"] = 0.10  # 生成后偷偷改分
    invalid["case_k3_digest_mismatch"] = doc

    return invalid


# ════════════════════════════════════════════════════════════════
#  落盘
# ════════════════════════════════════════════════════════════════

def _dump(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def write_fixtures(root: str | Path) -> dict[str, list[Path]]:
    """把全部合成样本写入 root/valid 与 root/invalid。返回写入清单。

    【为什么要落盘而不是只在内存构造？】
      落盘的 fixtures 是可被人工审阅、可被 git 追踪、可被 drift 测试
      比对的**证据**。只在内存构造的话，「样本长什么样」这件事
      无法被独立复核。
    """
    root_path = Path(root)
    written: dict[str, list[Path]] = {"valid": [], "invalid": []}

    for bucket, builder in (("valid", build_valid_runs), ("invalid", build_invalid_runs)):
        target = root_path / bucket
        target.mkdir(parents=True, exist_ok=True)
        for name, document in sorted(builder().items()):
            path = target / f"{name}.json"
            path.write_text(_dump(document), encoding="utf-8")
            written[bucket].append(path)

    return written


if __name__ == "__main__":  # pragma: no cover —— 人工重生成入口
    import sys

    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/synthetic")
    result = write_fixtures(destination)
    for bucket, paths in result.items():
        print(f"{bucket}: {len(paths)} 个文件")
        for path in paths:
            print(f"  {path}")
