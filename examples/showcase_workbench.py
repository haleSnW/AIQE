"""Reproducible invented Workbench evidence. No models, devices or customer data.

Usage: PYTHONPATH=src python3 examples/showcase_workbench.py
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from AIQE.dashboard import _find_git_root, render_html, write_dashboard
from AIQE.workbench_contract import SCHEMA_VERSION, validate_workbench_document


def synthetic_documents() -> list[dict]:
    """Three explicitly synthetic states: accepted, regression, unknown/stale."""
    versions = {
        "requirement": "scope-v1", "rule": "rules-v1", "test_before": "tests-v1",
        "test_after": "tests-v2", "implementation_good": "correct-v1",
        "implementation_bad": "known-defect-v1", "environment": "offline-demo-v1",
        "challenge": "challenge-v1", "oracle": "oracle-v1",
    }
    def digest(label):
        return hashlib.sha256(('explicitly synthetic: ' + label).encode()).hexdigest()
    base = {
        "schema_version": SCHEMA_VERSION, "source_type": "synthetic",
        "data_classification": "public_synthetic",
        "provenance": {"run_id": "synthetic-workbench-demo",
                       "report_sha256": digest('invented-report'),
                       "frozen_versions": versions, "observed_versions": versions.copy()},
        "work_item": {"id": "WB-101", "frozen_scope": "Reject expired session tokens while preserving valid sessions.",
                      "claimed_complete": True,
                      "validation": {"result": "passed", "evidence_sha256": digest('invented-validation')},
                      "review": {"state": "accepted", "actor": "synthetic-reviewer"}},
        "q6": {"challenge_id": "synthetic-expired-token", "before_correct": "passed",
               "before_defective": "failed", "after_correct": "passed", "after_defective": "failed"},
        "effort": {"preparation": {"minutes": 12, "source": "measured"},
                   "review": {"minutes": 8, "source": "self_reported"},
                   "rework": {"minutes": 0, "source": "measured"},
                   "acceptance": {"minutes": 4, "source": "self_reported"},
                   "coordination": {"minutes": None, "source": "not_applicable"}},
    }
    regression = deepcopy(base)
    regression['work_item']['id'] = 'WB-102'
    regression['work_item']['frozen_scope'] = 'Keep the known duplicate-payment defect detectable after test refactoring.'
    regression['q6']['challenge_id'] = 'synthetic-duplicate-payment'
    regression['q6']['after_defective'] = 'passed'
    regression['work_item']['review'] = {'state': 'pending', 'actor': None}
    regression['effort']['review'] = {'minutes': None, 'source': 'missing'}
    pending = deepcopy(base)
    pending['work_item']['id'] = 'WB-103'
    pending['work_item']['frozen_scope'] = 'Validate empty export handling against the updated acceptance rule.'
    pending['work_item']['validation'] = {'result': 'unknown', 'evidence_sha256': None}
    pending['work_item']['review'] = {'state': 'pending', 'actor': None}
    pending['q6'] = None
    pending['provenance']['observed_versions']['rule'] = 'rules-v2'
    pending['effort'] = {key: {'minutes': None, 'source': 'missing'} for key in base['effort']}
    documents = [base, regression, pending]
    for document in documents:
        validate_workbench_document(document)
    return documents


def generate(output: Path) -> Path:
    output = output.expanduser().resolve()
    if _find_git_root(output) is not None:
        raise ValueError('Synthetic showcase output must be outside a Git worktree')
    documents_dir = output / 'documents'
    documents_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for document in synthetic_documents():
        path = documents_dir / (document['work_item']['id'] + '.json')
        path.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
        paths.append(path)
    target, payload = write_dashboard([], output / 'index.html',
                                      generated_at='2026-10-24T00:00:00+00:00',
                                      workbench_paths=paths)
    # Display relative demo paths so the public synthetic artifact is reproducible.
    for item in payload['workbench']['items']:
        item['source_path'] = 'documents/' + Path(item['source_path']).name
    target.write_text(render_html(payload), encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('/private/tmp/aiqe-workbench'))
    print('Explicitly synthetic Workbench: ' + str(generate(parser.parse_args().out)))
