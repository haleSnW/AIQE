# Changelog

本仓库所有值得记录的变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

All notable changes to this repository. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **统一结果数据契约 `aiqe.result/0.1.0`** — `AIQE.contract`：运行/用例/指标校验、
  内容摘要、敏感字段默认拒绝；来源默认只接受受信生成器产出的 `synthetic`。
  配套指标口径 `aiqe.metrics/0.1.0` 与运行级回归对比 `AIQE.comparison`
  （与 `RegressionAnalyzer` 共用 `classify_delta` 阈值）。
- **公开合成数据生成器** — `AIQE.synthetic`（`aiqe.synthetic/0.1.0`）与
  `tests/fixtures/synthetic/` 有效/无效夹具。
- **离线质量看板** — `AIQE.dashboard`：总览、回归、趋势、多维分析、数据完整性五区，
  单文件 HTML、零 CDN、`file://` 直接打开、亮暗主题与移动布局；示例
  `examples/showcase_dashboard.py`。
- **多维质量分析** — `AIQE.dashboard_analysis` 加法聚合层：按数据集、评分器、模型、
  后端、来源、分级切换柱状图、构成环图和精确透视表；比率合并分子/分母，
  token 实测与估算分离，幻觉与火焰图缺数据时显式显示 unavailable。
- **看板来源控制** — `--allow-source` 显式放开非合成来源；出现非合成来源时横幅常驻
  「禁止提交入库、禁止对外分享」警示；非 `public_synthetic` 产物拒绝写入 Git 工作树。
- **工作项证据契约 `aiqe.workbench/0.1.0`** — `AIQE.workbench_contract` /
  `workbench_adapter`：Q5/Q6/Q7 展示事实，声明值不冒充已验证事实；示例
  `examples/showcase_workbench.py`。
- **OpenAI 兼容后端** — `AIQE.backends.openai_compatible` 与标准库 HTTP 传输
  `AIQE.http_transport`：非流式、超时与响应大小有界、禁止重定向、凭据不进 repr、
  `resolved_model_id` 只取自响应（缺失为 `None`，不以别名代填）。
- **看板浏览器 E2E（可选）** — `tools/dashboard_browser_check.cjs`（Playwright 为开发工具，
  非运行时依赖）。
- **看板证据契约冻结** — `docs/architecture/AIQE_EVIDENCE_CONTRACT_FREEZE_20261108.md`：
  定义 E0–E3 证据等级、Runner provenance 最小字段与人工 Gold 最小要求（仅冻结契约，实现未开始）。

### Changed

- `RegressionAnalyzer` 的退化阈值提取为模块级 `DEGRADATION_THRESHOLD` 与
  `classify_delta()`，行为不变。
- `.gitignore` 增加 `outputs/`、`.playwright-cli/` 与 macOS `._*` 伴随文件。

## [v0.1.0] - 2026-08-18

### Initial open-source release

首次开源发布。这是 AIQE 的 Alpha 参考实现：评估流水线完整、测试全绿，
可通过 Backend Protocol 接入任意推理后端。

Initial open-source release. This is AIQE's Alpha reference implementation:
the evaluation pipeline is complete with a green test suite, and any inference
backend can be plugged in via the Backend Protocol.

**Features:**

- deterministic evaluation — 确定性评分：关键词 / 长度 / 格式 三维综合（无 LLM 裁判）
- backend protocol — 统一后端接入契约（BackendType / ModelProfile / GenerateOptions / GenerateResult / Backend）
- execution runner — 执行器：trace_id / payload_hash 完整性校验，错误显式传播
- regression detection — 回归检测：对比历史基线（pass / degraded / regression / new）
- report generation — JSON 报告 + 控制台条形图摘要
- boundary testing — 18 个内置用例（标准 4 + 扩展 6 + 边界 8）
- mock backend — 内置确定性 mock 后端：零依赖、零网络、30 秒出报告
- CI — GitHub Actions（Python 3.10 / 3.11 / 3.12）
- bilingual docs — 中英文双语文档（README / INTEGRATION / methodology）

### Fixes

- 评分器：格式分（format_score）真实计入最终综合分——此前格式错误（如
  要求 JSON 却输出纯文本）不会降低最终分数，现已修复并有回归测试锁定
  （`tests/test_format_regression.py`）
- 后端标识：LocalRunner 的 backend 标识从内部占位名改为公开名 `local`，
  报告数据不再携带内部信息
- 清理仓库中的内部项目痕迹（注释 / 文档 / 元数据），全部改为公开描述

### Changed

- README 重构：新增后端支持矩阵（Built-in / Example / Skeleton /
  Protocol Compatible 状态明确）；捐赠信息移至文末并新增海外渠道
  （GitHub Sponsors / PayPal）

[v0.1.0]: https://github.com/haleSnW/AIQE/releases/tag/v0.1.0
