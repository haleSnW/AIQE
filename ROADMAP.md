# AIQE Roadmap

> AIQE 是 Apache-2.0 开源的测试左移 AI 质量评估框架参考实现。
> 本路线图描述**可能的发展方向**——**不承诺时间线、不承诺具体交付**。
> 优先级跟随真实使用与社区反馈（issues / PRs / discussions）调整。
>
> This roadmap lists **possible directions**, with **no timeline and no
> commitments**. Priorities respond to real usage and community feedback.

## 范围边界 / Scope

- **公共范围（Public scope）**: framework + templates + methodology —
  代码、测试、模板、方法论文档。
- **私有范围（Private scope）**: MyFri 内部 AIQE 数据集与验证资产。
  私有评估资产**永远不会**出现在本仓库。

## 可能的方向 / Possible directions

### 1. 更多模型适配器 / More model adapters

当前的接入契约为 `AIQE.protocol.Backend`，新增后端不触碰评估流水线：

- **Ollama adapter 稳定化**：从「示例级」提升为受支持的内置后端
- **MLX 真实适配**：把现在的骨架实现（`backends/mlx.py`）补成可用适配层
- **llama.cpp / OpenAI 兼容端点**：通过 Backend Protocol 接入
- **多后端对比**：同一用例集跑多个模型/量化，输出横向对比

为什么值得做：换模型是质量回归的头号来源——评估成本越低，团队越愿意常测。

### 2. 可选的 LLM 裁判模式 / Optional LLM judge

确定性评分保持默认与核心；在此基础上评估**可选**的 LLM 裁判维度
（如语义相似度、开放性任务的质性分），并明确其与确定性评分的分工
与回退策略。引入原则：**默认仍然离线、确定性、零依赖**。

### 3. 更丰富的评估数据集 / Richer evaluation datasets

- 扩充标准用例与边界用例库（多语言、多任务类型、对抗输入）
- 面向场景的公开用例包（RAG、工具调用、Agent 工作流、结构化输出）
- 用例贡献规范：什么用例值得进库、如何验证其判别力

### 4. 多语言报告 / Multilingual reports

- 报告 JSON 与 Markdown 输出支持 中文 / English 双语言
- 报告模板的多语言版本（目前 `templates/report-template.md` 为中文）

### 5. 开发者体验 / Developer experience

- CLI 入口（`aiqe run` / `aiqe compare`），把流水线从示例脚本提升为一等命令
- GitHub Action 复用：仓库内现成的 `test.yml` 抽成可复用 action 的评估
- pytest 插件集成模式（与现有 pytest 测试共存的具体约定）

### 6. 社区共建 / Community

- 新后端接入指南（walkthrough：从协议到测试全绿）
- 用例贡献指南（模板 + 校验流程）
- 公开基准发布规范（数据、基线、报告如何一起发布，保证可复现）

## 明确不做 / Explicitly out of scope

- **私有评估资产**：MyFri 内部数据集、内部用例、内部基线、内部报告
- **伪造基准**：任何未经真实执行的 benchmark 数字
- **收费功能**：AIQE 保持 Apache-2.0 免费开源

## 如何影响路线图 / How to influence

- 开 issue 描述你实际遇到的问题（见 `.github/ISSUE_TEMPLATE/`）
- 提交 PR——尤其适配器与用例集
- 在 issue 里说明你正在用什么后端/场景评估什么，帮助排优先级

> 路线图随项目演化更新；内容变更遵循与代码相同的透明原则。
