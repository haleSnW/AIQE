"""合成 fixtures 的完整性与漂移测试。

验证三件事：
  1. **有效性**：全部 valid fixtures 能通过契约校验，且覆盖 Case A–L。
  2. **拒绝性**：全部 invalid fixtures 被拒绝，且拒绝原因码符合预期。
  3. **可复现性**：提交的 fixtures 与生成器当前输出**逐字节一致**
     —— 防止「改了生成器却忘了重新生成 fixtures」导致文档与产物分叉。

本文件全部测试离线运行。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from AIQE.contract import (
    ContractViolation,
    DataClassification,
    SourceType,
    build_run,
    load_run,
    validate_run,
)
from AIQE.synthetic import (
    GENERATOR_ID,
    build_invalid_runs,
    build_valid_runs,
    write_fixtures,
)

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"

#: invalid fixtures 与其**预期拒绝原因码**的映射。
#: 断言原因码而不只是「抛了异常」，确保拒绝理由是我们设计的那一条。
EXPECTED_REJECTIONS: dict[str, str] = {
    "case_f_invalid_metric_type": "INVALID_TYPE",
    "case_i_schema_incompatible": "SCHEMA_VERSION_INCOMPATIBLE",
    "case_j1_sensitive_key": "SENSITIVE_FIELD_DETECTED",
    "case_j2_sensitive_value": "SENSITIVE_VALUE_DETECTED",
    "case_k1_no_generator": "SYNTHETIC_GENERATOR_UNTRUSTED",
    "case_k2_untrusted_generator": "SYNTHETIC_GENERATOR_UNTRUSTED",
    "case_k3_digest_mismatch": "SYNTHETIC_DIGEST_MISMATCH",
}

#: Case A–L 的覆盖声明（任务要求的 12 个场景 → 实际承载它们的 fixture）
CASE_COVERAGE: dict[str, tuple[str, ...]] = {
    "A_normal_pass": ("run_a_normal_pass",),
    "B_case_fail": ("run_b_case_fail",),
    "C_execution_error": ("run_c_execution_error",),
    "D_timeout": ("run_d_timeout",),
    "E_missing_metric": ("run_e_missing_metric",),
    "F_invalid_metric_type": ("case_f_invalid_metric_type",),
    "G_baseline_and_candidate": ("run_g_baseline", "run_g_candidate"),
    "H_valid_regression": ("run_h_candidate",),
    "I_schema_incompatible": ("case_i_schema_incompatible",),
    "J_sensitive_input": ("case_j1_sensitive_key", "case_j2_sensitive_value"),
    "K_forged_synthetic_marker": (
        "case_k1_no_generator", "case_k2_untrusted_generator", "case_k3_digest_mismatch",
    ),
    "L_incomparable_dataset_versions": ("run_l_dataset_v2",),
}


def _paths(bucket: str) -> list[Path]:
    """列出 fixtures；过滤 macOS 伴随元数据文件（._*）。"""
    return sorted(
        p for p in (FIXTURES / bucket).glob("*.json") if not p.name.startswith("._")
    )


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ════════════════════════════════════════════════════════════════
#  存在性与覆盖
# ════════════════════════════════════════════════════════════════

def test_fixture_directories_exist():
    assert (FIXTURES / "valid").is_dir(), "缺少 valid fixtures 目录"
    assert (FIXTURES / "invalid").is_dir(), "缺少 invalid fixtures 目录"


def test_valid_fixtures_present():
    names = {p.stem for p in _paths("valid")}
    assert names == set(build_valid_runs()), (
        f"提交的 valid fixtures 与生成器不一致；"
        f"缺失={set(build_valid_runs()) - names}，多余={names - set(build_valid_runs())}"
    )


def test_invalid_fixtures_present():
    names = {p.stem for p in _paths("invalid")}
    assert names == set(build_invalid_runs())


def test_all_twelve_cases_are_covered():
    """任务要求的 Case A–L 必须全部有 fixture 承载。"""
    available = {p.stem for p in _paths("valid")} | {p.stem for p in _paths("invalid")}
    missing = {
        case: [name for name in names if name not in available]
        for case, names in CASE_COVERAGE.items()
        if any(name not in available for name in names)
    }
    assert not missing, f"以下 Case 缺少 fixture: {missing}"


# ════════════════════════════════════════════════════════════════
#  有效性
# ════════════════════════════════════════════════════════════════

def test_every_valid_fixture_passes_validation():
    for path in _paths("valid"):
        run = build_run(load_run(path).document)  # 不抛异常即通过
        assert run.run_id, f"{path.name} 缺少 run_id"
        assert run.cases is not None


def test_every_invalid_fixture_is_rejected_with_expected_reason():
    for path in _paths("invalid"):
        expected = EXPECTED_REJECTIONS.get(path.stem)
        assert expected is not None, f"未声明预期原因码: {path.stem}"
        with pytest.raises(ContractViolation) as excinfo:
            validate_run(_read(path))
        assert excinfo.value.reason_code == expected, (
            f"{path.name}: 期望 {expected}，实际 {excinfo.value.reason_code}"
        )


def test_invalid_fixture_rejection_is_not_caused_by_broken_digest():
    """负样本的拒绝原因必须唯一，不能被摘要检查「顺手」拦下。

    除 case_k3（其设计目标就是摘要失配）外，其余负样本的 content_digest
    必须是**有效的**——否则测试通过就不能证明我们想测的规则生效了。
    """
    from AIQE.contract import compute_content_digest

    for path in _paths("invalid"):
        if path.stem == "case_k3_digest_mismatch":
            continue
        doc = _read(path)
        declared = doc["metadata"]["content_digest"]
        assert declared == compute_content_digest(doc), (
            f"{path.name} 的摘要本身无效——该负样本会因摘要而非目标规则被拒"
        )


def test_no_valid_fixture_is_silently_misclassified():
    """valid 目录里的文件不得含有 invalid 目录的设计缺陷。"""
    for path in _paths("valid"):
        doc = _read(path)
        assert doc["metadata"]["source_type"] == "synthetic"
        assert doc["metadata"]["generator"] in {"aiqe.synthetic/0.1.0"}


# ════════════════════════════════════════════════════════════════
#  合成标记与数据分级
# ════════════════════════════════════════════════════════════════

def test_all_fixtures_are_marked_synthetic():
    """所有合成样本必须有明确的 synthetic 标记。"""
    for bucket in ("valid", "invalid"):
        for path in _paths(bucket):
            doc = _read(path)
            assert doc["metadata"]["source_type"] == "synthetic", path.name


def test_all_fixtures_are_public_synthetic_classification():
    for bucket in ("valid", "invalid"):
        for path in _paths(bucket):
            doc = _read(path)
            assert doc["metadata"]["data_classification"] == "public_synthetic", path.name


def test_valid_fixture_metadata_enums_round_trip():
    for path in _paths("valid"):
        run = load_run(path)
        assert run.metadata.source_type is SourceType.SYNTHETIC
        assert run.metadata.data_classification is DataClassification.PUBLIC_SYNTHETIC


def test_fixtures_declare_the_trusted_generator():
    for path in _paths("valid"):
        assert _read(path)["metadata"]["generator"] == GENERATOR_ID


# ════════════════════════════════════════════════════════════════
#  漂移检测（提交产物 ⟷ 生成器）
# ════════════════════════════════════════════════════════════════

def test_committed_fixtures_match_generator_output(tmp_path):
    """重新生成 fixtures 并与提交版本逐字节比对。

    失败意味着「生成器改了但 fixtures 没重新生成」——
    此时文档描述的样本与仓库里的样本已经不是同一份。
    """
    write_fixtures(tmp_path)
    mismatches: list[str] = []
    for bucket in ("valid", "invalid"):
        for committed in _paths(bucket):
            regenerated = tmp_path / bucket / committed.name
            if not regenerated.exists():
                mismatches.append(f"生成器不再产出 {bucket}/{committed.name}")
                continue
            if committed.read_bytes() != regenerated.read_bytes():
                mismatches.append(f"{bucket}/{committed.name} 内容漂移")
    assert not mismatches, (
        "fixtures 与生成器输出不一致（请重新运行 "
        "`PYTHONPATH=src python -m AIQE.synthetic tests/fixtures/synthetic`）: "
        + "; ".join(mismatches)
    )


def test_generator_is_deterministic():
    """同一生成器两次运行必须产出完全相同的内容（可复现性）。"""
    assert build_valid_runs() == build_valid_runs()
    assert build_invalid_runs() == build_invalid_runs()


def test_fixtures_contain_no_real_data_markers():
    """合成样本不得包含任何真实数据痕迹。

    这是**结构性检查**，不是「证明数据是合成的」——证明手段见
    tests/fixtures/synthetic/README.md 中说明的信任边界。
    """
    forbidden = ["/Users/", "/Volumes/", "/home/", "private_customer_marker"]
    for bucket in ("valid", "invalid"):
        for path in _paths(bucket):
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                assert marker not in text, f"{path.name} 含禁用标记 {marker!r}"


def test_fixture_files_are_utf8_json():
    for bucket in ("valid", "invalid"):
        for path in _paths(bucket):
            json.loads(path.read_text(encoding="utf-8"))
