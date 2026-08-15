# AIQE —— 测试左移（Shift-Left）AI 质量评估框架参考实现

> 在生成之前先跑分。用确定性评分，把模型质量回归挡在发布之前。

AIQE 是一套面向**大模型与 agent 开发、以及 AI 产品开发**的质量评估框架
参考实现：**用例集 → 执行（Backend Protocol）→ 确定性评分 → 回归对比 →
JSON 报告**。它在开发流程中**同步配合开发 harness 使用**——随每次构建/
改动跑分与回归，而不是事后审计。**产品形态无关**：无论被评估对象是
系统/OS、模型、算法、APK 还是 Web 产品，都复用同一套「用例 → 评分 →
回归」流程。

- 纯标准库实现，运行时零依赖；唯一的开发依赖是 pytest
- 默认 mock 后端：确定性响应，无需模型、无需网络，30 秒出报告
- 通过 Backend Protocol 接入任意推理后端（MLX / Ollama / llama.cpp / 自研）
- 本仓库是参考实现：代码完整、测试全绿，可直接使用、fork、改造

---

## 目录

1. [测试左移思想：为什么在生成前先跑分](#1-测试左移思想为什么在生成前先跑分)
2. [适用对象：不同产品形态怎么用 AIQE](#2-适用对象不同产品形态怎么用aiqe)
3. [快速跑分：mock 后端 30 秒出报告](#3-快速跑分mock-后端-30-秒出报告)
4. [框架结构](#4-框架结构)
5. [镜像契约与导出说明](#5-镜像契约与导出说明)
6. [引用规范](#6-引用规范)
9. [方法论文档：分层、流程、协作、触发](#9-方法论文档分层流程协作触发)
10. [与开发 harness 同步使用：pytest、CI、基线、换模型流程](#10-与开发harness同步使用pytestci基线换模型流程)
11. [示例集：ollama 接入与回归对比](#11-示例集ollama-接入与回归对比)
12. [流程管理与多 agent 协作](#12-流程管理与多agent协作)
13. [测试触发策略：四档 × 自动/手动](#13-测试触发策略四档-自动手动)
14. [模板集与配套 skill](#14-模板集与配套skill)

---

## 1. 测试左移思想：为什么在生成前先跑分

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
   格式校验这三类可复现的判定（外加可选的 JSON/代码结构检测）。同样的响应
   永远得到同样的分数——分数才能进基线、做回归。
2. **用例即资产**：用例集（含 8 个边界场景：超长输入、对抗性提示、多指令
   冲突、数字精确性等）本身就是对产品期望的编码。模型换版时先过用例集，
   而不是先上线。
3. **回归基线是硬门槛**：RegressionAnalyzer 对比当前分数与历史基线，
   下降超 0.15 判定为 regression。没有基线文件时自动记为 `new`，不误伤
   首次接入的模型。

> 一句话总结：**测试左移 = 把「模型行不行」从拍脑袋变成跑分，
> 把「什么时候发现退化」从发布后提前到发布前。**

---

## 2. 适用对象：不同产品形态怎么用 AIQE

AIQE 的流程与产品形态无关——「用例 → 评分 → 回归」对任何 AI 产品都成立，
区别只在于**用例编码的是什么**：

| 被评估对象 | 怎么用 AIQE |
|---|---|
| 系统/OS（含 agent 运行时） | agent 决策链路评估：把「决策是否正确」编码成用例（期望关键词/格式/长度），跑分即决策质量回归 |
| 模型（大模型/端侧模型） | 跑分与换版回归：全量用例集对比基线，五步流程（见第 10 节）定去留 |
| 算法（RAG/路由/排序/后处理） | 确定性输出回归：相同输入必须产出相同质量输出，分数变化即告警 |
| APK/Web 产品 | 产品功能用例（含 UI 输出断言）：把功能验收编码为用例，发布前过卷 |
| 通用（任意 AI 功能） | 配合开发 harness 的 CI 门禁：每次构建/改动自动跑相关用例，评分与回归结果作为质量信号 |

不同形态对 12 个测试层级的价值权重不同——见
[docs/methodology/testing-layers.md](docs/methodology/testing-layers.md)
总览表的「适用产品形态」列。

---

## 3. 快速跑分：mock 后端 30 秒出报告

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

跑全部测试（含镜像契约测试）：

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

## 4. 框架结构

```
src/AIQE/
├── protocol.py        # Backend Protocol 镜像副本：BackendType / ModelProfile /
│                      #   GenerateOptions / GenerateResult / Backend / 默认实现
├── schema.py          # 数据模型：TestCase / ScoreBreakdown / EvaluationResult
│                      #   + ModelRunner / LocalRunner（本地确定性）/ OllamaRunner
├── runner.py          # ExecutionRunner：执行用例 → ExecutionResult
│                      #   （含 trace_id / payload_hash 完整性校验）
├── judge.py           # OutputJudge：确定性评分（关键词/长度/格式）
├── regression.py      # RegressionAnalyzer：对比历史基线，判定回归
├── reporter.py        # EvaluationReport：JSON 报告 + 控制台条形图摘要
├── backends/
│   ├── base.py        #   EvaluationBackend Protocol（Backend 超集 + setup/teardown）
│   ├── mock.py        #   MockEvalBackend：确定性 mock（默认）
│   ├── mlx.py         #   MlxEvalBackend：真实 MLX 推理骨架（需自行注入适配层）
│   └── factory.py     #   create_eval_backend()：MLX_EVAL_LIVE 环境变量切换
└── cases/
    ├── test_cases.py      # 4 个标准用例（chat/translation/json/coding）
    ├── extended_cases.py  # 6 个扩展用例（中文场景）
    └── boundary_cases.py  # 8 个边界用例（长输入/对抗/冲突/精度…）
tests/                       # 镜像契约测试（见下节）
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
>   两次跑分回归对比（详见第 11 节）

---

## 5. 镜像契约与导出说明

本仓库是 上游项目 项目内部 AIQE 测试体系的**独立导出版**（协议副本说明：
导出来源为 上游项目 仓库的 framework/ai_eval/ 模块集合与 framework/models/backend.py
协议定义）。两边的公开 API 同构，靠各自的镜像契约测试共同保障——同一份
断言语义在两边各自成立，任何一边的破坏都会被自己的测试抓住。

| 项目 | 上游项目 内部 | 本仓库（AIQE） |
|------|-----------|----------------|
| 包路径 | framework/ai_eval/* | AIQE/* |
| Backend 协议 | 上游项目 内部 models/backend.py | AIQE/protocol.py（单文件镜像副本） |
| 数据模型 | pydantic BaseModel | 标准库 dataclass（保留 model_dump() 兼容） |
| Ollama HTTP | httpx | 标准库 urllib（行为一致） |
| 报告 project 标识 | "上游项目" | "AIQE" |
| 回归默认存储路径 | 上游项目 专用目录 | ~/.AIQE/results |
| 运行时依赖 | pydantic / httpx 等 | **零依赖（纯标准库）** |

镜像测试的边界：上游项目 内部依赖基础设施的两个测试（retry 装饰器、熔断器
与执行器的集成）不属于 AIQE 参考实现范围，未迁移；AIQE 侧对应保障是
「任意满足 Backend Protocol 的后端都可注入」。

---


## 6. 引用规范

- **fork 请标注来源**：派生仓库请在 README 或 LICENSE 注明：
  「派生自 AIQE（https://github.com/haleSnW/AIQE）」
- **发布修改版需声明差异**：在显著位置（如 README 顶部）列出与上游的
  改动清单，例如 `相对 AIQE 上游的改动：…`——保证社区能追溯判定规则
  的出处与演化，避免「改了评分器却没人知道」的静默漂移
- **用例集与判定规则的出处**：源自个人项目 上游项目 的内部测试体系，
  Apache-2.0 下保留上述出处即可自由使用（商用/闭源均可）

---


## 7. 捐赠入口

每一笔支持都会记录去向并公示在仓库 release 说明中，用途仅限三项：

| 用途 | 说明 |
|------|------|
| 真实推理验证 | 用例集在真机（Apple Silicon / MLX）上跑全量回归，单次约 ¥2~5 算力成本——历史基线数据全部来自这类实测 |
| 用例集扩充 | 新场景用例的构造与人工校准（每类用例约 1~2 小时校准工作） |
| 镜像契约维护 | 与上游测试体系保持同构的契约测试更新 |

<div align="center">

<img src="docs/donate_alipay.png" alt="支付宝收钱码" width="240">

**支付宝收钱码**

</div>

---

## 9. 方法论文档：分层、流程、协作、触发

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

配合使用方法（pytest 共存 / CI 接入 / 基线 SOP / 换模型五步）见第 10 节。

## 10. 与开发 harness 同步使用：pytest、CI、基线、换模型流程

[docs/INTEGRATION.md](docs/INTEGRATION.md) 回答「AIQE 怎么接进你的工程」：
与开发 harness 的同步模式（每次构建/改动自动跑分，结果作为质量门禁信号）、
与 pytest 共存的目录约定、GitHub Actions CI 接入片段、基线管理 SOP
（基线放哪 / 何时更新 / 哪些情况禁止更新）、换模型评估五步流程
（跑分→对比→看回归→记录→决策），以及与上游项目的关系说明。

## 11. 示例集：ollama 接入与回归对比

| 示例 | 用途 | 运行 |
|---|---|---|
| [examples/quick_score.py](examples/quick_score.py) | 30 秒快速跑分（mock，零依赖） | `python examples/quick_score.py` |
| [examples/ollama_backend.py](examples/ollama_backend.py) | 接入本地 ollama 真实模型跑分（含模型未就绪中文提示） | 先 `ollama pull llama3.2`，再 `python examples/ollama_backend.py` |
| [examples/regression_compare.py](examples/regression_compare.py) | 两次跑分回归对比：生成基线 → 改参数再跑 → 回归结论（mock 可离线） | `python examples/regression_compare.py --degrade` |

## 12. 流程管理与多 agent 协作

- [docs/methodology/process-management.md](docs/methodology/process-management.md)
  — AIQE 质量流程全生命周期（需求→用例设计→执行→评分→回归→报告→决策），
  每环节进出标准；质量门禁五状态词汇（PASS / WARN / FAIL / MANUAL_REVIEW /
  NOT_ASSESSED）与发布判定规则；与开发 harness/CI 的三个衔接点。
- [docs/methodology/multi-agent-testing.md](docs/methodology/multi-agent-testing.md)
  — 测试四角色分工模型（规划/执行/审查/质量回溯）+ 任务书模板（边界/验收
  命令/超时提示）+ 可直接复用的通用测试 agent skill。
- [docs/methodology/requirement-analysis.md](docs/methodology/requirement-analysis.md)
  — 需求 → 可测验收标准 → 测试用例的三步分解法（含完整示例：模糊需求 →
  三条验收标准 → 两个用例）。

## 13. 测试触发策略：四档 × 自动/手动

[docs/methodology/test-trigger-strategy.md](docs/methodology/test-trigger-strategy.md)
定义四档测试（冒烟/全量/回归/验收）与 12 层的分配关系、自动触发挂载点
（harness hook 的 SessionStart/PreToolUse/Stop/SessionEnd 与 CI 的
push/PR/定时/发布）、「改了 X → 自动跑 Y 档」决策表，以及必须手动触发的
四类场景与配套命令（见 [skills/aiqe-testing/](skills/aiqe-testing/SKILL.md)
的 /aiqe-smoke、/aiqe-full、/aiqe-regression、/aiqe-acceptance）。

## 14. 模板集与配套 skill

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

## 开源协议

本项目采用 **Apache License 2.0**（全文见 [LICENSE](LICENSE)），选择理由与要点：

| 维度 | 说明 |
|------|------|
| 可商用、可闭源派生 | 允许将本框架用于商业产品，派生仓库可选择闭源 |
| 专利授权 | Apache-2.0 附带专利许可条款，对评估框架类项目友好 |
| 保留义务 | 分发时必须保留版权声明、许可文件，并标注对原作的修改 |
| 无担保 | 参考实现不提供任何明示或暗示担保（Apache-2.0 标准条款） |
| 商标边界 | 「AIQE」「MaleDe / MLD」名称本身不受许可授权，派生项目请用自己的名称 |

**口径分层说明**：AIQE 是上游个人项目（上游项目）内部测试体系的独立导出，
上游项目 本身不开源；本仓库的 Apache-2.0 许可仅覆盖本仓库代码，不延伸至
上游项目的其他部分。

## License

[Apache-2.0](LICENSE) —— 引用友好、商用友好，保留署名。
