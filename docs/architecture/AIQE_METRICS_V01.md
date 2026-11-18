# AIQE 质量指标体系 v0.1

> **性质**：AIQE v0.1 可计算、可展示的质量指标**规范**。
> 指标状态以公开的[报告结构](../../src/AIQE/schema.py)和
> [指标实现](../../src/AIQE/contract.py)为依据。
>
> **日期**：2026-09-22
> **适用范围**：AIQE v0.1（`schema_version` = `aiqe.result/0.1.0`）

---

## 0. 状态词表

本文档对每个指标给出唯一状态，词表定义如下：

| 状态 | 含义 | 判定标准 |
|---|---|---|
| `IMPLEMENTED` | 指标可由**现有已持久化字段**直接计算，且已有测试锁定 | 存在可引用的代码行与测试函数 |
| `DESIGNED` | 计算规则已定义、输入字段已存在，但**尚无计算代码** | 有明确输入字段，无聚合实现 |
| `UNAVAILABLE` | **所需输入数据在现有数据模型中不存在**，且无法从已有字段推导 | 全仓库无该字段来源 |
| `UNDEFINED` | 数据可能存在，但**尚无可靠的测量方法**（口径未达成一致或依赖不可靠推断） | 无结构化字段，或只能靠字符串匹配等脆弱手段 |

**强制规则**：

1. **禁止将缺失值当作 0**。缺失一律表示为 `null` + `status` 字段说明原因。
   `0` 是合法测量结果，`null` 是「没测到」——两者语义不同，不得混同。
2. **禁止为通过检查而放宽口径**。若某指标只能靠字符串匹配得到，
   状态必须是 `UNDEFINED`，不得为了「有数据」而降级为 `DESIGNED`。
3. **`UNAVAILABLE` 与 `UNDEFINED` 不得参与排名或门禁**，只能以
   「数据缺失」形式在 Dashboard 显式呈现。

---

## 1. 三个不可混淆的语义边界

这一节是整份指标体系的**前置约束**。任何指标实现违反其中一条，
该指标结论即为无效。

### 1.1 `case_pass_rate` ≠ `execution_success_rate`

这是本体系**最容易被误用的一对指标**，必须严格区分：

| 维度 | `execution_success_rate` | `case_pass_rate` |
|---|---|---|
| 回答的问题 | **模型/后端有没有正常跑完？** | **跑出来的结果质量达标了吗？** |
| 判定依据 | `ExecutionResult.error is None` | `JudgeResult.passed`（即 `score >= 0.5`） |
| 失败原因 | 后端抛异常、模型未加载、连接被拒、超时 | 响应为空 / 长度不足 / 关键词命中率低 / 格式不合规 |
| 失败时另一指标的值 | —— | 执行失败时 `judge` 必然不通过（见下） |
| 责任方 | 基础设施、后端适配、运行时环境 | 模型质量、Prompt 设计、用例设计 |

**蕴含关系（单向）**：

```
execution 成功  ⊅  case 通过      ← 执行成功但答案错，完全正常
execution 失败  ⇒  case 不通过    ← 这是硬约束
```

**第二条是硬约束的理由**：`ExecutionRunner` 在异常路径返回
`response=""`，而 `OutputJudge` 的第 1 步是「空响应 → 强制 0 分」。
所以执行失败必然导致 `judge.passed == False`。
`tests/test_error_contract.py::test_judge_never_fabricates_success_on_failed_execution`
锁定了这一点。

**推论（对 Dashboard 的硬性要求）**：
一个运行可能 `execution_success_rate = 1.0` 但 `case_pass_rate = 0.25`；
也可能 `execution_success_rate = 0.6` 且 `case_pass_rate = 0.6`。
**这两个指标必须并排展示，不得只显示其中一个**，否则会把
「后端跑不起来」误读成「模型质量差」，或反之。

### 1.2 `judge_score` 不代表客观正确率

`OutputJudge` 是**确定性启发式评分器**，其分数由三部分构成
（`src/AIQE/judge.py:129-136`）：

```
score = keyword_hit_rate × (长度不达标 ? 0.5 : 1.0) × format_score
score = min(score, case.scoring.relevance)     # per-case 上限
```

由此产生的**固有局限**（必须随分数一起披露）：

- **关键词匹配不是语义理解**。响应包含关键词但语义完全错误，仍得高分。
  例：`boundary_conflicting_instructions` 的 `expected_keywords=["矛盾","无法"]`——
  模型输出「这里没有矛盾，我无法理解你的问题」会命中两个关键词。
- **长度惩罚是二值跳变**，不是连续衰减：`min_length - 1` 字符得 ×0.5，
  `min_length` 字符得 ×1.0。
- **格式分只对 2 个类别生效**。`_check_format()` 对 `json_output` /
  `coding_task` 做真实检查，其余类别（`chat` / `translation` / `edge_case`）
  **恒返回 1.0**（`src/AIQE/judge.py:176`）。因此
  `format_compliance` 在这些类别上是**无信息量的常数**。
- **无参考答案比对**。没有任何 case 定义 gold answer；
  `expected_keywords` 是唯一的正确性代理。

**结论**：`judge_score` 是**回归检测信号**，不是**绝对质量分数**。
它适合回答「这一版比上一版好还是差」，不适合回答「这个模型准确率是多少」。

### 1.3 跨模型 / 跨 Judge / 跨数据集不可直接排名

在**未统一评估条件**时，以下比较一律无效：

| 情形 | 为什么无效 |
|---|---|
| 不同 `model_id`，不同 `dataset_id` | 用例集不同 → 难度不同 → 分数不可比 |
| 不同 `dataset_version` | 同一数据集的不同版本，用例可能已增删改 |
| 不同 `judge_id` / `judge_version` | 评分规则变更 → 同一响应得到不同分数 |
| 不同 `backend_id` | 执行路径不同，时延与截断行为不同 |
| 不同 `max_tokens` / `temperature` | 生成条件不同 |

**强制要求**：任何 `RegressionComparison` 记录**必须**同时携带
`baseline_run_id`、`candidate_run_id`，以及两侧的
`dataset_id` / `dataset_version` / `judge_id` / `judge_version` / `model_id`。
只有当这些字段**逐项相等**时，`comparable` 才为 `true`。
（契约见 [`AIQE_RESULT_CONTRACT_V01.md`](AIQE_RESULT_CONTRACT_V01.md)）

### 1.4 回归判定必须记录评估条件

现有 `RegressionAnalyzer.analyze(case_id, current_score)` 的签名
（`src/AIQE/regression.py:64-68`）**只接收 case_id 与分数**，
完全不校验两次运行是否同源。这是 Phase 0 识别出的**核心缺口**。

v0.1 的处理方式：**不修改** `RegressionAnalyzer` 的既有公共行为
（属于「修改已有公共 API 的不兼容行为」，需用户批准），
而是在新增的结果契约层做**运行级可比性校验**，把
`RegressionAnalyzer` 作为 case 级判定器继续复用。取舍理由见 §5。

---

## 2. 指标总表

| metric_id | 分组 | 单位 | 聚合 | 状态 |
|---|---|---|---|---|
| [`case_pass_rate`](#31-case_pass_rate) | P0 执行质量 | ratio (0–1) | run 级 | `IMPLEMENTED` |
| [`execution_success_rate`](#32-execution_success_rate) | P0 执行质量 | ratio (0–1) | run 级 | `IMPLEMENTED` |
| [`execution_error_count`](#33-execution_error_count) | P0 执行质量 | count | run 级 | `IMPLEMENTED` |
| [`timeout_count`](#34-timeout_count) | P0 执行质量 | count | run 级 | `UNDEFINED` |
| [`regression_count`](#35-regression_count) | P0 执行质量 | count | run 级 | `IMPLEMENTED` |
| [`latency_ms`](#36-latency_ms) | P0 执行质量 | milliseconds | case 级 | `IMPLEMENTED` |
| [`judge_score`](#41-judge_score) | P1 评估质量 | score (0–1) | case 级 | `IMPLEMENTED` |
| [`judge_agreement`](#42-judge_agreement) | P1 评估质量 | ratio (0–1) | run 级 | `UNDEFINED` |
| [`format_compliance`](#43-format_compliance) | P1 评估质量 | ratio (0–1) | case 级 | `IMPLEMENTED` |
| [`baseline_delta`](#44-baseline_delta) | P1 评估质量 | score delta | case 级 | `IMPLEMENTED` |
| [`severity_distribution`](#45-severity_distribution) | P1 评估质量 | distribution | run 级 | `UNDEFINED` |
| [`input_tokens`](#51-input_tokens) | P2 资源指标 | tokens | case 级 | `UNAVAILABLE` |
| [`output_tokens`](#52-output_tokens) | P2 资源指标 | tokens | case 级 | `IMPLEMENTED` |
| [`tokens_per_second`](#53-tokens_per_second) | P2 资源指标 | tokens/second | case 级 | `IMPLEMENTED` |
| [`estimated_cost`](#54-estimated_cost) | P2 资源指标 | currency | run 级 | `UNAVAILABLE` |

**统计**：15 个候选指标 → `IMPLEMENTED` 9 / `UNDEFINED` 3 / `UNAVAILABLE` 2 / `DESIGNED` 1。

> 说明：总表把 `case_pass_rate` / `execution_success_rate` /
> `execution_error_count` / `regression_count` 标为 `IMPLEMENTED`，
> 依据是它们的**输入字段已持久化在报告 JSON 中**且可确定性推导
> （`reporter._compute_summary()` 已计算其中 2 个）。
> 但**聚合为 `MetricRecord` 的代码尚不存在**——见 §6 的诚实披露。

---

## 3. P0 —— 执行质量指标

### 3.1 `case_pass_rate`

| 属性 | 值 |
|---|---|
| **业务含义** | 本次评估中，用例质量达标的比例。回答「模型这次表现如何」。 |
| **输入字段** | `cases[].judge.passed`（bool） |
| **计算规则** | `count(judge.passed == true) / count(cases)` |
| **数据类型** | `float` |
| **单位** | ratio，闭区间 `[0.0, 1.0]` |
| **聚合方式** | run 级标量。可按 `category` 分组求子集比例；**不跨 run 求平均**（见 §1.3） |
| **缺失值处理** | 若 `cases` 为空 → `null`（**不是 0.0**），`status = "no_data"`。若某 case 的 `judge` 块缺失 → 该 case 计入分母、不计入分子，并置 `status = "partial"` |
| **适用场景** | 版本间回归对比、发布门禁（报告模式） |
| **最小测试用例** | 3 个 case：2 个 `passed=true`、1 个 `passed=false` → 期望 `0.6667`；另需 0 case → 期望 `null` |
| **已实现状态** | `IMPLEMENTED` —— 输入字段见 `src/AIQE/reporter.py:119`（`passed` 计数已存在）；本指标的 `MetricRecord` 封装见 `src/AIQE/contract.py` |

**必须与 `execution_success_rate` 并排展示**（§1.1）。

### 3.2 `execution_success_rate`

| 属性 | 值 |
|---|---|
| **业务含义** | 本次评估中，后端正常执行完成（未抛异常）的比例。回答「基础设施是否健康」。 |
| **输入字段** | `cases[].execution.error`（`str \| null`） |
| **计算规则** | `count(execution.error is null) / count(cases)` |
| **数据类型** | `float` |
| **单位** | ratio `[0.0, 1.0]` |
| **聚合方式** | run 级标量。可按 `backend` / `model_id` 分组 |
| **缺失值处理** | `cases` 为空 → `null` + `status="no_data"`。`execution` 块整体缺失 → 计入分母不计入分子 + `status="partial"` |
| **适用场景** | 环境健康度监控、区分「模型差」与「环境坏」 |
| **最小测试用例** | 3 个 case：2 个 `error=null`、1 个 `error="execution_error: ..."` → 期望 `0.6667` |
| **已实现状态** | `IMPLEMENTED` —— `ExecutionResult.success` property 见 `src/AIQE/runner.py:57-59` |

### 3.3 `execution_error_count`

| 属性 | 值 |
|---|---|
| **业务含义** | 本次评估中执行失败的用例数（绝对量，非比例）。 |
| **输入字段** | `cases[].execution.error` |
| **计算规则** | `count(execution.error is not null)` |
| **数据类型** | `int` |
| **单位** | count（个） |
| **聚合方式** | run 级标量。可与 `execution_success_rate` 交叉校验：`count == total × (1 - success_rate)` |
| **缺失值处理** | `cases` 为空 → `0`（**此处 0 是合法值**：没有用例就没有失败）。`execution` 块缺失 → 计为错误并置 `status="partial"` |
| **适用场景** | 快速判断「这轮有没有炸」 |
| **最小测试用例** | 3 个 case，1 个带 `error` → 期望 `1` |
| **已实现状态** | `IMPLEMENTED` |

> **注意**：与 §3.2 不同，本指标在空集时合法返回 `0`。
> 这是 §0 规则 1 的**精确应用**：「没有用例」是确定的测量结果（0 个失败），
> 不是「没测到」。而比例类指标在空集上无定义，故为 `null`。

### 3.4 `timeout_count`

| 属性 | 值 |
|---|---|
| **业务含义** | 因超时导致执行失败的用例数。 |
| **输入字段** | **无结构化字段** |
| **计算规则** | **无法可靠计算** |
| **数据类型** | `int`（若将来实现） |
| **单位** | count |
| **聚合方式** | run 级 |
| **缺失值处理** | 恒为 `null`，`status = "undefined"` |
| **适用场景** | （暂不适用） |
| **最小测试用例** | 无法编写有效测试——见下 |
| **已实现状态** | **`UNDEFINED`** |

**为什么是 `UNDEFINED` 而不是 `DESIGNED`**：

`ExecutionRunner` 的异常处理只有两条分支
（`src/AIQE/runner.py:100` 与 `:114`）：

```python
except RuntimeError as e:   → error = str(e)
except Exception as e:      → error = f"execution_error: {e}"
```

`TimeoutError` 是 `OSError` 的子类，**不是** `RuntimeError`，
因此落入第二条分支，被压平成自由文本
（实测见 `tests/test_runner.py:353-367`）。

当前**唯一**的识别手段是在 `error` 字符串里搜 `"timed out"`。
这个手段不可靠，理由有三：

1. **依赖异常消息文本**。消息由后端实现（`urllib` / `requests` /
   自研后端）决定，措辞会变、可被本地化。
2. **无法区分超时层级**。连接超时、读取超时、模型生成超时
   在业务上含义完全不同，但都会变成 `"execution_error: ...timed out..."`。
3. **`ConnectionError` 测试证明消息不可控**。`test_execution_runner_connection_error`
   注入的中文消息「连接被拒绝」说明错误文本是任意的。

**解除阻塞所需的条件**：在 `ExecutionResult` 上引入**结构化错误分类**
（如 `error_kind: Literal["none","runtime","timeout","connection","other"]`）。
这属于**新增可选字段**，不破坏既有消费者，但需要在
`ExecutionRunner` 的异常分支中做类型判断。

**本轮处置**：不实现。原因——本轮不修改 `ExecutionRunner` 的异常语义
（`tests/test_error_contract.py` 与 `test_runner.py` 共 6 个测试锁定
当前 `execution_error:` 前缀行为），且无真实超时数据可用于验证分类正确性。
记录为待办，见 §7。

### 3.5 `regression_count`

| 属性 | 值 |
|---|---|
| **业务含义** | 本次评估中，相较基线发生**显著退化**的用例数。 |
| **输入字段** | `cases[].regression.status` |
| **计算规则** | `count(regression.status == "regression")` |
| **数据类型** | `int` |
| **单位** | count |
| **聚合方式** | run 级标量。**必须同时给出 `degraded_count`**（`status == "degraded"`），否则语义混淆 |
| **缺失值处理** | 无 `regression` 块（未提供基线）→ `null` + `status="no_baseline"`。**不得返回 0**——「没有基线」与「有基线且无回归」是两件事 |
| **适用场景** | 发布门禁的核心信号 |
| **最小测试用例** | 4 个 case，状态分别为 `pass`/`regression`/`degraded`/`new` → `regression_count == 1`，`degraded_count == 1` |
| **已实现状态** | `IMPLEMENTED`（计算规则明确）；**但现有 `_compute_summary()` 的实现与本规范不一致** —— 见下 |

> ⚠️ **与现有实现的差异（必须记录）**
>
> `src/AIQE/reporter.py:120-124` 的现有实现：
> ```python
> regressions = [
>     c["case_id"] for c in self.cases
>     if c.get("regression", {}).get("status") in ("regression", "degraded")
> ]
> ```
> 它把 `regression` 与 `degraded` **合并**为一个列表，且当无 `regression`
> 块时静默返回 `[]`（即隐式当作「无回归」）。
>
> 本规范要求两者**分开计数**，且无基线时返回 `null`。
>
> **处置**：**不修改** `_compute_summary()`（其输出被
> `examples/regression_compare.py` 与 `print_summary()` 消费，
> 改动属公共行为变更）。新增的指标层在 `contract.py` 中**独立计算**
> 这两个计数，并在契约层明确标注与 `summary.regressions` 的口径差异。
> 这是有意的**双轨并存**，不是遗漏。

**阈值语义说明**：`RegressionAnalyzer.DEGRADATION_THRESHOLD = 0.15`
（`src/AIQE/regression.py:59`）。判定规则：

```
delta > 0                → "pass"
delta < -0.15            → "regression"
-0.15 <= delta <= 0      → "degraded"
```

**注意 `delta == 0` 被判为 `degraded`**——这是框架语义
（「只有提升才算 pass」），示例脚本中已有明确注释说明
（`examples/regression_compare.py:118-120`）。Dashboard 展示时
必须沿用该语义并显示提示，否则用户会把「完全可复现」误读为「轻微退化」。

### 3.6 `latency_ms`

| 属性 | 值 |
|---|---|
| **业务含义** | 单个用例的执行耗时（毫秒）。 |
| **输入字段** | `cases[].execution.elapsed_sec`（float，**单位：秒**） |
| **计算规则** | `elapsed_sec × 1000.0` |
| **数据类型** | `float` |
| **单位** | **milliseconds**（毫秒）——注意源字段是**秒**，必须显式换算 |
| **聚合方式** | case 级原始值；run 级聚合取 `p50` / `p95` / `max`。**不得只给平均值**——时延分布长尾，均值会掩盖超时个案 |
| **缺失值处理** | 执行失败的 case `elapsed_sec == 0.0`（异常分支硬编码，`src/AIQE/runner.py:108`）。**该 0.0 不是「瞬时完成」，必须置 `null`** —— 否则会拉低平均时延 |
| **适用场景** | 性能回归、后端对比 |
| **最小测试用例** | `elapsed_sec=0.1` → 期望 `100.0` ms；执行失败 case → 期望 `null` |
| **已实现状态** | `IMPLEMENTED`（换算规则明确） |

> ⚠️ **mock 数据的性能结论无效**
>
> `MockEvalBackend.generate_sync()` 硬编码 `elapsed_sec=0.1`
> （`src/AIQE/backends/mock.py:110`）。因此基于 mock 后端的
> `latency_ms` / `tokens_per_second` **只能验证计算管道正确性，
> 不能得出任何性能结论**。Dashboard 必须按 `backend_id` 区分展示，
> 并对 `mock` 来源标注「演示数据，无性能含义」。

---

## 4. P1 —— 评估质量指标

### 4.1 `judge_score`

| 属性 | 值 |
|---|---|
| **业务含义** | 单用例的确定性综合评分。**是回归信号，不是正确率**（§1.2）。 |
| **输入字段** | `cases[].judge.score`（float） |
| **计算规则** | 直接读取（由 `OutputJudge.judge()` 产出，规则见 `src/AIQE/judge.py:129-139`） |
| **数据类型** | `float` |
| **单位** | score，闭区间 `[0.0, 1.0]` |
| **聚合方式** | case 级原始值；run 级取 `mean` / `min` / `max`。**跨 run 求平均无效**（§1.3） |
| **缺失值处理** | `judge` 块缺失 → `null` + `status="missing"`。**不得填 0** |
| **适用场景** | 回归对比、逐用例排查 |
| **最小测试用例** | 空响应 → `0.0`；全关键词命中 + 长度达标 + 格式合规 → `1.0`（已有 `test_judge_*` 系列覆盖） |
| **已实现状态** | `IMPLEMENTED` |

**必须随分数披露的元数据**：`judge_id` / `judge_version`。
当前代码中**无版本标识**——`OutputJudge` 无类属性版本号，
`_VERSION = "0.1.0"`（`src/AIQE/reporter.py:23`）是**框架版本**不是评分器版本。
契约层将使用框架版本作为 `judge_version` 的初值，并明确标注
「评分规则变更时必须独立递增」。见 §7 待办。

### 4.2 `judge_agreement`

| 属性 | 值 |
|---|---|
| **业务含义** | 两个评分器（或两次评分）对同一响应判定的一致程度。用于评估评分器自身的可靠性。 |
| **输入字段** | **无** —— 系统只有一个评分器 `OutputJudge` |
| **计算规则** | **无法计算** |
| **数据类型** | `float`（若将来实现） |
| **单位** | ratio `[0.0, 1.0]` |
| **聚合方式** | run 级 |
| **缺失值处理** | 恒为 `null`，`status = "undefined"` |
| **适用场景** | （暂不适用） |
| **最小测试用例** | 无法编写——需先有第二个评分源 |
| **已实现状态** | **`UNDEFINED`** |

**为什么是 `UNDEFINED`**：一致性指标需要**两个独立判定源**。
当前 `OutputJudge` 是唯一评分器，且被设计为**确定性**
（相同输入恒得相同输出）——对自己求一致性恒为 `1.0`，无信息量。

可行的实现路径（本轮**不实施**，列入 §7）：
- 路径 A：引入第二个确定性评分器（不同关键词/格式策略），计算 Cohen's κ；
- 路径 B：引入可选 LLM 裁判作为第二源，计算一致率——
  但 `ROADMAP.md` 明确 LLM 裁判是「可选方向」，且本轮**禁止调用付费模型 API**。

**本轮处置**：标记 `UNDEFINED`，不实现。

### 4.3 `format_compliance`

| 属性 | 值 |
|---|---|
| **业务含义** | 响应对该类任务输出格式要求的符合程度。 |
| **输入字段** | `cases[].judge.metrics.format_score`（float）、`cases[].judge.checks.format_ok`（bool） |
| **计算规则** | 直接读取 `format_score`；`format_ok == (format_score >= 0.5)` |
| **数据类型** | `float` |
| **单位** | ratio `[0.0, 1.0]` |
| **聚合方式** | case 级；run 级仅对**格式相关类别**（`json_output` / `coding_task`）聚合 |
| **缺失值处理** | `metrics.format_score` 缺失 → `null` + `status="missing"`。空响应分支**不产出该字段**（`src/AIQE/judge.py:82-89` 提前 return）→ 必须处理为 `null`，不得当作 0 |
| **适用场景** | 结构化输出任务的专项质量监控 |
| **最小测试用例** | 合法 JSON → `1.0`；含花括号但解析失败 → `0.5`；纯文本 → `0.0`（已有 `test_format_*` 系列覆盖） |
| **已实现状态** | `IMPLEMENTED` |

> ⚠️ **类别适用性限制（必须随指标展示）**
>
> `_check_format()` 对 `chat` / `translation` / `edge_case` **恒返回 1.0**
> （`src/AIQE/judge.py:176`，并有
> `test_format_check_not_applied_to_chat_category` 锁定）。
>
> 因此在这三个类别上 `format_compliance` 是**常数 1.0，零信息量**。
> Dashboard **不得**把全量用例的 `format_compliance` 求平均后
> 当作「格式合规率」展示——那只会稀释成接近 1.0 的无意义数字。
> 正确做法：只对 `json_output` / `coding_task` 类别的用例聚合，
> 并在无该类用例时返回 `null` + `status="not_applicable"`。

### 4.4 `baseline_delta`

| 属性 | 值 |
|---|---|
| **业务含义** | 当前评分相对基线的变化量。正=改善，负=退化。 |
| **输入字段** | `cases[].regression.delta`、`regression.baseline_score`、`regression.current_score` |
| **计算规则** | 直接读取 `delta`（= `current_score - baseline_score`） |
| **数据类型** | `float` |
| **单位** | score delta，区间 `[-1.0, 1.0]` |
| **聚合方式** | case 级；run 级取 `mean`（须同时给出 `regression_count`，否则均值会掩盖个别大幅退化） |
| **缺失值处理** | `regression.baseline_score is null`（状态 `new`）→ `delta` 为 `0.0` 但**无意义**，必须置 `null` + `status="no_baseline"`。**这是当前实现的一个真实陷阱** —— 见下 |
| **适用场景** | 逐用例排查退化原因 |
| **最小测试用例** | 基线 0.8 → 当前 0.5 → 期望 `delta = -0.3`、`status="regression"`；无基线 → 期望 `delta = null` |
| **已实现状态** | `IMPLEMENTED`（读取规则明确） |

> ⚠️ **`status="new"` 时 `delta=0.0` 是陷阱**
>
> `RegressionResult` 在无基线时返回 `delta=0.0`
> （`src/AIQE/regression.py:84-90` 与 `:94-100`）。
> 这个 `0.0` 表示「无基线可比」，**不是**「无变化」。
> 若 Dashboard 直接对 `delta` 求平均，所有 `new` 用例会以 0 参与，
> 稀释真实退化幅度。
>
> 契约层处理：`baseline_delta` 在 `status == "new"` 时置 `null`，
> 并在 `MetricRecord.status` 中记录 `"no_baseline"`。
> 这是**契约层的显式修正**，不修改 `RegressionResult` 本身。

### 4.5 `severity_distribution`

| 属性 | 值 |
|---|---|
| **业务含义** | 按严重程度分档的失败用例分布（如 critical / major / minor）。 |
| **输入字段** | **无 severity 字段** |
| **计算规则** | **无法计算** |
| **数据类型** | `dict[str, int]`（若将来实现） |
| **单位** | distribution |
| **聚合方式** | run 级 |
| **缺失值处理** | 恒为 `null`，`status = "undefined"` |
| **适用场景** | （暂不适用） |
| **最小测试用例** | 无法编写——需先定义 severity 分类规则 |
| **已实现状态** | **`UNDEFINED`** |

**为什么是 `UNDEFINED`**：全仓库 `grep -ri severity` **零命中**。
现有可用的失败信号只有：

- `judge.checks`：`empty_response` / `length_ok` / `keywords_match` / `format_ok`（4 个 bool）
- `judge.reasons`：自由文本列表
- `judge.metrics`：`response_length` / `keyword_hits` / `keyword_total` / `format_score`

这些都是**正交的检查项**，没有天然的严重度排序。
把 `checks` 硬映射为 severity（例如「格式错=critical」）是
**主观赋权**，需要领域论证与用户确认，不属于本轮可自主决定的范围。

**本轮处置**：标记 `UNDEFINED`。作为替代，Dashboard 直接展示
`judge.checks` 的 4 个布尔项分布，见 [看板实现](../../src/AIQE/dashboard.py)。

---

## 5. P2 —— 资源指标

### 5.1 `input_tokens`

| 属性 | 值 |
|---|---|
| **业务含义** | 输入（prompt）消耗的 token 数。 |
| **输入字段** | **不存在** |
| **计算规则** | **无法计算** |
| **数据类型** | `int`（若将来实现） |
| **单位** | tokens |
| **聚合方式** | case 级；run 级求和 |
| **缺失值处理** | 恒为 `null`，`status = "unavailable"` |
| **适用场景** | （暂不适用） |
| **最小测试用例** | 无法编写——无数据来源 |
| **已实现状态** | **`UNAVAILABLE`** |

**为什么是 `UNAVAILABLE`**：`grep -rniE 'prompt_eval|input_token|prompt_token' src/ tests/ examples/`
**零命中**。数据模型中的 token 字段只有两个，**都指输出**：

| 字段 | 位置 | 含义 |
|---|---|---|
| `GenerateResult.tokens_generated` | `src/AIQE/protocol.py:131` | 输出 token |
| `ExecutionResult.tokens_generated` | `src/AIQE/runner.py:47` | 输出 token |

`OllamaRunner` 只读 `eval_count`（输出），**未读 `prompt_eval_count`**（输入）
（`src/AIQE/schema.py:200`）——即使后端提供了输入 token 数，当前代码也丢弃了它。

**注意 `case.prompt` 是原始文本，不是 token 数**。
若用 `len(prompt)` 粗估，会得到**字符数而非 token 数**，
且中文/英文/代码的换算比完全不同。§0 规则 2 禁止这种降级。

### 5.2 `output_tokens`

| 属性 | 值 |
|---|---|
| **业务含义** | 输出（响应）消耗的 token 数。 |
| **输入字段** | `cases[].execution.tokens_generated`（int） |
| **计算规则** | 直接读取 |
| **数据类型** | `int` |
| **单位** | tokens |
| **聚合方式** | case 级；run 级求和与 `mean` |
| **缺失值处理** | 执行失败时 `tokens_generated == 0`（异常分支硬编码）。**该 0 不是「零 token 输出」，必须置 `null`**——失败用例根本没有输出 |
| **适用场景** | 成本估算输入、输出长度回归 |
| **最小测试用例** | mock 后端 `simple_chat` → `18`；执行失败 case → 期望 `null` |
| **已实现状态** | `IMPLEMENTED`（读取规则明确） |

> ⚠️ **精度披露：多数路径下这是估算值，不是真实 token 数**
>
> | 来源 | 计算方式 | 性质 |
> |---|---|---|
> | `MockEvalBackend` | `max(1, len(text) // 2)` | **字符数估算** |
> | `make_generate_sync_default` | `max(1, len(text))` | **字符数估算** |
> | `OllamaRunner` | `data["eval_count"]` | **真实 token 数** |
>
> 因此 `output_tokens` **必须携带 `source_precision` 标记**
> （`measured` / `estimated`）。Dashboard 不得把估算值与实测值
> 混在同一趋势线上比较。契约层用 `MetricRecord.precision` 承载。

### 5.3 `tokens_per_second`

| 属性 | 值 |
|---|---|
| **业务含义** | 生成速度。 |
| **输入字段** | `cases[].execution.tok_per_sec`（float） |
| **计算规则** | 直接读取（`ExecutionResult.tok_per_sec`） |
| **数据类型** | `float` |
| **单位** | tokens/second |
| **聚合方式** | case 级；run 级取 `p50` / `mean` |
| **缺失值处理** | 执行失败时 `tok_per_sec == 0.0`（硬编码）→ 置 `null`。**不得当作「0 速度」参与聚合** |
| **适用场景** | 性能回归、后端对比 |
| **最小测试用例** | mock 后端 → `15.0`；失败 case → `null` |
| **已实现状态** | `IMPLEMENTED`（读取规则明确） |

> ⚠️ **与 §3.6 相同的 mock 限制**：mock 后端硬编码 `tok_per_sec=15.0`
> （`src/AIQE/backends/mock.py:111`），仅可验证管道，不可得性能结论。
> 另注意：在估算路径下 `tok_per_sec` 的分子是字符数估算，
> 故该值是「字符/秒」而非真实「token/秒」。同样需要 `precision` 标记。

### 5.4 `estimated_cost`

| 属性 | 值 |
|---|---|
| **业务含义** | 本次评估的估算费用。 |
| **输入字段** | **不存在**（无价格表、无模型计价元数据） |
| **计算规则** | **无法计算** |
| **数据类型** | `float`（若将来实现） |
| **单位** | currency（币种未定义） |
| **聚合方式** | run 级 |
| **缺失值处理** | 恒为 `null`，`status = "unavailable"` |
| **适用场景** | （暂不适用） |
| **最小测试用例** | 无法编写 |
| **已实现状态** | **`UNAVAILABLE`** |

**为什么是 `UNAVAILABLE`**：

1. 全仓库无价格表（`grep -riE 'cost|price|pricing' src/` 仅命中
   `boundary_cases.py` 中一个名为 `calculate_total(prices)` 的**测试用例示例代码**，
   与计费无关）。
2. **AIQE 的定位是本地推理评估**（MLX / Ollama / llama.cpp），
   这些路径**没有按量计费**——成本概念不适用。
3. 即使未来接入付费 API，也需要：① `input_tokens` 先可用（当前 `UNAVAILABLE`）；
   ② 用户提供价格表；③ 明确币种与汇率口径。
4. 本轮**禁止调用付费模型 API**，因此无真实计费数据可校准。

---

## 6. 诚实披露：`IMPLEMENTED` 的确切含义

**必须澄清一处容易误读的地方。**

§2 总表把 `case_pass_rate` / `execution_success_rate` /
`execution_error_count` / `regression_count` 标为 `IMPLEMENTED`，
含义是：

> **它们的输入字段已存在于持久化报告中，且计算规则完全确定、
> 无歧义、不依赖脆弱推断。**

而**不是**：

> 已经存在一个 `MetricRecord` 聚合层在自动产出这些指标。

本轮新增的 `src/AIQE/contract.py` **实现了** `MetricRecord` 与
`compute_run_metrics()`，把这 9 个 `IMPLEMENTED` 指标从
「报告 JSON 中的原始字段」提升为「结构化指标记录」。
可运行[契约测试](../../tests/test_contract.py)验证指标计算和缺失值行为。

对 `UNAVAILABLE` / `UNDEFINED` 的 5 个指标，
`contract.py` **不产出数值**，只产出 `status` 说明缺失原因 ——
这是**有意的**，符合 §0 规则 1 与规则 2。

---

## 7. 待办与阻塞登记

| # | 事项 | 阻塞类型 | 解除条件 |
|---|---|---|---|
| M-1 | `timeout_count` 无法可靠计算 | **设计缺口** | 在 `ExecutionResult` 引入结构化 `error_kind` 字段；需评估对 6 个现有错误契约测试的影响 |
| M-2 | `judge_agreement` 无法计算 | **无第二评分源** | 引入第二个确定性评分器（路径 A）或经批准的可选 LLM 裁判（路径 B，需用户授权） |
| M-3 | `severity_distribution` 无法计算 | **需领域决策** | 用户确认严重度分档规则（不得由 Agent 主观赋权） |
| M-4 | `input_tokens` 无数据来源 | **数据模型缺口** | 后端适配层补采 `prompt_eval_count` 等输入 token 字段 |
| M-5 | `estimated_cost` 不适用 | **定位不符 + 无价格表** | 仅在接入付费 API 后有意义；需用户提供价格表 |
| M-6 | `judge_version` 无独立版本标识 | **元数据缺口** | 为 `OutputJudge` 引入独立版本号，评分规则变更时递增 |
| M-7 | `_compute_summary().regressions` 合并了 `regression`+`degraded` | **口径差异（有意保留）** | 若需统一，属公共 API 行为变更，需用户批准 |

---

## 8. 指标与现有代码的对应索引

| 指标 | 输入字段来源（文件:行） | 锁定测试 |
|---|---|---|
| `case_pass_rate` | `src/AIQE/reporter.py:119` | `test_report_summary_counts` |
| `execution_success_rate` | `src/AIQE/runner.py:57-59` | `test_execution_runner_successful` / `_runtime_error` |
| `execution_error_count` | `src/AIQE/runner.py:52` | `test_error_is_never_none_on_failure` |
| `timeout_count` | —（无来源） | `test_execution_runner_timeout_error`（证明只有文本匹配） |
| `regression_count` | `src/AIQE/regression.py:19` | `test_full_pipeline_with_regression` |
| `latency_ms` | `src/AIQE/runner.py:48` | `test_execution_runner_successful` |
| `judge_score` | `src/AIQE/judge.py:138` | `test_judge_*` 系列（10+） |
| `judge_agreement` | —（无来源） | — |
| `format_compliance` | `src/AIQE/judge.py:118` | `test_format_*` 系列（7 个） |
| `baseline_delta` | `src/AIQE/regression.py:35` | `test_full_pipeline_with_regression` |
| `severity_distribution` | —（无来源） | — |
| `input_tokens` | —（无来源） | — |
| `output_tokens` | `src/AIQE/runner.py:47` | `test_execution_runner_successful` |
| `tokens_per_second` | `src/AIQE/runner.py:49` | `test_execution_runner_successful` |
| `estimated_cost` | —（无来源） | — |

---

## 9. 版本与变更策略

- **本规范版本**：`aiqe.metrics/0.1.0`（与结果契约 `aiqe.result/0.1.0` 配套）
- **指标增删改**：任何计算规则变更都必须递增
  `MetricRecord.metric_version`，并在 CHANGELOG 中记录。
- **向后兼容**：新增指标是兼容变更；**修改既有指标的计算规则是不兼容变更**，
  需用户批准，且必须提供新旧口径的并行期。
