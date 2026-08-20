# Changelog

本仓库所有值得记录的变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

All notable changes to this repository. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
