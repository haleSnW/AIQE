# AIQE —— 测试左移（Shift-Left）AI 质量评估框架参考实现

> 在生成之前先跑分。用确定性评分，把模型质量回归挡在发布之前。

[简体中文](README.md) | [English](README.en.md)

> **一句话定义**：AIQE 是一个开源的**测试左移（Shift-Left）AI 质量评估框架**——
> 在 LLM 应用与 AI Agent 部署到生产环境之前，用确定性评分对它们做质量评估与
> 回归测试，在发布前把模型质量回归挡下来。

AIQE 是一套面向**大模型与 agent 开发、以及 AI 产品开发**的质量评估框架
参考实现：**用例集 → 执行（Backend Protocol）→ 确定性评分 → 回归对比 →
JSON 报告**。它在开发流程中**同步配合开发 harness 使用**——随每次构建/
改动跑分与回归，而不是事后审计。**产品形态无关**：无论被评估对象是
系统/OS、模型、算法、APK 还是 Web 产品，都复用同一套「用例 → 评分 →
回归」流程。

- 纯标准库实现，运行时零依赖；唯一的开发依赖是 pytest
- 默认 mock 后端：确定性响应，无需模型、无需网络，30 秒出报告
- 通过 Backend Protocol 接入任意推理后端（MLX / Ollama / llama.cpp / 自研）
- 本仓库是独立分发的参考实现（Apache-2.0）：代码完整、测试全绿，
  可直接使用、fork、改造

> **⚠️ 版本状态**：当前为 **v0.1.0 Alpha** 参考实现。核心链路（执行 →
> 评分 → 回归 → 报告）已完整并有测试保障；真实推理后端为「示例 / 骨架」
> 状态，接入细节见下文 [后端支持矩阵](#后端支持矩阵)。

---

## 目录

- [AIQE —— 测试左移（Shift-Left）AI 质量评估框架参考实现](#aiqe--测试左移shift-leftai-质量评估框架参考实现)
  - [目录](#目录)
  - [后端支持矩阵](#后端支持矩阵)
  - [2. 测试左移思想：为什么在生成前先跑分](#2-测试左移思想为什么在生成前先跑分)
  - [3. 适用对象：不同产品形态怎么用 AIQE](#3-适用对象不同产品形态怎么用-aiqe)
  - [4. AIQE 与现有 LLM 评估框架的对比](#4-aiqe-与现有-llm-评估框架的对比)
  - [5. 快速开始：mock 后端 30 秒出报告](#5-快速开始mock-后端-30-秒出报告)
  - [6. 框架结构](#6-框架结构)
  - [7. 方法论文档：分层、流程、协作、触发](#7-方法论文档分层流程协作触发)
  - [8. 与开发 harness 同步使用：pytest、CI、基线、换模型流程](#8-与开发-harness-同步使用pytestci基线换模型流程)
  - [9. 示例集：ollama 接入与回归对比](#9-示例集ollama-接入与回归对比)
  - [10. 测试触发策略：四档 × 自动/手动](#10-测试触发策略四档--自动手动)
  - [11. 模板集与配套 skill](#11-模板集与配套-skill)
  - [12. 开源协议](#12-开源协议)
  - [13. 捐赠支持](#13-捐赠支持)
  - [FAQ](#faq)
  - [关于作者](#关于作者)

---

## 后端支持矩阵

**先看这里**：AIQE 的评估流水线对后端类型一无所知——它只依赖
`AIQE.protocol.Backend` 这个接入契约。下表是各后端在本仓库中的
**真实状态**（v0.1.0），避免误认为所有后端都已开箱即用：

| 后端 | 状态 | 开箱即用？ | 说明 |
|---|---|---|---|
| **Mock Backend**（默认） | **Built-in** | ✅ 是 | `backends/mock.py` 确定性响应，零依赖零网络，CI/离线演示用它 |
| **Ollama Adapter** | **Example Adapter** | 🟡 实验性 | `examples/ollama_backend.py` 是接入示例；需本地 Ollama 服务与模型，按示例自行组装 |
| **MLX Backend** | **Skeleton Adapter** | 🟠 需自行集成 | `backends/mlx.py` 是骨架：结构完整但 `setup()` 明确报 `ImportError`，需自行安装 mlx-lm 并注入满足 Backend Protocol 的适配层 |
| **llama.cpp** | **Protocol Compatible** | 🟠 需外部适配层 | 仓库内无实现；只要实现 `AIQE.protocol.Backend`（`generate_sync` / `generate` / `backend_type` / `profile`）即可注入，流水线零改动 |

接入真实模型的完整契约见 [AIQE/protocol.py](src/AIQE/protocol.py)；
接入示例见 [examples/ollama_backend.py](examples/ollama_backend.py)。

---

## 2. 测试左移思想：为什么在生成前先跑分

传统 AI 应用的质量保障是「后置」的：模型上线后靠用户反馈、靠人工抽查、
靠事故复盘。问题出在——

- **反馈周期太长**：一次劣化从产生到被发现，往往以天/周计；
- **无法归因**：提示词改了？模型换版了？上下文变长了？后置反馈说不清；
- **没有基线**：没有数字就没有「回归」这个概念，全靠体感。

**测试左移（Shift-Left）** 把质量保障推到生成链路的**最前端**：在模型被
集成进产品之前，先让它跑一组固定的、可判分的任务。每个版本、每次提示词
改动、每个新模型，都先过一遍同样的试卷，拿到同样的分数，再和上一次的
分数对比。

```
                测试左移：生成前先跑分
  ┌──────────────────────────────────────────────────────┐
  │  用例集 (TestCase)                                    │
  │   ├─ chat / translation / json_output / coding_task   │
  │   └─ 边界/对抗/长上下文 扩展用例                        │
  │                                                       │
  │  执行器 (ExecutionRunner)  ← 注入任意 Backend          │
  │  评分器 (OutputJudge)     ← 确定性：关键词/长度/格式    │
  │  回归分析 (RegressionAnalyzer) ← 对比历史基线           │
  │  报告 (EvaluationReport)  ← JSON + 控制台摘要          │
  └──────────────────────────────────────────────────────┘
                           ↓
            分数下降 → 拒绝发布 / 触发排查
```

三个关键设计，让「跑分」这件事在本地、在开发期就能天天做：

1. **确定性评分，不依赖 LLM 裁判**：OutputJudge 只做关键词命中、长度检查、
   格式校验这三类可复现的判定（外加可选的 JSON/代码结构检测）。当前 mock 后端评分流程为确定性评分，相同输入得到一致结果——分数才能进基线、做回归。
2. **用例即资产**：用例集（含 8 个边界场景：超长输入、对抗性提示、多指令
   冲突、数字精确性等）本身就是对产品期望的编码。模型换版时先过用例集，
   而不是先上线。
3. **回归基线是硬门槛**：RegressionAnalyzer 对比当前分数与历史基线，
   下降超 0.15 判定为 regression。没有基线文件时自动记为 `new`，不误伤
   首次接入的模型。

> 一句话总结：**测试左移 = 把「模型行不行」从拍脑袋变成跑分，
> 把「什么时候发现退化」从发布后提前到发布前。**

---

## 3. 适用对象：不同产品形态怎么用 AIQE

AIQE 的流程与产品形态无关——「用例 → 评分 → 回归」对任何 AI 产品都成立，
区别只在于**用例编码的是什么**：

| 被评估对象 | 怎么用 AIQE |
|---|---|
| 系统/OS（含 agent 运行时） | 把 Agent 的预期决策行为编码成测试用例，用于验证 Agent 工作流输出质量和回归稳定性 |
| 模型（大模型/端侧模型） | 跑分与换版回归：全量用例集对比基线，五步流程（见第 8 节）定去留 |
| 算法（RAG/路由/排序/后处理） | 确定性输出回归：相同输入必须产出相同质量输出，分数变化即告警 |
| APK/Web 产品 | 产品功能用例（含 UI 输出断言）：把功能验收编码为用例，发布前过卷 |
| 通用（任意 AI 功能） | 配合开发 harness 的 CI 门禁：每次构建/改动自动跑相关用例，评分与回归结果作为质量信号 |

不同形态对 12 个测试层级的价值权重不同——见
[docs/methodology/testing-layers.md](docs/methodology/testing-layers.md)
总览表的「适用产品形态」列。

**按角色使用：**

| 角色 | 怎么用 AIQE |
|---|---|
| AI 应用团队（产品团队） | 把功能验收标准编码为用例，在每次构建/改动时自动跑分，作为发布前的质量门禁 |
| Agent 开发者 | 把 Agent 的预期决策行为编码成测试用例，用于验证 Agent 工作流输出质量和回归稳定性 |
| QA 工程师 | 把「模型行不行」从主观抽查变成确定性指标——用例即资产、基线即门槛，配合方法论文档建立完整的 LLM 评估体系 |
| 研究人员 | 用同一套用例快速对比模型 / 提示词 / 参数变体：跑分即结论，基准可复现、可对比 |

---

## 4. AIQE 与现有 LLM 评估框架的对比

AIQE 不是任何现有评估工具的替代品——它解决的是**发布前、离线、确定性**
的质量门禁问题。下表仅陈述各项目公开文档中的典型设计差异，不做优劣断言
（各项目能力以各自最新文档为准）：

| 维度 | **AIQE** | DeepEval | Promptfoo | LangSmith | Ragas |
|---|---|---|---|---|---|
| 定位 | 发布前确定性质量门禁 | LLM 评测指标框架 | 提示词测试与红队工具 | 可观测性 + 评测 SaaS 平台 | RAG 评测指标库 |
| 评分方式 | 确定性规则：关键词 / 长度 / 格式（无需 LLM 裁判） | 以 LLM 裁判指标为主（如 G-Eval） | 断言 + LLM 评估混合 | 平台内评测与追踪 | 以 LLM 裁判指标为主 |
| 运行方式 | 纯标准库、零依赖、可完全离线 | 通常需调用 LLM API | 独立 CLI / 库，需对接 provider | 云端平台 + SDK | 通常需调用 LLM |
| 本地模型支持 | 任意 Backend Protocol 注入；仓库内置 Ollama 示例与 MLX 骨架 | 视 provider 而定 | 支持本地 provider | 有限 | 视所用 LLM |
| 集成形态 | Python 库 + 可运行示例 + CI 工作流 | Python / pytest | CLI + YAML 配置 | 平台 + SDK | Python 库 |
| 开源/商业 | Apache-2.0 开源参考实现 | 开源 | 开源 | 商业产品（有免费额度） | 开源 |

**如何选择**：需要 LLM 裁判类指标（DeepEval / Ragas）、提示词与红队测试
（Promptfoo）、或线上可观测性（LangSmith）时，使用对应工具；需要给
「每次构建 / 换模型」加一道零成本、可离线、可进 CI 的确定性评分门禁时，
用 AIQE。两者可以组合——例如 AIQE 做发布前门禁，LangSmith 做线上观测。

---

## 5. 快速开始：mock 后端 30 秒出报告

无需任何模型和网络。默认 mock 后端按 prompt 内容返回确定性响应
（JSON / 代码 / 翻译 / 中文对话），让整条流水线在 30 秒内跑完：

```bash
# 安装（推荐独立虚拟环境）
python3 -m venv .venv
.venv/bin/pip install -e . pytest

# 跑分示例（4 个标准用例 → 评分 → 回归 → 报告）
.venv/bin/python examples/quick_score.py
```

示例输出（节选）：

```
  AIQE Evaluation Report
  AIQE v0.1.0 · 2026-08-15T...
════════════════════════════════════════════
  simple_chat         █████████░  0.90  ✓
  long_translation    ██████████  1.00  ✓
  json_output         ██████████  1.00  ✓
  coding_task         █████████░  0.90  ✓

  Summary: 4/4 passed
════════════════════════════════════════════
```

跑全部测试：

```bash
.venv/bin/python -m pytest -q
```

接入真实模型：实现或注入一个满足 `AIQE.protocol.Backend` 的对象
（`generate_sync` / `generate` / `backend_type` / `profile` 等），
流水线零改动：

```python
from AIQE.backends.mock import MockEvalBackend
from AIQE.runner import ExecutionRunner

backend = MockEvalBackend()          # 换成你的真实后端实例即可
backend.setup()
runner = ExecutionRunner(backend)    # 下游 judge/regression/reporter 不变
```

---

## 6. 框架结构

```
src/AIQE/
├── protocol.py        # Backend Protocol：BackendType / ModelProfile /
│                      #   GenerateOptions / GenerateResult / Backend / 默认实现
├── schema.py          # 数据模型：TestCase / ScoreBreakdown / EvaluationResult
│                      #   + ModelRunner / LocalRunner（本地确定性）/ OllamaRunner
├── runner.py          # ExecutionRunner：执行用例 → ExecutionResult
│                      #   （含 trace_id / payload_hash 完整性校验）
├── judge.py           # OutputJudge：确定性评分（关键词/长度/格式，格式分真实计入）
├── regression.py      # RegressionAnalyzer：对比历史基线，判定回归
├── reporter.py        # EvaluationReport：JSON 报告 + 控制台条形图摘要
├── backends/
│   ├── base.py        #   EvaluationBackend Protocol（Backend 超集 + setup/teardown）
│   ├── mock.py        #   MockEvalBackend：确定性 mock（默认，Built-in）
│   ├── mlx.py         #   MlxEvalBackend：真实 MLX 推理骨架（需自行注入适配层）
│   └── factory.py     #   create_eval_backend()：MLX_EVAL_LIVE 环境变量切换
└── cases/
    ├── test_cases.py      # 4 个标准用例（chat/translation/json/coding）
    ├── extended_cases.py  # 6 个扩展用例（中文场景）
    └── boundary_cases.py  # 8 个边界用例（长输入/对抗/冲突/精度…）
tests/                       # 契约测试（111 项，pytest -q 全绿）
examples/
    quick_score.py           # 30 秒快速跑分示例（mock）
    ollama_backend.py        # ollama 真实模型接入示例
    regression_compare.py    # 两次跑分回归对比演示（mock 离线）
docs/
    methodology/                 # 方法论文档（分层/流程/协作/需求/数据/报告/触发）
    INTEGRATION.md               # 与开发 harness 同步使用
templates/
    test-case-template.md        # TestCase 字段填写指南
    test-script-template.py      # 可运行脚本骨架（3 用例 + 跑分流水线）
    report-template.md           # 五段式报告模板
skills/
    testing-agent/               # 测试 agent 工作纪律 skill
    aiqe-testing/                # 四档测试手动触发 skill
```

数据流：`TestCase → ExecutionRunner(Backend) → ExecutionResult → OutputJudge
→ JudgeResult → [RegressionAnalyzer] → EvaluationReport → JSON`

> **不只是代码：方法论文档索引**
>
> - [docs/methodology/testing-layers.md](docs/methodology/testing-layers.md)
>   — 十二层测试层级框架：每层「测什么 / 在哪测 / 不建什么」+ 测试左移分层原则
> - [docs/methodology/process-management.md](docs/methodology/process-management.md)
>   — 质量流程全生命周期 + 门禁五状态（PASS/WARN/FAIL/MANUAL_REVIEW/NOT_ASSESSED）+ 发布判定规则
> - [docs/methodology/multi-agent-testing.md](docs/methodology/multi-agent-testing.md)
>   — 多 agent 测试四角色分工 + 任务书模板 + 通用测试 skill
> - [docs/methodology/requirement-analysis.md](docs/methodology/requirement-analysis.md)
>   — 需求 → 验收标准 → 用例的分解方法（含完整示例）
> - [docs/methodology/test-data-management.md](docs/methodology/test-data-management.md)
>   — 用例集/基线/报告三类数据管理 + 基线入 git + 隐私脱敏
> - [docs/methodology/report-generation.md](docs/methodology/report-generation.md)
>   — 报告链路与字段解释 + Markdown 扩展示例
> - [docs/methodology/test-trigger-strategy.md](docs/methodology/test-trigger-strategy.md)
>   — 四档测试（冒烟/全量/回归/验收）× 自动/手动触发矩阵
> - [docs/INTEGRATION.md](docs/INTEGRATION.md)
>   — 与开发 harness 同步使用：pytest 共存、CI 接入、基线管理 SOP、换模型五步流程
> - [templates/](templates/) — 用例模板 / 可运行脚本骨架 / 五段式报告模板
> - [skills/](skills/) — 测试 agent 纪律 skill + 四档手动触发 skill
> - [examples/](examples/) — 可运行示例集：mock 快速跑分 / ollama 真实接入 /
>   两次跑分回归对比（详见第 9 节）

---

## 7. 方法论文档：分层、流程、协作、触发

方法论文档全部位于 `docs/methodology/`，覆盖「测什么 → 怎么定标准 →
怎么分工 → 怎么触发 → 怎么管数据 → 怎么出报告」的完整链路：

| 文档 | 内容 | 入口章节 |
|---|---|---|
| [testing-layers.md](docs/methodology/testing-layers.md) | 十二层测试层级框架（分层 / 测试左移 / 决策表 / 不建自研设施） | 想清楚「测什么」 |
| [process-management.md](docs/methodology/process-management.md) | 质量流程全生命周期 + 门禁五状态（PASS/WARN/FAIL/MANUAL_REVIEW/NOT_ASSESSED）+ 发布判定规则 | 想清楚「怎么判」 |
| [requirement-analysis.md](docs/methodology/requirement-analysis.md) | 需求 → 可测验收标准 → 测试用例的分解方法（含完整示例） | 想清楚「测什么标准」 |
| [multi-agent-testing.md](docs/methodology/multi-agent-testing.md) | 多 agent 测试四角色分工 + 任务书模板 + 通用测试 skill | 想清楚「谁来做」 |
| [test-trigger-strategy.md](docs/methodology/test-trigger-strategy.md) | 四档测试（冒烟/全量/回归/验收）× 自动/手动触发矩阵 | 想清楚「何时跑」 |
| [test-data-management.md](docs/methodology/test-data-management.md) | 用例集/基线/报告三类数据管理、基线入 git、隐私脱敏 | 想清楚「数据放哪」 |
| [report-generation.md](docs/methodology/report-generation.md) | 报告链路与字段逐项解释 + Markdown 扩展示例 | 想清楚「怎么汇报」 |

配合使用方法（pytest 共存 / CI 接入 / 基线 SOP / 换模型五步）见第 8 节。

## 8. 与开发 harness 同步使用：pytest、CI、基线、换模型流程

[docs/INTEGRATION.md](docs/INTEGRATION.md) 回答「AIQE 怎么接进你的工程」：
与开发 harness 的同步模式（每次构建/改动自动跑分，结果作为质量门禁信号）、
与 pytest 共存的目录约定、GitHub Actions CI 接入片段、基线管理 SOP
（基线放哪 / 何时更新 / 哪些情况禁止更新）、换模型评估五步流程
（跑分→对比→看回归→记录→决策）。

本仓库自带 `.github/workflows/test.yml`：任何 clone 本仓库的用户，
一次 CI 即可在 Python 3.10 / 3.11 / 3.12 上验证 AIQE（安装 + 全量测试）。

## 9. 示例集：ollama 接入与回归对比

| 示例 | 用途 | 运行 |
|---|---|---|
| [examples/quick_score.py](examples/quick_score.py) | 30 秒快速跑分（mock，零依赖） | `python examples/quick_score.py` |
| [examples/ollama_backend.py](examples/ollama_backend.py) | 接入本地 ollama 真实模型跑分（含模型未就绪中文提示） | 先 `ollama pull llama3.2`，再 `python examples/ollama_backend.py` |
| [examples/regression_compare.py](examples/regression_compare.py) | 两次跑分回归对比：生成基线 → 改参数再跑 → 回归结论（mock 可离线） | `python examples/regression_compare.py --degrade` |

## 10. 测试触发策略：四档 × 自动/手动

[docs/methodology/test-trigger-strategy.md](docs/methodology/test-trigger-strategy.md)
定义四档测试（冒烟/全量/回归/验收）与 12 层的分配关系、自动触发挂载点
（harness hook 的 SessionStart/PreToolUse/Stop/SessionEnd 与 CI 的
push/PR/定时/发布）、「改了 X → 自动跑 Y 档」决策表，以及必须手动触发的
四类场景与配套命令（见 [skills/aiqe-testing/](skills/aiqe-testing/SKILL.md)
的 /aiqe-smoke、/aiqe-full、/aiqe-regression、/aiqe-acceptance）。

## 11. 模板集与配套 skill

- [templates/test-case-template.md](templates/test-case-template.md)
  — TestCase 逐字段填写指南 + 好用例/坏用例对照
- [templates/test-script-template.py](templates/test-script-template.py)
  — 可直接复制运行的脚本骨架（3 用例 + runner + judge + 报告，注释标注自定义点）
- [templates/report-template.md](templates/report-template.md)
  — 五段式报告模板（执行摘要/用例明细/回归结论/性能数据/决策建议）
- [skills/testing-agent/SKILL.md](skills/testing-agent/SKILL.md)
  — 测试 agent 工作纪律（红→绿、验收命令、禁止自证空转、边界声明）
- [skills/aiqe-testing/SKILL.md](skills/aiqe-testing/SKILL.md)
  — 四档测试手动触发命令映射

---

## 12. 开源协议

本项目采用 **Apache License 2.0**（全文见 [LICENSE](LICENSE)），选择理由与要点：

| 维度 | 说明 |
|------|------|
| 可商用、可闭源派生 | 允许将本框架用于商业产品，派生仓库可选择闭源 |
| 专利授权 | Apache-2.0 附带专利许可条款，对评估框架类项目友好 |
| 保留义务 | 分发时必须保留版权声明、许可文件，并标注对原作的修改 |
| 无担保 | 参考实现不提供任何明示或暗示担保（Apache-2.0 标准条款） |

**引用与修改规范**：

- **fork 请标注来源**：派生仓库请在 README 或 LICENSE 注明：
  「派生自 AIQE（https://github.com/haleSnW/AIQE）」
- **发布修改版需声明差异**：在显著位置（如 README 顶部）列出与 AIQE 的
  改动清单——保证社区能追溯判定规则的出处与演化，避免「改了评分器却没
  人知道」的静默漂移
- **独立分发**：AIQE 是独立分发的参考实现，Apache-2.0 许可覆盖本仓库
  全部内容；商业使用（含闭源）无需额外授权

---

## 13. 捐赠支持

AIQE 是完全开源、免费使用的项目。

如果 AIQE 对你的工作或研究有所帮助，
欢迎支持项目持续维护。

支持主要用于：

| 用途 | 说明 |
|-|-|
| 真实推理验证 | Apple Silicon / MLX / Ollama 等环境测试与回归 |
| 用例扩充 | 新 AI 场景测试用例设计与验证 |
| 维护与文档 | 框架维护、CI、文档完善与多语言支持 |

所有支持都会用于 AIQE 项目相关工作。

<div align="center">

<img src="docs/donate_alipay.png" alt="支付宝收钱码" width="240">

**支付宝收钱码**

</div>

无论金额大小，都感谢你对开源社区的支持。❤️


## FAQ

**AIQE 是什么？**

AIQE 是一个开源的测试左移（Shift-Left）AI 质量评估框架：在 LLM 应用与
AI Agent 进入生产环境之前，用确定性评分对模型输出做质量评估与回归测试。
它提供「用例集 → 执行（Backend Protocol）→ 确定性评分 → 回归对比 →
JSON 报告」的完整流水线，纯标准库实现、零运行时依赖，Apache-2.0 开源。

**AIQE 解决什么问题？**

模型质量回归被发现得太晚——上线后靠用户反馈与人工抽查，反馈周期以天/周
计且无法归因。AIQE 把评估前移到发布前：每次构建、每次提示词改动、每次
换模型，都跑同一套用例、对比同一份基线，分数下降即触发排查或拒绝发布。

**谁应该使用 AIQE？**

LLM / Agent 应用开发者、QA 工程师、AI 应用产品团队与研究人员——任何
需要在部署前对 AI 系统做确定性质量评估与回归测试的团队（详见第 3 节
「按角色使用」）。

**为什么要在部署前测试 AI 系统？**

越晚发现的缺陷，修复成本越高。对 AI 系统而言，「体感」不可量化、无法
归因；只有部署前跑分、建立基线、对比回归，质量变化才能变成数字和门禁。

**AIQE 能评估本地模型吗？**

能。AIQE 的评估流水线不绑定任何模型——任何满足 `AIQE.protocol.Backend`
契约的后端都可以注入，包括本地模型。仓库内置 Ollama 接入示例与 MLX
骨架，也支持通过协议接入 llama.cpp 等任意推理服务，全程无需云端 API。

**AIQE 支持 Ollama 吗？**

支持。`examples/ollama_backend.py` 是官方接入示例（实验性）：先
`ollama pull llama3.2`，再运行示例脚本即可对本地模型跑分。

**AIQE 与 DeepEval / Promptfoo / LangSmith 等框架有何区别？**

它们解决不同问题：DeepEval / Ragas 提供 LLM 裁判类指标，Promptfoo 专注
提示词测试与红队，LangSmith 是线上可观测平台；AIQE 专注「发布前、离线、
确定性」的质量门禁——无需 LLM 裁判、无需网络、零依赖，30 秒出报告。
详细对照见第 4 节。

**AIQE 支持 AI Agent 测试吗？**

支持。AIQE 的流水线与产品形态无关：把 Agent 的预期决策行为编码成测试用例
（期望关键词 / 格式 / 长度），用于验证 Agent 工作流输出质量和回归稳定性。
方法论文档（docs/methodology/）提供了 agent 测试的分工、触发与数据管理策略。

**需要 API key 或联网吗？**

不需要。默认 mock 后端完全离线、确定性输出，开箱即用；只有接入真实模型
时才需要你本地的模型服务（Ollama / MLX）或自研后端。

**一次评估要多久？**

mock 后端 30 秒内出完整报告（4 用例 + 评分 + 回归 + JSON）；真实模型
取决于后端速度与用例量。

**AIQE 的测试可信吗？**

仓库自带 111 项契约测试（`pytest -q` 全绿），覆盖协议、评分、回归、
错误契约与格式回归；当前 mock 后端评分流程为确定性评分，相同输入得到一致结果。

**AIQE 是商业产品吗？**

不是。AIQE 是 Apache-2.0 开源的参考实现，零运行时依赖，可自由使用、
fork、商用（含闭源）。


## 关于作者

AIQE 由独立开发者 haleSnW 创建。

作者拥有多年软件测试、质量工程与自动化测试经验，
目前专注于 AI 应用测试、AI Agent 评估、模型可靠性验证方向。

如果你的团队正在探索：

- AI 应用质量体系
- LLM / Agent 测试框架
- 自动化质量工程平台
- AI 工程可靠性保障体系

欢迎进行技术交流与合作。

联系方式：

- GitHub: @haleSnW
- Email: halewon@outlook.com
