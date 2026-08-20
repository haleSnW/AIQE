[简体中文](INTEGRATION.md) | [English](INTEGRATION.en.md)

# 与开发 harness 同步使用（INTEGRATION）

> 把 AIQE 接进你现有工程的三件事：目录怎么摆、CI 怎么接、基线怎么管。
> 外加与开发 harness 的同步模式、一条完整的「换模型评估五步流程」。

---

## 1. 与开发 harness 的同步模式

AIQE 的定位是**随开发流程同步使用**的质量评估：跑分不是发布前的一次性
审计，而是开发 harness（构建/CI/本地开发脚本）在每个环节自动带上的一层
质量信号。

```
开发 harness（每次构建 / 每次改动）
        │
        ├─ 代码级回归：pytest（断言「代码没写坏」）
        └─ 模型级回归：AIQE 跑分（断言「模型/产品行为没变差」）
              │
              ├─ 用例集 → 执行 → 确定性评分
              ├─ 与基线对比 → 回归结论（new/pass/degraded/regression）
              └─ 结果作为质量门禁信号：
                   · 门禁模式：发现 regression 即阻断（适合确定性 mock / 稳定后端）
                   · 报告模式：结论进报告 artifact，人工判断（适合真机波动环境）
```

落地要点：

- **触发点**：每次代码改动跑相关用例（决策见 `docs/methodology/
  testing-layers.md` 第 3 节决策表），每次换模型/换配置跑全量用例。
- **信号形式**：评分与回归结果作为质量门禁信号——既可以硬阻断（CI 里
  regression 就失败），也可以软提示（进报告人工判断）。默认推荐后者，
  真机结果波动大，硬门禁容易变成噪音。
- **与 pytest 的分工**：pytest 管代码、AIQE 管模型行为，两者在同一
  harness 里并行存在（见第 2 节目录约定）。

---

## 2. 与 pytest 共存的目录约定

AIQE 不是 pytest 的替代品，两者各管一段：

| 层面 | 工具 | 管什么 | 何时跑 |
|---|---|---|---|
| 代码级回归 | pytest | 函数/分支/契约/集成测试，断言「代码没写坏」 | 每次提交、每次 CI |
| 模型级回归 | AIQE 跑分 | 用例集 + 确定性评分 + 基线对比，断言「模型没变差」 | 换模型/调 prompt/发布前 |

**目录约定**（本仓库即是范例）：

```
src/AIQE/          # 框架产品代码
tests/             # pytest 契约测试（testpaths=["tests"]，examples 不会被收集）
examples/          # 可运行脚本：quick_score / ollama_backend / regression_compare
docs/              # 方法论文档（testing-layers.md、本文件）
```

- `examples/` 不进 pytest 收集范围（`pyproject.toml` 的 `testpaths = ["tests"]`），
  它是「人工/CI 可执行的冒烟脚本」，不是单元测试。
- 你自己项目的既有 pytest 测试目录不需要任何改造：AIQE 以**脚本方式**运行
  （`python examples/quick_score.py`），跑分结果作为 JSON 报告产物，不进入
  pytest 的断言域。
- 如果希望跑分结果进 pytest（比如 CI 里「发现 regression 就失败」），
  推荐做法：pytest 里用 `subprocess.run` 调示例脚本并把退出码/报告 JSON
  作为断言依据，而不是在 pytest 进程内 import AIQE 串流水线——保持两边
  生命周期解耦，任一边失败都容易定位。
- 报告与基线默认落在 `~/.AIQE/results/`，与代码仓库分离；需要随仓库归档
  时改用显式路径（见第 3 节）。

## 3. CI 接入片段（GitHub Actions）

mock 后端零依赖零网络，标准 GitHub Actions 即可跑完整流水线（无需 GPU）：

```yaml
# .github/workflows/aiqe-eval.yml
name: aiqe-eval

on:
  push:
    branches: [master, main]
  pull_request:

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: 安装（AIQE 零运行时依赖 + pytest）
        run: |
          python -m pip install --upgrade pip
          pip install -e . pytest

      - name: 代码级回归（pytest 契约测试）
        run: python -m pytest -q

      - name: 模型级回归——快速跑分（mock，30 秒）
        run: python examples/quick_score.py

      - name: 模型级回归——两次跑分对比（含基线写入与回归判定）
        run: python examples/regression_compare.py --degrade

      - name: 归档评估报告
        uses: actions/upload-artifact@v4
        with:
          name: aiqe-reports
          path: |
            AIQE-report.json
            examples/.regression-demo/*.json
          if-no-files-found: ignore
```

要点：

- **CI 里只用 mock**：`examples/ollama_backend.py` 需要本地模型，属于
  真机评估，放 CI 会引入不稳定与成本。真机评估按第 5 节五步流程在
  本地或带模型的 runner 上做。
- **基线初始化**：首次接入 CI 时，第一次跑分会把全部用例标为
  `new`（无历史可比），属正常现象；跑通一次后把报告归档，人工选定
  一份作为基线（见第 4 节）。
- **把 regression 变成门禁是可选的**：默认策略是报告进 artifact 人工
  判断（确定性评分的 mock 结果稳定，可以放心做门禁；真机结果波动大，
  不建议直接阻断）。

## 4. 基线管理 SOP

### 基线放哪

| 场景 | 存放位置 | 说明 |
|---|---|---|
| 单人本地 | `~/.AIQE/results/baseline.json` | RegressionAnalyzer 默认路径，无需配置 |
| 团队/CI 归档 | 仓库外共享存储（或 CI artifact） | 按 `AIQE-report-<模型>-<日期>.json` 命名归档，人工挑稳定版本做基线 |
| 示例/演示 | 脚本内显式路径（如 `examples/.regression-demo/`） | 不污染正式基线 |

基线文件两种可读格式（`regression.py` 都能解析）：

1. 顶层 dict：`{"simple_chat": 1.0, "long_translation": 0.8, ...}`
2. EvaluationReport 嵌套结构（`{"test_plan_id": ..., "cases": [{"case_id": ...,
   "judge": {"score": ...}}]}`）——**直接把一次跑分的报告 JSON 当基线用**，
   最常见，保留了 prompt 与判分明细。

### 何时更新基线

| 场景 | 是否更新 | 说明 |
|---|---|---|
| 用例集定义变更（增删改用例） | 更新 | 用例变了，新旧分不可比，必须重建基线 |
| 评分器规则变更（judge 逻辑） | 更新 | 度量本身变了；更新前先重跑全部历史用例，确认新老分数趋势一致 |
| 模型重大版本升级后跑通且稳定 | 更新 | 新模型连续 N 次跑分无回归后，把新分定为新基线 |
| 基线过期（用例久未验证） | 更新 | 建议周期（如每 30 天）用当前配置重跑一次刷新基线 |
| 分数下降时 | **禁止**更新 | 分数下降就更新基线 = 对度量作弊；先排查（第 4 节第 3 步） |

一条铁律：**基线更新必须独立于单次跑分结果**——每次跑分自动写入的是
「当前报告」，基线是人工或定时任务挑选的「参考版本」。脚本/CI 里如果
写成「跑完直接把当前分当基线」，回归检测就永远报不出回归了。

## 5. 换模型评估五步流程

把「换个模型试试」从拍脑袋变成走流程——每次换模型（版本/量化/后端）都走
这五步，全程约 5 分钟（mock 30 秒，真机视模型而定）：

```
跑分 → 对比 → 看回归 → 记录 → 决策
```

1. **跑分**：新模型跑全量用例集（标准 + 扩展 + 边界，18 个用例）。
   真机：`OLLAMA_MODEL=<新模型> python examples/ollama_backend.py`；
   离线验证流水线：`python examples/regression_compare.py --degrade`。
2. **对比**：与基线对比（RegressionAnalyzer 输出 new/pass/degraded/
   regression 四种状态 + delta）。
3. **看回归**：对每个 regression/degraded 用例，打开报告 JSON 看判分明细
   （关键词命中率/长度/格式分）——是关键词没覆盖到（用例问题），还是
   模型行为真变差（模型问题）？对比两份报告的响应原文。
4. **记录**：报告 JSON 归档，文件名含模型与日期
   （`AIQE-report-<模型>-<日期>.json`），并附一行结论。
5. **决策**：

| 结论 | 处置 |
|---|---|
| 全部 pass | 可换。更新基线（第 3 节）后投入使用 |
| ≤2 个 degraded（轻微下降） | 低风险：人工抽检受影响用例的响应原文后可放行 |
| 出现 regression | 拒绝或回退；若必须换，先针对性调 prompt 重测 |
| 全量 new（无基线） | 观察期：先跑分记录，跑通稳定后再定基线 |

## 6. 本仓库定位与演进方式

- **独立发布**：AIQE 是独立分发的 Apache-2.0 参考实现（v0.1.0），对外发布、
  独立演进，不依赖任何未公开的代码库。
- **协议开放**：`AIQE/protocol.py` 定义唯一的后端接入契约（Backend
  Protocol）。任何满足该协议的后端（MLX / Ollama / llama.cpp / 自研 /
  mock）都可以注入 `ExecutionRunner`，由 `tests/test_backends.py` 的
  契约测试保障。
- **引用与修改**：本仓库可在 Apache-2.0 下 fork/修改，包括改判分规则与
  用例集。派生仓库请在 README 或 LICENSE 注明来源，并在显著位置列出与
  AIQE 的改动清单——保证社区能追溯判定规则的出处与演化，避免「改了评
  分器却没人知道」的静默漂移。
- **定位差异**：AIQE 只保留「用例 → 执行 → 确定性评分 → 回归 → 报告」
  这条评估链路——它是方法论载体与可复用的评估框架，不是特定产品的运行时。

## 7. 常见问题

- **报告里 project 标识是什么**：`AIQE`（`reporter.py` 的 `_PROJECT`
  常量；旧版本曾输出 `aiqe` 小写，以当前代码为准）。
- **基线文件损坏/格式不对**：`_load_baseline` 解析失败返回 None，
  全部用例按 `new` 处理，不会崩溃——修复文件后重跑即可。
- **ollama 模型没装 / 服务没起**：`examples/ollama_backend.py` 会打印
  中文修复指引（`ollama pull <model>` / 启动服务）后退出，不会半路崩溃；
  CI 场景请使用 mock 后端。
- **真机跑分慢/内存不足**：本地推理环境先确认可用内存再跑全量；性能
  数据（tok/s）只进报告，不做自动门禁。
