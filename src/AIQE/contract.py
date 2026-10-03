# AIQE/contract.py —— 统一结果数据契约 v0.1
#
# 定位：在既有报告 JSON（EvaluationReport 产出）之上，加一层**验证与指标聚合**。
# 不替换、不重写既有数据模型——既有顶层字段（test_plan_id / generated_at /
# project / version / cases / summary）原样保留，本契约只做两件事：
#
#   ① 追加契约字段：schema_version / metadata / metrics
#   ② 在读取时**失败关闭**（fail-closed）地校验数据来源与结构
#
# 设计约束：
#   - 纯标准库（零第三方运行时依赖，与项目既有约束一致）
#   - 不修改任何既有公共 API 的行为（ExecutionRunner / OutputJudge /
#     RegressionAnalyzer / EvaluationReport 全部不动）
#   - 缺失值一律表示为 null + status，**绝不填 0**
#
# 信任边界（重要，详见 docs/architecture/AIQE_RESULT_CONTRACT_V01.md）：
#   本模块能验证「文档结构合法」与「文档由受信生成入口产出」，
#   **不能**证明文档底层数据在语义上真的是合成数据。
#   source_type 是**声明**，content_digest 是**防篡改证据**，
#   二者都不构成「数据来源真实可信」的证明。

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

# ════════════════════════════════════════════════════════════════
#  1. 版本常量
# ════════════════════════════════════════════════════════════════

SCHEMA_VERSION = "aiqe.result/0.1.0"
METRICS_VERSION = "aiqe.metrics/0.1.0"

#: 本模块声明支持的 schema 主版本。主版本不同 → 不兼容 → 拒绝读取。
SUPPORTED_SCHEMA_MAJOR = 0


class ContractViolation(Exception):
    """契约校验失败。

    【为什么是异常而不是返回值？】
      读取失败必须是**显式失败**。若返回 None 或空对象，调用方很容易
      把「数据损坏」当成「没有数据」，从而在 Dashboard 上显示成
      「零回归」——这是本契约要杜绝的最危险误读。
      因此校验失败一律抛异常，并携带结构化 reason_code。

    reason_code : 稳定的机器可读原因码（见 REASON_* 常量）
    detail      : 人工可读的补充说明
    path        : 出错字段的 JSON 路径（如 "metadata.run_id"）
    """

    def __init__(self, reason_code: str, detail: str = "", path: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        self.path = path
        msg = f"[{reason_code}]"
        if path:
            msg += f" at {path}"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


# ── 稳定原因码（测试与 Dashboard 依赖这些字符串）──────────────
REASON_DOCUMENT_NOT_OBJECT = "DOCUMENT_NOT_OBJECT"
REASON_REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
REASON_INVALID_TYPE = "INVALID_TYPE"
REASON_INVALID_ENUM_VALUE = "INVALID_ENUM_VALUE"
REASON_DUPLICATE_CASE_ID = "DUPLICATE_CASE_ID"
REASON_TIMESTAMP_MALFORMED = "TIMESTAMP_MALFORMED"
REASON_SCHEMA_VERSION_MISSING = "SCHEMA_VERSION_MISSING"
REASON_SCHEMA_VERSION_MALFORMED = "SCHEMA_VERSION_MALFORMED"
REASON_SCHEMA_VERSION_INCOMPATIBLE = "SCHEMA_VERSION_INCOMPATIBLE"
REASON_SOURCE_TYPE_NOT_ALLOWED = "SOURCE_TYPE_NOT_ALLOWED"
REASON_SYNTHETIC_GENERATOR_UNTRUSTED = "SYNTHETIC_GENERATOR_UNTRUSTED"
REASON_SYNTHETIC_DIGEST_MISSING = "SYNTHETIC_DIGEST_MISSING"
REASON_SYNTHETIC_DIGEST_MISMATCH = "SYNTHETIC_DIGEST_MISMATCH"
REASON_SENSITIVE_FIELD_DETECTED = "SENSITIVE_FIELD_DETECTED"
REASON_SENSITIVE_VALUE_DETECTED = "SENSITIVE_VALUE_DETECTED"
REASON_FILE_NOT_FOUND = "FILE_NOT_FOUND"
REASON_FILE_UNREADABLE = "FILE_UNREADABLE"
REASON_FILE_NOT_JSON = "FILE_NOT_JSON"


# ════════════════════════════════════════════════════════════════
#  2. 枚举：来源 / 敏感级别 / 状态
# ════════════════════════════════════════════════════════════════

class SourceType(str, Enum):
    """数据来源标记。

    synthetic     : 本地显式生成的合成样本（本轮唯一允许的来源）
    local_test    : 本地测试运行产生的数据（非合成，非生产）
    local_import  : 经独立文件契约导入的外部数据（本轮**未授权**）
    """
    SYNTHETIC = "synthetic"
    LOCAL_TEST = "local_test"
    LOCAL_IMPORT = "local_import"


class DataClassification(str, Enum):
    """数据敏感级别。"""
    PUBLIC_SYNTHETIC = "public_synthetic"   # 合成数据，可入库
    INTERNAL = "internal"                   # 内部数据，不入 Git
    PERSONAL = "personal"                   # 个人数据，禁止入库
    RESTRICTED = "restricted"               # 最高级别，禁止入库


class CaseStatus(str, Enum):
    """单个用例的结果状态。

    【为什么没有 TIMEOUT？】
      AIQE 目前无法可靠区分超时与其他执行异常——ExecutionRunner 把所有
      非 RuntimeError 异常压平成自由文本（见 docs/architecture/
      AIQE_METRICS_V01.md §3.4）。把 timeout 列为状态会造成「有分类」的
      假象。超时用例的状态是 ERROR，其 error 文本可能提及 timeout，
      但契约层不据此推断分类。
    """
    PASSED = "passed"     # 执行成功 且 judge 通过
    FAILED = "failed"     # 执行成功 但 judge 不通过
    ERROR = "error"       # 执行失败（error 非 null）
    SKIPPED = "skipped"   # 未执行


class MetricStatus(str, Enum):
    """指标记录状态。缺失原因必须显式区分，不得一律归为「无数据」。"""
    OK = "ok"                       # 有值且有效
    MISSING = "missing"             # 期望的输入字段不存在
    NO_DATA = "no_data"             # 分母为空，比例无定义
    NO_BASELINE = "no_baseline"     # 无基线可比（regression 状态为 new）
    NOT_APPLICABLE = "not_applicable"  # 该指标对此类别不适用
    UNDEFINED = "undefined"         # 无可靠测量方法
    UNAVAILABLE = "unavailable"     # 数据源不存在
    PARTIAL = "partial"             # 部分输入缺失，值基于不完整数据


class MetricPrecision(str, Enum):
    """数值精度来源。禁止把估算值与实测值混在同一比较中。"""
    MEASURED = "measured"              # 真实测量
    ESTIMATED = "estimated"            # 由字符数等启发式估算
    NOT_APPLICABLE = "not_applicable"  # 无值


#: 本轮允许的 source_type 集合。**只允许 synthetic。**
#: 放宽此集合需要用户明确授权（真实数据接入门禁 G1–G6 全绿）。
ALLOWED_SOURCE_TYPES: frozenset[SourceType] = frozenset({SourceType.SYNTHETIC})

#: 受信的合成数据生成入口白名单。
#: 只有从这里列出的生成器产出的文档才允许声明 source_type="synthetic"。
TRUSTED_SYNTHETIC_GENERATORS: frozenset[str] = frozenset({"aiqe.synthetic/0.1.0"})


# ════════════════════════════════════════════════════════════════
#  3. 敏感字段默认拒绝策略
# ════════════════════════════════════════════════════════════════
#
# 【这是纵深防御，不是主控制】
#   对未来的本地数据导入路径，主控制是字段**白名单**（默认拒绝），
#   见 docs/architecture/AIQE_MYFRI_IMPORT_CONTRACT_DRAFT.md。
#   本处的键名/取值扫描是**第二道**检查，用于在合成数据管道里
#   兜住「不小心把真实数据混进来」的情况。
#
# 【为什么不只用黑名单？】
#   黑名单永远不完备——新增一种敏感字段类型就漏一次。
#   因此黑名单只作为兜底，不作为唯一安全措施。
#
# 【为什么不能用「包含 token」这类宽松匹配？】
#   合法报告里有 tokens_generated / max_tokens / tokens_per_second，
#   宽松子串匹配会把每一份正常报告都误判为敏感。
#   因此采用**归一化后的精确匹配 + 明确后缀**。

#: 归一化（小写、去除非字母数字）后精确匹配即判定为敏感
_SENSITIVE_KEYS_EXACT: frozenset[str] = frozenset({
    "apikey", "accesskey", "secretkey", "privatekey", "secret", "password",
    "passwd", "pwd", "credential", "credentials", "accesstoken",
    "authtoken", "refreshtoken", "bearertoken", "sessiontoken", "authtoken",
    "useremail", "emailaddress", "phone", "phonenumber", "mobile",
    "idcard", "idnumber", "nationalid", "ssn", "passport",
    "homeaddress", "streetaddress", "realname", "birthdate",
    "chatlog", "chatlogs", "rawprompt", "rawchat", "conversationlog",
    "memorydb", "memorystore", "userprofile",
})

#: 归一化后以这些后缀结尾即判定为敏感（如 "openai_api_key" → "...apikey"）
_SENSITIVE_KEY_SUFFIXES: tuple[str, ...] = (
    "apikey", "secretkey", "privatekey", "accesstoken", "authtoken",
    "password", "passwd", "credential", "credentials",
)

#: 取值模式（仅扫描字符串值）
_SENSITIVE_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("cn_mobile", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("cn_id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("pem_private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

#: 扫描时跳过的键（这些是框架自身的合法字段，不参与敏感判定）
_SENSITIVE_SCAN_SKIP_KEYS: frozenset[str] = frozenset({"content_digest"})


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _is_sensitive_key(key: str) -> bool:
    norm = _normalize_key(key)
    if norm in _SENSITIVE_KEYS_EXACT:
        return True
    return any(norm.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


def scan_sensitive(node: Any, path: str = "$") -> None:
    """递归扫描文档，命中敏感字段/取值则抛 ContractViolation（失败关闭）。

    【失败关闭语义】命中即拒绝整份文档，**不做自动脱敏**。
    自动删除敏感字段后继续处理，会让人误以为「处理过了所以安全」，
    而实际上我们既没有证据证明删干净了，也没有证据证明剩余部分是合成数据。
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SENSITIVE_SCAN_SKIP_KEYS:
                continue
            child_path = f"{path}.{key}"
            if _is_sensitive_key(key):
                raise ContractViolation(
                    REASON_SENSITIVE_FIELD_DETECTED,
                    f"字段名 '{key}' 命中敏感字段拒绝名单；"
                    f"本契约不做自动脱敏，请从数据源头移除该字段",
                    child_path,
                )
            scan_sensitive(value, child_path)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            scan_sensitive(item, f"{path}[{index}]")
    elif isinstance(node, str):
        for label, pattern in _SENSITIVE_VALUE_PATTERNS:
            if pattern.search(node):
                raise ContractViolation(
                    REASON_SENSITIVE_VALUE_DETECTED,
                    f"字符串取值命中敏感模式 '{label}'；"
                    f"本契约不做自动脱敏，请从数据源头移除该内容",
                    path,
                )


# ════════════════════════════════════════════════════════════════
#  4. 内容摘要（防篡改证据）
# ════════════════════════════════════════════════════════════════

def _canonical_json(payload: Any) -> str:
    """规范化 JSON 序列化：键排序 + 紧凑分隔符 + 不转义非 ASCII。

    这是摘要计算的唯一输入形式——保证同一逻辑内容恒得同一摘要。
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_content_digest(document: dict[str, Any]) -> str:
    """计算文档内容摘要（sha256 前 32 位 hex）。

    【覆盖范围】整个文档**除 metadata 之外**的全部内容。
      - 排除 metadata：否则摘要字段自身会造成自引用（鸡生蛋问题）
      - 包含 cases：用例数据是被绑定的主体

    【这是防篡改证据，不是真实性证明】
      摘要能证明「文档自生成后未被改动」，且「由掌握生成入口的一方产出」。
      它**不能**证明文档里的数据在语义上真的是合成数据——
      掌握生成入口的人可以把任何数据喂进去。
      真实数据接入的控制手段是**独立契约的字段白名单**与**授权门禁**，
      不是这个摘要。
    """
    projection = {k: v for k, v in document.items() if k != "metadata"}
    return hashlib.sha256(_canonical_json(projection).encode("utf-8")).hexdigest()[:32]


# ════════════════════════════════════════════════════════════════
#  5. 时间戳
# ════════════════════════════════════════════════════════════════

def parse_timestamp(value: Any, path: str) -> datetime:
    """解析 ISO8601 时间戳，要求**必须带时区**。

    【为什么拒绝无时区的时间戳？】
      naive datetime 无法确定绝对时刻，跨时区汇总趋势时会静默错位。
      宁可在读取时失败，也不要在 Dashboard 上展示错位的时间线。
      解析成功后统一转换为 UTC。
    """
    if not isinstance(value, str) or not value:
        raise ContractViolation(
            REASON_TIMESTAMP_MALFORMED,
            f"时间戳必须是非空字符串，实际为 {type(value).__name__}",
            path,
        )
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractViolation(
            REASON_TIMESTAMP_MALFORMED, f"无法解析 ISO8601 时间戳: {value!r} ({exc})", path
        ) from exc
    if parsed.tzinfo is None:
        raise ContractViolation(
            REASON_TIMESTAMP_MALFORMED,
            f"时间戳缺少时区信息: {value!r}；必须带 UTC 偏移（如 +00:00 或 Z）",
            path,
        )
    return parsed.astimezone(timezone.utc)


# ════════════════════════════════════════════════════════════════
#  6. 实体
# ════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EvaluationMetadata:
    """一次评估运行的元数据（评估条件）。

    这些字段是**回归可比性的判定依据**——缺少它们，两次运行的分数
    就没有共同基准，任何 delta 都不可信。
    """
    run_id: str
    created_at: str                 # ISO8601，必须带时区；规范化后为 UTC
    dataset_id: str
    dataset_version: str
    judge_id: str
    judge_version: str
    model_id: str
    backend_id: str
    source_type: SourceType
    data_classification: DataClassification
    generator: str = ""             # source_type=synthetic 时必填
    generator_version: str = ""
    content_digest: str = ""        # source_type=synthetic 时必填
    test_plan_id: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "judge_id": self.judge_id,
            "judge_version": self.judge_version,
            "model_id": self.model_id,
            "backend_id": self.backend_id,
            "source_type": self.source_type.value,
            "data_classification": self.data_classification.value,
            "generator": self.generator,
            "generator_version": self.generator_version,
            "content_digest": self.content_digest,
            "test_plan_id": self.test_plan_id,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class MetricRecord:
    """单条指标记录。

    【核心不变式】metric_value 为 None ⟺ status 不为 OK。
    缺失值永远是 None，**永远不是 0**。
    """
    metric_id: str
    metric_value: float | int | None
    metric_unit: str
    status: MetricStatus
    metric_version: str = METRICS_VERSION
    precision: MetricPrecision = MetricPrecision.MEASURED
    scope: str = "run"              # "run" | "case" | "category"
    case_id: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "metric_value": self.metric_value,
            "metric_unit": self.metric_unit,
            "status": self.status.value,
            "metric_version": self.metric_version,
            "precision": self.precision.value,
            "scope": self.scope,
            "case_id": self.case_id,
            "reason": self.reason,
        }


@dataclass
class CaseResult:
    """单个用例结果的**视图**。

    raw 保存原始 case 字典（含 execution / judge / regression 等既有字段），
    保证序列化回写时不丢字段。归一化属性只是方便读取，不是第二套数据模型。
    """
    raw: dict[str, Any]

    @property
    def case_id(self) -> str:
        return self.raw["case_id"]

    @property
    def category(self) -> str:
        return self.raw.get("category", "")

    @property
    def error(self) -> str | None:
        return self.raw.get("execution", {}).get("error")

    @property
    def execution_ok(self) -> bool:
        return self.error is None

    @property
    def score(self) -> float | None:
        value = self.raw.get("judge", {}).get("score")
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @property
    def passed(self) -> bool | None:
        value = self.raw.get("judge", {}).get("passed")
        return value if isinstance(value, bool) else None

    @property
    def status(self) -> CaseStatus:
        if not self.execution_ok:
            return CaseStatus.ERROR
        if self.passed is None:
            return CaseStatus.SKIPPED
        return CaseStatus.PASSED if self.passed else CaseStatus.FAILED

    @property
    def regression_status(self) -> str | None:
        return self.raw.get("regression", {}).get("status")


@dataclass
class EvaluationRun:
    """一次评估运行 = 既有报告文档 + 契约元数据 + 指标记录。"""
    metadata: EvaluationMetadata
    cases: list[CaseResult]
    metrics: list[MetricRecord] = field(default_factory=list)
    document: dict[str, Any] = field(default_factory=dict)

    @property
    def run_id(self) -> str:
        return self.metadata.run_id

    @property
    def dataset_key(self) -> tuple[str, str]:
        """回归可比性的最小数据集标识。"""
        return (self.metadata.dataset_id, self.metadata.dataset_version)

    @property
    def judge_key(self) -> tuple[str, str]:
        """回归可比性的最小评分器标识。"""
        return (self.metadata.judge_id, self.metadata.judge_version)

    def metric(self, metric_id: str) -> MetricRecord | None:
        for record in self.metrics:
            if record.metric_id == metric_id and record.scope == "run":
                return record
        return None

    def to_dict(self) -> dict[str, Any]:
        """回写为完整文档（既有字段 + 契约字段）。"""
        document = dict(self.document)
        document["schema_version"] = SCHEMA_VERSION
        document["metadata"] = self.metadata.to_dict()
        document["metrics"] = [record.to_dict() for record in self.metrics]
        return document


# ════════════════════════════════════════════════════════════════
#  7. 校验
# ════════════════════════════════════════════════════════════════

_SCHEMA_RE = re.compile(r"^([A-Za-z0-9_.-]+)/(\d+)\.(\d+)\.(\d+)$")

#: metadata 中必填的字符串字段
_REQUIRED_METADATA_STRINGS = (
    "run_id", "created_at", "dataset_id", "dataset_version",
    "judge_id", "judge_version", "model_id", "backend_id",
)


def _require_non_empty_str(node: dict[str, Any], key: str, path: str) -> str:
    value = node.get(key)
    if value is None:
        raise ContractViolation(
            REASON_REQUIRED_FIELD_MISSING, f"缺少必填字段 '{key}'", f"{path}.{key}"
        )
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(
            REASON_INVALID_TYPE,
            f"字段 '{key}' 必须是非空字符串，实际为 {type(value).__name__}={value!r}",
            f"{path}.{key}",
        )
    return value.strip()


def _parse_schema_version(raw: Any) -> tuple[int, int, int]:
    if raw is None:
        raise ContractViolation(
            REASON_SCHEMA_VERSION_MISSING,
            "文档缺少 schema_version；无法判断结构兼容性，拒绝读取",
            "schema_version",
        )
    if not isinstance(raw, str):
        raise ContractViolation(
            REASON_SCHEMA_VERSION_MALFORMED,
            f"schema_version 必须是字符串，实际为 {type(raw).__name__}",
            "schema_version",
        )
    match = _SCHEMA_RE.match(raw.strip())
    if not match:
        raise ContractViolation(
            REASON_SCHEMA_VERSION_MALFORMED,
            f"schema_version 格式非法: {raw!r}；期望 '<name>/MAJOR.MINOR.PATCH'",
            "schema_version",
        )
    return int(match.group(2)), int(match.group(3)), int(match.group(4))


def _validate_case(raw_case: Any, index: int, seen_ids: set[str]) -> CaseResult:
    path = f"cases[{index}]"
    if not isinstance(raw_case, dict):
        raise ContractViolation(
            REASON_INVALID_TYPE, f"用例必须是对象，实际为 {type(raw_case).__name__}", path
        )
    case_id = _require_non_empty_str(raw_case, "case_id", path)
    if case_id in seen_ids:
        raise ContractViolation(
            REASON_DUPLICATE_CASE_ID, f"case_id '{case_id}' 在同一运行内重复", f"{path}.case_id"
        )
    seen_ids.add(case_id)

    # category 允许为空字符串，但类型必须是字符串
    category = raw_case.get("category", "")
    if not isinstance(category, str):
        raise ContractViolation(
            REASON_INVALID_TYPE,
            f"category 必须是字符串，实际为 {type(category).__name__}",
            f"{path}.category",
        )

    # execution 若存在，必须是对象，且 error 必须是 str | None
    execution = raw_case.get("execution")
    if execution is not None:
        if not isinstance(execution, dict):
            raise ContractViolation(
                REASON_INVALID_TYPE,
                f"execution 必须是对象，实际为 {type(execution).__name__}",
                f"{path}.execution",
            )
        error = execution.get("error")
        if error is not None and not isinstance(error, str):
            raise ContractViolation(
                REASON_INVALID_TYPE,
                f"execution.error 必须是字符串或 null，实际为 {type(error).__name__}",
                f"{path}.execution.error",
            )

    # judge.score / judge.passed 若存在，类型必须正确（Case F：指标非法类型）
    judge = raw_case.get("judge")
    if judge is not None:
        if not isinstance(judge, dict):
            raise ContractViolation(
                REASON_INVALID_TYPE,
                f"judge 必须是对象，实际为 {type(judge).__name__}",
                f"{path}.judge",
            )
        if "score" in judge and judge["score"] is not None:
            score = judge["score"]
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ContractViolation(
                    REASON_INVALID_TYPE,
                    f"judge.score 必须是数值或 null，实际为 {type(score).__name__}={score!r}",
                    f"{path}.judge.score",
                )
        if "passed" in judge and judge["passed"] is not None:
            if not isinstance(judge["passed"], bool):
                raise ContractViolation(
                    REASON_INVALID_TYPE,
                    f"judge.passed 必须是布尔或 null，实际为 {type(judge['passed']).__name__}",
                    f"{path}.judge.passed",
                )

    return CaseResult(raw=raw_case)


def validate_run(
    document: Any,
    *,
    allowed_source_types: Iterable[SourceType] = ALLOWED_SOURCE_TYPES,
    require_synthetic_provenance: bool = True,
) -> EvaluationRun:
    """校验并解析一份结果契约文档。失败一律抛 ContractViolation。

    【校验顺序】（顺序有意设计——先便宜的后安全）
      1. 文档是对象
      2. schema_version 存在、格式合法、主版本兼容
      3. 敏感字段/取值扫描（默认拒绝）
      4. metadata 必填字段与枚举
      5. 合成数据来源证明（生成器白名单 + 内容摘要）
      6. 用例列表结构、case_id 唯一性、字段类型

    【为什么敏感扫描在来源证明之前？】
      敏感扫描是最强的拒绝条件，且与来源无关。先做它，可以保证
      即使一份文档伪造了来源标记，只要含敏感数据就必定被拒——
      不依赖后续证明步骤是否正确执行。

    allowed_source_types        : 允许的来源集合（默认仅 synthetic）
    require_synthetic_provenance: synthetic 来源是否必须提供生成器白名单
                                  命中与内容摘要匹配（默认必须）
    """
    if not isinstance(document, dict):
        raise ContractViolation(
            REASON_DOCUMENT_NOT_OBJECT,
            f"结果文档必须是 JSON 对象，实际为 {type(document).__name__}",
            "$",
        )

    # ── 2. schema 版本 ────────────────────────────────────────
    major, _minor, _patch = _parse_schema_version(document.get("schema_version"))
    if major != SUPPORTED_SCHEMA_MAJOR:
        raise ContractViolation(
            REASON_SCHEMA_VERSION_INCOMPATIBLE,
            f"文档 schema 主版本 {major} 与本读取器支持的主版本 "
            f"{SUPPORTED_SCHEMA_MAJOR} 不兼容；拒绝读取（不做字段猜测）",
            "schema_version",
        )

    # ── 3. 敏感数据扫描（失败关闭）──────────────────────────
    scan_sensitive(document)

    # ── 4. metadata ──────────────────────────────────────────
    raw_metadata = document.get("metadata")
    if raw_metadata is None:
        raise ContractViolation(
            REASON_REQUIRED_FIELD_MISSING, "文档缺少 metadata 块", "metadata"
        )
    if not isinstance(raw_metadata, dict):
        raise ContractViolation(
            REASON_INVALID_TYPE,
            f"metadata 必须是对象，实际为 {type(raw_metadata).__name__}",
            "metadata",
        )

    for key in _REQUIRED_METADATA_STRINGS:
        _require_non_empty_str(raw_metadata, key, "metadata")

    created_at = parse_timestamp(raw_metadata["created_at"], "metadata.created_at")

    raw_source = raw_metadata.get("source_type")
    try:
        source_type = SourceType(raw_source)
    except ValueError as exc:
        raise ContractViolation(
            REASON_INVALID_ENUM_VALUE,
            f"source_type 取值非法: {raw_source!r}；合法值 "
            f"{[item.value for item in SourceType]}",
            "metadata.source_type",
        ) from exc

    raw_classification = raw_metadata.get("data_classification")
    try:
        data_classification = DataClassification(raw_classification)
    except ValueError as exc:
        raise ContractViolation(
            REASON_INVALID_ENUM_VALUE,
            f"data_classification 取值非法: {raw_classification!r}；合法值 "
            f"{[item.value for item in DataClassification]}",
            "metadata.data_classification",
        ) from exc

    allowed = frozenset(allowed_source_types)
    if source_type not in allowed:
        raise ContractViolation(
            REASON_SOURCE_TYPE_NOT_ALLOWED,
            f"source_type='{source_type.value}' 当前不被允许；本轮允许集合 = "
            f"{sorted(item.value for item in allowed)}。"
            f"接入真实数据需要独立授权（门禁 G1–G6），"
            f"不得通过修改 source_type 绕过。",
            "metadata.source_type",
        )

    # ── 5. 合成数据来源证明 ──────────────────────────────────
    generator = raw_metadata.get("generator") or ""
    generator_version = raw_metadata.get("generator_version") or ""
    content_digest = raw_metadata.get("content_digest") or ""

    if source_type is SourceType.SYNTHETIC and require_synthetic_provenance:
        if not isinstance(generator, str) or generator not in TRUSTED_SYNTHETIC_GENERATORS:
            raise ContractViolation(
                REASON_SYNTHETIC_GENERATOR_UNTRUSTED,
                f"source_type='synthetic' 但 generator={generator!r} 不在受信生成器"
                f"白名单 {sorted(TRUSTED_SYNTHETIC_GENERATORS)} 中。"
                f"仅声明 source_type 不足以证明数据来源——"
                f"伪造该标记不会被接受。",
                "metadata.generator",
            )
        if not isinstance(content_digest, str) or not content_digest:
            raise ContractViolation(
                REASON_SYNTHETIC_DIGEST_MISSING,
                "source_type='synthetic' 但缺少 content_digest；"
                "无法证明文档由受信生成入口产出",
                "metadata.content_digest",
            )
        expected = compute_content_digest(document)
        if content_digest != expected:
            raise ContractViolation(
                REASON_SYNTHETIC_DIGEST_MISMATCH,
                f"content_digest 不匹配（声明 {content_digest!r}，"
                f"实算 {expected!r}）；文档在生成后被改动，或来源声明系伪造",
                "metadata.content_digest",
            )

    metadata = EvaluationMetadata(
        run_id=raw_metadata["run_id"].strip(),
        created_at=created_at.isoformat(),
        dataset_id=raw_metadata["dataset_id"].strip(),
        dataset_version=raw_metadata["dataset_version"].strip(),
        judge_id=raw_metadata["judge_id"].strip(),
        judge_version=raw_metadata["judge_version"].strip(),
        model_id=raw_metadata["model_id"].strip(),
        backend_id=raw_metadata["backend_id"].strip(),
        source_type=source_type,
        data_classification=data_classification,
        generator=generator,
        generator_version=generator_version,
        content_digest=content_digest,
        test_plan_id=str(document.get("test_plan_id", "")),
        notes=str(raw_metadata.get("notes", "")),
    )

    # ── 6. cases ─────────────────────────────────────────────
    raw_cases = document.get("cases")
    if raw_cases is None:
        raise ContractViolation(
            REASON_REQUIRED_FIELD_MISSING, "文档缺少 cases 列表", "cases"
        )
    if not isinstance(raw_cases, list):
        raise ContractViolation(
            REASON_INVALID_TYPE,
            f"cases 必须是数组，实际为 {type(raw_cases).__name__}",
            "cases",
        )

    seen: set[str] = set()
    cases = [_validate_case(raw, index, seen) for index, raw in enumerate(raw_cases)]

    return EvaluationRun(metadata=metadata, cases=cases, document=document)


# ════════════════════════════════════════════════════════════════
#  8. 读取
# ════════════════════════════════════════════════════════════════

def load_run(path: str | Path, **kwargs: Any) -> EvaluationRun:
    """从文件读取并校验结果契约文档。

    【读取失败行为】文件不存在 / 不可读 / 非 JSON / 校验不通过
    ——全部抛 ContractViolation。**绝不返回空对象或 None**。
    调用方若想「没有文件就当作没有数据」，必须显式捕获
    REASON_FILE_NOT_FOUND，而不是依赖本函数静默降级。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise ContractViolation(
            REASON_FILE_NOT_FOUND, f"结果文件不存在: {file_path}", str(file_path)
        )
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractViolation(
            REASON_FILE_UNREADABLE, f"结果文件不可读: {exc}", str(file_path)
        ) from exc
    except UnicodeDecodeError as exc:
        # 二进制文件 / 编码不符。UnicodeDecodeError 是 ValueError 子类，
        # **不是** OSError，必须单独捕获——否则损坏文件会以未捕获异常逃逸，
        # 调用方就失去了「失败关闭」的保证。
        raise ContractViolation(
            REASON_FILE_UNREADABLE,
            f"结果文件不是 UTF-8 文本（可能是二进制或已损坏）: {exc}",
            str(file_path),
        ) from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractViolation(
            REASON_FILE_NOT_JSON, f"结果文件不是合法 JSON: {exc}", str(file_path)
        ) from exc
    return validate_run(document, **kwargs)


# ════════════════════════════════════════════════════════════════
#  9. 指标聚合
# ════════════════════════════════════════════════════════════════
#
# 规则来源：docs/architecture/AIQE_METRICS_V01.md
# 核心不变式：缺失 → metric_value=None + 明确 status；**绝不填 0**。

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _execution_failed(case: CaseResult) -> bool:
    """执行失败时，runner 会把 tokens/elapsed/tok_per_sec 硬编码为 0。

    这些 0 **不是测量结果**，是异常分支的占位值，必须置 null。
    """
    return not case.execution_ok


def compute_run_metrics(run: EvaluationRun) -> list[MetricRecord]:
    """计算 run 级指标记录（含不可计算指标的显式缺失记录）。"""
    records: list[MetricRecord] = []
    cases = run.cases
    total = len(cases)

    # ── P0: execution_success_rate ───────────────────────────
    if total == 0:
        records.append(MetricRecord(
            "execution_success_rate", None, "ratio", MetricStatus.NO_DATA,
            reason="用例集为空，比例无定义",
        ))
    else:
        ok = sum(1 for c in cases if c.execution_ok)
        records.append(MetricRecord(
            "execution_success_rate", round(ok / total, 6), "ratio", MetricStatus.OK,
        ))

    # ── P0: execution_error_count ────────────────────────────
    # 空集时合法为 0（「没有用例」是确定的测量结果，不是「没测到」）
    error_count = sum(1 for c in cases if _execution_failed(c))
    records.append(MetricRecord(
        "execution_error_count", error_count, "count", MetricStatus.OK,
    ))

    # ── P0: case_pass_rate ───────────────────────────────────
    if total == 0:
        records.append(MetricRecord(
            "case_pass_rate", None, "ratio", MetricStatus.NO_DATA,
            reason="用例集为空，比例无定义",
        ))
    else:
        judged = [c for c in cases if c.passed is not None]
        if not judged:
            records.append(MetricRecord(
                "case_pass_rate", None, "ratio", MetricStatus.MISSING,
                reason="所有用例均无 judge.passed 字段",
            ))
        else:
            passed = sum(1 for c in judged if c.passed)
            status = MetricStatus.OK if len(judged) == total else MetricStatus.PARTIAL
            records.append(MetricRecord(
                "case_pass_rate", round(passed / total, 6), "ratio", status,
                reason="" if status is MetricStatus.OK
                else f"{total - len(judged)}/{total} 个用例缺少 judge 结果，按不通过计入分母",
            ))

    # ── P0: regression_count / degraded_count ────────────────
    has_regression_block = any(c.regression_status is not None for c in cases)
    if not has_regression_block:
        records.append(MetricRecord(
            "regression_count", None, "count", MetricStatus.NO_BASELINE,
            reason="用例不含 regression 块（未提供基线）；"
                   "「无基线」与「有基线且无回归」语义不同，不得返回 0",
        ))
        records.append(MetricRecord(
            "degraded_count", None, "count", MetricStatus.NO_BASELINE,
            reason="用例不含 regression 块（未提供基线）",
        ))
    else:
        records.append(MetricRecord(
            "regression_count",
            sum(1 for c in cases if c.regression_status == "regression"),
            "count", MetricStatus.OK,
        ))
        records.append(MetricRecord(
            "degraded_count",
            sum(1 for c in cases if c.regression_status == "degraded"),
            "count", MetricStatus.OK,
        ))

    # ── P0: latency_ms ───────────────────────────────────────
    latencies: list[float] = []
    for case in cases:
        if _execution_failed(case):
            continue  # 失败用例 elapsed_sec 硬编码为 0.0，不是测量值
        elapsed = case.raw.get("execution", {}).get("elapsed_sec")
        if _is_number(elapsed):
            latencies.append(float(elapsed) * 1000.0)
    records.append(_percentile_record("latency_ms", latencies, "milliseconds",
                                      "p50", lambda v: v[len(v) // 2] if v else None))

    # ── P1: judge_score ──────────────────────────────────────
    scores = [c.score for c in cases if c.score is not None]
    if not scores:
        records.append(MetricRecord(
            "judge_score", None, "score", MetricStatus.MISSING,
            reason="无任何用例含数值型 judge.score",
        ))
    else:
        records.append(MetricRecord(
            "judge_score", round(sum(scores) / len(scores), 6), "score", MetricStatus.OK,
            reason="run 级均值为 case 级 judge.score 的算术平均",
        ))

    # ── P1: format_compliance ────────────────────────────────
    # 只对格式检查真正生效的类别聚合（chat/translation/edge_case 恒为 1.0，零信息量）
    FORMAT_AWARE = {"json_output", "coding_task"}
    fmt_values: list[float] = []
    fmt_missing = 0
    for case in cases:
        if case.category not in FORMAT_AWARE:
            continue
        value = case.raw.get("judge", {}).get("metrics", {}).get("format_score")
        if _is_number(value):
            fmt_values.append(float(value))
        elif case.passed is not None:
            # 空响应分支提前 return，不产出 format_score —— 是「缺失」不是 0
            fmt_missing += 1
    if not fmt_values and fmt_missing == 0:
        records.append(MetricRecord(
            "format_compliance", None, "ratio", MetricStatus.NOT_APPLICABLE,
            reason="本次运行不含 json_output / coding_task 类别用例；"
                   "其他类别的 format_score 恒为 1.0，无信息量",
        ))
    elif not fmt_values:
        records.append(MetricRecord(
            "format_compliance", None, "ratio", MetricStatus.MISSING,
            reason=f"{fmt_missing} 个格式相关用例均缺少 format_score（空响应分支不产出该字段）",
        ))
    else:
        status = MetricStatus.OK if fmt_missing == 0 else MetricStatus.PARTIAL
        records.append(MetricRecord(
            "format_compliance", round(sum(fmt_values) / len(fmt_values), 6), "ratio",
            status,
            reason="" if status is MetricStatus.OK
            else f"{fmt_missing} 个格式相关用例缺少 format_score，未计入分子",
        ))

    # ── P1: baseline_delta ───────────────────────────────────
    deltas = [
        c.raw["regression"]["delta"] for c in cases
        if c.regression_status not in (None, "new")
        and _is_number(c.raw.get("regression", {}).get("delta"))
    ]
    if not deltas:
        records.append(MetricRecord(
            "baseline_delta", None, "score_delta", MetricStatus.NO_BASELINE,
            reason="无可比基线（全部用例 regression 状态为 new 或无 regression 块）；"
                   "new 状态携带的 delta=0.0 是占位值，不是「无变化」",
        ))
    else:
        records.append(MetricRecord(
            "baseline_delta", round(sum(deltas) / len(deltas), 6), "score_delta",
            MetricStatus.OK,
            reason="run 级均值为 case 级 delta 的算术平均（已排除 new 状态的占位 0.0）",
        ))

    # ── P2: output_tokens / tokens_per_second ────────────────
    tokens: list[float] = []
    tps: list[float] = []
    for case in cases:
        if _execution_failed(case):
            continue
        execution = case.raw.get("execution", {})
        if _is_number(execution.get("tokens_generated")):
            tokens.append(float(execution["tokens_generated"]))
        if _is_number(execution.get("tok_per_sec")):
            tps.append(float(execution["tok_per_sec"]))

    precision = _token_precision(run)
    records.append(MetricRecord(
        "output_tokens",
        int(sum(tokens)) if tokens else None,
        "tokens",
        MetricStatus.OK if tokens else MetricStatus.MISSING,
        precision=precision,
        reason="" if tokens else "无可用 output token 数据",
    ))
    records.append(MetricRecord(
        "tokens_per_second",
        round(sum(tps) / len(tps), 6) if tps else None,
        "tokens/second",
        MetricStatus.OK if tps else MetricStatus.MISSING,
        precision=precision,
        reason="" if tps else "无可用生成速度数据",
    ))

    # ── 不可计算指标：显式产出缺失记录（不产出数值）─────────
    records.append(MetricRecord(
        "timeout_count", None, "count", MetricStatus.UNDEFINED,
        reason="ExecutionRunner 将所有非 RuntimeError 异常压平为自由文本，"
               "无结构化超时分类；字符串匹配不可靠，故不产出数值",
    ))
    records.append(MetricRecord(
        "judge_agreement", None, "ratio", MetricStatus.UNDEFINED,
        reason="系统只有一个确定性评分器，无第二个判定源；对自身求一致性恒为 1.0，无信息量",
    ))
    records.append(MetricRecord(
        "severity_distribution", None, "distribution", MetricStatus.UNDEFINED,
        reason="全仓库无 severity 字段；将 judge.checks 硬映射为严重度属主观赋权，需领域决策",
    ))
    records.append(MetricRecord(
        "input_tokens", None, "tokens", MetricStatus.UNAVAILABLE,
        reason="数据模型中无输入 token 字段（tokens_generated 指输出）；"
               "OllamaRunner 未采集 prompt_eval_count",
    ))
    records.append(MetricRecord(
        "estimated_cost", None, "currency", MetricStatus.UNAVAILABLE,
        reason="无价格表；AIQE 定位为本地推理评估，不适用按量计费；"
               "且 input_tokens 尚不可用",
    ))

    return records


def _percentile_record(
    metric_id: str, values: list[float], unit: str, label: str, picker: Any
) -> MetricRecord:
    if not values:
        return MetricRecord(
            metric_id, None, unit, MetricStatus.MISSING,
            reason="无可用时延数据（执行失败用例的 elapsed_sec=0.0 是占位值，已排除）",
        )
    ordered = sorted(values)
    return MetricRecord(
        metric_id, round(float(picker(ordered)), 6), unit, MetricStatus.OK,
        reason=f"{label}（共 {len(ordered)} 个有效样本；失败用例已排除）",
    )


def _token_precision(run: EvaluationRun) -> MetricPrecision:
    """判断 token 类指标的精度来源。

    mock / 默认 generate_sync 路径用字符数估算 token 数，
    只有真实后端自报 eval_count 时才是 measured。
    禁止把估算值与实测值混在同一比较中。
    """
    backends = {c.raw.get("execution", {}).get("backend") for c in run.cases}
    if backends and backends <= {"mlx", "mock"}:
        return MetricPrecision.ESTIMATED
    return MetricPrecision.MEASURED


def build_run(
    document: dict[str, Any],
    *,
    allowed_source_types: Iterable[SourceType] = ALLOWED_SOURCE_TYPES,
    require_synthetic_provenance: bool = True,
) -> EvaluationRun:
    """校验文档并附加 run 级指标记录。"""
    run = validate_run(
        document,
        allowed_source_types=allowed_source_types,
        require_synthetic_provenance=require_synthetic_provenance,
    )
    run.metrics = compute_run_metrics(run)
    return run
