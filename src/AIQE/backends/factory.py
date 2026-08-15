# AIQE/backends/factory.py —— 评估后端工厂（独立版）
#
# 根据 MLX_EVAL_LIVE 环境变量决定创建 mock 还是真实 MLX 后端。
#
#   MLX_EVAL_LIVE != "1"（默认）-> MockEvalBackend（确定性，无依赖）
#   MLX_EVAL_LIVE == "1"         -> MlxEvalBackend（真实 MLX 推理骨架）
#
# 镜像说明（协议副本说明）：本模块是 上游项目 仓库内
# framework/ai_eval/backends/factory.py 的独立导出版，逻辑逐行一致。

from __future__ import annotations

import os

from AIQE.backends.base import EvaluationBackend
from AIQE.backends.mock import MockEvalBackend
from AIQE.backends.mlx import MlxEvalBackend


def create_eval_backend(
    model_id: str = "mock-eval-model",
    **kwargs,
) -> EvaluationBackend:
    """创建评估后端实例。

    【环境变量】
      MLX_EVAL_LIVE: "1"/"true"/"yes"（不区分大小写）-> 真实 MLX
                     其他 / 未设置                       -> Mock（默认）

    【参数】
      model_id : 模型标识。mock 模式下仅用于报告标识；
                 live 模式下是真实 MLX 模型 id。
      **kwargs : 透传给具体后端（如 quant）。

    【返回】
      满足 EvaluationBackend Protocol 的实例（未 setup，调用方需自行 setup()）。
    """
    live = os.environ.get("MLX_EVAL_LIVE", "").lower() in ("1", "true", "yes")

    if live:
        return MlxEvalBackend(model_id=model_id, **kwargs)
    return MockEvalBackend(model_id=model_id)
