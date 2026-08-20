[简体中文](testing-layers.md) | [English](testing-layers.en.md)

# AIQE Generic Testing-Layer Framework (Testing Layers)

> A test layering method that any AI project can apply directly: 12 test layers, each answering "what to test, where to test, what to test with, and which facilities not to build yourself".

**About the source**: this document organizes common industry test classifications into 12 transferable layering methods, with the wording generalized — not bound to any specific project's module names or hardware constraints. In the text, "AIQE" refers to this repository, serving as the reference carrier for how each layer is put into practice.

---

## 1. Overview of the Twelve Layers

| # | Layer | One-line definition | Applicable product forms | How it is implemented in AIQE | Corresponding code/test files | Boundary: facilities not built in-house |
|---|---|---|---|---|---|---|
| 1 | **Unit testing** | Independently verify the behavior of the smallest code units (functions/methods/classes) | All forms (code quality is independent of product form) | Assert behavior module by module on the runner, scorer, regression analyzer, and reporter | `tests/test_runner.py`, `tests/test_schema.py`, `tests/test_backends.py` | No coverage/pytest-cov gates; when metrics are needed, manually run `coverage run` to inspect the numbers, not counted as a CI blocker |
| 2 | **Interface testing (contract testing)** | Verify that the public contracts between components (method signatures/fields/state semantics) are not broken | System/OS and agent (the forms with the most protocols/interfaces); model backend integration | `Backend Protocol` uses `@runtime_checkable` for structural subtyping checks; any backend implementation that satisfies the protocol is accepted | `src/AIQE/protocol.py`, `tests/test_backends.py` (isinstance contract assertions) | Contract assertions cover only the public API; no `inspect.getsource`-style source guards (they break on any refactor) |
| 3 | **Integration testing** | Verify the collaborative behavior of multiple assembled components | System/OS, agent, APK/Web (multi-component assembly forms) | Chain assertions across the whole execute → score → regression → report pipeline; `trace_id`/`payload_hash` ensure all stages share the same data origin | Pipeline cases in `tests/test_runner.py`, `examples/quick_score.py` (smoke) | No in-house integration framework; pytest's `tmp_path`/`monkeypatch` are sufficient |
| 4 | **System testing (end-to-end)** | Verify the complete flow in a real or near-real environment | All forms (must run before release) | Three runnable example scripts cover three complete scoring flows: mock offline → real ollama → regression comparison; the real backend is gated by an environment variable | `examples/quick_score.py`, `examples/ollama_backend.py`, `examples/regression_compare.py` | Real-device/network tests are always gated (`MLX_EVAL_LIVE=1` or an equivalent switch); the default `pytest` run contains no live cases |
| 5 | **Black-box testing** | Ignore internal implementation; verify behavior only from the external interface and user perspective | APK/Web, system/OS (forms sensitive to external interfaces/user-visible behavior) | The scoring scripts' stdout summary, JSON report structure, and exit codes serve as externally verifiable contracts | Report-structure assertions in `tests/test_runner.py`; `examples/*` output is the acceptance | No heavyweight black-box "spawn a real process and feed stdin"; mainly example scripts + documented acceptance commands |
| 6 | **White-box testing** | Design cases based on internal implementation structure, covering every branch | Algorithms, models (forms with high logical branch density) | All scorer branches (empty response/full-half-zero keyword hits/length penalty/format branches/score cap), all regression states (new/pass/degraded/regression), runner exception paths | Branch matrix in `tests/test_runner.py` | Branch-level details are triggered only through public methods; private functions are covered indirectly via public behavior |
| 7 | **Gray-box testing** | Combine internal structure knowledge with external interfaces for verification | System/OS, agent (forms needing internal state to corroborate behavior) | Protocol-satisfaction assertions (structure checks) + key internal-state assertions (trace_id threading, payload_hash integrity) | trace_id/payload_hash assertions in `tests/test_runner.py` | Only assert the "externally observable" parts of internal state; no binding to private implementation details |
| 8 | **Functional testing** | Verify that product features work per specification | All forms (the case set is the spec, independent of form) | The case set is the spec: standard cases + extended cases + boundary cases encode the expected product behavior; a single scoring run is the functional acceptance | `src/AIQE/cases/` (4 standard + 6 extended + 8 boundary), `tests/test_extended_cases.py`, `tests/test_boundary_cases.py` | No new test framework; pytest is the only one; new cases must go through real product code paths |
| 9 | **Performance testing** | Verify that throughput, latency, and resource usage meet the targets | Models, system/OS (throughput/latency-sensitive forms) | Execution results capture `elapsed_sec`/`tok_per_sec`/`tokens_generated`; reports and baselines retain the performance fields | Timing fields in `src/AIQE/runner.py`, `examples/*` output, the baseline SOP in `docs/INTEGRATION.md` | Performance has **no automatic gating** (local-inference tok/s fluctuates a lot); regressions go into the report for human judgment; no in-house load-testing platform |
| 10 | **Stability testing** | Under long/repeated runs, resources stay bounded and behavior does not degrade | System/OS, agent, APK (resident/long-running forms) | The mock backend's determinism guarantees reproducible repeated scoring; the `setup`/`teardown` lifecycle is idempotent and safe; soak and memory boundedness are gated scripts | Lifecycle constraints in `src/AIQE/backends/base.py`, soak recommendations in `docs/INTEGRATION.md` | Soak/memory checks are gated scripts (reuse existing facilities such as psutil on real hardware), not resident tests |
| 11 | **Security testing** | Verify the system's resistance to malicious/adversarial input | Agent, APK/Web, system/OS (forms with a large adversarial surface) | Adversarial prompt cases (asserting "refuse/not manipulated" keywords), boundary input cases (full-width/emoji/overlong single line/empty-message follow-ups) | `src/AIQE/cases/boundary_cases.py`, `tests/test_boundary_cases.py` | No in-house security scanner; tools like bandit are used manually as optional dev dependencies; injection-type cases reuse the existing scoring mechanism with zero new dependencies |
| 12 | **UI testing** | Verify the presentation and copy of user-visible output | APK/Web, system/OS (forms with a user interface) | Precise text assertions on the console bar-chart summary (capsys), no screenshots, no browser | `print_summary` rendering assertions in `tests/test_runner.py`, terminal output in `examples/*` | No playwright/selenium/snapshot libraries; text assertions are sufficient and zero-dependency |

**Reading guide**: rows 1-4 are layers "divided by test target" (unit → contract → integration → system); rows 5-8 are perspectives "divided by visibility/purpose" (black-box/white-box/gray-box/functional); rows 9-12 are non-functional layers "divided by quality attribute" (performance/stability/security/UI). The same piece of code can belong to several perspectives at once — for example, a batch of assertions on the scorer is both unit testing and white-box testing; layering is not about attaching labels, but about answering "for this change, which layers should I run".

---

## 2. Shift-Left Testing: Why Score First

Quality assurance for traditional AI applications is "post-hoc": after a model ships, it relies on user feedback, manual spot checks, and incident postmortems. Three fundamental flaws:

1. **Feedback loop too long**: from when a degradation occurs to when it is discovered takes days/weeks;
2. **Cannot attribute causes**: was the prompt changed? Was the model version upgraded? Did the context grow longer? Post-hoc feedback cannot tell;
3. **No baseline**: without numbers there is no concept of "regression" — everything relies on gut feeling.

**Shift-Left testing** pushes quality assurance to the very front of the generation pipeline: before a model is integrated into the product, let it run a fixed set of scoreable tasks first. The position of each test layer in the pipeline follows the same principle — **the cheaper and more deterministic the layer, the earlier it runs**:

```
Contract tests ──→ Unit/white-box ──→ Integration ──→ Functional (case-set scoring) ──→ System/end-to-end
  cheapest         fast               medium          run on every change               before release
  (seconds)        (seconds)          (seconds)       (30 s to minutes)                 (minutes)
                                                                                                        │
                              Performance / stability / security / UI───────────────────────────────────┘
                              (on demand, gated, human judgment, does not block daily work)
```

Key premise: **scoring must be deterministic**. Only when the same input always produces the same score can scores enter a baseline and be compared for regression. This is also why AIQE's scorer uses only the three kinds of reproducible judgments — keyword hits/length checks/format validation: LLM-as-judge is neither realistic in a low-resource local environment (two models would have to reside in memory in parallel) nor reproducible (the same input yields different scores on two runs).

## 3. Decision Table for Layer Usage

Different change scenarios trigger different layers — no need to run all 12 layers every time:

| Change scenario | Which layers to run | Why |
|---|---|---|
| **Model swap** (version/quantization/backend) | Full case set (functional layer: standard+extended+boundary) | Model behavior changes as a whole; which dimension is affected cannot be predicted, so a full sweep is required |
| **Prompt tuning** (prompt rewrite/optimization) | Relevant cases (the category the prompt belongs to and its adjacent categories) | The impact is limited to that task type; running the full set is fine too, but running the relevant cases first gives fast feedback |
| **Scorer change** (judge rules) | Full test suite + re-run all historical cases | The scorer is the "metric" itself; changing it requires first proving the old and new scores are comparable — otherwise all baselines are distorted |
| **Runner/backend protocol change** (runner or Backend Protocol) | Contract tests + integration tests | Protocol breakage is a structural error and surfaces first at the contract layer |
| **Adding new cases** (expanding the case set) | New cases + adjacent-category cases | The case set is an asset; new cases must be able to run independently and produce meaningful scores |
| **Report/output format change** | Black-box (report-structure assertions) + UI (text assertions) | The output format is the contract for downstream consumers |
| **Pre-release full check** | Full case set + performance (check the tok/s report) + security cases | Run all gated and slow layers once more before release |

## 4. Testing Discipline: Test Product Code, Not Self-Verifying No-Ops

No matter how well the test-layer skeleton is built, one common accident slips through: **all tests are green, but the tests are not testing the product at all**. Before writing each test, go through these five questions one by one (this framework's testing-discipline checklist):

1. **Does this test import the real module/function under test?** If the test body re-implements the logic under test — that is a self-verifying test, not a regression test; stop and fix it.
2. **Does it assert product behavior, or the intrinsic properties of strings/numbers?** If the variables are fabricated inside the test function itself and never pass through any product code — the assertions are testing the language itself, not the product.
3. **If the product code is deliberately broken, would this test fail?** After writing it, run a thought experiment: inject an obvious bug into the function under test (invert the return value, delete a branch); if the test is still green = no protective power, rewrite it.
4. **Where were the hard-coded constants copied from?** Magic numbers/label strings in tests should reference the same source as the product code, rather than being typed once each by hand — two independently maintained "supposed to be identical" copies will drift sooner or later.
5. **Does it need real hardware/network?** If so, use dependency injection/monkeypatch so the core logic can be tested offline, instead of skipping the whole group without anyone noticing it never actually ran.

**After fixing a bug, add a regression test with one extra red→green verification step**: first run it against the version where the bug still exists and confirm the test genuinely fails (red), then apply the fix and confirm it turns green. Doing only the second step is as good as doing nothing — the test may have been a no-op from the moment it was written. Put the red→green process in the commit message so reviewers can verify it, instead of trusting "all passed" at face value.

## 5. Lightweight Boundaries: Which Facilities Are Explicitly Not Built In-House

"Complete layers" does not equal "complete facilities". General principle: **prefer existing tools to fill gaps; add new ones only when truly needed, and any addition must be lightweight**. Below are the items this framework explicitly does not build in-house:

| What not to build | Who takes it on | Reason |
|---|---|---|
| LLM-as-judge scorer | Deterministic scoring (keywords/length/format) | A low-resource local environment cannot accommodate a judge model and the model under test in parallel; and LLM scoring is not reproducible, so it cannot enter a baseline |
| Coverage measurement facilities | coverage (used manually, not gated) | Gate-enforced coverage breeds fake "written-for-coverage" tests |
| Static code scanners | ruff / mypy (existing tools; only maintain the gate command) | Scanners are mature tools; building your own is pure reinventing the wheel |
| Security scanners | Optional dev dependencies like bandit (used manually) + injection-type cases in the case set + manual review | Security coverage relies on cases and review, not on in-house scanners |
| UI automation facilities | pytest capsys text assertions (CLI); TestClient lightweight assertions (Web, where applicable) | No playwright/selenium/snapshot libraries — text assertions are sufficient and zero-dependency |
| Load-testing/soak platform | Gated scripts (reuse existing facilities such as psutil on real hardware) | Soak and memory stability are a pre-release campaign, not resident tests |
| Automatic performance gating | Report + human judgment | Local-inference tok/s fluctuates a lot; a hard gate only produces noise or gets relaxed until meaningless |
| New test framework | pytest, the only one | A new framework adds maintenance surface; testing discipline (§4) matters more than the framework |

In one sentence: **layer coverage comes from design; facility building comes from restraint** — most of the 12 layers can be delivered with pytest + existing tools + a set of runnable example scripts, which is also the complete test-facility inventory of this AIQE repository.
