"""Result-only adapter for the approved native aiqe.result document.

The existing ingress gate remains synthetic-only. Native judge observations
are not independent Q5 acceptance, Q6 experiments, or human review.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from typing import Any

from .contract import validate_run
from .workbench_contract import SCHEMA_VERSION, validate_workbench_document


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("non-finite JSON constant")


def _measurement(value, unit, *, integer=False):
    valid = (
        not isinstance(value, bool)
        and isinstance(value, int if integer else (int, float))
        and value >= 0
    )
    try:
        valid = valid and math.isfinite(value)
    except OverflowError:
        valid = False
    return {
        "value": value if valid else None,
        "unit": unit,
        "status": "reported" if valid else "missing_or_invalid",
        # Native token counts can be estimates; no measured claim is invented.
        "precision": "unspecified",
    }


def adapt_native_report(
    report_bytes: bytes,
    *,
    case_id: str,
    frozen_scope: str,
    frozen_versions: dict[str, str],
    observed_versions: dict[str, str],
) -> dict[str, Any]:
    """Project one approved native case without raw inputs, outputs or errors.

    run_id comes only from validated native metadata. report_sha256 hashes the
    exact supplied UTF-8 bytes (including formatting), never a reserialization.
    No digest is manufactured for independent validation: it remains unknown.
    """
    if not isinstance(report_bytes, bytes) or len(report_bytes) > 4 * 1024 * 1024:
        raise ValueError("expected bounded report bytes")
    native = json.loads(
        report_bytes.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_constant=_invalid_constant,
    )
    # Do not widen ALLOWED_SOURCE_TYPES, bypass the scanner or provenance gate.
    run = validate_run(native)
    matches = [case for case in run.cases if case.case_id == case_id]
    if len(matches) != 1:
        raise ValueError("case must exist exactly once")
    case = matches[0]
    document = {
        "schema_version": SCHEMA_VERSION,
        "source_type": run.metadata.source_type.value,
        "data_classification": run.metadata.data_classification.value,
        "provenance": {
            "run_id": run.run_id,
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "frozen_versions": deepcopy(frozen_versions),
            "observed_versions": deepcopy(observed_versions),
        },
        "work_item": {
            "id": case.case_id,
            "frozen_scope": frozen_scope,
            "claimed_complete": case.status.value == "passed",
            "validation": {"result": "unknown", "evidence_sha256": None},
            "review": {"state": "pending", "actor": None},
        },
        "q6": None,
        "effort": {
            key: {"minutes": None, "source": "missing"}
            for key in ("preparation", "review", "rework", "acceptance", "coordination")
        },
    }
    validate_workbench_document(document)
    execution = case.raw.get("execution", {})
    # Fixed keys only: never copy raw case dictionaries or provider error text.
    observations = {
        "case_id": case.case_id,
        "status": case.status.value,
        "error_code": "native_execution_error" if not case.execution_ok else None,
        "elapsed": _measurement(execution.get("elapsed_sec"), "s"),
        "tokens_generated": _measurement(execution.get("tokens_generated"), "token", integer=True),
        "throughput": _measurement(execution.get("tok_per_sec"), "token/s"),
    }
    return {"document": document, "native_observations": observations}
