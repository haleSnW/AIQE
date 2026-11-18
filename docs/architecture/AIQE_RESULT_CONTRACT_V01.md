# AIQE 统一结果数据契约 v0.1

> **实现位置**：[`src/AIQE/contract.py`](../../src/AIQE/contract.py)（契约与指标）、
> [`src/AIQE/comparison.py`](../../src/AIQE/comparison.py)（运行级对比）
> **测试**：[`tests/test_contract.py`](../../tests/test_contract.py)（121 个新增测试中的主体）
> **日期**：2026-09-22
> **schema_version**：`aiqe.result/0.1.0`

---

## 1. 设计目标与复用原则

### 1.1 目标数据流

```
ExecutionRunner → Result Contract → Reporter（既有）
                       ↓
                 RegressionAnalyzer（既有，case 级）
                       ↓
                 comparison.compare_runs（新增，run 级）
                       ↓
                 Future Dashboard
```

### 1.2 复用原则（关键设计决定）

**没有建立新的数据模型。** 契约是**既有报告 JSON 之上的一层**：

| 既有顶层字段 | 处理方式 |
|---|---|
| `test_plan_id` / `generated_at` / `project` / `version` | **原样保留**，契约不改写 |
| `cases[].case_id` / `category` / `prompt` | **原样保留** |
| `cases[].execution.*` | **原样保留**（response / tokens_generated / elapsed_sec / tok_per_sec / backend / model_id / error / trace_id / payload_hash） |
| `cases[].judge.*` | **原样保留**（score / passed / breakdown / checks / reasons / metrics） |
| `cases[].regression.*` | **原样保留**（case_id / status / delta / baseline_score / current_score） |
| `summary` | **原样保留**（含其既有的 `regression`+`degraded` 合并口径） |

契约**只追加**三个字段：

| 新增字段 | 作用 |
|---|---|
| `schema_version` | 结构版本标识（`"aiqe.result/0.1.0"`） |
| `metadata` | 评估条件（run_id / 数据集 / 评分器 / 模型 / 来源 / 敏感级别 / 摘要） |
| `metrics` | 结构化指标记录数组 |

**这样设计的好处**：既有的 `RegressionAnalyzer._load_baseline()` 按
`cases[].judge.score` 取值并**忽略未知字段**，因此一份契约文档可以直接
当作它认识的基线文件使用——零改动兼容（见 `src/AIQE/regression.py:139-141`）。

**代价（明确记录）**：文档中同时存在 `summary.regressions`（既有口径，
合并 `regression`+`degraded`，无基线时为 `[]`）与
`metrics[regression_count]`（新口径，只数 `regression`，无基线时为 `null`）。
这是**有意的双轨并存**，不是遗漏。理由：修改 `_compute_summary()` 属公共
行为变更，需用户批准；且既有消费者（`print_summary()`、
`examples/regression_compare.py`）依赖当前口径。

---

## 2. 实体定义

### 2.1 `EvaluationMetadata`

一次评估运行的**评估条件**。这些字段是回归可比性的判定依据。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `run_id` | string | **是** | 运行唯一标识，非空 |
| `created_at` | string | **是** | ISO8601，**必须带时区** |
| `dataset_id` | string | **是** | 数据集标识 |
| `dataset_version` | string | **是** | 数据集版本 |
| `judge_id` | string | **是** | 评分器标识 |
| `judge_version` | string | **是** | 评分器版本 |
| `model_id` | string | **是** | 被评估模型 |
| `backend_id` | string | **是** | 执行后端 |
| `source_type` | enum | **是** | 数据来源标记（§5） |
| `data_classification` | enum | **是** | 数据敏感级别（§6） |
| `generator` | string | 条件必填 | `source_type=synthetic` 时必填，须命中白名单 |
| `generator_version` | string | 否 | 生成器版本 |
| `content_digest` | string | 条件必填 | `source_type=synthetic` 时必填（§5.3） |
| `test_plan_id` | string | 否 | 透传自既有报告 |
| `notes` | string | 否 | 人工备注 |

### 2.2 `MetricRecord`

| 字段 | 类型 | 说明 |
|---|---|---|
| `metric_id` | string | 指标标识，见 [AIQE_METRICS_V01.md](AIQE_METRICS_V01.md) |
| `metric_value` | number \| **null** | 指标值。**为 null ⟺ status 非 OK** |
| `metric_unit` | string | 单位（§4） |
| `status` | enum | `ok` / `missing` / `no_data` / `no_baseline` / `not_applicable` / `undefined` / `unavailable` / `partial` |
| `metric_version` | string | 指标定义版本，默认 `aiqe.metrics/0.1.0` |
| `precision` | enum | `measured` / `estimated` / `not_applicable` |
| `scope` | string | `run` / `case` / `category` |
| `case_id` | string \| null | `scope=case` 时非空 |
| `reason` | string | 状态说明；非 OK 状态**必须**非空 |

**核心不变式**：

```
metric_value is None  ⟺  status is not OK
```

由 `tests/test_contract.py::test_metric_value_none_iff_status_not_ok`
对**全部 valid fixtures 全量扫描**锁定。

### 2.3 `CaseResult`

`CaseResult` 是既有 case 字典的**只读视图**（`raw` 持有原字典，
保证序列化回写不丢字段），不是第二套数据模型。归一化属性：

| 属性 | 来源 | 语义 |
|---|---|---|
| `case_id` / `category` | 既有字段 | 直读 |
| `execution_ok` | `execution.error is None` | 后端是否正常跑完 |
| `score` | `judge.score` | 数值型才返回值，否则 `None` |
| `passed` | `judge.passed` | 布尔型才返回值，否则 `None` |
| `status` | 派生 | `passed` / `failed` / `error` / `skipped`（§3.1） |
| `regression_status` | `regression.status` | 直读 |

### 2.4 `RegressionComparison`

由 `compare_runs(baseline, candidate)` 产出。

| 字段 | 类型 | 说明 |
|---|---|---|
| `baseline_run_id` / `candidate_run_id` | string | 两侧标识 |
| `comparable` | bool | **是否可比较**（§7） |
| `incomparable_reasons` | string[] | 不可比原因码 |
| `flags` | string[] | 软差异标记（不阻断） |
| `degradation_threshold` | number | 判定阈值，当前 `0.15` |
| `baseline_conditions` / `candidate_conditions` | object | 两侧评估条件快照 |
| `case_comparisons` | array | case 级对比（不可比时**必为空**） |
| `metric_deltas` | object | run 级指标 delta（不可比时**必为空**） |

---

## 3. 枚举定义

### 3.1 结果状态 `CaseStatus`

| 值 | 判定条件 |
|---|---|
| `passed` | `execution.error is None` **且** `judge.passed is True` |
| `failed` | `execution.error is None` **且** `judge.passed is False` |
| `error` | `execution.error is not None` |
| `skipped` | `judge.passed` 缺失（非布尔） |

**没有 `timeout` 状态。** 理由：AIQE 目前无法可靠区分超时与其他执行异常
（`ExecutionRunner` 把所有非 `RuntimeError` 异常压平为自由文本）。
把 `timeout` 列为状态会造成「有分类」的假象。超时用例的状态是 `error`，
其 `error` 文本可能提及 timeout，但契约层**不据此推断分类**。
详见 [AIQE_METRICS_V01.md §3.4](AIQE_METRICS_V01.md#34-timeout_count)。

**硬约束**：`execution.error is not None` ⇒ `judge.passed is False`。
由 `test_execution_failure_implies_case_not_passed` 对全部 fixtures 锁定。

### 3.2 指标状态 `MetricStatus`

| 值 | 含义 | 典型场景 |
|---|---|---|
| `ok` | 有值且有效 | 正常 |
| `missing` | 期望的输入字段不存在 | 空响应分支不产出 `format_score` |
| `no_data` | 分母为空，比例无定义 | 空用例集上的 `case_pass_rate` |
| `no_baseline` | 无基线可比 | `regression` 状态为 `new` |
| `not_applicable` | 该指标对此类别不适用 | 无 `json_output`/`coding_task` 用例时的 `format_compliance` |
| `undefined` | 无可靠测量方法 | `timeout_count` / `judge_agreement` / `severity_distribution` |
| `unavailable` | 数据源不存在 | `input_tokens` / `estimated_cost` |
| `partial` | 部分输入缺失，值基于不完整数据 | 一半用例缺 `judge` |

### 3.3 精度 `MetricPrecision`

| 值 | 含义 |
|---|---|
| `measured` | 真实测量 |
| `estimated` | 由字符数等启发式估算（mock / 默认 `generate_sync` 路径） |
| `not_applicable` | 无值 |

**规则**：`compare_runs()` **不产出** precision 不同的两侧之间的 delta
（估算值与实测值不可相减）。

---

## 4. 指标单位

| 单位字符串 | 适用指标 | 说明 |
|---|---|---|
| `ratio` | `case_pass_rate` / `execution_success_rate` / `format_compliance` / `judge_agreement` | 闭区间 `[0.0, 1.0]` |
| `count` | `execution_error_count` / `timeout_count` / `regression_count` / `degraded_count` | 整数 |
| `milliseconds` | `latency_ms` | **源字段 `elapsed_sec` 单位是秒，必须 ×1000** |
| `score` | `judge_score` | 闭区间 `[0.0, 1.0]` |
| `score_delta` | `baseline_delta` | 区间 `[-1.0, 1.0]` |
| `tokens` | `input_tokens` / `output_tokens` | 整数 |
| `tokens/second` | `tokens_per_second` | 浮点 |
| `distribution` | `severity_distribution` | 分档计数 |
| `currency` | `estimated_cost` | 币种未定义（指标本身 `UNAVAILABLE`） |

---

## 5. 数据来源标记 `source_type`

### 5.1 取值

| 值 | 含义 | 本轮是否允许 |
|---|---|---|
| `synthetic` | 本地显式生成的合成样本 | ✅ **唯一允许** |
| `local_test` | 本地测试运行产生的数据 | ❌ 拒绝 |
| `local_import` | 经独立文件契约导入的外部数据 | ❌ 拒绝 |

### 5.2 门禁实现

```python
ALLOWED_SOURCE_TYPES: frozenset[SourceType] = frozenset({SourceType.SYNTHETIC})
```

`validate_run()` 在 `source_type` 不属于允许集合时抛
`SOURCE_TYPE_NOT_ALLOWED`，错误信息中明确写出：

> 接入真实数据需要独立授权（门禁 G1–G6），**不得通过修改 source_type 绕过**。

门禁是**参数化**的（`allowed_source_types` 参数），不是写死的分支——
这使策略可审计、可测试。
`test_source_type_gate_is_configurable_not_hardcoded` 证明了这一点。

### 5.3 合成数据的来源证明

**问题**：仅声明 `source_type="synthetic"` 不能证明数据真的是合成的。

**机制**：

1. `generator` 必须命中受信白名单
   `TRUSTED_SYNTHETIC_GENERATORS = {"aiqe.synthetic/0.1.0"}`；
2. `content_digest` 必须存在且与**实算摘要**匹配。

**摘要算法**：

```
content_digest = sha256(canonical_json(文档除去 metadata 的全部内容))[:32]
canonical_json = json.dumps(payload, sort_keys=True, separators=(",",":"), ensure_ascii=False)
```

排除 `metadata` 的原因：否则 `content_digest` 字段自身造成自引用。

### 5.4 ⚠️ 信任边界（必须诚实声明）

**`source_type` + `content_digest` 能证明**：

- ✅ 文档结构符合结果契约
- ✅ 文档由受信生成入口产出，且生成后未被改动（防篡改证据）

**不能证明**：

- ❌ 文档底层数据在语义上「真的是」合成数据

掌握生成入口的一方可以把任意数据喂进去并得到合法摘要。
因此：

> **验证合成数据结构 ≠ 证明数据来源真实可信。**

真实数据接入需要独立的字段白名单、数据授权和隐私评审。
结构校验和内容摘要仅验证结果文档的结构和完整性。

本轮采用**本地显式生成的合成 fixtures**，生成入口为
`PYTHONPATH=src python -m AIQE.synthetic <目录>`，可信边界记录在
[`tests/fixtures/synthetic/README.md`](../../tests/fixtures/synthetic/README.md)。

---

## 6. 数据敏感级别 `data_classification`

| 值 | 含义 | 可否入 Git |
|---|---|---|
| `public_synthetic` | 合成数据 | ✅ |
| `internal` | 内部数据 | ❌ |
| `personal` | 个人数据 | ❌ |
| `restricted` | 最高级别 | ❌ |

本轮全部 fixtures 为 `public_synthetic`，
由 `test_all_fixtures_are_public_synthetic_classification` 锁定。

### 6.1 敏感字段默认拒绝（纵深防御）

`scan_sensitive()` 递归扫描整份文档，命中即抛异常，**不做自动脱敏**。

**拒绝键名**（归一化后精确匹配 + 明确后缀）：

```
api_key / access_token / secret / password / private_key / credential /
user_email / phone / id_card / ssn / passport / home_address / real_name /
chat_log / raw_prompt / memory_db / user_profile / ...
```

**拒绝取值模式**（仅扫描字符串值）：

```
email / cn_mobile / cn_id_card / openai_style_key /
github_token / aws_access_key / pem_private_key
```

**为什么不做自动脱敏**：

> 自动删除敏感字段后继续处理，会让人误以为「处理过了所以安全」，
> 而实际上我们既没有证据证明删干净了，也没有证据证明剩余部分是合成数据。

**这是纵深防御，不是主控制。** 对导入路径，主控制是字段**白名单**
（默认拒绝）。黑名单永远不完备——新增一种敏感字段类型就漏一次。

**误报防护**：`tokens_generated` / `max_tokens` / `tokens_per_second`
等框架自身字段**不得**被误判为敏感。
`test_legitimate_token_fields_are_not_false_positives` 锁定这一点。

---

## 7. 回归可比性

### 7.1 硬条件（阻断对比）

| 原因码 | 条件 |
|---|---|
| `DATASET_ID_MISMATCH` | `dataset_id` 不同 |
| `DATASET_VERSION_MISMATCH` | `dataset_version` 不同 |
| `JUDGE_ID_MISMATCH` | `judge_id` 不同 |
| `JUDGE_VERSION_MISMATCH` | `judge_version` 不同 |
| `SCHEMA_MAJOR_MISMATCH` | schema 主版本不同 |
| `SAME_RUN_ID` | 两侧是同一个 run |

**为什么是这些**：它们决定「分数代表什么」——题目不同、或评分规则不同，
分数就不可比。

### 7.2 软条件（记录 flag，不阻断）

| 标记 | 条件 |
|---|---|
| `MODEL_CHANGED` | `model_id` 不同 |
| `BACKEND_CHANGED` | `backend_id` 不同 |
| `SOURCE_TYPE_CHANGED` | `source_type` 不同 |
| `CASE_SET_DIFFERS` | 用例集合不同 |

**为什么换模型不阻断**：「同一套题、同一个评分器，新模型比旧模型好还是差」
**正是回归测试的正当用途**。但差异必须被记录，因为跨模型的**绝对分数**
不能横向排名。

### 7.3 不可比时的行为

```python
comparison.comparable is False
comparison.case_comparisons == []      # 必为空
comparison.metric_deltas == {}         # 必为空
```

**不可比时绝不产出 delta。** 产出再标注「仅供参考」是危险的——
下游很容易忽略标注。由
`test_incomparable_comparison_never_emits_deltas` 锁定。

### 7.4 阈值语义

复用 `regression.classify_delta()`（与 `RegressionAnalyzer` **同一实现**，
避免两处规则分叉）：

```
delta > 0                → "pass"
delta < -0.15            → "regression"
-0.15 <= delta <= 0      → "degraded"
```

**`delta == 0` 判为 `degraded`** 是框架既有语义（只有提升才算 pass）。
Dashboard 展示时必须附带提示，否则用户会把「完全可复现」误读为「轻微退化」。

---

## 8. 时间戳规则

| 规则 | 说明 |
|---|---|
| 格式 | ISO8601 |
| 时区 | **必须带时区偏移**（`+00:00` 或 `Z`） |
| 拒绝 | 无时区的 naive datetime → `TIMESTAMP_MALFORMED` |
| 规范化 | 解析后统一转为 **UTC**，`created_at` 存储为 UTC ISO8601 |

**为什么拒绝 naive datetime**：无法确定绝对时刻，跨时区汇总趋势时会静默错位。
宁可在读取时失败，也不要在 Dashboard 上展示错位的时间线。

---

## 9. Schema 版本与兼容性策略

### 9.1 版本格式

```
aiqe.result/MAJOR.MINOR.PATCH
```

当前：`aiqe.result/0.1.0`，`SUPPORTED_SCHEMA_MAJOR = 0`。

### 9.2 兼容性矩阵

| 变更类型 | 兼容性 | 读取器行为 |
|---|---|---|
| 主版本不同 | **不兼容** | 抛 `SCHEMA_VERSION_INCOMPATIBLE`，**不做字段猜测** |
| 次版本不同（主版本相同） | 兼容 | 正常读取 |
| 补丁版本不同 | 兼容 | 正常读取 |
| 新增可选字段 | 兼容 | 忽略未知字段 |
| 缺失可选字段 | 兼容 | 使用默认值 |
| 修改既有字段语义 | **不兼容** | 必须递增主版本 |

`test_schema_version_minor_bump_is_accepted` 锁定次版本兼容性。

### 9.3 版本缺失

缺少 `schema_version` → `SCHEMA_VERSION_MISSING`，**拒绝读取**。
不做「假定是最新版」的猜测。

---

## 10. 无效输入处理

**总原则：失败关闭（fail-closed）。**

| 输入问题 | 原因码 | 行为 |
|---|---|---|
| 文档不是 JSON 对象 | `DOCUMENT_NOT_OBJECT` | 拒绝 |
| 缺 `schema_version` | `SCHEMA_VERSION_MISSING` | 拒绝 |
| `schema_version` 格式非法 | `SCHEMA_VERSION_MALFORMED` | 拒绝 |
| 主版本不兼容 | `SCHEMA_VERSION_INCOMPATIBLE` | 拒绝 |
| 缺 `metadata` | `REQUIRED_FIELD_MISSING` | 拒绝 |
| 必填字段缺失 | `REQUIRED_FIELD_MISSING` | 拒绝 |
| 字段类型错误 | `INVALID_TYPE` | 拒绝，**不静默转换** |
| 枚举值非法 | `INVALID_ENUM_VALUE` | 拒绝 |
| `case_id` 重复 | `DUPLICATE_CASE_ID` | 拒绝 |
| 时间戳无时区/不可解析 | `TIMESTAMP_MALFORMED` | 拒绝 |
| 敏感字段/取值 | `SENSITIVE_FIELD_DETECTED` / `SENSITIVE_VALUE_DETECTED` | 拒绝，**不脱敏** |
| 来源不允许 | `SOURCE_TYPE_NOT_ALLOWED` | 拒绝 |
| 生成器不可信 | `SYNTHETIC_GENERATOR_UNTRUSTED` | 拒绝 |
| 摘要缺失/失配 | `SYNTHETIC_DIGEST_MISSING` / `_MISMATCH` | 拒绝 |

**`null` 是合法值**（表示缺失），不得与类型错误混为一谈——
`test_null_optional_fields_are_accepted` 锁定。

**`bool` 不是数值**：`judge.score = True` 被拒绝，尽管 `bool` 是 `int` 的子类。

### 校验顺序（有意设计）

```
1. 文档是对象
2. schema_version 存在、格式合法、主版本兼容
3. 敏感字段/取值扫描          ← 最强的拒绝条件，且与来源无关
4. metadata 必填字段与枚举
5. 合成数据来源证明
6. 用例结构、唯一性、类型
```

**为什么敏感扫描在来源证明之前**：即使一份文档伪造了来源标记，
只要含敏感数据就必定被拒——不依赖后续证明步骤是否正确执行。

---

## 11. 读取失败行为

`load_run(path)` 的失败语义：

| 情况 | 原因码 |
|---|---|
| 文件不存在 | `FILE_NOT_FOUND` |
| 文件不可读 / 非 UTF-8（二进制、损坏） | `FILE_UNREADABLE` |
| 不是合法 JSON | `FILE_NOT_JSON` |
| 校验不通过 | 见 §10 |

**`load_run` 绝不返回 `None` 或空对象。**

> 读取失败必须是**显式失败**。若返回 `None` 或空对象，调用方很容易把
> 「数据损坏」当成「没有数据」，从而在 Dashboard 上显示成「零回归」——
> 这是本契约要杜绝的最危险误读。

调用方若想「没有文件就当作没有数据」，必须**显式捕获**
`FILE_NOT_FOUND`，而不是依赖静默降级。

> **真实缺陷修复记录**：初版 `load_run` 只捕获 `OSError`。
> 实测发现二进制文件会抛 `UnicodeDecodeError`——它是 `ValueError` 的子类，
> **不是** `OSError`，因此会以未捕获异常逃逸，破坏「失败关闭」保证。
> 已修复并由 `test_load_binary_file_raises_contract_violation` 锁定。

---

## 12. 唯一标识规则

| 实体 | 唯一键 | 作用域 |
|---|---|---|
| 运行 | `metadata.run_id` | 全局 |
| 用例 | `case_id` | **运行内唯一**（跨运行可重名，用于回归配对） |
| 指标记录 | `(run_id, metric_id, scope, case_id)` | 运行内 |

`run_id` 目前由调用方提供，**契约不强制其格式**（可以是 UUID、
时间戳串或业务命名）。契约只保证非空且在同一对比中两侧不同。

---

## 13. 与既有代码的关系（变更清单）

| 文件 | 变更 | 性质 |
|---|---|---|
| `src/AIQE/contract.py` | **新增** | 纯增量 |
| `src/AIQE/comparison.py` | **新增** | 纯增量 |
| `src/AIQE/synthetic.py` | **新增** | 纯增量 |
| `src/AIQE/regression.py` | 抽出 `classify_delta()` 模块级函数；`analyze()` 改为调用它；`DEGRADATION_THRESHOLD` 提升为模块常量（类属性保留同名引用） | **行为不变的重构**，111 个既有测试全绿 |
| `src/AIQE/__init__.py` | 追加导出 | 兼容变更（纯增量） |
| `.gitignore` | 追加 `._*` | 兼容变更 |
| `ExecutionRunner` / `OutputJudge` / `EvaluationReport` / `Reporter` | **零改动** | —— |

**未修改任何既有公共 API 的不兼容行为。**

---

## 14. 已知局限与后续

| # | 局限 | 影响 | 后续 |
|---|---|---|---|
| C-1 | `summary.regressions` 与 `metrics.regression_count` 口径不同 | 两个数字可能不一致 | 需用户批准后统一（属公共 API 变更） |
| C-2 | `run_id` 无生成器 | 调用方需自行保证唯一 | 后续可加 `new_run_id()` 工具 |
| C-3 | 无运行索引 / 目录约定 | Dashboard 无法「列出历史运行」 | Dashboard MVP 设计已覆盖（见 Phase 4 文档） |
| C-4 | `judge_version` 用框架版本代替 | 评分规则变更时不会自动递增 | 为 `OutputJudge` 引入独立版本号（M-6） |
| C-5 | 摘要只证明「未被改动」，不证明「数据是合成的」 | 信任边界（§5.4） | 由导入契约的字段白名单承担 |
