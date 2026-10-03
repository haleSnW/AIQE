"""统一结果契约（AIQE/contract.py）与运行对比（AIQE/comparison.py）的契约测试。

覆盖范围：
  - Schema 版本兼容性（Case I）
  - 敏感字段默认拒绝（Case J）
  - 合成数据来源证明 / 伪造标记拒绝（Case K）
  - 指标非法类型拒绝（Case F）
  - 来源类型门禁（本轮只允许 synthetic）
  - 读取失败行为（失败关闭，绝不静默返回空）
  - 指标聚合：缺失值绝不填 0、比例与计数语义区分
  - 运行级可比性判定（Case G / H / L）

本文件全部测试离线运行，不触网、不依赖模型。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from AIQE.comparison import (
    FLAG_CASE_SET_DIFFERS,
    FLAG_MODEL_CHANGED,
    INCOMPARABLE_DATASET_ID,
    INCOMPARABLE_DATASET_VERSION,
    INCOMPARABLE_JUDGE_VERSION,
    INCOMPARABLE_SAME_RUN,
    compare_runs,
)
from AIQE.contract import (
    ALLOWED_SOURCE_TYPES,
    REASON_DOCUMENT_NOT_OBJECT,
    REASON_DUPLICATE_CASE_ID,
    REASON_FILE_NOT_FOUND,
    REASON_FILE_NOT_JSON,
    REASON_FILE_UNREADABLE,
    REASON_INVALID_ENUM_VALUE,
    REASON_INVALID_TYPE,
    REASON_REQUIRED_FIELD_MISSING,
    REASON_SCHEMA_VERSION_INCOMPATIBLE,
    REASON_SCHEMA_VERSION_MALFORMED,
    REASON_SCHEMA_VERSION_MISSING,
    REASON_SENSITIVE_FIELD_DETECTED,
    REASON_SENSITIVE_VALUE_DETECTED,
    REASON_SOURCE_TYPE_NOT_ALLOWED,
    REASON_SYNTHETIC_DIGEST_MISMATCH,
    REASON_SYNTHETIC_DIGEST_MISSING,
    REASON_SYNTHETIC_GENERATOR_UNTRUSTED,
    REASON_TIMESTAMP_MALFORMED,
    ContractViolation,
    DataClassification,
    MetricPrecision,
    MetricStatus,
    SourceType,
    build_run,
    compute_content_digest,
    load_run,
    scan_sensitive,
    validate_run,
)
from AIQE.synthetic import _reseal, build_valid_runs, make_case, make_document

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


# ════════════════════════════════════════════════════════════════
#  辅助
# ════════════════════════════════════════════════════════════════

def _fixture_paths(bucket: str) -> list[Path]:
    """列出 fixtures；过滤掉 macOS 伴随元数据文件（._*）。"""
    return sorted(
        p for p in (FIXTURES / bucket).glob("*.json") if not p.name.startswith("._")
    )


def _load(name: str) -> dict:
    return json.loads((FIXTURES / "valid" / f"{name}.json").read_text(encoding="utf-8"))


def _minimal_doc(**overrides) -> dict:
    """一份最小合法合成文档，供各测试注入单一缺陷。"""
    doc = make_document(
        run_id="unit-run",
        dataset_id="unit-ds", dataset_version="1.0.0",
        model_id="unit-model", backend_id="mock",
        cases=[make_case(
            "c1", "chat", "hi",
            response="你好，我是一个 AI 助手。",
            tokens_generated=10, elapsed_sec=0.1, tok_per_sec=100.0,
            backend="mock", model_id="unit-model",
            score=1.0, passed=True,
            checks={"empty_response": False, "length_ok": True,
                    "keywords_match": True, "format_ok": True},
            metrics={"response_length": 13, "keyword_hits": 2,
                     "keyword_total": 2, "format_score": 1.0},
        )],
    )
    for key, value in overrides.items():
        doc[key] = value
    return doc


def _expect(document, reason_code: str) -> ContractViolation:
    """断言校验失败且原因码匹配。"""
    with pytest.raises(ContractViolation) as excinfo:
        validate_run(document)
    assert excinfo.value.reason_code == reason_code, (
        f"期望 {reason_code}，实际 {excinfo.value.reason_code}: {excinfo.value}"
    )
    return excinfo.value


# ════════════════════════════════════════════════════════════════
#  Schema 版本（Case I）
# ════════════════════════════════════════════════════════════════

def test_schema_version_missing_is_rejected():
    doc = _minimal_doc()
    del doc["schema_version"]
    _expect(doc, REASON_SCHEMA_VERSION_MISSING)


def test_schema_version_malformed_is_rejected():
    _expect(_minimal_doc(schema_version="0.1.0"), REASON_SCHEMA_VERSION_MALFORMED)
    _expect(_minimal_doc(schema_version=100), REASON_SCHEMA_VERSION_MALFORMED)


def test_schema_version_major_mismatch_is_rejected():
    """Case I：主版本不同 → 拒绝读取，不做字段猜测。"""
    _expect(_minimal_doc(schema_version="aiqe.result/1.0.0"),
            REASON_SCHEMA_VERSION_INCOMPATIBLE)


def test_schema_version_minor_bump_is_accepted():
    """次版本提升是兼容变更，必须继续可读。"""
    doc = _minimal_doc(schema_version="aiqe.result/0.9.0")
    _reseal(doc)
    assert validate_run(doc).metadata.run_id == "unit-run"


def test_case_i_fixture_is_rejected():
    doc = json.loads((FIXTURES / "invalid" / "case_i_schema_incompatible.json")
                     .read_text(encoding="utf-8"))
    _expect(doc, REASON_SCHEMA_VERSION_INCOMPATIBLE)


# ════════════════════════════════════════════════════════════════
#  敏感字段默认拒绝（Case J）
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("key", [
    "api_key", "apiKey", "access_token", "password", "secret",
    "private_key", "user_email", "phone", "id_card", "chat_log",
    "raw_prompt", "memory_db", "openai_api_key",
])
def test_sensitive_keys_are_rejected(key):
    """默认拒绝：命中敏感键名即拒绝整份文档，不做自动脱敏。"""
    doc = _minimal_doc()
    doc["metadata"][key] = "placeholder"
    _expect(doc, REASON_SENSITIVE_FIELD_DETECTED)


# ⚠️ 下面 parametrize 中的取值是**测试输入**，不是真实凭据。
# 全部为公开文档中的规范占位示例：
#   - alice@example.com          RFC 2606 保留域名
#   - 13800138000                中国运营商公开示例号段
#   - 11010519491231002X         GB 11643 文档中的身份证示例
#   - 以下凭据形状均在运行时由占位片段拼接，不包含真实凭据
# 它们的作用是**验证扫描器能拒绝这些模式**，因此必然出现在本文件中。
# 任何敏感内容扫描工具对本文件的告警均应视为预期命中。
@pytest.mark.parametrize("value,label", [
    ("alice@example.com", "email"),
    ("13800138000", "cn_mobile"),
    ("11010519491231002X", "cn_id_card"),
    ("sk-" + "abcdefghijklmnopqrstuvwxyz", "openai_style_key"),
    ("ghp_" + "a" * 24, "github_token"),
    ("AKIA" + "IOSFODNN7EXAMPLE", "aws_access_key"),
    ("-----BEGIN RSA PRIVATE KEY-----", "pem_private_key"),
])
def test_sensitive_values_are_rejected(value, label):
    doc = _minimal_doc()
    doc["cases"][0]["execution"]["response"] = f"内容 {value} 结束"
    _expect(doc, REASON_SENSITIVE_VALUE_DETECTED)


def test_sensitive_scan_is_recursive():
    """深层嵌套的敏感字段也必须被检出。"""
    doc = _minimal_doc()
    doc["cases"][0]["execution"]["meta"] = {"nested": [{"deep": {"api_key": "x"}}]}
    _expect(doc, REASON_SENSITIVE_FIELD_DETECTED)


def test_legitimate_token_fields_are_not_false_positives():
    """关键回归保护：框架自身的 token 类字段绝不能被误判为敏感。

    若这里失败，说明敏感规则过宽——正常报告将无法通过校验。
    """
    doc = _minimal_doc()
    execution = doc["cases"][0]["execution"]
    execution["tokens_generated"] = 123
    execution["max_tokens"] = 512
    execution["tokens_per_second"] = 42.0
    execution["prompt"] = "这是一段正常的中文提示词，不含任何敏感信息。"
    _reseal(doc)
    run = validate_run(doc)
    assert run.cases[0].raw["execution"]["tokens_generated"] == 123


def test_scan_sensitive_accepts_clean_document():
    scan_sensitive({"a": {"b": [{"tokens_generated": 5}]}})  # 不抛异常


def test_case_j1_and_j2_fixtures_are_rejected():
    j1 = json.loads((FIXTURES / "invalid" / "case_j1_sensitive_key.json")
                    .read_text(encoding="utf-8"))
    _expect(j1, REASON_SENSITIVE_FIELD_DETECTED)
    j2 = json.loads((FIXTURES / "invalid" / "case_j2_sensitive_value.json")
                    .read_text(encoding="utf-8"))
    _expect(j2, REASON_SENSITIVE_VALUE_DETECTED)


# ════════════════════════════════════════════════════════════════
#  合成数据来源证明（Case K）
# ════════════════════════════════════════════════════════════════

def test_synthetic_without_generator_is_rejected():
    """仅声明 source_type="synthetic" 不足以通过——必须证明来源。"""
    doc = _minimal_doc()
    doc["metadata"]["generator"] = ""
    _reseal(doc)
    _expect(doc, REASON_SYNTHETIC_GENERATOR_UNTRUSTED)


def test_synthetic_with_untrusted_generator_is_rejected():
    doc = _minimal_doc()
    doc["metadata"]["generator"] = "evil.generator/9.9.9"
    _reseal(doc)
    _expect(doc, REASON_SYNTHETIC_GENERATOR_UNTRUSTED)


def test_synthetic_without_digest_is_rejected():
    doc = _minimal_doc()
    doc["metadata"]["content_digest"] = ""
    _expect(doc, REASON_SYNTHETIC_DIGEST_MISSING)


def test_synthetic_with_tampered_content_is_rejected():
    """生成后改动内容 → 摘要失配 → 拒绝。"""
    doc = _minimal_doc()
    doc["cases"][0]["judge"]["score"] = 0.01  # 不重新封装
    _expect(doc, REASON_SYNTHETIC_DIGEST_MISMATCH)


def test_valid_synthetic_document_is_accepted():
    run = validate_run(_minimal_doc())
    assert run.metadata.source_type is SourceType.SYNTHETIC
    assert run.metadata.generator == "aiqe.synthetic/0.1.0"


def test_content_digest_ignores_metadata_block():
    """摘要不覆盖 metadata —— 否则 content_digest 自身会造成自引用。"""
    doc = _minimal_doc()
    before = compute_content_digest(doc)
    doc["metadata"]["notes"] = "改一下元数据"
    assert compute_content_digest(doc) == before


def test_content_digest_changes_when_cases_change():
    doc = _minimal_doc()
    before = compute_content_digest(doc)
    doc["cases"][0]["judge"]["score"] = 0.5
    assert compute_content_digest(doc) != before


def test_case_k_fixtures_are_rejected():
    k1 = json.loads((FIXTURES / "invalid" / "case_k1_no_generator.json")
                    .read_text(encoding="utf-8"))
    _expect(k1, REASON_SYNTHETIC_GENERATOR_UNTRUSTED)
    k2 = json.loads((FIXTURES / "invalid" / "case_k2_untrusted_generator.json")
                    .read_text(encoding="utf-8"))
    _expect(k2, REASON_SYNTHETIC_GENERATOR_UNTRUSTED)
    k3 = json.loads((FIXTURES / "invalid" / "case_k3_digest_mismatch.json")
                    .read_text(encoding="utf-8"))
    _expect(k3, REASON_SYNTHETIC_DIGEST_MISMATCH)


# ════════════════════════════════════════════════════════════════
#  来源类型门禁
# ════════════════════════════════════════════════════════════════

def test_only_synthetic_is_allowed_by_default():
    assert ALLOWED_SOURCE_TYPES == frozenset({SourceType.SYNTHETIC})


@pytest.mark.parametrize("source", ["local_test", "local_import"])
def test_non_synthetic_sources_are_blocked(source):
    """真实数据接入保持 BLOCKED：不得通过改 source_type 绕过。"""
    doc = _minimal_doc()
    doc["metadata"]["source_type"] = source
    _expect(doc, REASON_SOURCE_TYPE_NOT_ALLOWED)


def test_source_type_gate_is_configurable_not_hardcoded():
    """门禁来自配置参数，证明它是可审计的策略而非写死的分支。"""
    doc = _minimal_doc()
    doc["metadata"]["source_type"] = "local_import"
    _reseal(doc)
    run = validate_run(
        doc,
        allowed_source_types={SourceType.LOCAL_IMPORT},
        require_synthetic_provenance=False,
    )
    assert run.metadata.source_type is SourceType.LOCAL_IMPORT


def test_invalid_source_type_value_is_rejected():
    doc = _minimal_doc()
    doc["metadata"]["source_type"] = "production"
    _expect(doc, REASON_INVALID_ENUM_VALUE)


def test_invalid_data_classification_is_rejected():
    doc = _minimal_doc()
    doc["metadata"]["data_classification"] = "top_secret"
    _expect(doc, REASON_INVALID_ENUM_VALUE)


def test_data_classification_enum_covers_required_levels():
    assert {c.value for c in DataClassification} == {
        "public_synthetic", "internal", "personal", "restricted"
    }


# ════════════════════════════════════════════════════════════════
#  结构与类型校验
# ════════════════════════════════════════════════════════════════

def test_document_must_be_object():
    for bad in ([], "text", 42, None):
        with pytest.raises(ContractViolation) as excinfo:
            validate_run(bad)
        assert excinfo.value.reason_code == REASON_DOCUMENT_NOT_OBJECT


def test_missing_metadata_is_rejected():
    doc = _minimal_doc()
    del doc["metadata"]
    _expect(doc, REASON_REQUIRED_FIELD_MISSING)


@pytest.mark.parametrize("field", [
    "run_id", "created_at", "dataset_id", "dataset_version",
    "judge_id", "judge_version", "model_id", "backend_id",
])
def test_required_metadata_fields(field):
    doc = _minimal_doc()
    del doc["metadata"][field]
    _expect(doc, REASON_REQUIRED_FIELD_MISSING)


def test_empty_run_id_is_rejected():
    doc = _minimal_doc()
    doc["metadata"]["run_id"] = "   "
    _expect(doc, REASON_INVALID_TYPE)


def test_naive_timestamp_is_rejected():
    """无时区的时间戳无法确定绝对时刻 → 拒绝，不猜测。"""
    doc = _minimal_doc()
    doc["metadata"]["created_at"] = "2026-09-22T00:00:00"
    _expect(doc, REASON_TIMESTAMP_MALFORMED)


def test_timestamp_with_z_suffix_is_accepted():
    doc = _minimal_doc()
    doc["metadata"]["created_at"] = "2026-09-22T08:00:00Z"
    assert validate_run(doc).metadata.created_at.startswith("2026-09-22T08:00:00")


def test_timestamp_is_normalized_to_utc():
    doc = _minimal_doc()
    doc["metadata"]["created_at"] = "2026-09-22T08:00:00+08:00"
    assert validate_run(doc).metadata.created_at.startswith("2026-09-22T00:00:00")


def test_malformed_timestamp_is_rejected():
    doc = _minimal_doc()
    doc["metadata"]["created_at"] = "not-a-timestamp"
    _expect(doc, REASON_TIMESTAMP_MALFORMED)


def test_duplicate_case_id_is_rejected():
    doc = _minimal_doc()
    doc["cases"].append(dict(doc["cases"][0]))
    _reseal(doc)
    _expect(doc, REASON_DUPLICATE_CASE_ID)


def test_cases_must_be_list():
    doc = _minimal_doc(cases={"a": 1})
    _reseal(doc)
    _expect(doc, REASON_INVALID_TYPE)


def test_case_f_invalid_metric_type_is_rejected():
    """Case F：judge.score 是字符串 → 拒绝，不静默转换。"""
    doc = _minimal_doc()
    doc["cases"][0]["judge"]["score"] = "0.95"
    _reseal(doc)
    _expect(doc, REASON_INVALID_TYPE)


def test_case_f_fixture_is_rejected():
    doc = json.loads((FIXTURES / "invalid" / "case_f_invalid_metric_type.json")
                     .read_text(encoding="utf-8"))
    _expect(doc, REASON_INVALID_TYPE)


def test_boolean_score_is_rejected():
    """bool 是 int 的子类，但语义上不是分数——必须拒绝。"""
    doc = _minimal_doc()
    doc["cases"][0]["judge"]["score"] = True
    _reseal(doc)
    _expect(doc, REASON_INVALID_TYPE)


def test_non_string_execution_error_is_rejected():
    doc = _minimal_doc()
    doc["cases"][0]["execution"]["error"] = {"code": 500}
    _reseal(doc)
    _expect(doc, REASON_INVALID_TYPE)


def test_non_boolean_passed_is_rejected():
    doc = _minimal_doc()
    doc["cases"][0]["judge"]["passed"] = "yes"
    _reseal(doc)
    _expect(doc, REASON_INVALID_TYPE)


def test_null_optional_fields_are_accepted():
    """null 是合法值（表示缺失），不得与类型错误混为一谈。"""
    doc = _minimal_doc()
    doc["cases"][0]["judge"]["score"] = None
    doc["cases"][0]["judge"]["passed"] = None
    doc["cases"][0]["execution"]["error"] = None
    _reseal(doc)
    assert validate_run(doc).cases[0].score is None


# ════════════════════════════════════════════════════════════════
#  读取失败行为（失败关闭）
# ════════════════════════════════════════════════════════════════

def test_load_missing_file_raises(tmp_path):
    with pytest.raises(ContractViolation) as excinfo:
        load_run(tmp_path / "nope.json")
    assert excinfo.value.reason_code == REASON_FILE_NOT_FOUND


def test_load_non_json_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("这不是 JSON", encoding="utf-8")
    with pytest.raises(ContractViolation) as excinfo:
        load_run(path)
    assert excinfo.value.reason_code == REASON_FILE_NOT_JSON


def test_load_binary_file_raises_contract_violation(tmp_path):
    """二进制/损坏文件必须转成契约异常，不得以未捕获异常逃逸。

    UnicodeDecodeError 是 ValueError 子类而非 OSError——这是一个真实的
    健壮性缺口，本测试锁定修复。
    """
    path = tmp_path / "binary.json"
    path.write_bytes(b"\xb0\x01\x02 not utf-8 at all \xff\xfe")
    with pytest.raises(ContractViolation) as excinfo:
        load_run(path)
    assert excinfo.value.reason_code == REASON_FILE_UNREADABLE


def test_load_run_never_returns_none():
    """读取失败必须是显式异常——静默返回空值会让「数据损坏」显示成「零回归」。"""
    with pytest.raises(ContractViolation):
        load_run("/nonexistent/path/that/does/not/exist.json")


def test_load_valid_fixture_roundtrip(tmp_path):
    source = FIXTURES / "valid" / "run_a_normal_pass.json"
    run = load_run(source)
    assert run.run_id == "synth-run-a"
    assert run.dataset_key == ("aiqe-demo", "1.0.0")


# ════════════════════════════════════════════════════════════════
#  指标聚合
# ════════════════════════════════════════════════════════════════

def _metric(run, metric_id):
    record = run.metric(metric_id)
    assert record is not None, f"缺少指标记录 {metric_id}"
    return record


def test_metric_value_none_iff_status_not_ok():
    """核心不变式：有值 ⟺ 状态为 OK。所有 fixtures 全量验证。"""
    for path in _fixture_paths("valid"):
        run = build_run(load_run(path).document)
        for record in run.metrics:
            if record.status is MetricStatus.OK:
                assert record.metric_value is not None, (
                    f"{path.name}/{record.metric_id}: OK 状态必须有值"
                )
            else:
                assert record.metric_value is None, (
                    f"{path.name}/{record.metric_id}: 非 OK 状态必须为 null，"
                    f"实际 {record.metric_value!r}（禁止把缺失值填成 0）"
                )


def test_case_pass_rate_differs_from_execution_success_rate():
    """Case B vs Case C：两个指标必须给出不同的诊断。

    Case B：执行全成功，但一半用例不通过。
    Case C：执行一半失败，通过率同样是一半，但原因完全不同。
    """
    run_b = build_run(load_run(FIXTURES / "valid" / "run_b_case_fail.json").document)
    run_c = build_run(load_run(FIXTURES / "valid" / "run_c_execution_error.json").document)

    assert _metric(run_b, "execution_success_rate").metric_value == 1.0
    assert _metric(run_b, "case_pass_rate").metric_value == 0.5
    assert _metric(run_b, "execution_error_count").metric_value == 0

    assert _metric(run_c, "execution_success_rate").metric_value == 0.5
    assert _metric(run_c, "case_pass_rate").metric_value == 0.5
    assert _metric(run_c, "execution_error_count").metric_value == 1


def test_execution_failure_implies_case_not_passed():
    """硬约束：执行失败 ⇒ 用例不通过（空响应强制 0 分）。"""
    for path in _fixture_paths("valid"):
        run = build_run(load_run(path).document)
        for case in run.cases:
            if not case.execution_ok:
                assert case.passed is False, f"{path.name}/{case.case_id}"


def test_timeout_count_is_never_a_number():
    """Case D：即使 error 文本含 'timed out'，也不得推断出数值。"""
    run = build_run(load_run(FIXTURES / "valid" / "run_d_timeout.json").document)
    record = _metric(run, "timeout_count")
    assert record.metric_value is None
    assert record.status is MetricStatus.UNDEFINED
    assert run.cases[0].error is not None and "timed out" in run.cases[0].error


def test_format_compliance_not_applicable_without_format_cases():
    """chat/translation 类别的 format_score 恒为 1.0，无信息量 → 不得聚合。"""
    run = build_run(load_run(FIXTURES / "valid" / "run_a_normal_pass.json").document)
    record = _metric(run, "format_compliance")
    assert record.metric_value is None
    assert record.status is MetricStatus.NOT_APPLICABLE


def test_format_compliance_missing_when_metric_absent():
    """Case E：format_score 字段缺失（空响应分支）→ MISSING，不是 0。"""
    run = build_run(load_run(FIXTURES / "valid" / "run_e_missing_metric.json").document)
    record = _metric(run, "format_compliance")
    assert record.metric_value is None
    assert record.status is MetricStatus.MISSING


def test_baseline_delta_is_null_without_baseline():
    """Case：无基线时 delta 必须是 null —— new 状态携带的 0.0 是占位值。"""
    run = build_run(load_run(FIXTURES / "valid" / "run_a_normal_pass.json").document)
    record = _metric(run, "baseline_delta")
    assert record.metric_value is None
    assert record.status is MetricStatus.NO_BASELINE


def test_baseline_delta_computed_with_baseline():
    run = build_run(load_run(FIXTURES / "valid" / "run_h_candidate.json").document)
    record = _metric(run, "baseline_delta")
    assert record.status is MetricStatus.OK
    assert record.metric_value == pytest.approx(-0.30, abs=1e-6)


def test_regression_count_separates_regression_from_degraded():
    """regression 与 degraded 必须分开计数（区别于 reporter 的合并口径）。"""
    run_g = build_run(load_run(FIXTURES / "valid" / "run_g_candidate.json").document)
    assert _metric(run_g, "regression_count").metric_value == 0
    assert _metric(run_g, "degraded_count").metric_value == 1

    run_h = build_run(load_run(FIXTURES / "valid" / "run_h_candidate.json").document)
    assert _metric(run_h, "regression_count").metric_value == 2
    assert _metric(run_h, "degraded_count").metric_value == 0


def test_regression_count_null_without_baseline():
    run = build_run(load_run(FIXTURES / "valid" / "run_a_normal_pass.json").document)
    record = _metric(run, "regression_count")
    assert record.metric_value is None
    assert record.status is MetricStatus.NO_BASELINE


def test_latency_ms_converts_seconds_to_milliseconds():
    run = build_run(load_run(FIXTURES / "valid" / "run_a_normal_pass.json").document)
    record = _metric(run, "latency_ms")
    assert record.metric_unit == "milliseconds"
    assert record.metric_value == pytest.approx(120.0)  # 0.12s


def test_latency_ms_excludes_failed_cases():
    """失败用例 elapsed_sec=0.0 是占位值，必须排除而非计入。"""
    run = build_run(load_run(FIXTURES / "valid" / "run_d_timeout.json").document)
    record = _metric(run, "latency_ms")
    assert record.metric_value is None
    assert record.status is MetricStatus.MISSING


def test_output_tokens_marked_estimated_for_mock_backend():
    """mock 路径的 token 数是字符估算，必须标记 precision=estimated。"""
    run = build_run(load_run(FIXTURES / "valid" / "run_a_normal_pass.json").document)
    assert _metric(run, "output_tokens").precision is MetricPrecision.ESTIMATED
    assert _metric(run, "tokens_per_second").precision is MetricPrecision.ESTIMATED


def test_empty_case_set_ratios_null_but_counts_zero():
    """空集边界：比例无定义（null），计数是确定结果（0）。"""
    run = build_run(load_run(FIXTURES / "valid" / "run_m_empty_cases.json").document)
    assert _metric(run, "case_pass_rate").metric_value is None
    assert _metric(run, "case_pass_rate").status is MetricStatus.NO_DATA
    assert _metric(run, "execution_success_rate").metric_value is None
    assert _metric(run, "execution_success_rate").status is MetricStatus.NO_DATA
    assert _metric(run, "execution_error_count").metric_value == 0


@pytest.mark.parametrize("metric_id,expected_status", [
    ("timeout_count", MetricStatus.UNDEFINED),
    ("judge_agreement", MetricStatus.UNDEFINED),
    ("severity_distribution", MetricStatus.UNDEFINED),
    ("input_tokens", MetricStatus.UNAVAILABLE),
    ("estimated_cost", MetricStatus.UNAVAILABLE),
])
def test_uncomputable_metrics_are_explicitly_marked(metric_id, expected_status):
    """不可计算指标必须产出显式缺失记录，而不是被静默省略。"""
    run = build_run(load_run(FIXTURES / "valid" / "run_a_normal_pass.json").document)
    record = _metric(run, metric_id)
    assert record.metric_value is None
    assert record.status is expected_status
    assert record.reason, f"{metric_id} 必须说明缺失原因"


def test_every_metric_record_carries_version_and_unit():
    run = build_run(load_run(FIXTURES / "valid" / "run_a_normal_pass.json").document)
    for record in run.metrics:
        assert record.metric_version
        assert record.metric_unit
        assert record.scope in {"run", "case", "category"}


# ════════════════════════════════════════════════════════════════
#  运行级可比性（Case G / H / L）
# ════════════════════════════════════════════════════════════════

def _run(name: str):
    return build_run(load_run(FIXTURES / "valid" / f"{name}.json").document)


def test_case_g_same_dataset_is_comparable():
    comparison = compare_runs(_run("run_g_baseline"), _run("run_g_candidate"))
    assert comparison.comparable is True
    assert comparison.incomparable_reasons == []
    assert comparison.regression_count == 0


def test_case_h_regression_is_detected():
    comparison = compare_runs(_run("run_g_baseline"), _run("run_h_candidate"))
    assert comparison.comparable is True
    assert comparison.regression_count == 2
    assert set(comparison.regressed_case_ids) == {"alpha", "beta"}
    assert comparison.metric_deltas["case_pass_rate"] == pytest.approx(-0.5)


def test_case_h_model_change_is_flagged_but_not_blocking():
    """换模型是回归测试的正当用途：记录 flag，但不阻断对比。"""
    comparison = compare_runs(_run("run_g_baseline"), _run("run_h_candidate"))
    assert FLAG_MODEL_CHANGED in comparison.flags
    assert comparison.comparable is True


def test_case_l_different_dataset_version_is_incomparable():
    """Case L：数据集版本不同 → 不可比 → 绝不产出 delta。"""
    comparison = compare_runs(_run("run_g_baseline"), _run("run_l_dataset_v2"))
    assert comparison.comparable is False
    assert INCOMPARABLE_DATASET_VERSION in comparison.incomparable_reasons
    assert comparison.case_comparisons == []
    assert comparison.metric_deltas == {}


def test_case_l_fixture_scores_are_identical_to_case_h():
    """证明 Case L 的不可比结论来自数据集版本，而非分数形态差异。

    run_h_candidate 与 run_l_dataset_v2 的分数完全一致，
    唯一差别是 dataset_version —— 因此结论差异只能归因于可比性门禁。
    """
    h = _run("run_h_candidate")
    l = _run("run_l_dataset_v2")
    assert [c.score for c in h.cases] == [c.score for c in l.cases]
    assert h.metadata.dataset_version != l.metadata.dataset_version


def test_same_run_id_is_incomparable():
    run = _run("run_g_baseline")
    comparison = compare_runs(run, run)
    assert comparison.comparable is False
    assert INCOMPARABLE_SAME_RUN in comparison.incomparable_reasons


def test_dataset_id_mismatch_is_incomparable():
    baseline = _run("run_g_baseline")
    doc = _load("run_g_candidate")
    doc["metadata"]["dataset_id"] = "other-dataset"
    _reseal(doc)
    comparison = compare_runs(baseline, build_run(doc))
    assert INCOMPARABLE_DATASET_ID in comparison.incomparable_reasons
    assert comparison.case_comparisons == []


def test_judge_version_mismatch_is_incomparable():
    """评分器版本不同 → 同一响应会得到不同分数 → 不可比。"""
    baseline = _run("run_g_baseline")
    doc = _load("run_g_candidate")
    doc["metadata"]["judge_version"] = "2.0.0"
    _reseal(doc)
    comparison = compare_runs(baseline, build_run(doc))
    assert INCOMPARABLE_JUDGE_VERSION in comparison.incomparable_reasons


def test_case_set_difference_is_flagged():
    baseline = _run("run_g_baseline")
    doc = _load("run_g_candidate")
    doc["cases"] = doc["cases"][:1]
    doc["summary"]["total"] = 1
    _reseal(doc)
    comparison = compare_runs(baseline, build_run(doc))
    assert FLAG_CASE_SET_DIFFERS in comparison.flags
    assert comparison.comparable is True


def test_incomparable_comparison_never_emits_deltas():
    """不可比 ⇒ case_comparisons 与 metric_deltas 必为空。"""
    comparison = compare_runs(_run("run_g_baseline"), _run("run_l_dataset_v2"))
    assert comparison.case_comparisons == []
    assert comparison.metric_deltas == {}
    assert comparison.regression_count == 0


def test_comparison_records_both_sides_conditions():
    """回归判断必须记录基线与候选的评估条件。"""
    comparison = compare_runs(_run("run_g_baseline"), _run("run_h_candidate"))
    for side in (comparison.baseline_conditions, comparison.candidate_conditions):
        for field in ("run_id", "dataset_id", "dataset_version",
                      "judge_id", "judge_version", "model_id", "backend_id"):
            assert side[field], f"评估条件缺少 {field}"


def test_comparison_serializes_to_dict():
    comparison = compare_runs(_run("run_g_baseline"), _run("run_h_candidate"))
    payload = comparison.to_dict()
    assert payload["comparable"] is True
    assert payload["summary"]["regression_count"] == 2
    assert json.dumps(payload, ensure_ascii=False)  # 可 JSON 序列化


def test_comparison_delta_ignores_missing_metrics():
    """指标在一侧缺失时不得产出 delta —— 把缺失当 0 会制造虚假变化。"""
    baseline = _run("run_g_baseline")
    candidate = _run("run_h_candidate")
    # 两侧 format_compliance 都是 NOT_APPLICABLE（非 OK）→ 不应出现在 deltas
    comparison = compare_runs(baseline, candidate)
    assert "format_compliance" not in comparison.metric_deltas
    assert "timeout_count" not in comparison.metric_deltas
    assert "input_tokens" not in comparison.metric_deltas
