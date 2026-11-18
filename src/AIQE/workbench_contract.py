"""R1 workbench contract for a single quality-engineering work item.

This is a result-only, allowlisted projection. It neither executes tests nor
imports customer reports. Q6 cells are observations supplied by a future
runner; accepting this document does not authenticate their provenance.
Likewise, effort entries are claims: a ``measured`` source string is not an
independent timer or human attestation, so this contract never reports
verified human minutes or a verified effort trust state.
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
_EFFORT_LEGACY_KEYS = (
    "observed_minutes", "total_minutes", "covered_categories", "applicable_categories",
)
_EFFORT_TRUST_KEYS = (
    "verified_minutes", "claimed_measured_minutes", "self_reported_minutes",
    "verified_categories", "claimed_measured_categories",
    "self_reported_categories", "missing_categories",
    "not_applicable_categories", "trust",
)
_CELL_KEYS = frozenset({"before_correct", "before_defective", "after_correct", "after_defective"})
_Q6_CELL_SPECS = {
    "before_correct": ("before", "correct"),
    "before_defective": ("before", "defective"),
    "after_correct": ("after", "correct"),
    "after_defective": ("after", "defective"),
}
_Q6_CELL_FIELDS = frozenset({
    "test_version", "implementation", "status", "exit_code",
    "test_sha256", "implementation_sha256", "evidence_sha256",
})
_Q6_OBSERVED = frozenset({"passed", "failed"})
_Q6_ATTEMPTED = frozenset({"passed", "failed", "error"})
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


def build_q6_runner_matrix(
    *,
    challenge_id: Any,
    defect_source: Any,
    cells: Any,
    comparable: bool = True,
) -> dict[str, Any]:
    """Validate four real runner observations and derive Q6 facts.

    ``cells`` records actual executions rather than claims: each passed/failed
    cell must carry its process exit code and an evidence digest.  The returned
    ``matrix`` is directly usable as ``document["q6"]``.  Classification is
    delegated to the existing ``_q6`` function so the four-cell business
    semantics stay in one place.

    ``comparable=False`` keeps the observations visible but forces the derived
    status to ``unknown``; when the caller claims comparability, inconsistent
    test or implementation digests are rejected as a conflict.
    """
    _text(challenge_id, "$.q6_runner.challenge_id")
    _text(defect_source, "$.q6_runner.defect_source")
    if not isinstance(comparable, bool):
        raise WorkbenchContractError("INVALID_BOOLEAN", "$.q6_runner.comparable")
    if not isinstance(cells, Mapping) or any(not isinstance(key, str) for key in cells):
        raise WorkbenchContractError("INVALID_OBJECT", "$.q6_runner.cells")

    expected = set(_Q6_CELL_SPECS)
    missing = expected - set(cells)
    if missing:
        raise WorkbenchContractError(
            "Q6_CELL_MISSING", f"$.q6_runner.cells.{sorted(missing)[0]}"
        )
    extra = set(cells) - expected
    if extra:
        raise WorkbenchContractError(
            "Q6_CELL_UNKNOWN", f"$.q6_runner.cells.{sorted(extra)[0]}"
        )

    matrix: dict[str, str] = {"challenge_id": challenge_id}
    normalized: dict[str, Mapping[str, Any]] = {}
    for name, (phase, implementation) in _Q6_CELL_SPECS.items():
        path = f"$.q6_runner.cells.{name}"
        cell = _object(cells[name], path, _Q6_CELL_FIELDS)
        if cell["test_version"] != phase:
            raise WorkbenchContractError(
                "Q6_CELL_VERSION_MISMATCH", f"{path}.test_version"
            )
        if cell["implementation"] != implementation:
            raise WorkbenchContractError(
                "Q6_CELL_IMPLEMENTATION_MISMATCH", f"{path}.implementation"
            )
        status = _choice(
            cell["status"], f"{path}.status",
            frozenset({"passed", "failed", "error", "skipped", "unknown"}),
        )
        exit_code = cell["exit_code"]
        evidence = cell["evidence_sha256"]
        if status in _Q6_OBSERVED:
            if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                raise WorkbenchContractError(
                    "Q6_EXIT_CODE_MISSING", f"{path}.exit_code"
                )
            if (status == "passed") != (exit_code == 0):
                raise WorkbenchContractError(
                    "Q6_EXIT_CODE_CONFLICT", f"{path}.exit_code"
                )
            _digest(evidence, f"{path}.evidence_sha256")
        elif status == "error":
            if exit_code is not None and (
                isinstance(exit_code, bool)
                or not isinstance(exit_code, int)
                or exit_code == 0
            ):
                raise WorkbenchContractError(
                    "Q6_EXIT_CODE_CONFLICT", f"{path}.exit_code"
                )
            _digest(evidence, f"{path}.evidence_sha256")
        else:
            if exit_code is not None:
                raise WorkbenchContractError(
                    "Q6_EXIT_CODE_CONFLICT", f"{path}.exit_code"
                )
            if evidence is not None:
                raise WorkbenchContractError(
                    "Q6_EVIDENCE_CONFLICT", f"{path}.evidence_sha256"
                )
        _digest(cell["test_sha256"], f"{path}.test_sha256")
        _digest(cell["implementation_sha256"], f"{path}.implementation_sha256")
        matrix[name] = status
        normalized[name] = cell

    attempted_evidence = [
        cell["evidence_sha256"]
        for cell in normalized.values()
        if cell["status"] in _Q6_ATTEMPTED
    ]
    if len(attempted_evidence) != len(set(attempted_evidence)):
        raise WorkbenchContractError(
            "Q6_EVIDENCE_CONFLICT", "$.q6_runner.cells"
        )

    if comparable:
        before_tests = {
            normalized[name]["test_sha256"]
            for name in ("before_correct", "before_defective")
        }
        after_tests = {
            normalized[name]["test_sha256"]
            for name in ("after_correct", "after_defective")
        }
        correct_impls = {
            normalized[name]["implementation_sha256"]
            for name in ("before_correct", "after_correct")
        }
        defective_impls = {
            normalized[name]["implementation_sha256"]
            for name in ("before_defective", "after_defective")
        }
        if len(before_tests) != 1 or len(after_tests) != 1:
            raise WorkbenchContractError(
                "Q6_COMPARABILITY_CONFLICT", "$.q6_runner.cells.test_sha256"
            )
        if before_tests == after_tests:
            raise WorkbenchContractError(
                "Q6_COMPARABILITY_CONFLICT", "$.q6_runner.cells.test_sha256"
            )
        if len(correct_impls) != 1 or len(defective_impls) != 1:
            raise WorkbenchContractError(
                "Q6_COMPARABILITY_CONFLICT",
                "$.q6_runner.cells.implementation_sha256",
            )
        if correct_impls == defective_impls:
            raise WorkbenchContractError(
                "Q6_COMPARABILITY_CONFLICT",
                "$.q6_runner.cells.implementation_sha256",
            )

    q6_status, findings = _q6(matrix)
    if not comparable:
        q6_status, findings = "unknown", []
    observed = sum(1 for name in _Q6_CELL_SPECS if matrix[name] in _Q6_OBSERVED)
    errors = sum(1 for name in _Q6_CELL_SPECS if matrix[name] == "error")
    return {
        "challenge_id": challenge_id,
        "defect_source": defect_source,
        "comparable": comparable,
        "matrix": matrix,
        "q6_status": q6_status,
        "q6_findings": findings,
        "counts": {
            "cells_total": 4,
            "observed_cells": observed,
            "unobserved_cells": 4 - observed - errors,
            "error_cells": errors,
            "detection_cells": 2,
            "correctness_cells": 2,
        },
    }


def _effort_facts(value: Any) -> dict[str, Any]:
    """Validate the five-category sidecar and keep claims out of trust.

    Legacy ``observed_minutes``/``total_minutes`` still include claimed
    ``measured`` and ``self_reported`` minutes for compatibility.  A document
    can only *claim* a measurement: this contract has no independent timer,
    attestation or human-record channel, so every applicable category remains
    ``unverified`` and ``verified_minutes`` is always ``None`` with
    ``verified_categories == 0``.
    """
    sidecar = _object(value, "$.effort", _EFFORT_KEYS)
    observed = 0
    claimed_measured = 0
    self_reported = 0
    covered = 0
    applicable = 0
    claimed_measured_categories = 0
    self_reported_categories = 0
    missing_categories = 0
    not_applicable_categories = 0
    for key in sorted(_EFFORT_KEYS):
        item = _object(sidecar[key], f"$.effort.{key}", frozenset({"minutes", "source"}))
        source = _choice(item["source"], f"$.effort.{key}.source", frozenset({"measured", "self_reported", "missing", "not_applicable"}))
        minutes = item["minutes"]
        if source in {"missing", "not_applicable"}:
            if minutes is not None:
                raise WorkbenchContractError("EXPECTED_NULL", f"$.effort.{key}.minutes")
        elif isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            raise WorkbenchContractError("INVALID_MINUTES", f"$.effort.{key}.minutes")
        if source == "not_applicable":
            not_applicable_categories += 1
        else:
            applicable += 1
            if source == "missing":
                missing_categories += 1
        if source == "measured":
            covered += 1
            claimed_measured_categories += 1
            observed += minutes
            claimed_measured += minutes
        elif source == "self_reported":
            covered += 1
            self_reported_categories += 1
            observed += minutes
            self_reported += minutes
    # No trusted verification channel exists in this contract, so applicable
    # categories never become verified regardless of their claimed source.
    trust = "not_applicable" if applicable == 0 else "unverified"
    return {
        "observed_minutes": observed if covered else None,
        "total_minutes": observed if covered == applicable and applicable else None,
        "covered_categories": covered,
        "applicable_categories": applicable,
        "verified_minutes": None,
        "claimed_measured_minutes": claimed_measured if claimed_measured_categories else None,
        "self_reported_minutes": self_reported if self_reported_categories else None,
        "verified_categories": 0,
        "claimed_measured_categories": claimed_measured_categories,
        "self_reported_categories": self_reported_categories,
        "missing_categories": missing_categories,
        "not_applicable_categories": not_applicable_categories,
        "trust": trust,
    }


def _effort(value: Any) -> dict[str, Any]:
    facts = _effort_facts(value)
    return {key: facts[key] for key in _EFFORT_LEGACY_KEYS}


def validate_workbench_document(document: Any) -> dict[str, Any]:
    """Validate one work item and derive Q5/Q6/Q7 display facts.

    Unknown Q6 or incomplete effort stays unknown. A claim, including a
    ``measured`` effort source, is recorded but never substitutes for
    independent validation or explicit human approval.
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
    effort_facts = _effort_facts(root["effort"])
    effort = {key: effort_facts[key] for key in _EFFORT_LEGACY_KEYS}
    effort_trust = {key: effort_facts[key] for key in _EFFORT_TRUST_KEYS}
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
        "effort_trust": effort_trust,
    }
