# ollama_backend.py —— 接入本地 ollama 后端的完整跑分示例
#
# 用途：用真实本地模型（ollama 管理）跑 AIQE 全流程：
#   OllamaEvalBackend（满足 AIQE 后端协议，urllib 零依赖）
#     → ExecutionRunner 执行 4 个标准用例
#     → OutputJudge 确定性评分
#     → RegressionAnalyzer 对比历史基线（~/.AIQE/results/baseline.json）
#     → EvaluationReport 输出 JSON 报告 + 控制台摘要
#
# 【先做什么再跑】
#   1. 安装并启动 ollama（macOS: brew install ollama && ollama serve；
#      其他平台见 https://ollama.com/download）
#   2. 拉取模型：ollama pull llama3.2
#      （也可用任意已安装模型，见第 3 步的环境变量）
#   3. 运行本脚本：
#        python examples/ollama_backend.py
#      可选环境变量：
#        OLLAMA_BASE_URL  默认 http://localhost:11434
#        OLLAMA_MODEL     默认 llama3.2（换成你已 pull 的模型，如 qwen2.5:7b）
#   4. 模型未就绪时脚本会打印中文指引后退出——按指引安装/拉取即可，不会半路崩溃
#
# 零第三方依赖：HTTP 用标准库 urllib（与 AIQE 内部实现一致）。

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 允许直接以脚本方式运行（不依赖安装）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from AIQE.backends.base import EvaluationBackend  # noqa: E402
from AIQE.cases.test_cases import get_test_cases   # noqa: E402
from AIQE.judge import OutputJudge                 # noqa: E402
from AIQE.protocol import BackendType, GenerateOptions, GenerateResult, ModelProfile  # noqa: E402
from AIQE.regression import RegressionAnalyzer     # noqa: E402
from AIQE.reporter import EvaluationReport         # noqa: E402
from AIQE.runner import ExecutionRunner            # noqa: E402


class OllamaEvalBackend:
    """Ollama 评估后端：满足 AIQE 的 EvaluationBackend 协议。

    只依赖标准库 urllib，可整体复制进你自己的项目使用。
    生命周期：setup()（检查服务与模型就绪）→ generate_sync() → teardown()。
    """

    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "llama3.2", timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._profile: ModelProfile | None = None
        self._setup_done = False

    # ── 评估生命周期 ─────────────────────────────────────
    def setup(self) -> None:
        """检查 ollama 服务与模型是否就绪（幂等）。

        模型未就绪时打印中文指引并退出（不抛半截异常）：
          - 服务连不上 → 提示安装/启动 ollama、核对 OLLAMA_BASE_URL
          - 模型不存在  → 提示 ollama pull <model>
        """
        if self._setup_done:
            return

        # 1) 服务连通性检查：GET /api/tags
        try:
            with urllib.request.urlopen(
                f"{self._base_url}/api/tags", timeout=min(self._timeout, 10.0)
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            print(
                f"\n[ollama] 无法连接 {self._base_url}（{e.reason}）。\n"
                "  修复建议：\n"
                "    1. 安装 ollama：https://ollama.com/download\n"
                "    2. 启动服务：macOS/Linux 运行 `ollama serve`，"
                "Windows 打开 Ollama 应用\n"
                "    3. 若服务在别的地址，设置环境变量 OLLAMA_BASE_URL 后重跑\n"
            )
            sys.exit(1)

        # 2) 模型存在性检查：/api/tags 返回的 models 列表
        installed = {m.get("name", "") for m in data.get("models", [])}
        if self._model not in installed:
            print(
                f"\n[ollama] 模型 {self._model!r} 未安装。已安装: "
                f"{', '.join(sorted(installed)) or '（无）'}。\n"
                "  修复建议：运行 `ollama pull "
                f"{self._model}` 下载模型后重跑本脚本；\n"
                "  或设置环境变量 OLLAMA_MODEL 指定已安装的模型。\n"
            )
            sys.exit(1)

        # 3) 就绪：建立能力画像
        self._profile = ModelProfile(
            model_id=self._model,
            backend=BackendType.OLLAMA,
            quant="fp16",          # ollama 侧按 tag 管理量化，此处仅作标识
            ctx_len=8192,
            loaded=True,
        )
        self._setup_done = True
        print(f"[ollama] 后端就绪：model={self._model} @ {self._base_url}")

    def teardown(self) -> None:
        """清理（安全：未 setup 也不抛）。"""
        self._profile = None
        self._setup_done = False

    @property
    def model_id(self) -> str:
        return self._model

    # ── Backend Protocol 实现 ────────────────────────────
    @property
    def backend_type(self) -> BackendType:
        return BackendType.OLLAMA

    def is_loaded(self) -> bool:
        return self._setup_done and self._profile is not None

    def profile(self) -> ModelProfile | None:
        return self._profile

    def load(self, model_id: str, quant: str = "fp16") -> ModelProfile:
        """兼容 Backend.load()：设置模型并 setup。"""
        self._model = model_id
        self.setup()
        return self._profile  # type: ignore[return-value]

    def unload(self) -> None:
        self.teardown()

    def generate_sync(
        self, prompt: str, opts: GenerateOptions | None = None
    ) -> GenerateResult:
        """非流式生成：POST /api/chat（messages 格式，与生产一致）。

        未 setup 时抛 RuntimeError（与协议语义一致，由 ExecutionRunner 捕获
        记录为 error 结果，不会让整次跑分崩溃）。
        """
        if not self.is_loaded():
            raise RuntimeError("模型未加载，请先调用 setup()")

        body = json.dumps({
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_predict": opts.max_tokens if opts else 512},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        start = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.perf_counter() - start

        text: str = data.get("message", {}).get("content", "")
        tokens = data.get("eval_count", 0) or max(1, len(text))
        tok_per_sec = tokens / elapsed if elapsed > 0 else 0.0
        return GenerateResult(
            text=text,
            tokens_generated=tokens,
            elapsed_sec=elapsed,
            tok_per_sec=tok_per_sec,
            thinking="",
        )


def main() -> None:
    # 1. 后端：ollama（环境变量可覆盖默认地址/模型）
    backend = OllamaEvalBackend(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.environ.get("OLLAMA_MODEL", "llama3.2"),
    )
    backend.setup()  # 模型未就绪时此处打印中文指引并退出
    try:
        # 2. 组装流水线
        runner = ExecutionRunner(backend)
        judge = OutputJudge()
        analyzer = RegressionAnalyzer()        # 默认基线 ~/.AIQE/results/baseline.json
        report = EvaluationReport(test_plan_id=f"ollama-{backend.model_id}")

        # 3. 执行 → 评分 → 回归 → 聚合
        for case in get_test_cases():
            exec_result = runner.run(case)
            judge_result = judge.judge(case, exec_result)
            regression_result = analyzer.analyze(case.id, judge_result.score)
            report.add_case(case, exec_result, judge_result, regression_result)

        # 4. 落盘报告（文件名含模型名，便于多模型对比归档）
        out = Path(f"AIQE-report-ollama-{backend.model_id.replace(':', '_')}.json")
        report.to_json(path=out)
        print(f"报告已写入: {out.resolve()}")

        # 5. 控制台摘要
        report.print_summary()
    finally:
        backend.teardown()


if __name__ == "__main__":
    main()
