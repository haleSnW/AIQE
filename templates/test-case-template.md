# TestCase 字段模板与填写指南

> 用例是评估体系的资产，字段填写质量决定跑分意义。本文档逐字段说明
> TestCase 的填写规则，并给出好用例/坏用例对照。
> 字段定义以 `src/AIQE/schema.py` 为准（零依赖 dataclass 实现）。

## 1. 字段总览与填写规则

| 字段 | 类型 | 必填 | 填写规则 |
|---|---|---|---|
| `id` | str | ✅ | 全仓库唯一、含类别前缀（如 `ac1_encoding_robustness`）；只允许小写字母/数字/下划线；不允许「描述性长句」当 id |
| `category` | str | ✅ | **必须复用既有类别**（chat / translation / json_output / coding_task / summarization / multi_turn / edge_case 等）——judge 的格式分支按 category 字符串匹配，造新类别会导致格式检查走通用分支或漏判 |
| `prompt` | str | ✅ | 完整可独立执行的输入（不依赖「上一条对话」）；包含判定所需的关键信号词；贴需求场景（见 requirement-analysis.md） |
| `expected_keywords` | list[str] | ✅ | 期望输出**必须包含**的词；2~5 个为宜；对对抗类用例，写「拒绝/不被诱导时应输出的词」；**注意大小写敏感性**：`"artificial"` 不会命中 `"Artificial"` |
| `min_length` | int | ✅ | 输出最短长度（字符数）；防「空响应/截断残句」被误判为合格；正常对话类 ≥ 10，代码类 ≥ 30，翻译类 ≥ 20 |
| `max_tokens` | int | ✅ | 生成预算上限；thinking 模型场景 512 起步（思考过程会吃预算，太小则正式回答被截断）；普通模型按任务量估 |
| `scoring` | ScoreBreakdown | 建议 | 各维度上限；`relevance` 同时是**单用例分数上限**（judge 里 `score = min(score, relevance)`）；不确定就全默认 1.0 |
| `description` | str | 建议 | 注明需求/验收标准来源（如 `AC-1：……`），保证用例可回溯；长度 1~2 句 |

## 2. 模板（直接复制）

```python
from AIQE.schema import TestCase, ScoreBreakdown

cases = [
    TestCase(
        id="<类别>_<语义名>",                    # 如 chat_greeting_required
        category="<复用既有类别>",               # 如 chat
        prompt="<完整可独立执行的输入>",
        expected_keywords=["<词1>", "<词2>"],    # 输出必须包含；2~5 个
        min_length=<数字>,                        # 最短输出长度
        max_tokens=<数字>,                        # 生成预算（thinking 模型 ≥ 512）
        scoring=ScoreBreakdown(
            relevance=1.0, correctness=1.0,
            completeness=1.0, formatting=1.0, confidence=1.0,
        ),
        description="<来源标注：AC-x / 需求 xxx>",
    ),
]
```

## 3. 好用例 vs 坏用例对照

| 维度 | 坏用例（为什么） | 好用例（为什么） |
|---|---|---|
| id | `case1`、`test`（不可读、不可追溯） | `edge_encoding_robustness`（类别前缀 + 语义名） |
| category | `"new_special_thing"`（judge 不认识的类别 → 格式检查全走通用分支，误判风险） | `"edge_case"`（复用既有类别，格式/关键词机制全部生效） |
| prompt | `"你好"`（太短，无法区分任何模型能力） | `"你好，请用一句话介绍你自己，并说明你能做什么。"`（含可判定的回应信号） |
| expected_keywords | `["你"]`（任何响应都含，无区分度） | `["你好", "AI"]`（两个词都有区分度） |
| expected_keywords | `["artificial"]`（而响应是 `"Artificial"`——大小写不敏感场景中常见的失效陷阱） | `["intelligence", "computer"]`（避开大小写陷阱，或确认响应风格后用小写可命中词） |
| min_length | `0`（空响应也过长度关；等于没设） | `20`（翻译类响应明显短于此即异常） |
| max_tokens | `64` 用于长翻译（预算吃光 → 截断 → 稳定低分，测的不是模型是预算） | `256` 起（按任务量留足余量） |
| description | 空（半年后没人知道这个用例要验证什么） | `"AC-1：全角/emoji/超长输入正常处理"`（可回溯到验收标准） |

## 4. 用例集自检命令

写完后跑一遍全用例集，检查「分数有区分度」（不全 1.0 也不全 0）：

```bash
.venv/bin/python examples/quick_score.py        # mock 全量：观察各用例分数分布
.venv/bin/python -m pytest -q                   # 用例元数据合法性（如类别白名单断言）全绿
```
