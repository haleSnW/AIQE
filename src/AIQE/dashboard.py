"""AIQE Dashboard —— 本地质量看板（数据层）。

设计依据：[`docs/plans/AIQE_DASHBOARD_MVP.md`](../../docs/plans/AIQE_DASHBOARD_MVP.md)

本模块只负责**读取、校验、分组、比对、组装 payload**，不产生任何新指标、
不做任何判定。所有数值都来自 [`contract.compute_run_metrics`] 与
[`comparison.compare_runs`]——展示层不得重算。

三条贯穿全模块的硬规则（均由测试锁定）：

1. **缺失 = N/A，永远不是 0。** 契约层的 `metric_value is None ⟺ status is not OK`
   不变式必须在展示层保持，否则「没测到」会被渲染成「测得 0 分」。
2. **不可比 ⇒ 不产出 delta。** `comparable=False` 时页面不得出现任何变化数字，
   包括「仅供参考」式的补算。
3. **读取失败必须可见。** 校验不通过的文件计入 `unreadable` 并附原因码，
   **不得静默跳过**——静默跳过会让「数据损坏」看起来像「那次运行不存在」。

本模块**零第三方依赖**，只使用标准库。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .comparison import RegressionComparison, compare_runs
from .contract import (
    METRICS_VERSION,
    ContractViolation,
    DataClassification,
    EvaluationRun,
    MetricRecord,
    MetricStatus,
    SourceType,
    compute_run_metrics,
    load_run,
)

DASHBOARD_VERSION = "aiqe.dashboard/0.1.0"

#: 一个分组内参与两两比对的运行数上限（取最近的若干个）。
#: 两两比对是 O(n²)，不设上限时 100 次运行会产生 4950 份对比结果。
MAX_COMPARISON_RUNS = 12

#: 页面渲染时视为「有数值可画」的状态。其余状态一律按缺失处理。
_PLOTTABLE_STATUSES = frozenset({MetricStatus.OK, MetricStatus.PARTIAL})


class DashboardError(Exception):
    """Dashboard 数据层错误。"""


class OutputNotSafeError(DashboardError):
    """目标路径被判定为「可能把数据写进 Git」——拒绝写入。

    这是设计文档 §7 的 D2/D3 措施，属**默认拒绝**：
    无法确认安全时一律拒绝，而不是放行后提示。
    """


# ════════════════════════════════════════════════════════════════
#  1. 数据结构
# ════════════════════════════════════════════════════════════════


@dataclass
class LoadedRun:
    """一次成功加载并通过契约校验的运行。"""
    run: EvaluationRun
    source_path: Path

    @property
    def run_id(self) -> str:
        return self.run.metadata.run_id

    @property
    def sort_key(self) -> tuple[str, str]:
        """趋势与「最近一次」的排序键。

        以 `created_at` 为主键、`run_id` 为**稳定次键**。
        次键不可省：合成样本使用固定时间戳，只按时间排序会得到
        依赖文件系统枚举顺序的不稳定结果，测试也就无法断言。
        """
        return (self.run.metadata.created_at, self.run.metadata.run_id)


@dataclass(frozen=True)
class LoadFailure:
    """一份无法读取的文件。必须展示，不得静默跳过。"""
    source_path: str
    reason_code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "reason_code": self.reason_code,
            "message": self.message,
        }


@dataclass
class RunGroup:
    """一组评估条件相同的运行。

    分组键 = (dataset_id, dataset_version, judge_id, judge_version)，
    与 [`comparison.check_comparable`] 的硬阻断条件完全一致。
    只有同组运行之间才可能可比，因此趋势也只在组内连线。
    """
    dataset_id: str
    dataset_version: str
    judge_id: str
    judge_version: str
    runs: list[LoadedRun] = field(default_factory=list)

    @property
    def key(self) -> str:
        return _key_parts(self.dataset_id, self.dataset_version,
                          self.judge_id, self.judge_version)

    @property
    def sorted_runs(self) -> list[LoadedRun]:
        return sorted(self.runs, key=lambda r: r.sort_key)


# ════════════════════════════════════════════════════════════════
#  2. 发现与加载
# ════════════════════════════════════════════════════════════════


def _iter_json_files(target: Path) -> list[Path]:
    """展开一个输入路径为 JSON 文件列表。

    - 目录 → 其下的 `*.json`（不递归，避免误扫到无关子目录）
    - 文件 → 自身
    - 不存在 → 返回空，由调用方记录为失败

    以 `.` 开头的伴随文件（macOS 的 `._*`）一律跳过：它们是文件系统元数据，
    不是运行结果，计入「无法读取」只会制造噪音。
    """
    if target.is_dir():
        return sorted(
            p for p in target.glob("*.json")
            if not p.name.startswith(".")
        )
    if target.is_file():
        return [target]
    return []


def load_runs(paths: Sequence[str | Path]) -> tuple[list[LoadedRun], list[LoadFailure]]:
    """加载并校验若干路径下的运行结果。

    返回 `(成功列表, 失败列表)`。**失败不会被丢弃**——调用方必须把
    `failures` 展示出来。校验严格复用 [`contract.load_run`]，
    不为了「让图表好看」而放宽任何一条规则。
    """
    loaded: list[LoadedRun] = []
    failures: list[LoadFailure] = []
    seen_paths: set[Path] = set()

    for raw in paths:
        target = Path(raw).expanduser()
        files = _iter_json_files(target)

        if not files and not target.exists():
            failures.append(LoadFailure(
                source_path=str(target),
                reason_code="PATH_NOT_FOUND",
                message="路径不存在",
            ))
            continue

        for path in files:
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            try:
                run = load_run(path)
            except ContractViolation as exc:
                failures.append(LoadFailure(
                    source_path=str(path),
                    reason_code=exc.reason_code,
                    message=str(exc),
                ))
                continue
            except OSError as exc:  # 权限 / IO —— 同样必须可见
                failures.append(LoadFailure(
                    source_path=str(path),
                    reason_code="FILE_UNREADABLE",
                    message=str(exc),
                ))
                continue

            loaded.append(LoadedRun(run=run, source_path=path))

    # run_id 是跨文件的运行身份，不允许 first/last wins。
    # 同一路径已在 seen_paths 处去重；因此这里出现同 run_id，必然来自
    # 两个或更多不同输入文件。所有冲突记录都必须移出 loaded 并显式报错，
    # 否则趋势/比较索引可能把其中一份静默覆盖。
    by_run_id: dict[str, list[LoadedRun]] = {}
    for item in loaded:
        by_run_id.setdefault(item.run_id, []).append(item)

    conflicts = {
        run_id: items
        for run_id, items in by_run_id.items()
        if len(items) > 1
    }
    if conflicts:
        conflicting_ids = set(conflicts)
        loaded = [item for item in loaded if item.run_id not in conflicting_ids]

        for run_id in sorted(conflicts):
            items = sorted(conflicts[run_id], key=lambda item: str(item.source_path))
            conflict_paths = ", ".join(str(item.source_path) for item in items)
            for item in items:
                failures.append(LoadFailure(
                    source_path=str(item.source_path),
                    reason_code="DUPLICATE_RUN_ID",
                    message=(
                        f"run_id {run_id!r} 在多个不同输入文件中重复："
                        f"{conflict_paths}"
                    ),
                ))

    return loaded, failures


def ensure_metrics(loaded: LoadedRun) -> LoadedRun:
    """确保运行的指标记录可用。

    契约文档中的 `metrics` 是**可选的持久化缓存**；合成样本并未写入它。
    缺失时用 [`contract.compute_run_metrics`] 现场计算——这是唯一的指标来源，
    Dashboard 不自行定义任何新指标。
    """
    if not loaded.run.metrics:
        loaded.run.metrics = compute_run_metrics(loaded.run)
    return loaded


# ════════════════════════════════════════════════════════════════
#  3. 分组与排序
# ════════════════════════════════════════════════════════════════


def group_runs(loaded: Sequence[LoadedRun]) -> list[RunGroup]:
    """按可比性硬条件分组。组间顺序稳定（按 key 排序），便于测试。"""
    buckets: dict[tuple[str, str, str, str], RunGroup] = {}

    for item in loaded:
        meta = item.run.metadata
        key = (meta.dataset_id, meta.dataset_version, meta.judge_id, meta.judge_version)
        group = buckets.get(key)
        if group is None:
            group = RunGroup(
                dataset_id=meta.dataset_id,
                dataset_version=meta.dataset_version,
                judge_id=meta.judge_id,
                judge_version=meta.judge_version,
            )
            buckets[key] = group
        group.runs.append(item)

    return [buckets[k] for k in sorted(buckets)]


# ════════════════════════════════════════════════════════════════
#  4. 用例状态统计与迁移
# ════════════════════════════════════════════════════════════════


def case_status_counts(run: EvaluationRun) -> dict[str, int]:
    """统计 passed / failed / error / skipped。

    注意 `skipped` 是**独立**状态，不是 failed 的子集：
    用例缺 `judge.passed` 时无法判定通过与否，把它计入失败会虚增失败数。
    """
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for case in run.cases:
        counts[case.status.value] += 1
    return counts


def case_transitions(
    baseline: EvaluationRun, candidate: EvaluationRun
) -> dict[str, list[str]]:
    """对比两次运行的**用例通过/失败迁移**。

    这与 [`comparison.compare_runs`] 的 `case_comparisons` 是**两个不同维度**：
      - `case_comparisons` 看的是**分数变化**（delta 超阈值 → regression）
      - 本函数看的是**通过/失败迁移**（通过 → 失败 → 新增失败）

    两者都需要：一个用例可能分数只掉 0.05（不算 regression）却从 passed 翻成
    failed；也可能分数掉很多但两边都没通过。UI 必须能分别呈现。

    无法判定（`skipped`）的用例单独归类，不并入失败。
    """
    base_cases = {c.case_id: c for c in baseline.cases}
    cand_cases = {c.case_id: c for c in candidate.cases}

    new_failure: list[str] = []
    fixed: list[str] = []
    persistent_failure: list[str] = []
    still_passing: list[str] = []
    indeterminate: list[str] = []
    added: list[str] = []
    removed: list[str] = []

    for case_id in sorted(set(base_cases) | set(cand_cases)):
        b = base_cases.get(case_id)
        c = cand_cases.get(case_id)

        if b is None:
            added.append(case_id)
            continue
        if c is None:
            removed.append(case_id)
            continue

        b_ok = b.status.value == "passed"
        c_ok = c.status.value == "passed"
        b_bad = b.status.value in ("failed", "error")
        c_bad = c.status.value in ("failed", "error")

        if b_ok and c_bad:
            new_failure.append(case_id)
        elif b_bad and c_ok:
            fixed.append(case_id)
        elif b_bad and c_bad:
            persistent_failure.append(case_id)
        elif b_ok and c_ok:
            still_passing.append(case_id)
        else:
            # 至少一侧是 skipped —— 无从判定，不得猜测
            indeterminate.append(case_id)

    return {
        "new_failure": new_failure,
        "fixed": fixed,
        "persistent_failure": persistent_failure,
        "still_passing": still_passing,
        "indeterminate": indeterminate,
        "added": added,
        "removed": removed,
    }


# ════════════════════════════════════════════════════════════════
#  5. 趋势序列（断线规则在此实现，故可被测试）
# ════════════════════════════════════════════════════════════════


def build_trend(group: RunGroup, metric_id: str) -> dict[str, Any]:
    """构造某分组内、某指标的折线序列。

    断线规则（设计文档 §6.2）：

    | 情况 | 处理 |
    |---|---|
    | `status` 非 OK/PARTIAL | **断线**，记入 `gaps`，不画点 |
    | `metric_version` 变化 | **断线**（版本不同 → 语义可能已变） |
    | `precision` 变化 | **分系列**（`estimated` 与 `measured` 不可连成一条） |
    | 跨分组 | 不连线（本函数只处理单组，故天然满足） |

    绝不允许把 `None` 当作 0 画点——那会在图上产生「断崖式下跌」的假象。
    """
    # series_key = (metric_version, precision)
    series: dict[tuple[str, str], dict[str, Any]] = {}
    unit = ""

    for item in group.sorted_runs:
        record = item.run.metric(metric_id)
        created_at = item.run.metadata.created_at
        run_id = item.run_id

        if record is None:
            # 该运行完全没有这条指标记录 —— 同样是缺失，同样要断线
            key = (METRICS_VERSION, "unknown")
            bucket = series.setdefault(key, {
                "metric_version": METRICS_VERSION,
                "precision": "unknown",
                "points": [],
                "gaps": [],
            })
            bucket["gaps"].append({
                "run_id": run_id,
                "created_at": created_at,
                "status": MetricStatus.MISSING.value,
                "reason": "该运行不含此指标的记录",
            })
            continue

        unit = unit or record.metric_unit
        key = (record.metric_version, record.precision.value)
        bucket = series.setdefault(key, {
            "metric_version": record.metric_version,
            "precision": record.precision.value,
            "points": [],
            "gaps": [],
        })

        if record.status in _PLOTTABLE_STATUSES and record.metric_value is not None:
            bucket["points"].append({
                "run_id": run_id,
                "created_at": created_at,
                "value": record.metric_value,
            })
        else:
            bucket["gaps"].append({
                "run_id": run_id,
                "created_at": created_at,
                "status": record.status.value,
                "reason": record.reason,
            })

    ordered = [series[k] for k in sorted(series)]
    return {
        "metric_id": metric_id,
        "metric_unit": unit,
        "series": ordered,
        # 有断点或分了多条系列时，UI 必须显式提示「数据不完整/不可连」
        "has_gaps": any(s["gaps"] for s in ordered),
        "is_split": len(ordered) > 1,
    }


# ════════════════════════════════════════════════════════════════
#  6. 比对
# ════════════════════════════════════════════════════════════════


def comparison_payload(
    baseline: LoadedRun, candidate: LoadedRun
) -> dict[str, Any]:
    """组装一次比对的展示数据。

    【硬规则】`comparable=False` 时**不产出任何 delta**。
    `compare_runs` 已保证此时 `case_comparisons` 与 `metric_deltas` 为空；
    本函数也不做任何「尽力而为」的补算，只把原因原样带出。
    """
    result: RegressionComparison = compare_runs(baseline.run, candidate.run)
    payload = result.to_dict()

    # 用例通过/失败迁移 —— 独立于分数 delta 的第二个维度
    payload["case_transitions"] = (
        case_transitions(baseline.run, candidate.run) if result.comparable else {}
    )

    # 两侧的分母，供 UI 显示「3/10 新增失败」这类需要基数的表述
    payload["baseline_case_count"] = len(baseline.run.cases)
    payload["candidate_case_count"] = len(candidate.run.cases)

    # 指标两侧原值：UI 需要显示 "0.80 → 0.40"，而不只是差值
    payload["metric_series"] = _metric_side_by_side(
        baseline.run, candidate.run, result.metric_deltas
    )

    return payload


def _metric_side_by_side(
    baseline: EvaluationRun, candidate: EvaluationRun, deltas: dict[str, float]
) -> dict[str, dict[str, Any]]:
    """指标的两侧原值与状态（供展示，不参与判定）。"""
    out: dict[str, dict[str, Any]] = {}
    baseline_metrics = {m.metric_id: m for m in baseline.metrics if m.scope == "run"}
    candidate_metrics = {m.metric_id: m for m in candidate.metrics if m.scope == "run"}
    for metric_id in sorted(baseline_metrics.keys() | candidate_metrics.keys()):
        record = baseline_metrics.get(metric_id)
        other = candidate_metrics.get(metric_id)
        out[metric_id] = {
            "metric_unit": (record or other).metric_unit,
            "baseline": _metric_side(record),
            "candidate": _metric_side(other),
            # 展示层只消费比较层已批准的差值，禁止另行计算。
            "display_delta": deltas.get(metric_id),
        }
    return out


def _metric_side(record: MetricRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "value": record.metric_value,
        "status": record.status.value,
        "precision": record.precision.value,
        "metric_unit": record.metric_unit,
        "metric_version": record.metric_version,
        "reason": record.reason,
    }


def _key_parts(*parts: str) -> str:
    """JSON array encoding has no delimiter collisions and matches JS JSON.stringify."""
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def _comparison_key(baseline_id: str, candidate_id: str) -> str:
    return _key_parts(baseline_id, candidate_id)


def build_group_comparisons(group: RunGroup) -> dict[str, Any]:
    """为分组内最近 `MAX_COMPARISON_RUNS` 个运行预计算两两比对。

    预计算而非前端重算，是为了让「不可比 ⇒ 无 delta」这条规则
    只存在于 Python 侧一处，前端无从绕过。
    """
    ordered = group.sorted_runs
    truncated = len(ordered) > MAX_COMPARISON_RUNS
    window = ordered[-MAX_COMPARISON_RUNS:]

    comparisons: dict[str, Any] = {}
    for i, baseline in enumerate(window):
        for candidate in window[i + 1:]:
            comparisons[_comparison_key(baseline.run_id, candidate.run_id)] = (
                comparison_payload(baseline, candidate)
            )

    return {
        "keys": sorted(comparisons),
        "by_key": comparisons,
        "truncated": truncated,
        "considered_run_ids": [r.run_id for r in window],
    }


# ════════════════════════════════════════════════════════════════
#  7. Payload 组装
# ════════════════════════════════════════════════════════════════


def _run_payload(item: LoadedRun) -> dict[str, Any]:
    meta = item.run.metadata
    return {
        "run_id": meta.run_id,
        "created_at": meta.created_at,
        "source_path": str(item.source_path),
        "dataset_id": meta.dataset_id,
        "dataset_version": meta.dataset_version,
        "judge_id": meta.judge_id,
        "judge_version": meta.judge_version,
        "model_id": meta.model_id,
        "backend_id": meta.backend_id,
        "source_type": meta.source_type.value,
        "data_classification": meta.data_classification.value,
        "generator": meta.generator,
        "content_digest": meta.content_digest,
        "case_count": len(item.run.cases),
        "case_status_counts": case_status_counts(item.run),
        "metrics": {
            record.metric_id: record.to_dict()
            for record in item.run.metrics
            if record.scope == "run"
        },
    }


def _group_payload(group: RunGroup) -> dict[str, Any]:
    ordered = group.sorted_runs
    metric_ids = sorted({
        record.metric_id
        for item in ordered
        for record in item.run.metrics
        if record.scope == "run"
    })
    return {
        "key": group.key,
        "dataset_id": group.dataset_id,
        "dataset_version": group.dataset_version,
        "judge_id": group.judge_id,
        "judge_version": group.judge_version,
        "run_ids": [r.run_id for r in ordered],
        "metric_ids": metric_ids,
        "trends": {mid: build_trend(group, mid) for mid in metric_ids},
        "comparisons": build_group_comparisons(group),
    }


def build_payload(
    paths: Sequence[str | Path],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """组装完整页面数据。

    `generated_at` 可注入，使输出**确定性可测**（默认取当前 UTC 时间）。
    """
    loaded, failures = load_runs(paths)
    for item in loaded:
        ensure_metrics(item)

    groups = group_runs(loaded)

    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return {
        "dashboard_version": DASHBOARD_VERSION,
        "metrics_version": METRICS_VERSION,
        "generated_at": generated_at,
        "input_paths": [str(p) for p in paths],
        "totals": {
            "run_count": len(loaded),
            "group_count": len(groups),
            "unreadable_count": len(failures),
        },
        "runs": [_run_payload(item) for item in sorted(loaded, key=lambda r: r.sort_key)],
        "groups": [_group_payload(g) for g in groups],
        "unreadable": [f.to_dict() for f in failures],
    }


# ════════════════════════════════════════════════════════════════
#  8. 输出安全检查（设计文档 §7 的 D2 / D3）
# ════════════════════════════════════════════════════════════════


def _find_git_root(start: Path) -> Path | None:
    """向上查找 Git 工作树根。找不到返回 None。

    不依赖 `git` 可执行文件——只认 `.git` 的存在，因此
    「git 没装」不会让检查静默放行。
    """
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _git_ignores(path: Path, repo_root: Path) -> bool:
    """询问 git 该路径是否被忽略。git 不可用或出错时**拒绝**（失败关闭）。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "-q", str(path)],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False  # 问不出来 → 当作「没被忽略」→ 拒绝
    return proc.returncode == 0


def check_output_safety(target: Path, payload: dict[str, Any]) -> None:
    """拒绝把内联了数据的产物写进 Git 工作树。

    D2：目标在 Git 工作树内时，必须已被 gitignore 忽略。
    D3：**即使**已被忽略，只要任一运行不是 `public_synthetic`，仍然拒绝。

    为什么 D3 比 D2 严格：`git check-ignore` 只回答「这个路径会不会被提交」，
    不回答「这份数据**允许**被提交」。gitignore 可能被改、可能被
    `git add -f` 绕过。默认拒绝。
    """
    repo_root = _find_git_root(target.parent)
    if repo_root is None:
        return  # 不在任何工作树内 —— 安全

    if not _git_ignores(target, repo_root):
        raise OutputNotSafeError(
            f"拒绝写入：目标位于 Git 工作树内且未被忽略\n"
            f"  目标：{target}\n"
            f"  工作树：{repo_root}\n"
            f"  该产物内联了运行数据，可能被误提交。\n"
            f"  请改用仓库外的路径（默认 ~/.AIQE/results/dashboard/），"
            f"或先在 .gitignore 中忽略该路径。"
        )

    unsafe = sorted({
        r["run_id"]
        for r in payload["runs"]
        if r["data_classification"] != DataClassification.PUBLIC_SYNTHETIC.value
    })
    if unsafe:
        raise OutputNotSafeError(
            f"拒绝写入：运行数据不是 public_synthetic，不得进入 Git 工作树\n"
            f"  目标：{target}\n"
            f"  非公开合成数据的运行：{', '.join(unsafe)}\n"
            f"  无论 .gitignore 状态如何，这条都不可绕过（D3，默认拒绝）。"
        )


# ════════════════════════════════════════════════════════════════
#  9. 渲染与写入
# ════════════════════════════════════════════════════════════════


def inline_json(payload: Any) -> str:
    """把 payload 序列化为可安全内联进 `<script>` 的 JSON。

    必须转义 `<`、`>`、`&`：否则数据中一旦出现 `</script>`，
    浏览器会提前结束脚本块，页面结构被数据破坏（也是 XSS 面）。
    同时转义 U+2028 / U+2029 —— 它们在 JS 字符串字面量中是非法字符。
    """
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=None)
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def render_html(payload: dict[str, Any]) -> str:
    """渲染为单文件、自包含的 HTML。"""
    from .dashboard_template import TEMPLATE

    return TEMPLATE.replace("__AIQE_DATA__", inline_json(payload))


def write_dashboard(
    paths: Sequence[str | Path],
    out: str | Path,
    generated_at: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """读取 → 校验 → 组装 → 安全检查 → 写入。返回 (产物路径, payload)。

    先写 `.tmp` 再 `replace`，避免中途失败留下半成品
    （与既有 `reporter.to_json` 的落盘方式一致）。
    """
    payload = build_payload(paths, generated_at=generated_at)
    target = Path(out).expanduser()

    check_output_safety(target, payload)

    target.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(payload)
    # 独占创建同目录临时文件，防止固定 .tmp 文件被预置为符号链接。
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(html)
        os.replace(temp_path, target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return target, payload


# ════════════════════════════════════════════════════════════════
#  11. 命令行入口
# ════════════════════════════════════════════════════════════════

DEFAULT_OUT = "~/.AIQE/results/dashboard/index.html"


def main(argv: Iterable[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m AIQE.dashboard",
        description="AIQE 本地质量看板 —— 从契约运行结果生成单文件 HTML。",
    )
    parser.add_argument(
        "--runs", "-r", action="append", default=[], metavar="PATH",
        help="运行结果文件或目录，可重复指定。目录下的 *.json 会被逐个校验。",
    )
    parser.add_argument(
        "--out", "-o", default=DEFAULT_OUT, metavar="FILE",
        help=f"输出 HTML 路径（默认 {DEFAULT_OUT}）",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    paths = args.runs or ["~/.AIQE/results/runs"]

    try:
        target, payload = write_dashboard(paths, args.out)
    except OutputNotSafeError as exc:
        print(f"错误：{exc}")
        return 2
    except DashboardError as exc:
        print(f"错误：{exc}")
        return 1

    totals = payload["totals"]
    print(f"已生成：{target}")
    print(f"  运行数：{totals['run_count']}    分组：{totals['group_count']}")
    if totals["unreadable_count"]:
        print(f"  ⚠️  {totals['unreadable_count']} 个文件无法读取（页面中已列出原因）")
        for failure in payload["unreadable"]:
            print(f"      [{failure['reason_code']}] {failure['source_path']}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
