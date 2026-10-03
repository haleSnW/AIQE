"""The public demo must remain reproducible and clearly synthetic."""

import json

from examples.showcase_dashboard import STORY, generate


def test_showcase_emits_six_valid_synthetic_runs(tmp_path):
    target = generate(tmp_path)
    assert target.is_file()
    runs = sorted((tmp_path / "runs").glob("*.json"))
    assert len(runs) == len(STORY) == 6
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in runs]
    assert [doc["metadata"]["created_at"] for doc in documents] == [
        timestamp for _, timestamp in STORY
    ]
    assert all(doc["metadata"]["source_type"] == "synthetic" for doc in documents)
    assert all(doc["metadata"]["data_classification"] == "public_synthetic" for doc in documents)
    html = target.read_text(encoding="utf-8")
    assert "public_synthetic" in html


def test_showcase_html_is_path_independent_and_reproducible(tmp_path):
    first = generate(tmp_path / "first").read_bytes()
    second = generate(tmp_path / "second").read_bytes()
    assert first == second
    assert str(tmp_path).encode() not in first
