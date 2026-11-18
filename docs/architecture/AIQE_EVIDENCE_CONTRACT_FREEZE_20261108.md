# AIQE 看板证据契约冻结（v0.1-freeze）

- 日期：2026-11-08
- 状态：**FROZEN（契约冻结）/ 实现未开始**
- 适用范围：`AIQE.dashboard`、`aiqe.result/0.1.0`（`contract.py`）、`aiqe.workbench/0.1.0`（`workbench_contract.py`）
- 冻结目的：在缺少真实 Runner 来源证明（provenance）和人工 Gold 标注的情况下，先把“看板可以声称什么、不能声称什么”固定下来，后续接入真实数据时只能按本契约扩展，不能反向放宽。

## 1. 冻结时的事实

| 项 | 当前状态 | 结论 |
|---|---|---|
| 公开看板数据 | 只来自 `aiqe.synthetic/0.1.0` 生成器，`source_type=synthetic`，带 `content_digest` | 只能展示“框架如何呈现质量”，不代表任何真实模型或设备质量 |
| 本地导入数据 | `local_import`，结果-only，`internal` 分级，不进入 Git | 可在本机看板查看，不能公开、不能作为发布证据 |
| Runner 来源证明 | 结果文档里的 `model_id` / `backend_id` 是声明值；`workbench` 的 Q6 单元格是“未来 Runner 提供的观测”，契约不认证其来源 | **缺口 G-R**：没有可验证的 Runner provenance |
| 人工 Gold | 没有任何经人工复核的参考标签；校准夹具仍是 `synthetic_proposal` | **缺口 G-G**：语义评分不能作为必需门禁，只能是探索性信号 |
| 工时证据 | `effort` 中的 `measured` 只是声明，契约从不输出 verified 人工分钟数 | 维持现状，不在看板上显示“已验证工时” |

## 2. 证据等级（Evidence Tier）

每条运行记录在看板上必须且只能落在一个等级。等级由契约推导，**不接受文档自报**。

| 等级 | 名称 | 进入条件 | 看板可声称 | 看板禁止声称 |
|---|---|---|---|---|
| E0 | 合成展示 | `source_type=synthetic` + 受信生成器 + digest 一致 | 呈现方式、聚合口径、缺失语义 | 任何模型/设备/业务质量结论 |
| E1 | 本地结果 | `local_import` 或 `local_test`，结果-only，分级 `internal` | 本机趋势与回归观察 | 公开发布、跨机器比较、发布放行 |
| E2 | Runner 证明 | E1 全部条件 + §3 的 `runner_provenance` 完整且摘要校验通过 | 同条件可比的执行质量与回归结论 | 语义质量（幻觉、正确性）的必需判定 |
| E3 | Gold 校准 | E2 全部条件 + §4 的已批准 Gold 包 + 评分器就绪门禁为 READY | 对已校准维度给出语义质量结论（附置信区间与分类计数） | 未校准维度、跨项目排名 |

规则：

1. 等级只能由低到高逐级满足，任一条件缺失即降级，不得“部分升级”。
2. 不同等级的运行**不得**在同一比率、趋势线或透视单元格内合并；跨等级只能并列展示。
3. 缺字段按契约既有语义处理（`missing` / `unavailable` / `N/A`），**不补 0、不沿用上一次值**。
4. 当前冻结版本下，公开看板只会出现 E0；E1 只出现在本机产物；E2/E3 在实现与评审完成前一律不可达。

## 3. Runner provenance 最小字段（E2 门槛）

以下字段组成 `runner_provenance` 对象。任一字段缺失 → 记录为 `INVALID_PROVENANCE`，运行降为 E1，而不是 `UNKNOWN` 后继续使用。

| 字段 | 类型 | 规则 |
|---|---|---|
| `runner_id` | string | Runner 实现的稳定标识，如 `aiqe.runner/<name>` |
| `runner_version` | semver | Runner 自身版本 |
| `framework_version` | string | AIQE 版本；有 Git 时附提交摘要 |
| `execution_mode` | enum | `offline_mock` / `local_device` / `remote_endpoint` |
| `backend_type` | enum | 与 `protocol.BackendType` 一致 |
| `requested_model` | string | 调用方请求的模型名或别名 |
| `resolved_model_id` | string \| null | 由后端响应给出；拿不到时为 `null`，**不得用别名代填** |
| `model_revision_digest` | string \| null | 不可变模型修订或权重摘要；为 `null` 时该运行最高只能到 E2，不能参与 E3 |
| `generation_config_digest` | sha256 | 温度、top_p、最大输出长度等生成参数的规范化 JSON 摘要 |
| `dataset_id` / `dataset_version` / `dataset_digest` | string / string / sha256 | 用例集身份与内容摘要 |
| `judge_id` / `judge_version` | string | 与结果契约中的同名字段一致 |
| `host_class` | string | 硬件/环境类别（如 `apple-silicon-16g`），**不得**含主机名、用户名、IP、绝对路径 |
| `started_at` / `finished_at` | RFC3339 UTC | 运行起止时间 |
| `records_digest` | sha256 | 对全部用例结果记录的规范化摘要，用于发现事后篡改 |
| `attestation` | object | `{ "kind": "none" \| "signed", "signer": string \| null }`；`none` 合法但必须显式写出 |

说明：

- 冻结版本**不要求签名**（`attestation.kind = none` 可以进入 E2），但看板必须显示“未签名”。签名机制属于后续独立变更。
- prompt、response、工具参数、自由文本错误仍不进入看板投影（沿用 `AIQE_MULTIDIM_QUALITY_E2E_20261024.md` §7 的边界）。

## 4. 人工 Gold 最小要求（E3 门槛）

Gold 包沿用评分器校准草案的字段设计，冻结版本只锁定看板必须检查的子集：

| 检查项 | 规则 |
|---|---|
| 包身份 | `pack_id`、`pack_version`、`dataset_digest`、`rubric_id/version/digest` 全部存在且与运行一致 |
| 标签来源 | 每条 `label_origin ∈ {human_reviewed, adjudicated}`；`synthetic_proposal` 不是 Gold |
| 复核状态 | 全部为 `AGREED` 或 `ADJUDICATED`，`DISPUTED` 数为 0 |
| 独立性 | 至少两名独立复核者；作者不能单独批准自己的包 |
| 批准 | `approval.status = APPROVED`，有批准角色与日期 |
| 隐私 | 不含姓名、账号、地址、电话、凭据或真实记忆；真实来源须有显式授权依据 |
| 局限 | `limitations` 非空时看板必须原样展示 |

评分器就绪门禁（READY / NOT_READY / UNKNOWN）的判定逻辑不在看板内实现，看板只消费其结果；任何缺项都是 `NOT_READY` 或 `UNKNOWN`，**永远不是 PASS**。

## 5. 看板展示规则（冻结）

1. 每个运行卡片和表格行显示证据等级徽标（E0–E3）；E0 常驻“合成数据”标识。
2. 语义类区块（幻觉、正确性）在没有 E3 数据时显示“未校准 / 未评估”及启用条件，不显示数值。
3. 回归对比要求两侧等级相同且 `generation_config_digest`、`dataset_digest`、`judge_version` 一致；否则标记“不可比”，不输出 delta。
4. 不输出没有校准依据的“质量置信度”百分比。
5. 公开产物（Git 工作树、开源示例页面）只允许 E0。

## 6. 变更规则

- 本文件冻结后，字段只能**新增可选字段**或**收紧规则**；删除字段、放宽等级条件、改变缺失语义都需要新契约版本（`v0.2`）和独立评审。
- 首个实现变更应同时提交：`runner_provenance` 校验器、等级推导函数、跨等级不合并的聚合测试、缺字段降级测试、主机名/路径泄漏拒绝测试。
- 实现完成前，`ALLOWED_SOURCE_TYPES` 的默认值（仅 `synthetic`）保持不变。

## 7. 解除冻结的条件

| 缺口 | 解除条件 | 负责人 |
|---|---|---|
| G-R Runner provenance | 至少一个真实 Runner 产出满足 §3 的运行，校验器与测试合入，独立评审通过 | 实现方 + 评审方 |
| G-G 人工 Gold | 至少一个满足 §4 的已批准 Gold 包，评分器就绪门禁结果为 READY | 项目负责人（人工复核不可由模型代替） |
