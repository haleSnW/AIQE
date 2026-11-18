# AIQE 模板选型

先选自己要证明的能力，再复制相应模板。以下模板分别面向不同阶段；不要把公开合成展示当作真机测量，也不要把原始设备报告直接交给质量看板。

- **定义可复现用例**：`test-case-template.md`。适合写清输入、判定词、类别和验收来源。执行前复核关键词评分的局限。
- **把 AIQE 接入项目**：`test-script-template.py`。适合验证 Runner → Judge → Reporter 最小流水线；示例默认 mock。输出的原始 `EvaluationReport` 含提示词和回复，不可直接送入公开看板。
- **审阅单次结果**：`report-template.md`。适合工程评审，区分执行失败与判定失败，并记录基线条件。
- **展示开源能力**：`dashboard-showcase-template.md`。用六次可复现的公开合成运行讲述回归故事，说明图表口径和不可用数据。

推荐开源展示顺序：用例模板 → 可运行脚本 → 合成看板。真实数据接入前，先满足[看板证据契约冻结](../docs/architecture/AIQE_EVIDENCE_CONTRACT_FREEZE_20261108.md)中的证据等级要求。每个阶段附原命令、退出码、产物路径和未验证项。
