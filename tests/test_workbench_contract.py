"""R1 contract tests use invented metadata; no model or customer data."""

from copy import deepcopy

import pytest

from AIQE.workbench_contract import (
    SCHEMA_VERSION,
    WorkbenchContractError,
    validate_workbench_document,
)


def sample() -> dict:
    versions = {
        "requirement": "r1", "rule": "a1", "test_before": "t1",
        "test_after": "t2", "implementation_good": "g1",
        "implementation_bad": "b1", "environment": "e1",
        "challenge": "c1", "oracle": "o1",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "source_type": "synthetic",
        "data_classification": "public_synthetic",
        "provenance": {
            "run_id": "demo-1", "report_sha256": "a" * 64,
            "frozen_versions": versions,
            "observed_versions": versions.copy(),
        },
        "work_item": {
            "id": "work-1", "frozen_scope": "one accepted behavior",
            "claimed_complete": True,
            "validation": {"result": "passed", "evidence_sha256": "b" * 64},
            "review": {"state": "accepted", "actor": "human-reviewer"},
        },
        "q6": {
            "challenge_id": "known-defect-1",
            "before_correct": "passed", "before_defective": "failed",
            "after_correct": "passed", "after_defective": "failed",
        },
        "effort": {
            key: {"minutes": 0, "source": "measured"}
            for key in ("preparation", "review", "rework", "acceptance", "coordination")
        },
    }


def test_acceptance_requires_independent_evidence_and_review():
    document = sample()
    output = validate_workbench_document(document)
    assert output["status"] == "accepted"
    assert output["effort"]["total_minutes"] == 0
    document["work_item"]["claimed_complete"] = False
    assert validate_workbench_document(document)["status"] == "accepted"
    document["work_item"]["validation"] = {"result": "unknown", "evidence_sha256": None}
    assert validate_workbench_document(document)["status"] == "pending_review"


def test_detection_loss_overrides_green_review():
    document = sample()
    document["q6"]["after_defective"] = "passed"
    result = validate_workbench_document(document)
    assert result["q6_findings"] == ["lost_detection"]
    assert result["status"] == "rejected"


def test_false_reject_is_visible_and_blocks_acceptance():
    document = sample()
    document["q6"]["after_correct"] = "failed"
    assert validate_workbench_document(document)["q6_findings"] == ["false_reject"]
    assert validate_workbench_document(document)["status"] == "rejected"


def test_skip_and_missing_matrix_are_unknown_not_preserved():
    document = sample()
    document["q6"]["after_defective"] = "skipped"
    assert validate_workbench_document(document)["status"] == "pending_review"
    document["q6"] = None
    assert validate_workbench_document(document)["q6_status"] == "unknown"


def test_stale_versions_block_acceptance():
    document = sample()
    document["provenance"]["observed_versions"]["rule"] = "a2"
    result = validate_workbench_document(document)
    assert result["stale"] is True
    assert result["status"] == "pending_review"


@pytest.mark.parametrize("path,value", [
    (("prompt",), "raw text"),
    (("response",), "raw text"),
    (("work_item", "test_source"), "assert True"),
    (("q6", "raw_prompt"), "raw text"),
])
def test_unapproved_raw_fields_rejected(path, value):
    document = sample()
    cursor = document
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value
    with pytest.raises(WorkbenchContractError) as error:
        validate_workbench_document(document)
    assert error.value.code == "FIELD_NOT_ALLOWED"


def test_source_classification_and_digest_must_be_valid():
    document = sample()
    document["source_type"] = "local_import"
    with pytest.raises(WorkbenchContractError, match="INVALID_ENUM"):
        validate_workbench_document(document)
    document = sample()
    document["data_classification"] = "internal"
    with pytest.raises(WorkbenchContractError, match="SOURCE_CLASSIFICATION_MISMATCH"):
        validate_workbench_document(document)
    document = sample()
    document["provenance"]["report_sha256"] = "not-a-digest"
    with pytest.raises(WorkbenchContractError, match="INVALID_DIGEST"):
        validate_workbench_document(document)


def test_effort_missing_is_not_zero_or_complete():
    document = sample()
    document["effort"]["review"] = {"minutes": None, "source": "missing"}
    result = validate_workbench_document(document)["effort"]
    assert result == {
        "observed_minutes": 0, "total_minutes": None,
        "covered_categories": 4, "applicable_categories": 5,
    }
    document["effort"]["review"] = {"minutes": 0, "source": "missing"}
    with pytest.raises(WorkbenchContractError, match="EXPECTED_NULL"):
        validate_workbench_document(document)


def test_input_is_not_mutated():
    document = sample()
    original = deepcopy(document)
    validate_workbench_document(document)
    assert document == original


def _native_fixture(name="run_a_normal_pass.json"):
    from pathlib import Path
    return (Path(__file__).parent / "fixtures/synthetic/valid" / name).read_bytes()


def test_native_projection_binds_exact_bytes_and_never_accepts_judge_claim():
    import hashlib
    import json
    from AIQE.workbench_adapter import adapt_native_report
    payload = _native_fixture()
    versions = sample()["provenance"]["frozen_versions"]
    result = adapt_native_report(payload, case_id="alpha", frozen_scope="synthetic case",
                                 frozen_versions=versions, observed_versions=versions)
    document = result["document"]
    assert document["provenance"]["run_id"] == "synth-run-a"
    assert document["provenance"]["report_sha256"] == hashlib.sha256(payload).hexdigest()
    assert validate_workbench_document(document)["status"] == "pending_review"
    assert document["work_item"]["validation"] == {"result": "unknown", "evidence_sha256": None}
    assert result["native_observations"]["elapsed"] == {
        "value": 0.12, "unit": "s", "status": "reported", "precision": "unspecified"}
    exported = json.dumps(result, ensure_ascii=False)
    assert "你好" not in exported
    assert '"prompt"' not in exported and '"response"' not in exported
    versions["rule"] = "changed"
    assert document["provenance"]["frozen_versions"]["rule"] == "a1"


@pytest.mark.parametrize("filename,status", [
    ("run_b_case_fail.json", "failed"),
    ("run_c_execution_error.json", "error"),
])
def test_native_projection_keeps_failure_kind(filename, status):
    import json
    from AIQE.workbench_adapter import adapt_native_report
    payload = _native_fixture(filename)
    native = json.loads(payload)
    versions = sample()["provenance"]["frozen_versions"]
    wanted = next(c for c in native["cases"]
                  if (c["execution"].get("error") is not None if status == "error"
                      else c["judge"]["passed"] is False))
    result = adapt_native_report(payload, case_id=wanted["case_id"], frozen_scope="synthetic",
                                 frozen_versions=versions, observed_versions=versions)
    assert result["native_observations"]["status"] == status
    assert result["document"]["work_item"]["claimed_complete"] is False
    if status == "error":
        assert result["native_observations"]["error_code"] == "native_execution_error"
        assert wanted["execution"]["error"] not in json.dumps(result)


def test_native_projection_rejects_unknown_case_duplicate_json_and_unapproved_source():
    import json
    from AIQE.workbench_adapter import adapt_native_report
    from AIQE.contract import ContractViolation
    versions = sample()["provenance"]["frozen_versions"]
    kwargs = dict(case_id="absent", frozen_scope="synthetic",
                  frozen_versions=versions, observed_versions=versions)
    with pytest.raises(ValueError):
        adapt_native_report(_native_fixture(), **kwargs)
    with pytest.raises(ValueError, match="duplicate"):
        adapt_native_report(b'{"x":1,"x":2}', **kwargs)
    native = json.loads(_native_fixture())
    native["metadata"]["source_type"] = "local_import"
    with pytest.raises(ContractViolation):
        adapt_native_report(json.dumps(native).encode(), **kwargs)
