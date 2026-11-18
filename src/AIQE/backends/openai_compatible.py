"""Minimal OpenAI-compatible HTTP client/backend for AIQE Public v0.2.

Supported subset: text-only, non-streaming ``/v1/chat/completions``. Endpoint
configuration is explicit per instance so callers can create separate MUT and
Judge clients without sharing credentials or silently falling back between
providers.
"""

from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterator, cast

from AIQE.http_transport import HttpTransportConfig, JsonHttpResponse, StdlibJsonTransport
from AIQE.protocol import BackendType, GenerateOptions, GenerateResult, ModelProfile


class OpenAICompatibleResponseError(RuntimeError):
    """Raised when a nominally successful response violates the supported schema."""


class OpenAICompatibleBackendKind(str, Enum):
    """Truthful runtime label until the shared BackendType enum is expanded."""

    OPENAI_COMPATIBLE = "openai-compatible"


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    """Public, serializable connection metadata. Credentials are not a field."""

    api_base_url: str
    model: str
    timeout_seconds: float = 30.0
    max_response_bytes: int = 1_048_576
    max_attempts: int = 1

    def __post_init__(self) -> None:
        parsed = urllib.parse.urlsplit(self.api_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("api_base_url must use http/https and include a host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("credentials must not be embedded in api_base_url")
        if parsed.query or parsed.fragment:
            raise ValueError("api_base_url must not contain query or fragment")
        if not self.model.strip():
            raise ValueError("model must be non-empty")
        HttpTransportConfig(
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
            max_attempts=self.max_attempts,
        )

    @property
    def chat_completions_url(self) -> str:
        base = self.api_base_url.rstrip("/")
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/v1/chat/completions"


@dataclass(frozen=True)
class OpenAIChatUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class OpenAIChatResult:
    text: str
    resolved_model_id: str | None
    finish_reason: str | None
    usage: OpenAIChatUsage | None
    request_id: str | None
    attempts: int


def _optional_count(obj: dict[str, Any], key: str) -> int | None:
    if key not in obj or obj[key] is None:
        return None
    value = obj[key]
    if type(value) is not int or value < 0:
        raise OpenAICompatibleResponseError(f"usage.{key} must be a non-negative integer")
    return value


def _parse_usage(payload: dict[str, Any]) -> OpenAIChatUsage | None:
    raw = payload.get("usage")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise OpenAICompatibleResponseError("usage must be an object when present")
    usage = OpenAIChatUsage(
        _optional_count(raw, "prompt_tokens"),
        _optional_count(raw, "completion_tokens"),
        _optional_count(raw, "total_tokens"),
    )
    if all(value is None for value in (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)):
        return None
    return usage


class OpenAICompatibleClient:
    """One explicitly configured OpenAI-compatible endpoint.

    The credential value is stored separately from the frozen public config and
    is never included in result objects or ``repr(config)``. Create distinct
    instances for MUT and Judge endpoints.
    """

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        api_key: str | None = None,
        transport: StdlibJsonTransport | None = None,
    ) -> None:
        self.config = config
        self._api_key = api_key
        self._transport = transport or StdlibJsonTransport(
            HttpTransportConfig(
                timeout_seconds=config.timeout_seconds,
                max_response_bytes=config.max_response_bytes,
                max_attempts=config.max_attempts,
            )
        )

    def complete(self, prompt: str, opts: GenerateOptions | None = None) -> OpenAIChatResult:
        options = opts or GenerateOptions()
        if options.images:
            raise ValueError("Public v0.2 OpenAI-compatible backend is text-only")
        if options.draft_model is not None:
            raise ValueError("draft_model is outside the supported HTTP subset")
        if options.enable_thinking is not None:
            raise ValueError("enable_thinking is outside the supported HTTP subset")

        messages: list[dict[str, str]] = []
        if options.system:
            messages.append({"role": "system", "content": options.system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "temperature": options.temperature,
            "top_p": options.top_p,
        }
        body["max_tokens"] = options.max_tokens
        if options.stop:
            body["stop"] = list(options.stop)

        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response: JsonHttpResponse = self._transport.post_json(
            self.config.chat_completions_url,
            body,
            headers=headers,
        )
        payload = response.payload
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise OpenAICompatibleResponseError("choices[0] is required")
        first = choices[0]
        message = first.get("message")
        if not isinstance(message, dict) or "content" not in message:
            raise OpenAICompatibleResponseError("choices[0].message.content is required")
        text = message["content"]
        if not isinstance(text, str):
            raise OpenAICompatibleResponseError("message.content must be a string")

        model = payload.get("model")
        if model is not None and not isinstance(model, str):
            raise OpenAICompatibleResponseError("model must be a string when present")
        finish_reason = first.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise OpenAICompatibleResponseError("finish_reason must be a string when present")
        request_id = payload.get("id")
        if request_id is not None and not isinstance(request_id, str):
            raise OpenAICompatibleResponseError("id must be a string when present")

        return OpenAIChatResult(
            text,
            model,
            finish_reason,
            _parse_usage(payload),
            request_id,
            response.attempts,
        )


class OpenAICompatibleBackend:
    """EvaluationBackend-shaped adapter backed by ``OpenAICompatibleClient``.

    The shared ``BackendType`` enum has no generic HTTP member yet. This adapter
    uses a small truthful enum with the same ``.value`` behavior consumed by
    ``ExecutionRunner`` instead of mislabeling HTTP traffic as Ollama or Mesh.

    Provider usage remains available via ``last_provider_usage``. When absent,
    ``GenerateResult`` uses the existing protocol fallback estimate and
    ``last_token_count_source`` records that it was estimated; callers must not
    present that estimate as provider-reported usage.
    """

    name = "openai-compatible"

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        api_key: str | None = None,
        transport: StdlibJsonTransport | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._transport = transport
        self._client = OpenAICompatibleClient(config, api_key, transport)
        self._loaded = False
        self._profile: ModelProfile | None = None
        self._last_chat_result: OpenAIChatResult | None = None
        self._count_source = "unavailable"

    @property
    def model_id(self) -> str:
        return self._config.model

    @property
    def backend_type(self) -> OpenAICompatibleBackendKind:
        return OpenAICompatibleBackendKind.OPENAI_COMPATIBLE

    @property
    def last_provider_usage(self) -> OpenAIChatUsage | None:
        return self._last_chat_result.usage if self._last_chat_result else None

    @property
    def last_token_count_source(self) -> str:
        return self._count_source

    def setup(self, quant: str = "remote") -> None:
        if self._loaded:
            return
        kind = cast(BackendType, OpenAICompatibleBackendKind.OPENAI_COMPATIBLE)
        self._profile = ModelProfile(
            model_id=self._config.model,
            backend=kind,
            quant=quant,
            loaded=True,
        )
        self._loaded = True

    def teardown(self) -> None:
        self._loaded = False
        self._profile = None
        self._last_chat_result = None
        self._count_source = "unavailable"

    def is_loaded(self) -> bool:
        return self._loaded and self._profile is not None

    def profile(self) -> ModelProfile | None:
        return self._profile

    def load(self, model_id: str, quant: str = "remote") -> ModelProfile:
        if model_id != self._config.model:
            self._config = replace(self._config, model=model_id)
            self._client = OpenAICompatibleClient(self._config, self._api_key, self._transport)
            self._loaded = False
            self._profile = None
            self._last_chat_result = None
            self._count_source = "unavailable"
        self.setup(quant)
        return self._profile  # type: ignore[return-value]

    def unload(self) -> None:
        self.teardown()

    def generate(self, prompt: str, opts: GenerateOptions | None = None) -> Iterator[str]:
        yield self.generate_sync(prompt, opts).text

    def generate_sync(self, prompt: str, opts: GenerateOptions | None = None) -> GenerateResult:
        if not self.is_loaded():
            raise RuntimeError("model is not loaded; call setup() first")
        self._last_chat_result = None
        self._count_source = "unavailable"
        start = time.perf_counter()
        chat = self._client.complete(prompt, opts)
        elapsed = time.perf_counter() - start
        self._last_chat_result = chat
        completion_count = chat.usage.completion_tokens if chat.usage else None
        if completion_count is None:
            count = max(1, len(chat.text))
            self._count_source = "estimated_protocol_fallback"
        else:
            count = completion_count
            self._count_source = "provider"
        return GenerateResult(
            text=chat.text,
            tokens_generated=count,
            elapsed_sec=elapsed,
            tok_per_sec=count / elapsed if elapsed > 0 else 0.0,
            thinking="",
        )
