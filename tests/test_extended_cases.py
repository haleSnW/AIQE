"""AIQE 扩展用例 —— 镜像契约测试

镜像说明：本文件是 上游项目 仓库 tests/unit/test_ai_eval_extended_cases.py 的
镜像导出版，断言语义逐字照抄，仅把 import 来源改为 AIQE 包。

覆盖：
- 6 个扩展用例可导入、字段完整（id / prompt / expected_keywords / max_tokens 等）
- category 合法：非空，且属于「既有 test_cases.py 类别 ∪ EXTENDED_CATEGORIES」
  （两者都从真实模块 import，不硬编码、不自造数据）
- 新用例 id 与既有用例（test_cases.py）不重复，内部也不重复
- 至少各有一个用例覆盖 judge.py 的 json_output / coding_task 特殊格式分支

说明：schema.py 中 category 是自由字符串（无枚举常量），因此"合法集合"取自
真实源头：get_test_cases() 实际使用的类别 + extended_cases 模块声明的
EXTENDED_CATEGORIES，两边都从真实模块读取。

pytest 收集时会对 TestCase 类发出 PytestCollectionWarning，此处与
test_schema.py 保持一致（pyproject.toml 已有 filterwarnings 兜底）。
"""
import warnings
warnings.filterwarnings("ignore", message=".*cannot collect test class.*")

import pytest

from AIQE.schema import TestCase
from AIQE.cases.test_cases import get_test_cases
from AIQE.cases.extended_cases import ALL_CASES, EXTENDED_CATEGORIES, get_extended_cases


def test_extended_cases_have_six_items():
    """扩展用例集必须恰好 6 个，且 ALL_CASES 与 get_extended_cases() 同源。"""
    assert len(ALL_CASES) == 6, f"扩展用例数量应为 6，实际 {len(ALL_CASES)}"
    assert ALL_CASES == get_extended_cases(), "ALL_CASES 与 get_extended_cases() 结果不一致"


def test_every_case_is_real_testcase():
    """每个用例都是 schema.py 的真实 TestCase 类型。"""
    for case in ALL_CASES:
        assert isinstance(case, TestCase), f"{case.id} 不是 TestCase 实例"


def test_required_fields_present():
    """每个用例的 id / prompt / expected_keywords 非空，max_tokens 为正数。"""
    for case in ALL_CASES:
        assert case.id, "存在 id 为空的用例"
        assert case.prompt, f"{case.id}: prompt 为空"
        assert case.expected_keywords, f"{case.id}: expected_keywords 为空"
        assert case.max_tokens > 0, f"{case.id}: max_tokens 必须为正数，实际 {case.max_tokens}"
        assert case.min_length >= 0, f"{case.id}: min_length 不能为负数，实际 {case.min_length}"


def test_category_in_union_of_existing_and_extended():
    """category 非空，且属于「既有用例类别 ∪ EXTENDED_CATEGORIES」两个真实来源。"""
    existing_categories = {c.category for c in get_test_cases()}
    allowed = existing_categories | set(EXTENDED_CATEGORIES)
    assert allowed, "合法类别集合为空（两个来源都没有类别）"
    for case in ALL_CASES:
        assert case.category, f"{case.id}: category 为空"
        assert case.category in allowed, (
            f"{case.id}: category={case.category!r} 不在合法集合 {sorted(allowed)} 中"
        )


def test_extended_categories_all_used():
    """EXTENDED_CATEGORIES 里声明的每个类别都必须被至少一个新增用例实际使用。"""
    used = {c.category for c in ALL_CASES}
    for cat in EXTENDED_CATEGORIES:
        assert cat in used, f"EXTENDED_CATEGORIES 声明了 {cat!r}，但没有用例使用它"


def test_ids_unique_and_not_overlap_existing():
    """新用例 id 内部唯一，且与 test_cases.py 既有 id 不重复（从真实模块读取）。"""
    existing_ids = {c.id for c in get_test_cases()}
    new_ids = [c.id for c in ALL_CASES]
    assert len(new_ids) == len(set(new_ids)), "扩展用例内部存在重复 id"
    overlap = existing_ids & set(new_ids)
    assert not overlap, f"与既有用例 id 冲突: {sorted(overlap)}"


def test_judge_special_branch_categories_covered():
    """至少各有一个用例覆盖 judge.py 的特殊格式分支。

    分支类别字符串是 judge.py _check_format 中的字面量、未导出为常量，
    此处与源码保持一致并注明出处。
    """
    categories = {c.category for c in ALL_CASES}
    assert "json_output" in categories, "缺少覆盖 judge 的 json_output 特殊分支的用例"
    assert "coding_task" in categories, "缺少覆盖 judge 的 coding_task 特殊分支的用例"


def test_extended_cases_judge_under_mock_backend():
    """扩展用例集在 mock 后端下可跑通 judge（不要求全部通过，只要求不崩溃且评分合法）。"""
    from AIQE.backends.mock import MockEvalBackend
    from AIQE.runner import ExecutionRunner
    from AIQE.judge import OutputJudge

    backend = MockEvalBackend()
    backend.setup()
    try:
        runner = ExecutionRunner(backend)
        judge = OutputJudge()
        for case in ALL_CASES:
            exec_result = runner.run(case)
            jr = judge.judge(case, exec_result)
            assert 0.0 <= jr.score <= 1.0, f"{case.id}: score 越界 {jr.score}"
            assert jr.passed in (True, False)
    finally:
        backend.teardown()
