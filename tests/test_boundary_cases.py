"""AIQE 边界用例 —— 契约测试（补充）

boundary_cases.py 的轻量契约测试，规则与 test_extended_cases.py 同源：
- 8 个边界用例字段完整、类别合法（复用既有类别）
- id 与 test_cases / extended_cases 两套用例都不重复
- 在 mock 后端下可跑通 judge（评分合法、不崩溃）

pytest 收集时会对 TestCase 类发出 PytestCollectionWarning，已在 pyproject.toml
中通过 filterwarnings 忽略（不影响测试结果）。
"""
import warnings
warnings.filterwarnings("ignore", message=".*cannot collect test class.*")

from AIQE.schema import TestCase
from AIQE.cases.test_cases import get_test_cases
from AIQE.cases.extended_cases import get_extended_cases
from AIQE.cases.boundary_cases import BOUNDARY_CASES, BOUNDARY_CATEGORIES, get_boundary_cases


def test_boundary_cases_have_eight_items():
    """边界用例集必须恰好 8 个，且 BOUNDARY_CASES 与 get_boundary_cases() 同源。"""
    assert len(BOUNDARY_CASES) == 8, f"边界用例数量应为 8，实际 {len(BOUNDARY_CASES)}"
    assert BOUNDARY_CASES == get_boundary_cases(), "BOUNDARY_CASES 与 get_boundary_cases() 结果不一致"


def test_boundary_required_fields_present():
    """每个用例字段完整：id / prompt / expected_keywords 非空，max_tokens 为正数。"""
    for case in BOUNDARY_CASES:
        assert isinstance(case, TestCase), f"{case.id} 不是 TestCase 实例"
        assert case.id and case.prompt and case.expected_keywords
        assert case.max_tokens > 0, f"{case.id}: max_tokens 必须为正数"
        assert case.min_length >= 0, f"{case.id}: min_length 不能为负数"


def test_boundary_category_all_reused_existing():
    """边界用例类别全部复用既有类别（标准 4 类 ∪ 扩展类别），不新造类别。

    BOUNDARY_CATEGORIES 中的 edge_case 由 extended_cases 引入，因此合法
    集合是 test_cases ∪ extended_cases 两个真实来源。
    """
    existing = {c.category for c in get_test_cases()} | {c.category for c in get_extended_cases()}
    for cat in BOUNDARY_CATEGORIES:
        assert cat in existing, f"BOUNDARY_CATEGORIES 声明了既有集合外的类别 {cat!r}"
    for case in BOUNDARY_CASES:
        assert case.category in BOUNDARY_CATEGORIES, (
            f"{case.id}: category={case.category!r} 不在 BOUNDARY_CATEGORIES 中"
        )


def test_boundary_ids_unique_across_all_case_sets():
    """边界用例 id 内部唯一，且与 test_cases / extended_cases 两套用例都不重复。"""
    all_ids = (
        {c.id for c in get_test_cases()}
        | {c.id for c in get_extended_cases()}
        | {c.id for c in BOUNDARY_CASES}
    )
    assert len(all_ids) == 4 + 6 + 8, "三套用例 id 之间存在重复"


def test_boundary_long_input_prompt_is_long():
    """超长输入用例的 prompt 必须 ≥2000 字符（设计约束）。"""
    long_case = next(c for c in BOUNDARY_CASES if c.id == "boundary_long_input")
    assert len(long_case.prompt) >= 2000, f"超长输入 prompt 只有 {len(long_case.prompt)} 字符"


def test_boundary_cases_judge_under_mock_backend():
    """边界用例集在 mock 后端下可跑通 judge（不要求全部通过，只要求不崩溃且评分合法）。"""
    from AIQE.backends.mock import MockEvalBackend
    from AIQE.runner import ExecutionRunner
    from AIQE.judge import OutputJudge

    backend = MockEvalBackend()
    backend.setup()
    try:
        runner = ExecutionRunner(backend)
        judge = OutputJudge()
        for case in BOUNDARY_CASES:
            exec_result = runner.run(case)
            jr = judge.judge(case, exec_result)
            assert 0.0 <= jr.score <= 1.0, f"{case.id}: score 越界 {jr.score}"
    finally:
        backend.teardown()
