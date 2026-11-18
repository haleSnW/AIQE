# E2E 质量门禁：AI 修过的测试不能悄悄变绿

[简体中文](E2E_GATE.md) | [English](E2E_GATE.en.md)

`AIQE.e2e_gate` 是一道接在 Playwright 后面的**确定性放行判定**。它回答一个问题：

> 测试变绿了，这次能不能自动放行？

Playwright 官方的 Test Agents（planner / generator / healer）已经能让 AI 生成并自动修复 E2E 测试。
接下来的风险是：healer 可能靠删断言、换宽松匹配器、加 `skip` 把红变绿。CI 只看退出码，看不出来。
AIQE 不重复造这些 agent，它只做判定这一层：AI 负责重复执行和修复，规则负责判定，人负责例外。

## 1. 一条命令看效果

```bash
PYTHONPATH=src python examples/e2e_gate_demo.py --out /tmp/aiqe-e2e-demo
```

| 场景 | Playwright | 门禁 | 原因 |
|---|---|---|---|
| 基线 | 全绿 | PASS | — |
| 新版本 | 2 失败 | BLOCK | `NEW_FAILURE` ×2 |
| 诚实 healer：只修定位器 | 1 失败 | BLOCK | `NEW_FAILURE`：剩下的是产品缺陷，照样拦下 |
| **取巧 healer：删断言 + 换宽松匹配** | **全绿** | **BLOCK** | `ASSERTION_REMOVED`、`MATCHER_LOOSENED` |
| 开发修复产品缺陷 + 诚实 healer | 全绿 | PASS | — |
| 重试才通过 | 全绿 | ESCALATE | `FLAKY` |

输入都在 [`examples/e2e_gate/`](../examples/e2e_gate/)：手写的公开样例，包括 Playwright JSON 报告和 healer diff。
输出包括每个场景的判定 JSON、Markdown 摘要、AIQE 结果契约文档，以及一个离线看板。
在看板趋势里，取巧那次的通过率是 83.3%，不是 100%：被削弱的用例按“未判定”计，不算通过。

## 2. 接入自己的项目

```bash
PLAYWRIGHT_JSON_OUTPUT_FILE=pw-report.json npx playwright test --reporter=json
git diff "$HEALER_BASE" "$HEALER_HEAD" > e2e.diff

python -m AIQE.e2e_gate \
  --report pw-report.json \
  --baseline last-green/pw-report.json \
  --patch e2e.diff \
  --out aiqe-gate.json --markdown summary.md \
  --result-out aiqe-run.json --sut-id "$GIT_SHA"
```

| 退出码 | 含义 |
|---|---|
| 0 | PASS：证据完整，没有风险信号 |
| 1 | BLOCK：阻断自动放行 |
| 2 | ESCALATE：不阻断，也不自动放行，交给人决定 |
| 3 | 输入不是可解析的 Playwright 报告或 diff（失败关闭） |

将 `HEALER_BASE` 和 `HEALER_HEAD` 指向单次测试修复开始和结束的可信提交。
`--baseline` 和 `--patch` 都是可选项。省略时仅检查本次报告。
工作流示例同时检查 Playwright 原始退出状态，公开摘要仅显示判定和退出码。原始报告、测试名称和路径应留在有访问控制的环境。
完整的 GitHub Actions 示例见 [`examples/ci/playwright-e2e-gate.yml`](../examples/ci/playwright-e2e-gate.yml)。

## 3. 原因码

严重度定义在 `AIQE.e2e_gate.SEVERITY`。v0.1 不开放配置，避免一行配置就把守卫关掉。

**运行结果**

| 原因码 | 严重度 | 触发条件 |
|---|---|---|
| `UNEXPECTED_FAILURE` | BLOCK | 没有基线，本次有用例未达预期 |
| `NEW_FAILURE` | BLOCK | 基线通过，本次失败 |
| `PERSISTENT_FAILURE` | BLOCK | 基线就失败，本次仍失败 |
| `FLAKY` | ESCALATE | 重试后才通过 |
| `EXPECTED_FAILURE_MARKED` | ESCALATE | `test.fail()` 让失败显示为“符合预期” |
| `SKIP_ADDED` | ESCALATE | 基线执行的用例本次被跳过 |
| `TEST_REMOVED` | ESCALATE | 基线存在的用例本次消失 |

**证据完整性**

| 原因码 | 严重度 | 触发条件 |
|---|---|---|
| `EVIDENCE_EMPTY` | BLOCK | 报告为空或全部跳过 |
| `REPORT_ERRORS` | BLOCK | 报告有顶层错误（配置或全局 setup 失败） |
| `TRACE_MISSING` | ESCALATE | 失败用例没有附 trace（`--no-trace-required` 可关） |
| `BASELINE_INCOMPARABLE` | ESCALATE | 基线和本次的 project 集合不同 |

**修复 diff（healer 守卫）**：按文件统计，被注释掉的代码算删除。

| 原因码 | 严重度 | 触发条件 |
|---|---|---|
| `ASSERTION_REMOVED` | BLOCK | `expect(` / `assert` 净减少 |
| `MATCHER_LOOSENED` | BLOCK | 精确匹配器（`toHaveText`、`toEqual`、`toHaveURL`…）减少，同时新增宽松匹配（`toBeVisible()`、`toBeTruthy()`、`/.*/`…） |
| `ASSERTION_SWALLOWED` | BLOCK | 新增 `.catch(() => {})`、`except: pass` 之类吞异常的写法 |
| `TEST_DISABLED` | BLOCK | 新增 `test.skip` / `fixme` / `fail` / `only`、`xit`、`@pytest.mark.skip` |
| `SCOPE_VIOLATION` | BLOCK | 改到了测试范围以外的文件（`--allow-path` 可替换默认范围） |
| `TIMEOUT_INFLATED` | ESCALATE | 超时变大；新写的超时超过 30s；新增 `test.slow()` |
| `FORCE_ACTION` | ESCALATE | 新增 `force: true`，跳过可见和可点击检查 |

带行号的 diff 发现会**归属到用例**：取同一文件中、起始行不晚于发现行的最近一个 spec。
被 BLOCK 级发现归属到的用例，投影到结果契约时按“未判定”计，不算通过。

## 4. 边界

- **不调用模型，不驱动浏览器，不依赖 Playwright 包。** 只读报告和 diff，纯标准库实现。同样的输入总是得到同样的判定。
- **结果契约只存原因码，不存消息。** 错误消息正文、stdout、附件路径都不进入 `aiqe.result` 文档。原始报告留在你自己的 CI 产物里。
- **来源标记为 `local_test`，分级默认 `internal`。** 看板需要显式传 `--allow-source local_test` 才能读取。非 `public_synthetic` 的产物照旧不能写进 Git 工作树。
- **这是规则，不是证明。** 正则和计数能抓住常见的削弱写法，抓不住所有写法，比如把断言挪进一个永远不执行的分支。
  所以 PASS 的意思是“没有发现风险信号”，不是“质量已证明”。
  行号归属同样是近似：它不解析 TS/JS 语法。
- **不替代人。** 产品语义变化、断言是否应该改，仍然由人判断。门禁只负责不让这些改动悄悄通过。

- 基线与候选应使用相同的项目和测试筛选条件。当前版本要求同一项目内的用例身份唯一，使用 `--repeat-each` 的报告可能被拒绝。
