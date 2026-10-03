# 合成测试样本（Synthetic Fixtures）

> **本目录下的一切数据都是人工构造的合成样本。**
> 不含任何真实质量数据、个人数据、聊天记录或来自其他项目的记录。
> 全部文件为 `source_type = "synthetic"`、`data_classification = "public_synthetic"`。

---

## 1. 生成入口（唯一可信来源）

```bash
# 仓库采用 src/ 布局，未安装包时需要显式指定 PYTHONPATH
PYTHONPATH=src python -m AIQE.synthetic tests/fixtures/synthetic
```

> 若已执行 `pip install -e .`，可直接 `python -m AIQE.synthetic tests/fixtures/synthetic`。
> 直接裸跑会得到 `ModuleNotFoundError: No module named 'AIQE'`——
> 这不是生成器缺陷，而是 src/ 布局的正常行为。
> （`pytest` 不受影响：`pyproject.toml` 中已配置 `pythonpath = ["src"]`。）

生成器实现：[`src/AIQE/synthetic.py`](../../../src/AIQE/synthetic.py)
生成器标识：`aiqe.synthetic/0.1.0`

生成器是**确定性**的——固定时间戳（`2026-09-22T00:00:00+00:00`），
不用 `datetime.now()`。因此重复运行产出**逐字节相同**的文件。

这一性质由 `tests/test_synthetic_fixtures.py::test_committed_fixtures_match_generator_output`
锁定：若改了生成器却忘了重新生成 fixtures，测试会失败并提示重新生成命令。

---

## 2. 信任边界（⚠️ 必读）

### 本目录 + `content_digest` 能证明

- ✅ 文档结构符合结果契约（`aiqe.result/0.1.0`）
- ✅ 文档由上述受信生成入口产出
- ✅ 文档自生成后未被改动（防篡改证据）

### 不能证明

- ❌ 文档底层数据在语义上「真的是」合成数据

**掌握生成入口的一方可以把任意数据喂进来并得到合法摘要。**

因此：

> **验证合成数据结构 ≠ 证明数据来源真实可信。**

`source_type="synthetic"` 是**声明**，`content_digest` 是**防篡改证据**，
二者都不构成「数据来源真实可信」的证明。

真实数据接入的控制手段是**独立导入契约的字段白名单**（默认拒绝）
与**授权门禁 G1–G6**，见
[`docs/architecture/AIQE_MYFRI_IMPORT_CONTRACT_DRAFT.md`](../../../docs/architecture/AIQE_MYFRI_IMPORT_CONTRACT_DRAFT.md)。
本目录的存在**不会**放宽那条路径的任何限制。

---

## 3. 目录结构

```
tests/fixtures/synthetic/
├── README.md          # 本文件
├── valid/             # 合法样本 —— 必须通过契约校验
└── invalid/           # 非法样本 —— 必须被拒绝（且原因码符合预期）
```

### `valid/` —— 合法样本

| 文件 | 承载 Case | 内容 |
|---|---|---|
| `run_a_normal_pass.json` | A 正常通过 | 2 用例，执行成功且评分通过 |
| `run_b_case_fail.json` | B 测试失败 | 执行全成功，一半用例评分不通过 |
| `run_c_execution_error.json` | C 执行异常 | 一半用例 `error` 非 null，judge 强制 0 分 |
| `run_d_timeout.json` | D 超时 | `error` 文本含 `timed out`（**仅文本，无结构化分类**） |
| `run_e_missing_metric.json` | E 指标缺失 | 空响应 → 不产出 `format_score`（缺失，非 0） |
| `run_g_baseline.json` | G 基线 | 数据集 v1，全通过 |
| `run_g_candidate.json` | G 候选 | 同源，无显著退化 |
| `run_h_candidate.json` | H 有效回归 | 同数据集同评分器、**换模型** → 检出 2 例 regression |
| `run_l_dataset_v2.json` | L 不可比 | 分数与 H 完全相同，**仅数据集版本不同** → 不可比 |
| `run_m_empty_cases.json` | 附加边界 | 空用例集：比例指标 null，计数指标 0 |

### `invalid/` —— 非法样本

每份都以合法样本为基底，**只注入单一缺陷**，然后重算摘要——
这样拒绝原因唯一，测试断言才有意义。

| 文件 | 承载 Case | 注入的缺陷 | 预期原因码 |
|---|---|---|---|
| `case_f_invalid_metric_type.json` | F 非法类型 | `judge.score = "0.95"`（字符串） | `INVALID_TYPE` |
| `case_i_schema_incompatible.json` | I 版本不兼容 | `schema_version = "aiqe.result/1.0.0"` | `SCHEMA_VERSION_INCOMPATIBLE` |
| `case_j1_sensitive_key.json` | J 敏感字段 | 注入 `api_key` 字段 | `SENSITIVE_FIELD_DETECTED` |
| `case_j2_sensitive_value.json` | J 敏感取值 | 响应含邮箱地址 | `SENSITIVE_VALUE_DETECTED` |
| `case_k1_no_generator.json` | K 伪造标记 | `generator = ""` | `SYNTHETIC_GENERATOR_UNTRUSTED` |
| `case_k2_untrusted_generator.json` | K 伪造标记 | `generator = "untrusted.generator/9.9.9"` | `SYNTHETIC_GENERATOR_UNTRUSTED` |
| `case_k3_digest_mismatch.json` | K 篡改证据 | 生成后改分，**不重算摘要** | `SYNTHETIC_DIGEST_MISMATCH` |

> **注**：除 `case_k3` 外，全部非法样本的 `content_digest` 都是**有效的**。
> 这由 `test_invalid_fixture_rejection_is_not_caused_by_broken_digest` 强制——
> 否则「测试通过」不能证明目标规则生效，可能只是被摘要检查顺手拦下。

---

## 4. 数据隔离

- 本目录全部内容**可以**进入 Git（合成数据，`public_synthetic`）。
- 生成器不读取任何外部路径、不联网、不依赖环境变量。
- 真实质量数据**禁止**写入本目录，也禁止写入本仓库任何位置。
- `test_fixtures_contain_no_real_data_markers` 会检查样本中不含
  本机绝对路径等非合成来源标记。

> 该检查是**结构性检查**，不是「证明数据是合成的」——见 §2 信任边界。

---

## 5. 相关文档

- 契约规范：[`docs/architecture/AIQE_RESULT_CONTRACT_V01.md`](../../../docs/architecture/AIQE_RESULT_CONTRACT_V01.md)
- 指标规范：[`docs/architecture/AIQE_METRICS_V01.md`](../../../docs/architecture/AIQE_METRICS_V01.md)
- 测试：`tests/test_contract.py`、`tests/test_synthetic_fixtures.py`
