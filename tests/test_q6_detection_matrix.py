"""Q6 four-cell detection matrix tests using real pytest subprocesses.

Each cell is an actual ``pytest`` run over one test version and one
implementation version.  No exit codes are mocked, no model is called, and no
customer data is used.  The contract under test only accepts observed exit
codes and evidence digests; a bare pass/fail string is not enough.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from AIQE.workbench_contract import (
    SCHEMA_VERSION,
    WorkbenchContractError,
    build_q6_runner_matrix,
    validate_workbench_document,
)


IMPL_CORRECT = """def normalize(value):
    return value.strip().lower()
"""

IMPL_DEFECTIVE = """def normalize(value):
    return value.strip()
"""

TEST_BEFORE = """from impl import normalize


def test_normalize_trims_and_lowercases():
    assert normalize(" A ") == "a"
"""

TEST_AFTER_DETECTS = """from impl import normalize


def test_normalize_still_detects_the_regression():
    assert normalize(" B ") == "b"
"""

TEST_AFTER_WEAK = """from impl import normalize


def test_normalize_returns_text():
    assert isinstance(normalize(" A "), str)
"""

TEST_AFTER_OVERSTRICT = """from impl import normalize


def test_normalize_has_unapproved_behavior():
    assert normalize(" A ") == "a"
    assert normalize("A.") == "a"
"""

ORDER = ("before_correct", "before_defective", "after_correct", "after_defective")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run_cell(root: Path, cell: str, test_source: str, implementation: str) -> dict:
    directory = root / cell
    directory.mkdir(parents=True)
    (directory / "impl.py").write_text(implementation, encoding="utf-8")
    (directory / "test_impl.py").write_text(test_source, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--disable-warnings", "test_impl.py"],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    evidence = hashlib.sha256(
        f"{cell}\0{completed.returncode}\0{completed.stdout}\0{completed.stderr}".encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "test_version": cell.split("_", 1)[0],
        "implementation": "correct" if cell.endswith("_correct") else "defective",
        "status": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "test_sha256": _digest(test_source),
        "implementation_sha256": _digest(implementation),
        "evidence_sha256": evidence,
    }


def _matrix(root: Path, after_test: str) -> dict:
    return {
        "before_correct": _run_cell(root, "before_correct", TEST_BEFORE, IMPL_CORRECT),
        "before_defective": _run_cell(
            root, "before_defective", TEST_BEFORE, IMPL_DEFECTIVE
        ),
        "after_correct": _run_cell(root, "after_correct", after_test, IMPL_CORRECT),
        "after_defective": _run_cell(
            root, "after_defective", after_test, IMPL_DEFECTIVE
        ),
    }


def _build(cells: dict, **overrides) -> dict:
    arguments = {
        "challenge_id": "synthetic-q6-normalize",
        "defect_source": "synthetic fixture authored in this test",
        "cells": cells,
    }
    arguments.update(overrides)
    return build_q6_runner_matrix(**arguments)


def _document(q6: dict) -> dict:
    versions = {
        "requirement": "r1",
        "rule": "a1",
        "test_before": "t1",
        "test_after": "t2",
        "implementation_good": "g1",
        "implementation_bad": "b1",
        "environment": "e1",
        "challenge": "c1",
        "oracle": "o1",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "source_type": "synthetic",
        "data_classification": "public_synthetic",
        "provenance": {
            "run_id": "q6-run-1",
            "report_sha256": "a" * 64,
            "frozen_versions": versions,
            "observed_versions": versions.copy(),
        },
        "work_item": {
            "id": "q6-work-1",
            "frozen_scope": "keep the normalize regression detectable",
            "claimed_complete": True,
            "validation": {"result": "passed", "evidence_sha256": "b" * 64},
            "review": {"state": "accepted", "actor": "human-reviewer"},
        },
        "q6": q6,
        "effort": {
            key: {"minutes": 1, "source": "measured"}
            for key in (
                "preparation",
                "review",
                "rework",
                "acceptance",
                "coordination",
            )
        },
    }


def test_real_runner_matrix_preserves_detection(tmp_path):
    cells = _matrix(tmp_path, TEST_AFTER_DETECTS)

    assert cells["before_correct"]["exit_code"] == 0
    assert cells["before_defective"]["exit_code"] != 0
    assert cells["after_correct"]["exit_code"] == 0
    assert cells["after_defective"]["exit_code"] != 0

    result = _build(cells)
    assert result["matrix"] == {
        "challenge_id": "synthetic-q6-normalize",
        "before_correct": "passed",
        "before_defective": "failed",
        "after_correct": "passed",
        "after_defective": "failed",
    }
    assert result["q6_status"] == "preserved"
    assert result["q6_findings"] == []
    assert result["counts"] == {
        "cells_total": 4,
        "observed_cells": 4,
        "unobserved_cells": 0,
        "error_cells": 0,
        "detection_cells": 2,
        "correctness_cells": 2,
    }
    assert validate_workbench_document(_document(result["matrix"]))["status"] == "accepted"


def test_real_runner_matrix_detects_lost_detection(tmp_path):
    cells = _matrix(tmp_path, TEST_AFTER_WEAK)

    assert cells["after_correct"]["exit_code"] == 0
    assert cells["after_defective"]["exit_code"] == 0

    result = _build(cells)
    assert result["q6_status"] == "regression"
    assert result["q6_findings"] == ["lost_detection"]
    assert validate_workbench_document(_document(result["matrix"]))["status"] == "rejected"


def test_real_runner_matrix_detects_false_reject(tmp_path):
    cells = _matrix(tmp_path, TEST_AFTER_OVERSTRICT)

    assert cells["after_correct"]["exit_code"] != 0
    assert cells["after_defective"]["exit_code"] != 0

    result = _build(cells)
    assert result["q6_status"] == "regression"
    assert result["q6_findings"] == ["false_reject"]


def test_missing_and_unknown_cells_are_not_preserved(tmp_path):
    cells = _matrix(tmp_path, TEST_AFTER_DETECTS)

    missing = dict(cells)
    del missing["after_defective"]
    with pytest.raises(WorkbenchContractError) as error:
        _build(missing)
    assert error.value.code == "Q6_CELL_MISSING"

    unknown = deepcopy(cells)
    unknown["after_defective"] = {
        **unknown["after_defective"],
        "status": "unknown",
        "exit_code": None,
        "evidence_sha256": None,
    }
    result = _build(unknown)
    assert result["q6_status"] == "unknown"
    assert result["counts"]["observed_cells"] == 3
    assert result["counts"]["unobserved_cells"] == 1


def test_exit_code_and_evidence_conflicts_are_rejected(tmp_path):
    cells = _matrix(tmp_path, TEST_AFTER_DETECTS)

    contradictory = deepcopy(cells)
    contradictory["before_correct"]["exit_code"] = 1
    with pytest.raises(WorkbenchContractError) as error:
        _build(contradictory)
    assert error.value.code == "Q6_EXIT_CODE_CONFLICT"

    duplicated = deepcopy(cells)
    duplicated["after_defective"]["evidence_sha256"] = duplicated[
        "before_defective"
    ]["evidence_sha256"]
    with pytest.raises(WorkbenchContractError) as error:
        _build(duplicated)
    assert error.value.code == "Q6_EVIDENCE_CONFLICT"

    unobserved_with_evidence = deepcopy(cells)
    unobserved_with_evidence["after_defective"] = {
        **unobserved_with_evidence["after_defective"],
        "status": "skipped",
        "exit_code": None,
    }
    with pytest.raises(WorkbenchContractError) as error:
        _build(unobserved_with_evidence)
    assert error.value.code == "Q6_EVIDENCE_CONFLICT"


def test_incomparable_runs_are_unknown_not_preserved(tmp_path):
    cells = _matrix(tmp_path, TEST_AFTER_DETECTS)

    result = _build(cells, comparable=False)
    assert result["comparable"] is False
    assert result["q6_status"] == "unknown"
    assert result["q6_findings"] == []
    assert result["matrix"]["after_defective"] == "failed"

    conflicting = deepcopy(cells)
    conflicting["after_defective"]["test_sha256"] = "f" * 64
    with pytest.raises(WorkbenchContractError) as error:
        _build(conflicting)
    assert error.value.code == "Q6_COMPARABILITY_CONFLICT"


def test_error_cell_has_a_clear_denominator_and_input_is_immutable(tmp_path):
    cells = _matrix(tmp_path, TEST_AFTER_DETECTS)

    cells["before_correct"] = {
        **cells["before_correct"],
        "status": "error",
        "exit_code": 2,
    }
    result = _build(cells)
    assert result["q6_status"] == "unknown"
    assert result["counts"]["observed_cells"] == 3
    assert result["counts"]["error_cells"] == 1

    untouched = _matrix(tmp_path / "immutable", TEST_AFTER_DETECTS)
    snapshot = deepcopy(untouched)
    _build(untouched)
    assert untouched == snapshot
