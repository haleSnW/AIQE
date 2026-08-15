---
name: aiqe-testing
description: AIQE 四档测试手动触发命令。触发场景：用户输入 /aiqe-smoke、/aiqe-full、/aiqe-regression、/aiqe-acceptance 任一命令，或需要手动跑测试档位（真机/人工判断/soak/基线更新）时。加载本 skill 后按命令映射执行，并把输出归档。
---

# AIQE 四档测试手动触发（skill 骨架）

配套文档：`docs/methodology/test-trigger-strategy.md`（四档 × 自动/手动
矩阵）；`docs/INTEGRATION.md`（CI 接入与基线 SOP）。

## 触发条件

以下情况**必须**手动触发（不能等自动 hook）：

- 需要真机/真实模型（CI 沙盒无模型或资源受限）
- 需要人工判断（WARN 处理、MANUAL_REVIEW 裁决、灰度观察）
- 长时间 soak / 稳定性验证
- 基线更新决策（更新前必须跑一次 ③ 回归档）

## 命令映射

| 命令 | 跑什么 | 预期耗时 | 说明 |
|---|---|---|---|
| `/aiqe-smoke` | ① 冒烟：单元 + 接口契约测试（`pytest tests/ -q`） | 秒~1 分钟 | 任何改动后跑；不过 → 停下修，不进下一档 |
| `/aiqe-full` | ② 全量：集成 + 功能 + 黑盒（`pytest -q` + `examples/quick_score.py` + 全量用例集） | 1~5 分钟 | 每日/合并前；报告归档 |
| `/aiqe-regression` | ③ 回归：基线对比 + 性能（`examples/regression_compare.py`；换模型时用 `examples/ollama_backend.py` + 基线对比） | 分钟级（真机可小时级） | 换模型/改评分器/基线更新时；输出回归结论表 |
| `/aiqe-acceptance` | ④ 验收：端到端 + 稳定性 + 安全 + UI + 灰盒（真机 gated 用例 + soak + 门禁五状态判定） | 分钟~小时级 | 发布前/需求完成时；需人工回填 MANUAL_REVIEW 结论 |

## 执行纪律（与 skills/testing-agent/SKILL.md 一致）

- 每条命令**实际运行**，回贴输出并标注「与预期一致/不一致」；
- 涉及真机/网络：环境不具备时如实报告 NOT_ASSESSED，绝不假装跑过；
- 手动档必须留痕：谁、何时、结果，归档进报告或任务书回贴；
- 四原则：能自动不手动、快档先行（冒烟不过不进全量）、回归永远先于
  验收、手动必须留痕。

## 自定义点

- 各档实际命令按项目调整（如 CI 已有冒烟档，/aiqe-smoke 仅跑本地增量）；
- 本 skill 与 skills/testing-agent/SKILL.md 配套：前者管「什么时候跑
  什么」，后者管「写测试/跑测试的动作纪律」。
