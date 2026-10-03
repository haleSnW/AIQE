"""Build a reproducible, public-synthetic dashboard story for a local demo.

No model or device is contacted. Every result is rebuilt from the trusted
AIQE synthetic generator and validated by the normal result contract.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from AIQE.dashboard import _find_git_root, render_html, write_dashboard
from AIQE.synthetic import build_valid_runs, make_document

STORY = (
    ("run_a_normal_pass", "2026-09-01T10:00:00+00:00"),
    ("run_b_case_fail", "2026-09-02T10:00:00+00:00"),
    ("run_c_execution_error", "2026-09-03T10:00:00+00:00"),
    ("run_g_baseline", "2026-09-04T10:00:00+00:00"),
    ("run_g_candidate", "2026-09-05T10:00:00+00:00"),
    ("run_h_candidate", "2026-09-06T10:00:00+00:00"),
)


def generate(output: Path) -> Path:
    output = output.expanduser().resolve()
    if _find_git_root(output) is not None:
        raise ValueError("展示数据目录必须位于 Git 工作树之外")
    output.mkdir(parents=True, exist_ok=True)
    runs_dir = output / "runs"
    runs_dir.mkdir(exist_ok=True)
    source = build_valid_runs()
    for index, (source_name, created_at) in enumerate(STORY, start=1):
        original = source[source_name]
        meta = original["metadata"]
        document = make_document(
            run_id=f"showcase-{index:02d}-{source_name}",
            dataset_id=meta["dataset_id"],
            dataset_version=meta["dataset_version"],
            model_id=meta["model_id"],
            backend_id=meta["backend_id"],
            judge_id=meta["judge_id"],
            judge_version=meta["judge_version"],
            cases=original["cases"],
            created_at=created_at,
            test_plan_id="public-synthetic-showcase",
            notes="公开合成展示；非真机测量",
        )
        (runs_dir / f"showcase-{index:02d}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    target, payload = write_dashboard(
        [runs_dir], output / "index.html", generated_at=STORY[-1][1]
    )
    assert payload["totals"]["run_count"] == len(STORY)
    assert payload["totals"]["unreadable_count"] == 0
    # The public artifact must be identical across machines and must not expose
    # the builder's temporary absolute path. This rewrites display-only paths;
    # the validated run digests and metrics remain untouched.
    payload["input_paths"] = ["runs"]
    for run in payload["runs"]:
        run["source_path"] = f"runs/{Path(run['source_path']).name}"
    target.write_text(render_html(payload), encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("/private/tmp/aiqe-showcase"))
    target = generate(parser.parse_args().out)
    print(f"合成质量看板：{target}")


if __name__ == "__main__":
    main()
