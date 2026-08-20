# AIQE/backends/ —— 评估后端抽象层
#
# 位于 ExecutionRunner 与具体推理后端之间。
# ExecutionRunner 只依赖 Backend Protocol，本层提供评估专用生命周期管理。
# base.py      EvaluationBackend Protocol（Backend 超集 + setup/teardown）
# mock.py      MockEvalBackend：确定性 mock（默认，零依赖零网络）
# mlx.py       MlxEvalBackend：真实 MLX 推理骨架（需自行注入适配层）
# factory.py   create_eval_backend()：按 MLX_EVAL_LIVE 环境变量切换

from __future__ import annotations

from AIQE.backends.base import EvaluationBackend
from AIQE.backends.mock import MockEvalBackend
from AIQE.backends.mlx import MlxEvalBackend
from AIQE.backends.factory import create_eval_backend

__all__ = [
    "EvaluationBackend",
    "MockEvalBackend",
    "MlxEvalBackend",
    "create_eval_backend",
]
