# AIQE/backends/ —— 评估后端抽象层（独立版）
#
# 镜像说明（协议副本说明）：本包是 上游项目 仓库内 framework/ai_eval/backends/
# 的独立导出版，仅将跨包 import 改为 AIQE.protocol 本地副本，逻辑逐行一致。
#
# 位于 ExecutionRunner 与具体推理后端之间。
# ExecutionRunner 只依赖 Backend Protocol，本层提供评估专用生命周期管理。

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
