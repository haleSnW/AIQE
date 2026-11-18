"""Q7 human-effort sidecar contract tests.

The sidecar is synthetic in this package: no real human gold, timer export or
customer record is created.  The contract must keep claimed ``measured`` and
``self_reported`` time separate from independently verified time.  Because no
trusted timer or attestation channel exists here, no category is ever promoted
to verified merely by carrying a source string.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from AIQE.workbench_contract import (
    SCHEMA_VERSION,
    WorkbenchContractError,
    validate_workbench_document,
)


CATEGORIES = ("preparation", "review", "rework", "acceptance", "coordination")


def _versions() -> dict[str, str]:
    return {
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


def _document(effort: dict) -> dict:
    versions = _versions()
    return {
        "schema_version": SCHEMA_VERSION,
        "source_type": "synthetic",
        "data_classification": "public_synthetic",
        "provenance": {
            "run_id": "q7-synthetic-1",
            "report_sha256": "a" * 64,
            "frozen_versions": versions,
            "observed_versions": versions.copy(),
        },
        "work_item": {
            "id": "q7-work-1",
            "frozen_scope": "record synthetic human effort without promotion",
            "claimed_complete": True,
            "validation": {"result": "unknown", "evidence_sha256": None},
            "review": {"state": "pending", "actor": None},
        },
        "q6": None,
        "effort": effort,
    }


def _effort(**overrides) -> dict:
    effort = {key: {"minutes": 0, "source": "measured"} for key in CATEGORIES}
    effort.update(overrides)
    return effort


def _result(effort: dict) -> dict:
    return validate_workbench_document(_document(effort))


def test_measured_claim_is_not_independently_verified():
    result = _result({key: {"minutes": 1, "source": "measured"} for key in CATEGORIES})
    legacy = result["effort"]
    trust = result["effort_trust"]

    assert legacy["observed_minutes"] == 5
    assert legacy["total_minutes"] == 5
    assert legacy["covered_categories"] == 5
    assert legacy["applicable_categories"] == 5
    assert trust["claimed_measured_minutes"] == 5
    assert trust["self_reported_minutes"] is None
    assert trust["verified_minutes"] is None
    assert trust["claimed_measured_categories"] == 5
    assert trust["self_reported_categories"] == 0
    assert trust["verified_categories"] == 0
    assert trust["missing_categories"] == 0
    assert trust["not_applicable_categories"] == 0
    assert trust["trust"] == "unverified"


def test_self_reported_minutes_are_visible_but_not_verified():
    effort = _effort(
        preparation={"minutes": 30, "source": "measured"},
        review={"minutes": 15, "source": "self_reported"},
        rework={"minutes": None, "source": "missing"},
        acceptance={"minutes": None, "source": "not_applicable"},
        coordination={"minutes": 5, "source": "measured"},
    )
    result = _result(effort)
    legacy = result["effort"]
    trust = result["effort_trust"]

    # Legacy fields remain visible for compatibility.
    assert legacy["observed_minutes"] == 50
    assert legacy["covered_categories"] == 3
    assert legacy["applicable_categories"] == 4
    assert legacy["total_minutes"] is None

    # Measured entries remain claims; self-reports stay separately visible.
    assert trust["claimed_measured_minutes"] == 35
    assert trust["self_reported_minutes"] == 15
    assert trust["verified_minutes"] is None
    assert trust["claimed_measured_categories"] == 2
    assert trust["self_reported_categories"] == 1
    assert trust["verified_categories"] == 0
    assert trust["missing_categories"] == 1
    assert trust["not_applicable_categories"] == 1
    assert trust["trust"] == "unverified"


def test_self_reported_only_is_unverified_not_measured():
    result = _result(
        {key: {"minutes": 10, "source": "self_reported"} for key in CATEGORIES}
    )
    legacy = result["effort"]
    trust = result["effort_trust"]

    assert legacy["observed_minutes"] == 50
    assert legacy["total_minutes"] == 50
    assert legacy["covered_categories"] == 5
    assert trust["claimed_measured_minutes"] is None
    assert trust["verified_minutes"] is None
    assert trust["self_reported_minutes"] == 50
    assert trust["claimed_measured_categories"] == 0
    assert trust["verified_categories"] == 0
    assert trust["self_reported_categories"] == 5
    assert trust["trust"] == "unverified"


def test_missing_and_not_applicable_have_explicit_denominators():
    missing = _result({key: {"minutes": None, "source": "missing"} for key in CATEGORIES})
    missing_legacy = missing["effort"]
    missing_trust = missing["effort_trust"]
    assert missing_legacy["observed_minutes"] is None
    assert missing_legacy["total_minutes"] is None
    assert missing_legacy["covered_categories"] == 0
    assert missing_legacy["applicable_categories"] == 5
    assert missing_trust["claimed_measured_minutes"] is None
    assert missing_trust["verified_minutes"] is None
    assert missing_trust["self_reported_minutes"] is None
    assert missing_trust["claimed_measured_categories"] == 0
    assert missing_trust["verified_categories"] == 0
    assert missing_trust["missing_categories"] == 5
    assert missing_trust["not_applicable_categories"] == 0
    assert missing_trust["trust"] == "unverified"

    not_applicable = _result(
        {key: {"minutes": None, "source": "not_applicable"} for key in CATEGORIES}
    )
    na_legacy = not_applicable["effort"]
    na_trust = not_applicable["effort_trust"]
    assert na_legacy["observed_minutes"] is None
    assert na_legacy["total_minutes"] is None
    assert na_legacy["covered_categories"] == 0
    assert na_legacy["applicable_categories"] == 0
    assert na_trust["claimed_measured_minutes"] is None
    assert na_trust["verified_minutes"] is None
    assert na_trust["self_reported_minutes"] is None
    assert na_trust["claimed_measured_categories"] == 0
    assert na_trust["verified_categories"] == 0
    assert na_trust["missing_categories"] == 0
    assert na_trust["not_applicable_categories"] == 5
    assert na_trust["trust"] == "not_applicable"


def test_zero_measured_minutes_is_claimed_not_missing():
    result = _result({key: {"minutes": 0, "source": "measured"} for key in CATEGORIES})
    legacy = result["effort"]
    trust = result["effort_trust"]

    assert trust["claimed_measured_minutes"] == 0
    assert trust["claimed_measured_categories"] == 5
    assert trust["verified_minutes"] is None
    assert trust["verified_categories"] == 0
    assert trust["self_reported_minutes"] is None
    assert legacy["total_minutes"] == 0
    assert trust["trust"] == "unverified"


def test_complete_measured_document_without_attestation_cannot_verify():
    """Every category claims measured, yet no independent channel exists."""
    document = _document(
        {key: {"minutes": 5, "source": "measured"} for key in CATEGORIES}
    )
    assert "attestation" not in document
    assert all("attestation" not in item for item in document["effort"].values())

    trust = validate_workbench_document(document)["effort_trust"]
    assert trust["claimed_measured_minutes"] == 25
    assert trust["claimed_measured_categories"] == 5
    assert trust["verified_minutes"] is None
    assert trust["verified_categories"] == 0
    assert trust["trust"] == "unverified"

    # Self-supplied booleans or hashes are not accepted trust shortcuts.
    document["effort"]["review"]["attestation"] = True
    with pytest.raises(WorkbenchContractError) as error:
        validate_workbench_document(document)
    assert error.value.code == "FIELD_NOT_ALLOWED"
    document["effort"]["review"].pop("attestation")

    document["attestation"] = {"source": "human_timer", "sha256": "c" * 64}
    with pytest.raises(WorkbenchContractError) as error:
        validate_workbench_document(document)
    assert error.value.code == "FIELD_NOT_ALLOWED"


def test_model_inferred_and_synthetic_fields_are_rejected():
    for field in ("model_reported", "inferred", "synthetic_sample", "confidence", "actor"):
        effort = _effort(review={"minutes": 10, "source": "measured", field: "x"})
        with pytest.raises(WorkbenchContractError) as error:
            _result(effort)
        assert error.value.code == "FIELD_NOT_ALLOWED"

    effort = _effort()
    effort["model_total"] = {"minutes": 10, "source": "measured"}
    with pytest.raises(WorkbenchContractError) as error:
        _result(effort)
    assert error.value.code == "FIELD_NOT_ALLOWED"


@pytest.mark.parametrize(
    "item,code",
    [
        ({"minutes": 10, "source": "model_self_report"}, "INVALID_ENUM"),
        ({"minutes": None, "source": "measured"}, "INVALID_MINUTES"),
        ({"minutes": None, "source": "self_reported"}, "INVALID_MINUTES"),
        ({"minutes": -1, "source": "self_reported"}, "INVALID_MINUTES"),
        ({"minutes": True, "source": "measured"}, "INVALID_MINUTES"),
        ({"minutes": "10", "source": "measured"}, "INVALID_MINUTES"),
        ({"minutes": 0, "source": "missing"}, "EXPECTED_NULL"),
        ({"minutes": 0, "source": "not_applicable"}, "EXPECTED_NULL"),
    ],
)
def test_source_and_minutes_contract(item, code):
    effort = _effort(review=item)
    with pytest.raises(WorkbenchContractError) as error:
        _result(effort)
    assert error.value.code == code


def test_input_sidecar_is_not_mutated():
    effort = _effort(review={"minutes": 15, "source": "self_reported"})
    snapshot = deepcopy(effort)
    _result(effort)
    assert effort == snapshot
