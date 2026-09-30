"""R1 workbench contract for a single quality-engineering work item.

This is a result-only, allowlisted projection. It neither executes tests nor
imports customer reports. Q6 cells are observations supplied by a future
runner; accepting this document does not authenticate their provenance.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = "aiqe.workbench/0.1.0"
_VERSION_KEYS = frozenset({
    "requirement", "rule", "test_before", "test_after", "implementation_good",
    "implementation_bad", "environment", "challenge", "oracle",
})
_EFFORT_KEYS = frozenset({"preparation", "review", "rework", "acceptance", "coordination"})
_CELL_KEYS = frozenset({"before_correct", "before_defective", "after_correct", "after_defective"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class WorkbenchContractError(ValueError):
    """A document cannot be used as workbench evidence."""

    def __init__(self, code: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}")


def _object(value: Any, path: str, keys: frozenset[str], required: frozenset[str] | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise WorkbenchContractError("INVALID_OBJECT", path)
    extra = set(value) - keys
    if extra:
        # A strict allowlist rejects raw prompt/response, source code and any
        # unreviewed extensions at every document level.
        raise WorkbenchContractError("FIELD_NOT_ALLOWED", f"{path}.{sorted(extra)[0]}")
    missing = (keys if required is None else required) - set(value)
    if missing:
        raise WorkbenchContractError("FIELD_MISSING", f"{path}.{sorted(missing)[0]}")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkbenchContractError("INVALID_TEXT", path)
    return value


def _choice(value: Any, path: str, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise WorkbenchContractError("INVALID_ENUM", path)
    return value


def _digest(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise WorkbenchContractError("INVALID_DIGEST", path)
    return value


def _versions(value: Any, path: str) -> Mapping[str, str]:
    versions = _object(value, path, _VERSION_KEYS)
    for key in _VERSION_KEYS:
        _text(versions[key], f"{path}.{key}")
    return versions


def _q6(value: Any) -> tuple[str, list[str]]:
    if value is None:
        return "unknown", []
    matrix = _object(value, "$.q6", _CELL_KEYS | {"challenge_id"})
    _text(matrix["challenge_id"], "$.q6.challenge_id")
    for key in _CELL_KEYS:
        _choice(matrix[key], f"$.q6.{key}", frozenset({"passed", "failed", "error", "skipped", "unknown"}))
    findings: list[str] = []
    if matrix["before_defective"] == "failed" and matrix["after_defective"] == "passed":
        findings.append("lost_detection")
    if matrix["before_correct"] == "passed" and matrix["after_correct"] == "failed":
        findings.append("false_reject")
    if findings:
        return "regression", findings
    if (matrix["before_correct"], matrix["after_correct"], matrix["before_defective"], matrix["after_defective"]) == (
        "passed", "passed", "failed", "failed"
    ):
        return "preserved", []
    return "unknown", []


def _effort(value: Any) -> dict[str, Any]:
    sidecar = _object(value, "$.effort", _EFFORT_KEYS)
    observed = 0
    covered = 0
    applicable = 0
    for key in sorted(_EFFORT_KEYS):
        item = _object(sidecar[key], f"$.effort.{key}", frozenset({"minutes", "source"}))
        source = _choice(item["source"], f"$.effort.{key}.source", frozenset({"measured", "self_reported", "missing", "not_applicable"}))
        minutes = item["minutes"]
        if source in {"missing", "not_applicable"}:
            if minutes is not None:
                raise WorkbenchContractError("EXPECTED_NULL", f"$.effort.{key}.minutes")
        elif isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            raise WorkbenchContractError("INVALID_MINUTES", f"$.effort.{key}.minutes")
        if source != "not_applicable":
            applicable += 1
        if source in {"measured", "self_reported"}:
            covered += 1
            observed += minutes
    return {
        "observed_minutes": observed if covered else None,
        "total_minutes": observed if covered == applicable and applicable else None,
        "covered_categories": covered,
        "applicable_categories": applicable,
    }


def validate_workbench_document(document: Any) -> dict[str, Any]:
    """Validate one work item and derive Q5/Q6/Q7 display facts.

    Unknown Q6 or incomplete effort stays unknown. A claim is recorded but
    never substitutes for independent validation or explicit human approval.
    """
    root = _object(document, "$", frozenset({
        "schema_version", "source_type", "data_classification", "provenance",
        "work_item", "q6", "effort",
    }))
    if root["schema_version"] != SCHEMA_VERSION:
        raise WorkbenchContractError("UNSUPPORTED_SCHEMA", "$.schema_version")
    source = _choice(root["source_type"], "$.source_type", frozenset({"synthetic", "local_test"}))
    classification = _choice(root["data_classification"], "$.data_classification", frozenset({"public_synthetic", "internal"}))
    if (source, classification) not in {("synthetic", "public_synthetic"), ("local_test", "internal")}:
        raise WorkbenchContractError("SOURCE_CLASSIFICATION_MISMATCH", "$.data_classification")

    provenance = _object(root["provenance"], "$.provenance", frozenset({
        "run_id", "report_sha256", "frozen_versions", "observed_versions",
    }))
    _text(provenance["run_id"], "$.provenance.run_id")
    _digest(provenance["report_sha256"], "$.provenance.report_sha256")
    frozen = _versions(provenance["frozen_versions"], "$.provenance.frozen_versions")
    observed = _versions(provenance["observed_versions"], "$.provenance.observed_versions")
    stale = any(frozen[key] != observed[key] for key in _VERSION_KEYS)

    item = _object(root["work_item"], "$.work_item", frozenset({
        "id", "frozen_scope", "claimed_complete", "validation", "review",
    }))
    work_id = _text(item["id"], "$.work_item.id")
    _text(item["frozen_scope"], "$.work_item.frozen_scope")
    if not isinstance(item["claimed_complete"], bool):
        raise WorkbenchContractError("INVALID_BOOLEAN", "$.work_item.claimed_complete")
    validation = _object(item["validation"], "$.work_item.validation", frozenset({"result", "evidence_sha256"}))
    validation_result = _choice(validation["result"], "$.work_item.validation.result", frozenset({"passed", "failed", "unknown"}))
    if validation_result == "unknown":
        if validation["evidence_sha256"] is not None:
            raise WorkbenchContractError("EXPECTED_NULL", "$.work_item.validation.evidence_sha256")
    else:
        _digest(validation["evidence_sha256"], "$.work_item.validation.evidence_sha256")
    review = _object(item["review"], "$.work_item.review", frozenset({"state", "actor"}))
    review_state = _choice(review["state"], "$.work_item.review.state", frozenset({"pending", "accepted", "rejected", "reopened"}))
    if review_state in {"accepted", "rejected", "reopened"}:
        _text(review["actor"], "$.work_item.review.actor")
    elif review["actor"] is not None:
        raise WorkbenchContractError("EXPECTED_NULL", "$.work_item.review.actor")

    q6_status, findings = _q6(root["q6"])
    effort = _effort(root["effort"])
    if validation_result == "failed" or q6_status == "regression" or review_state == "rejected":
        status = "rejected"
    elif review_state == "reopened":
        status = "reopened"
    elif review_state == "accepted" and validation_result == "passed" and q6_status == "preserved" and not stale:
        status = "accepted"
    else:
        status = "pending_review"
    return {
        "schema_version": SCHEMA_VERSION,
        "source_type": source,
        "data_classification": classification,
        "run_id": provenance["run_id"],
        "work_item_id": work_id,
        "claimed_complete": item["claimed_complete"],
        "validation_result": validation_result,
        "q6_status": q6_status,
        "q6_findings": findings,
        "stale": stale,
        "status": status,
        "effort": effort,
    }
