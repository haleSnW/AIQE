# AIQE/e2e_gate.py —— E2E 质量门禁：AI 修过的测试不能悄悄变绿
#
# 定位：自主 E2E 闭环（planner → generator → healer）里的**确定性判定层**。
#   AI 负责重复执行与修复测试实现；本模块负责回答「这次变绿能不能放行」。
#
# 输入（全部是文件，零网络、零第三方依赖）：
#   - Playwright JSON 报告（`--reporter=json` 的标准输出）           必填
#   - 基线 Playwright JSON 报告（上一次可信运行）                    可选
#   - AI healer / 人工修复产生的统一 diff（git diff 输出）           可选
#
# 输出：
#   - 门禁判定 aiqe.e2e-gate/0.1.0：PASS / ESCALATE / BLOCK + 稳定原因码
#   - AIQE 结果契约文档（source_type=local_test），可直接进入现有看板
#   - Markdown 摘要，适合贴到 PR 评论或 CI Step Summary
#
# 【核心原则】
#   1. 「测试全绿」不是放行条件。全绿 + 断言被削弱 = BLOCK。
#   2. 规则是确定性的正则/计数，不调用任何模型；同输入恒得同判定。
#   3. 只投影结果字段：错误消息、stdout、截图路径**不进入**结果契约，
#      只保留受控原因码。原始报告留在用户自己的 CI 产物里。
#   4. 缺证据时不猜：报告为空、顶层错误、基线不可比 → 不给 PASS。

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

from AIQE.contract import (
    SCHEMA_VERSION,
    DataClassification,
    SourceType,
    compute_content_digest,
    validate_run,
)

GATE_SCHEMA = "aiqe.e2e-gate/0.1.0"
GATE_VERSION = "0.1.0"
GENERATOR = "aiqe.e2e-gate/0.1.0"


# ════════════════════════════════════════════════════════════════
#  1. 判定等级与原因码（稳定字符串，供 CI / 看板 / 测试使用）
# ════════════════════════════════════════════════════════════════

class Verdict(str, Enum):
    PASS = "PASS"            # 证据完整且无风险信号 → 可进入候选发布
    ESCALATE = "ESCALATE"    # 需要人看一眼（不自动阻断，也不自动放行）
    BLOCK = "BLOCK"          # 阻断自动放行

    @property
    def rank(self) -> int:
        return {"PASS": 0, "ESCALATE": 1, "BLOCK": 2}[self.value]

    @property
    def exit_code(self) -> int:
        # 0 = 放行；1 = 阻断；2 = 需人工。与 pytest/大多数 CI 习惯一致：非 0 即不自动通过。
        return {"PASS": 0, "BLOCK": 1, "ESCALATE": 2}[self.value]


# —— 运行结果类 ——
UNEXPECTED_FAILURE = "UNEXPECTED_FAILURE"      # 本次有用例未达预期（无基线时）
NEW_FAILURE = "NEW_FAILURE"                    # 基线通过、本次失败
PERSISTENT_FAILURE = "PERSISTENT_FAILURE"      # 基线就失败、本次仍失败
FLAKY = "FLAKY"                                # 重试后才通过
EXPECTED_FAILURE_MARKED = "EXPECTED_FAILURE_MARKED"  # test.fail() 让失败显示为「符合预期」
SKIP_ADDED = "SKIP_ADDED"                      # 基线执行、本次跳过
TEST_REMOVED = "TEST_REMOVED"                  # 基线存在、本次消失
# —— 证据类 ——
EVIDENCE_EMPTY = "EVIDENCE_EMPTY"              # 报告里没有任何用例
REPORT_ERRORS = "REPORT_ERRORS"                # 报告顶层错误（配置/全局 setup 失败）
TRACE_MISSING = "TRACE_MISSING"                # 失败用例没有附 trace，无法复核
BASELINE_INCOMPARABLE = "BASELINE_INCOMPARABLE"  # 基线与本次 project 集合不同
# —— 修复 diff 类（healer 守卫）——
ASSERTION_REMOVED = "ASSERTION_REMOVED"        # 断言净减少（含被注释掉）
MATCHER_LOOSENED = "MATCHER_LOOSENED"          # 精确匹配器被换成宽松匹配器
ASSERTION_SWALLOWED = "ASSERTION_SWALLOWED"    # 新增吞异常（.catch(() => {}) 等）
TEST_DISABLED = "TEST_DISABLED"                # 新增 skip / fixme / fail / only 标记
TIMEOUT_INFLATED = "TIMEOUT_INFLATED"          # 超时被放大 / 新增 test.slow()
FORCE_ACTION = "FORCE_ACTION"                  # 新增 { force: true }，绕过可操作性检查
SCOPE_VIOLATION = "SCOPE_VIOLATION"            # 修复改到了测试目录以外（产品代码）

#: 默认严重度。改这张表就是改门禁策略——必须走评审。
SEVERITY: dict[str, Verdict] = {
    UNEXPECTED_FAILURE: Verdict.BLOCK,
    NEW_FAILURE: Verdict.BLOCK,
    PERSISTENT_FAILURE: Verdict.BLOCK,
    FLAKY: Verdict.ESCALATE,
    EXPECTED_FAILURE_MARKED: Verdict.ESCALATE,
    SKIP_ADDED: Verdict.ESCALATE,
    TEST_REMOVED: Verdict.ESCALATE,
    EVIDENCE_EMPTY: Verdict.BLOCK,
    REPORT_ERRORS: Verdict.BLOCK,
    TRACE_MISSING: Verdict.ESCALATE,
    BASELINE_INCOMPARABLE: Verdict.ESCALATE,
    ASSERTION_REMOVED: Verdict.BLOCK,
    MATCHER_LOOSENED: Verdict.BLOCK,
    ASSERTION_SWALLOWED: Verdict.BLOCK,
    TEST_DISABLED: Verdict.BLOCK,
    TIMEOUT_INFLATED: Verdict.ESCALATE,
    FORCE_ACTION: Verdict.ESCALATE,
    SCOPE_VIOLATION: Verdict.BLOCK,
}

#: healer 允许改动的路径（glob，相对仓库根）。超出即 SCOPE_VIOLATION。
DEFAULT_ALLOWED_PATHS: tuple[str, ...] = (
    "*.spec.*", "*.test.*", "*.e2e.*",
    "tests/*", "test/*", "e2e/*", "*/tests/*", "*/e2e/*",
    "playwright.config.*", "*/fixtures/*",
)


class GateInputError(ValueError):
    """输入文件无法作为 Playwright 报告 / diff 解析。失败关闭，不降级。"""


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Verdict
    message: str
    case_id: str | None = None
    file: str | None = None
    line: int | None = None
    #: diff 发现按行号归属到的用例（同一 spec 在多个 project 下各算一个）
    attributed_cases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "case_id": self.case_id,
            "file": self.file,
            "line": self.line,
            "attributed_cases": list(self.attributed_cases),
        }


def _finding(code: str, message: str, **where: Any) -> Finding:
    return Finding(code=code, severity=SEVERITY[code], message=message, **where)


# ════════════════════════════════════════════════════════════════
#  2. Playwright JSON 报告解析
# ════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class E2ECase:
    """一个 (project, spec) 组合的最终结果。只保留结果字段，不保留消息正文。"""
    case_id: str
    file: str
    title: str
    project: str
    line: int | None          # spec 在文件中的起始行（用于把 diff 发现归属到用例）
    outcome: str              # expected | unexpected | flaky | skipped
    final_status: str         # passed | failed | timedOut | skipped | interrupted
    expected_status: str      # passed | failed | skipped
    attempts: int
    duration_ms: int | None
    failure_kind: str | None  # ASSERTION | TIMEOUT | INTERRUPTED | RUNTIME | None
    has_trace: bool
    annotations: tuple[str, ...]


_ASSERTION_HINT = re.compile(
    r"expect\(|toHave|toBe|toEqual|toContain|toMatch|Expected:|Received:|AssertionError"
)


def _failure_kind(status: str, errors: Sequence[Any]) -> str | None:
    if status == "timedOut":
        return "TIMEOUT"
    if status == "interrupted":
        return "INTERRUPTED"
    if status != "failed":
        return None
    text = " ".join(
        str(item.get("message", "")) for item in errors if isinstance(item, dict)
    )
    return "ASSERTION" if _ASSERTION_HINT.search(text) else "RUNTIME"


def _object_list(document: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = document.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise GateInputError(f"{field} 必须是对象数组")
    return value


def _iter_specs(suite: dict[str, Any], titles: tuple[str, ...]) -> Iterable[tuple[tuple[str, ...], dict[str, Any]]]:
    title = str(suite.get("title") or "")
    # 顶层 suite 的 title 就是文件名，不重复进标题路径
    here = titles if suite.get("file") == title and not titles else titles + ((title,) if title else ())
    for spec in _object_list(suite, "specs"):
        yield here, spec
    for child in _object_list(suite, "suites"):
        yield from _iter_specs(child, here)


def parse_playwright_report(document: Any) -> tuple[list[E2ECase], dict[str, Any]]:
    """把 Playwright JSON 报告解析为用例列表 + 报告级事实。

    只依赖报告里长期稳定的字段（suites/specs/tests/results/status）。
    结构不符直接抛 GateInputError——不猜字段。
    """
    if not isinstance(document, dict) or not isinstance(document.get("suites"), list):
        raise GateInputError("不是 Playwright JSON 报告：缺少顶层 suites 数组")

    cases: list[E2ECase] = []
    seen: set[str] = set()
    for top in _object_list(document, "suites"):
        file = str(top.get("file") or top.get("title") or "")
        for titles, spec in _iter_specs(top, ()):
            spec_title = str(spec.get("title") or "")
            spec_file = str(spec.get("file") or file)
            for test in _object_list(spec, "tests"):
                project = str(test.get("projectName") or test.get("projectId") or "default")
                path = " › ".join(titles + (spec_title,))
                case_id = f"{project} › {spec_file} › {path}"
                if case_id in seen:
                    raise GateInputError(f"用例标识重复：{case_id}")
                seen.add(case_id)
                results = _object_list(test, "results")
                final = results[-1] if results else {}
                status = final.get("status", "skipped")
                outcome = test.get("status")
                expected = test.get("expectedStatus")
                if (outcome not in ("expected", "unexpected", "flaky", "skipped")
                        or expected not in ("passed", "failed", "skipped")
                        or status not in ("passed", "failed", "timedOut", "skipped", "interrupted")
                        or (not results and outcome != "skipped")):
                    raise GateInputError("用例或执行状态不符合 Playwright JSON 报告结构")
                if outcome in ("expected", "flaky") and status != expected:
                    raise GateInputError("用例结果与最后一次执行状态不一致")
                errors = final.get("errors") or ([final["error"]] if final.get("error") else [])
                durations = [r.get("duration") for r in results if isinstance(r.get("duration"), int)]
                attachments = [a for r in results for a in (r.get("attachments") or []) if isinstance(a, dict)]
                has_trace = any(
                    a.get("name") == "trace" or str(a.get("contentType", "")).endswith("zip")
                    for a in attachments
                )
                annotations = tuple(
                    sorted({str(a.get("type")) for a in (test.get("annotations") or []) if isinstance(a, dict)})
                )
                cases.append(E2ECase(
                    case_id=case_id,
                    file=spec_file,
                    title=path,
                    project=project,
                    line=spec.get("line") if isinstance(spec.get("line"), int) else None,
                    outcome=outcome,
                    final_status=status,
                    expected_status=expected,
                    attempts=len(results),
                    duration_ms=sum(durations) if durations else None,
                    failure_kind=_failure_kind(status, errors),
                    has_trace=has_trace,
                    annotations=annotations,
                ))

    config = document.get("config") if isinstance(document.get("config"), dict) else {}
    stats = document.get("stats") if isinstance(document.get("stats"), dict) else {}
    facts = {
        "playwright_version": str(config.get("version") or "unknown"),
        "projects": sorted({c.project for c in cases}),
        "start_time": stats.get("startTime"),
        "top_level_error_count": len(_object_list(document, "errors")),
    }
    return cases, facts


def load_playwright_report(path: str | Path) -> tuple[list[E2ECase], dict[str, Any], str]:
    file_path = Path(path)
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise GateInputError(f"报告不可读：{file_path}（{exc}）") from exc
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateInputError(f"报告不是合法 UTF-8 JSON：{file_path}（{exc}）") from exc
    cases, facts = parse_playwright_report(document)
    return cases, facts, hashlib.sha256(raw).hexdigest()


# ════════════════════════════════════════════════════════════════
#  3. healer diff 守卫
# ════════════════════════════════════════════════════════════════

_ASSERT_RE = re.compile(r"\bexpect(?:\.soft|\.poll)?\s*\(|\bassert\b|\bexpect\.toPass\b")
_STRICT_MATCHER_RE = re.compile(
    r"\.(toHaveText|toEqual|toStrictEqual|toBe|toHaveURL|toHaveTitle|toHaveCount|"
    r"toHaveValue|toHaveAttribute|toContainText|toMatchObject|toHaveScreenshot)\s*\("
)
_LOOSE_MATCHER_RE = re.compile(
    r"\.(toBeTruthy|toBeDefined|toBeAttached|toBeVisible)\s*\(\s*\)|"
    r"\.not\.(toBeNull|toBeUndefined)\s*\(|"
    r"\.toBeGreaterThanOrEqual\s*\(\s*0\s*\)"
)
#: toHaveText(/.*/) 之类的万能正则：形式上仍是精确匹配器，实际什么都匹配
_CATCHALL_RE = re.compile(r"\(\s*/\^?\.[*+]\$?/[a-z]*\s*[,)]")
_SWALLOW_RE = re.compile(
    r"\.catch\s*\(\s*(?:\(\s*\w*\s*\)|\w+)\s*=>\s*(?:\{\s*\}|null|undefined|void 0|false|true)\s*\)|"
    r"\bexcept\s*(?:Exception|AssertionError)?\s*:\s*pass\b"
)
_DISABLE_RE = re.compile(
    r"\b(?:test|it|describe)(?:\.describe)?\.(skip|fixme|fail|only)\s*\(|"
    r"\b(?:xit|xdescribe|xtest)\s*\(|@pytest\.mark\.(skip|skipif|xfail)\b"
)
_TIMEOUT_RE = re.compile(r"\btimeout\s*[:=]\s*(\d[\d_]*)|setTimeout\s*\(\s*(\d[\d_]*)\s*\)")
_SLOW_RE = re.compile(r"\btest\.slow\s*\(")
_FORCE_RE = re.compile(r"\bforce\s*:\s*true\b")
_COMMENT_RE = re.compile(r"^\s*(//|#|\*|/\*)")
PLAYWRIGHT_DEFAULT_TIMEOUT_MS = 30_000


@dataclass
class _FileDiff:
    path: str
    added: list[tuple[int, str]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def _parse_unified_diff(text: str) -> list[_FileDiff]:
    """最小统一 diff 解析：按 @@ 头里的行数消费 hunk，避免把内容行误判为文件头。"""
    merged: dict[str, _FileDiff] = {}
    current: _FileDiff | None = None
    old_path: str | None = None
    old_left = new_left = 0
    new_line = 0
    hunk_re = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    for raw in text.splitlines():
        if old_left > 0 or new_left > 0:
            if current is None:
                continue
            if raw.startswith("+"):
                current.added.append((new_line, raw[1:]))
                new_line += 1
                new_left -= 1
            elif raw.startswith("-"):
                current.removed.append(raw[1:])
                old_left -= 1
            elif raw.startswith("\\"):
                pass  # "\ No newline at end of file"
            else:
                new_line += 1
                old_left -= 1
                new_left -= 1
            continue
        if raw.startswith("--- "):
            source = raw[4:].strip().split("\t")[0]
            old_path = None if source == "/dev/null" else (source[2:] if source.startswith("a/") else source)
            continue
        if raw.startswith("+++ "):
            target = raw[4:].strip().split("\t")[0]
            path = old_path if target == "/dev/null" else (target[2:] if target.startswith("b/") else target)
            current = merged.setdefault(path, _FileDiff(path=path)) if path else None
            continue
        match = hunk_re.match(raw)
        if match:
            old_left = int(match.group(1)) if match.group(1) is not None else 1
            new_line = int(match.group(2))
            new_left = int(match.group(3)) if match.group(3) is not None else 1
    return list(merged.values())


def _code(line: str) -> bool:
    return bool(line.strip()) and not _COMMENT_RE.match(line)


def _max_timeout(lines: Iterable[str]) -> int:
    best = 0
    for line in lines:
        for match in _TIMEOUT_RE.finditer(line):
            value = match.group(1) or match.group(2)
            best = max(best, int(value.replace("_", "")))
    return best


def _path_allowed(path: str, allowed: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in allowed)


def inspect_patch(text: str, allowed_paths: Sequence[str] = DEFAULT_ALLOWED_PATHS) -> list[Finding]:
    """扫描一份统一 diff，找出「靠削弱测试变绿」的信号。

    规则全部按文件独立计数，并且**被注释掉的断言按删除计**。
    """
    findings: list[Finding] = []
    for diff in _parse_unified_diff(text):
        if not _path_allowed(diff.path, allowed_paths):
            findings.append(_finding(
                SCOPE_VIOLATION,
                "修复改动了测试范围以外的文件；healer 只允许修测试实现（定位器/等待/测试数据）",
                file=diff.path,
            ))
            continue
        added_code = [(n, line) for n, line in diff.added if _code(line)]
        removed_code = [line for line in diff.removed if _code(line)]
        first_line = added_code[0][0] if added_code else None

        removed_asserts = sum(len(_ASSERT_RE.findall(line)) for line in removed_code)
        added_asserts = sum(len(_ASSERT_RE.findall(line)) for _, line in added_code)
        if removed_asserts > added_asserts:
            findings.append(_finding(
                ASSERTION_REMOVED,
                f"断言净减少 {removed_asserts - added_asserts} 处（删除 {removed_asserts}，新增 {added_asserts}）",
                file=diff.path, line=first_line,
            ))

        strict_removed = sum(1 for line in removed_code if _STRICT_MATCHER_RE.search(line))
        strict_added = sum(
            1 for _, line in added_code
            if _STRICT_MATCHER_RE.search(line) and not _CATCHALL_RE.search(line)
        )
        loose_hits = [
            (n, line) for n, line in added_code
            if _LOOSE_MATCHER_RE.search(line) or _CATCHALL_RE.search(line)
        ]
        if strict_removed > strict_added and loose_hits:
            findings.append(_finding(
                MATCHER_LOOSENED,
                f"精确匹配器减少 {strict_removed - strict_added} 处，同时新增宽松匹配",
                file=diff.path, line=loose_hits[0][0],
            ))

        for code, pattern in ((ASSERTION_SWALLOWED, _SWALLOW_RE), (TEST_DISABLED, _DISABLE_RE),
                              (FORCE_ACTION, _FORCE_RE)):
            before = sum(1 for line in removed_code if pattern.search(line))
            hits = [(n, line) for n, line in added_code if pattern.search(line)]
            if len(hits) > before:
                label = {
                    ASSERTION_SWALLOWED: "新增吞异常写法，失败会被静默忽略",
                    TEST_DISABLED: "新增 skip/fixme/fail/only 标记",
                    FORCE_ACTION: "新增 force: true，跳过可见/可点击检查，可能掩盖真实 UI 缺陷",
                }[code]
                findings.append(_finding(code, label, file=diff.path, line=hits[0][0]))

        old_timeout = _max_timeout(removed_code)
        new_timeout = _max_timeout(line for _, line in added_code)
        slow_added = sum(1 for _, line in added_code if _SLOW_RE.search(line)) > sum(
            1 for line in removed_code if _SLOW_RE.search(line)
        )
        # 原来没写超时：只有超过 Playwright 默认用例超时（30s）才算放大
        inflated = new_timeout > old_timeout if old_timeout else new_timeout > PLAYWRIGHT_DEFAULT_TIMEOUT_MS
        if inflated or slow_added:
            detail = "新增 test.slow()" if slow_added else f"超时 {old_timeout} → {new_timeout} ms"
            findings.append(_finding(TIMEOUT_INFLATED, detail, file=diff.path))
    return findings


def _same_file(patch_path: str, report_file: str) -> bool:
    # 报告里的 file 相对 testDir，diff 路径相对仓库根：按路径后缀匹配
    patch_path, report_file = patch_path.replace("\\", "/"), report_file.replace("\\", "/")
    return patch_path == report_file or patch_path.endswith("/" + report_file)


def attribute_findings(findings: Sequence[Finding], cases: Sequence[E2ECase]) -> list[Finding]:
    """把带行号的 diff 发现归属到用例：同文件中起始行 ≤ 发现行的最近一个 spec。

    这是行号近似，不解析 TS/JS 语法；找不到就不归属，只保留文件级发现。
    """
    out: list[Finding] = []
    for item in findings:
        if item.file is None or item.line is None:
            out.append(item)
            continue
        candidates = [c for c in cases if c.line is not None and c.line <= item.line
                      and _same_file(item.file, c.file)]
        if not candidates:
            out.append(item)
            continue
        nearest = max(c.line for c in candidates if c.line is not None)
        owners = tuple(sorted(c.case_id for c in candidates if c.line == nearest))
        out.append(Finding(code=item.code, severity=item.severity, message=item.message,
                           case_id=item.case_id, file=item.file, line=item.line,
                           attributed_cases=owners))
    return out


# ════════════════════════════════════════════════════════════════
#  4. 判定
# ════════════════════════════════════════════════════════════════

def _is_executed(case: E2ECase) -> bool:
    return case.outcome != "skipped" and case.attempts > 0


def _is_green(case: E2ECase) -> bool:
    return (
        case.outcome in ("expected", "flaky")
        and case.expected_status == case.final_status == "passed"
        and case.attempts > 0
    )


@dataclass
class GateResult:
    verdict: Verdict
    findings: list[Finding]
    cases: list[E2ECase]
    report_facts: dict[str, Any]
    baseline: dict[str, Any] | None
    inputs: dict[str, Any]
    evaluated_at: str

    @property
    def exit_code(self) -> int:
        return self.verdict.exit_code

    def counts(self) -> dict[str, int]:
        out = {"total": len(self.cases), "passed": 0, "failed": 0, "flaky": 0, "skipped": 0}
        for case in self.cases:
            if case.outcome == "skipped":
                out["skipped"] += 1
            elif case.outcome == "flaky":
                out["flaky"] += 1
            elif _is_green(case):
                out["passed"] += 1
            else:
                out["failed"] += 1
        return out

    def to_dict(self) -> dict[str, Any]:
        reason_counts: dict[str, int] = {}
        for item in self.findings:
            reason_counts[item.code] = reason_counts.get(item.code, 0) + 1
        return {
            "schema_version": GATE_SCHEMA,
            "gate_version": GATE_VERSION,
            "evaluated_at": self.evaluated_at,
            "verdict": self.verdict.value,
            "exit_code": self.exit_code,
            "counts": self.counts(),
            "reason_counts": dict(sorted(reason_counts.items())),
            "findings": [item.to_dict() for item in self.findings],
            "report": self.report_facts,
            "baseline": self.baseline,
            "inputs": self.inputs,
        }


def evaluate(
    cases: Sequence[E2ECase],
    report_facts: dict[str, Any],
    *,
    baseline_cases: Sequence[E2ECase] | None = None,
    baseline_facts: dict[str, Any] | None = None,
    patch_text: str | None = None,
    allowed_paths: Sequence[str] = DEFAULT_ALLOWED_PATHS,
    require_trace_on_failure: bool = True,
    inputs: dict[str, Any] | None = None,
    evaluated_at: str | None = None,
) -> GateResult:
    findings: list[Finding] = []

    if not any(_is_executed(case) for case in cases):
        findings.append(_finding(EVIDENCE_EMPTY, "报告中没有执行过的用例，不能当作通过"))
    if report_facts.get("top_level_error_count"):
        findings.append(_finding(
            REPORT_ERRORS, f"报告有 {report_facts['top_level_error_count']} 个顶层错误（配置或全局 setup 失败）"
        ))

    base = {c.case_id: c for c in baseline_cases} if baseline_cases is not None else None
    baseline_summary: dict[str, Any] | None = None
    if base is not None and baseline_facts is not None:
        if set(baseline_facts.get("projects") or []) != set(report_facts.get("projects") or []):
            findings.append(_finding(
                BASELINE_INCOMPARABLE,
                f"project 集合不同：基线 {baseline_facts.get('projects')}，本次 {report_facts.get('projects')}",
            ))
        current_ids = {c.case_id for c in cases}
        removed = sorted(set(base) - current_ids)
        for case_id in removed:
            findings.append(_finding(TEST_REMOVED, "基线中存在的用例本次消失", case_id=case_id))
        baseline_summary = {
            "case_count": len(base),
            "removed": removed,
            "added": sorted(current_ids - set(base)),
            "fixed": sorted(
                c.case_id for c in cases
                if c.case_id in base and _is_green(c) and not _is_green(base[c.case_id])
                and _is_executed(base[c.case_id])
            ),
        }

    for case in cases:
        prior = base.get(case.case_id) if base is not None else None
        if case.expected_status == "failed":
            findings.append(_finding(
                EXPECTED_FAILURE_MARKED, "用例被标记为预期失败（test.fail），失败被计为符合预期",
                case_id=case.case_id,
            ))
        if case.outcome == "unexpected":
            if prior is None:
                code = UNEXPECTED_FAILURE
            elif _is_green(prior):
                code = NEW_FAILURE
            else:
                code = PERSISTENT_FAILURE
            findings.append(_finding(
                code, f"最终状态 {case.final_status}（{case.failure_kind or 'UNKNOWN'}），共尝试 {case.attempts} 次",
                case_id=case.case_id,
            ))
            if require_trace_on_failure and not case.has_trace:
                findings.append(_finding(
                    TRACE_MISSING, "失败用例未附 trace，无法复核根因", case_id=case.case_id,
                ))
        elif case.outcome == "flaky":
            findings.append(_finding(
                FLAKY, f"第 {case.attempts} 次尝试才通过", case_id=case.case_id,
            ))
        elif case.outcome == "skipped" and prior is not None and _is_executed(prior):
            findings.append(_finding(SKIP_ADDED, "基线中执行的用例本次被跳过", case_id=case.case_id))

    if patch_text:
        findings.extend(attribute_findings(inspect_patch(patch_text, allowed_paths), cases))

    verdict = Verdict.PASS
    for item in findings:
        if item.severity.rank > verdict.rank:
            verdict = item.severity

    return GateResult(
        verdict=verdict,
        findings=findings,
        cases=list(cases),
        report_facts=report_facts,
        baseline=baseline_summary,
        inputs=inputs or {},
        evaluated_at=evaluated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def run_gate(
    report: str | Path,
    *,
    baseline: str | Path | None = None,
    patch: str | Path | None = None,
    allowed_paths: Sequence[str] = DEFAULT_ALLOWED_PATHS,
    require_trace_on_failure: bool = True,
    evaluated_at: str | None = None,
) -> GateResult:
    """文件入口：读报告 / 基线 / diff → 判定。输入文件只记录 sha256，不记录路径。"""
    cases, facts, digest = load_playwright_report(report)
    inputs: dict[str, Any] = {"report_sha256": digest}
    baseline_cases = baseline_facts = None
    if baseline is not None:
        baseline_cases, baseline_facts, inputs["baseline_sha256"] = load_playwright_report(baseline)
    patch_text = None
    if patch is not None:
        try:
            raw = Path(patch).read_bytes()
            patch_text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise GateInputError(f"diff 不可读：{patch}（{exc}）") from exc
        inputs["patch_sha256"] = hashlib.sha256(raw).hexdigest()
    return evaluate(
        cases, facts,
        baseline_cases=baseline_cases, baseline_facts=baseline_facts,
        patch_text=patch_text, allowed_paths=allowed_paths,
        require_trace_on_failure=require_trace_on_failure,
        inputs=inputs, evaluated_at=evaluated_at,
    )


# ════════════════════════════════════════════════════════════════
#  5. 投影为 AIQE 结果契约（进入看板）
# ════════════════════════════════════════════════════════════════

_ERROR_CODES = {"TIMEOUT": "E2E_TIMEOUT", "INTERRUPTED": "E2E_INTERRUPTED", "RUNTIME": "E2E_RUNTIME_ERROR"}


def to_result_document(
    result: GateResult,
    *,
    run_id: str,
    suite_id: str = "e2e-suite",
    suite_version: str | None = None,
    sut_id: str = "sut",
    data_classification: DataClassification = DataClassification.INTERNAL,
    notes: str = "",
) -> dict[str, Any]:
    """把门禁结果投影为 aiqe.result 文档（source_type=local_test）。

    映射规则（与 contract.CaseStatus 对齐）：
      expected + passed        → judge.passed=true
      flaky                    → judge.passed=true，checks.flaky=true
      unexpected + ASSERTION   → judge.passed=false（产品/断言失败）
      unexpected + 其它        → execution.error=受控码（执行异常）
      skipped / test.fail 标记 → judge.passed=null（未作为通过计入）
      被 BLOCK 级 diff 发现归属的用例 → judge.passed=null（通过不可信）
    消息正文、stdout、附件路径一律不进入文档。
    """
    case_codes: dict[str, list[str]] = {}
    untrusted: set[str] = set()   # 通过是靠被削弱的测试拿到的
    for item in result.findings:
        for case_id in ((item.case_id,) if item.case_id else ()) + item.attributed_cases:
            case_codes.setdefault(case_id, []).append(item.code)
            if item.attributed_cases and item.severity is Verdict.BLOCK:
                untrusted.add(case_id)

    cases: list[dict[str, Any]] = []
    for case in result.cases:
        error = None
        passed: bool | None
        if case.outcome == "skipped" or case.expected_status != "passed":
            passed = None
        elif case.case_id in untrusted:
            passed = None   # 测试本身被削弱：「通过」不可信，按未判定计
        elif case.outcome == "unexpected":
            if case.failure_kind in _ERROR_CODES:
                error, passed = _ERROR_CODES[case.failure_kind], None
            else:
                passed = False
        else:
            passed = True
        cases.append({
            "case_id": case.case_id,
            "category": case.file,
            "execution": {
                "elapsed_sec": None if case.duration_ms is None else round(case.duration_ms / 1000, 3),
                "backend": "playwright",
                "model_id": sut_id,
                "error": error,
                "trace_id": hashlib.sha256(case.case_id.encode("utf-8")).hexdigest()[:16],
            },
            "judge": {
                "score": None,
                "passed": passed,
                "checks": {
                    "flaky": case.outcome == "flaky",
                    "trace_attached": case.has_trace,
                    "attempts": case.attempts,
                },
                "reasons": sorted(set(case_codes.get(case.case_id, []))),
            },
        })

    fingerprint = hashlib.sha256(
        "\n".join(sorted(c.case_id for c in result.cases)).encode("utf-8")
    ).hexdigest()[:12]
    document: dict[str, Any] = {
        "test_plan_id": suite_id,
        "generated_at": result.evaluated_at,
        "project": suite_id,
        "version": GATE_VERSION,
        "cases": cases,
        "summary": {
            "passed": sum(case["judge"]["passed"] is True for case in cases),
            "total": len(cases),
            "regressions": [f.case_id for f in result.findings if f.code == NEW_FAILURE],
        },
        "e2e_gate": {
            "verdict": result.verdict.value,
            "reason_counts": result.to_dict()["reason_counts"],
            "inputs": result.inputs,
        },
        "schema_version": SCHEMA_VERSION,
    }
    document["metadata"] = {
        "run_id": run_id,
        "created_at": result.evaluated_at,
        "dataset_id": suite_id,
        "dataset_version": suite_version or f"fp-{fingerprint}",
        "judge_id": "aiqe.e2e-gate",
        "judge_version": GATE_VERSION,
        "model_id": sut_id,
        "backend_id": "playwright",
        "source_type": SourceType.LOCAL_TEST.value,
        "data_classification": data_classification.value,
        "generator": GENERATOR,
        "generator_version": GATE_VERSION,
        "content_digest": compute_content_digest(document),
        "test_plan_id": suite_id,
        "notes": notes or f"E2E gate verdict {result.verdict.value}",
    }
    # 自检：产物必须能被同一份契约读回，否则不交付。
    validate_run(document, allowed_source_types={SourceType.LOCAL_TEST})
    return document


# ════════════════════════════════════════════════════════════════
#  6. Markdown 摘要（PR 评论 / CI Step Summary）
# ════════════════════════════════════════════════════════════════

_ICON = {"PASS": "✅", "ESCALATE": "🟡", "BLOCK": "⛔"}


def to_markdown(result: GateResult) -> str:
    counts = result.counts()
    lines = [
        f"## {_ICON[result.verdict.value]} AIQE E2E Gate: **{result.verdict.value}**",
        "",
        f"Playwright 结果（{counts['total']} 个用例）：通过 {counts['passed']} · 失败 {counts['failed']} · "
        f"flaky {counts['flaky']} · 跳过 {counts['skipped']}",
        "",
    ]
    if result.baseline:
        b = result.baseline
        lines += [
            f"基线对比：修复 {len(b['fixed'])} · 新增用例 {len(b['added'])} · 消失用例 {len(b['removed'])}",
            "",
        ]
    if not result.findings:
        lines.append("没有风险信号。")
    else:
        lines += ["| 严重度 | 原因码 | 位置 | 说明 |", "|---|---|---|---|"]
        order = sorted(result.findings, key=lambda f: (-f.severity.rank, f.code, f.case_id or f.file or ""))
        for item in order:
            where = item.case_id or (f"{item.file}:{item.line}" if item.line else item.file) or "—"
            if item.attributed_cases:
                titles = sorted({c.split(" › ", 2)[-1] for c in item.attributed_cases})
                where += " → " + "; ".join(titles)
            where = where.replace("|", "\\|")
            lines.append(f"| {item.severity.value} | `{item.code}` | {where} | {item.message} |")
    lines += ["", f"<sub>{GATE_SCHEMA} · 确定性规则，不调用模型</sub>", ""]
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
#  7. 命令行
# ════════════════════════════════════════════════════════════════

def main(argv: Iterable[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m AIQE.e2e_gate",
        description="AIQE E2E 质量门禁：Playwright 报告 (+基线 +修复 diff) → PASS / ESCALATE / BLOCK",
    )
    parser.add_argument("--report", required=True, help="Playwright JSON 报告（--reporter=json）")
    parser.add_argument("--baseline", help="基线 Playwright JSON 报告（上一次可信运行）")
    parser.add_argument("--patch", help="healer/人工修复的统一 diff（git diff 输出）")
    parser.add_argument("--allow-path", action="append", default=[], metavar="GLOB",
                        help="healer 允许改动的路径 glob，可重复；给出即替换默认集合")
    parser.add_argument("--no-trace-required", action="store_true",
                        help="失败用例不要求 trace 附件（默认要求）")
    parser.add_argument("--out", help="写出门禁判定 JSON")
    parser.add_argument("--markdown", help="写出 Markdown 摘要（如 $GITHUB_STEP_SUMMARY）")
    parser.add_argument("--result-out", help="同时写出 AIQE 结果契约文档（供看板读取）")
    parser.add_argument("--run-id", help="结果文档 run_id（默认取报告 sha256 前 12 位）")
    parser.add_argument("--suite-id", default="e2e-suite")
    parser.add_argument("--suite-version")
    parser.add_argument("--sut-id", default="sut", help="被测系统版本标识，如 commit 或构建号")
    parser.add_argument("--classification", default=DataClassification.INTERNAL.value,
                        choices=[item.value for item in DataClassification])
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        result = run_gate(
            args.report, baseline=args.baseline, patch=args.patch,
            allowed_paths=tuple(args.allow_path) or DEFAULT_ALLOWED_PATHS,
            require_trace_on_failure=not args.no_trace_required,
        )
    except GateInputError as exc:
        print(f"错误：{exc}")
        return 3

    markdown = to_markdown(result)
    if args.out:
        Path(args.out).write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.markdown:
        with open(args.markdown, "a", encoding="utf-8") as handle:
            handle.write(markdown)
    if args.result_out:
        document = to_result_document(
            result,
            run_id=args.run_id or f"e2e-{result.inputs['report_sha256'][:12]}",
            suite_id=args.suite_id, suite_version=args.suite_version, sut_id=args.sut_id,
            data_classification=DataClassification(args.classification),
        )
        Path(args.result_out).write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(markdown)
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
