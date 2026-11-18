import pytest

from AIQE.backends.openai_compatible import (
    OpenAICompatibleBackend,
    OpenAICompatibleBackendKind,
    OpenAICompatibleClient,
    OpenAICompatibleConfig,
    OpenAICompatibleResponseError,
)
from AIQE.http_transport import JsonHttpResponse
from AIQE.protocol import Backend, GenerateOptions


class FakeTransport:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = []
        self.error = None

    def post_json(self, url, payload, *, headers=None):
        self.calls.append({"url": url, "payload": payload, "headers": headers or {}})
        if self.error is not None:
            raise self.error
        return JsonHttpResponse(200, self.payload, 1)


def _ok_payload(*, include_usage: bool = True) -> dict:
    payload = {
        "id": "req-1",
        "model": "resolved-model-r1",
        "choices": [
            {
                "message": {"role": "assistant", "content": "hello"},
                "finish_reason": "stop",
            }
        ],
    }
    if include_usage:
        payload["usage"] = {
            "prompt_tokens": 2,
            "completion_tokens": 3,
            "total_tokens": 5,
        }
    return payload


def test_config_builds_one_explicit_chat_completions_endpoint() -> None:
    root = OpenAICompatibleConfig("http://127.0.0.1:8000", "model-a")
    v1 = OpenAICompatibleConfig("http://127.0.0.1:8001/v1", "model-b")

    assert root.chat_completions_url == "http://127.0.0.1:8000/v1/chat/completions"
    assert v1.chat_completions_url == "http://127.0.0.1:8001/v1/chat/completions"


def test_mut_and_judge_configs_are_independent() -> None:
    mut = OpenAICompatibleConfig("http://127.0.0.1:8100/v1", "mut-model")
    judge = OpenAICompatibleConfig("http://127.0.0.1:8200/v1", "judge-model")

    assert mut.api_base_url != judge.api_base_url
    assert mut.model != judge.model


def test_client_sends_text_only_non_streaming_request() -> None:
    fake = FakeTransport(_ok_payload())
    config = OpenAICompatibleConfig("http://127.0.0.1:8000/v1", "requested-model")
    client = OpenAICompatibleClient(config, "cred", fake)

    result = client.complete(
        "user text",
        GenerateOptions(system="system text", max_tokens=32, temperature=0.1, top_p=0.8),
    )

    assert result.text == "hello"
    assert result.resolved_model_id == "resolved-model-r1"
    assert result.usage is not None
    assert result.usage.completion_tokens == 3
    assert fake.calls[0]["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    sent = fake.calls[0]["payload"]
    assert sent["stream"] is False
    assert sent["model"] == "requested-model"
    assert sent["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]
    assert sent["max_tokens"] == 32
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer cred"
    assert "cred" not in repr(config)


def test_missing_provider_usage_stays_unavailable_on_client_result() -> None:
    fake = FakeTransport(_ok_payload(include_usage=False))
    config = OpenAICompatibleConfig("http://127.0.0.1:8000/v1", "model-a")

    result = OpenAICompatibleClient(config, None, fake).complete("hello")

    assert result.usage is None


def test_malformed_or_incomplete_response_is_error() -> None:
    fake = FakeTransport({"choices": []})
    config = OpenAICompatibleConfig("http://127.0.0.1:8000/v1", "model-a")

    with pytest.raises(OpenAICompatibleResponseError):
        OpenAICompatibleClient(config, None, fake).complete("hello")


def test_text_only_subset_rejects_images_and_thinking_extension() -> None:
    fake = FakeTransport(_ok_payload())
    config = OpenAICompatibleConfig("http://127.0.0.1:8000/v1", "model-a")
    client = OpenAICompatibleClient(config, None, fake)

    with pytest.raises(ValueError):
        client.complete("hello", GenerateOptions(images=["image-data"]))
    with pytest.raises(ValueError):
        client.complete("hello", GenerateOptions(enable_thinking=False))

    assert fake.calls == []


def test_backend_has_truthful_runtime_label_and_protocol_shape() -> None:
    fake = FakeTransport(_ok_payload())
    config = OpenAICompatibleConfig("http://127.0.0.1:8000/v1", "model-a")
    backend = OpenAICompatibleBackend(config, None, fake)

    assert isinstance(backend, Backend)
    assert backend.backend_type is OpenAICompatibleBackendKind.OPENAI_COMPATIBLE
    assert backend.backend_type.value == "openai-compatible"
    assert backend.is_loaded() is False

    backend.setup()
    assert backend.is_loaded() is True
    assert backend.profile() is not None
    assert backend.profile().model_id == "model-a"

    result = backend.generate_sync("hello")
    assert result.text == "hello"
    assert result.tokens_generated == 3
    assert backend.last_provider_usage is not None
    assert backend.last_token_count_source == "provider"


def test_backend_marks_protocol_count_as_estimated_when_usage_missing() -> None:
    fake = FakeTransport(_ok_payload(include_usage=False))
    config = OpenAICompatibleConfig("http://127.0.0.1:8000/v1", "model-a")
    backend = OpenAICompatibleBackend(config, None, fake)
    backend.setup()

    result = backend.generate_sync("hello")

    assert result.tokens_generated == len("hello")
    assert backend.last_provider_usage is None
    assert backend.last_token_count_source == "estimated_protocol_fallback"


def test_backend_requires_setup_and_never_silently_falls_back() -> None:
    fake = FakeTransport(_ok_payload())
    config = OpenAICompatibleConfig("http://127.0.0.1:8000/v1", "model-a")
    backend = OpenAICompatibleBackend(config, None, fake)

    with pytest.raises(RuntimeError):
        backend.generate_sync("hello")

    assert fake.calls == []


def test_loading_new_model_rebuilds_profile_and_clears_prior_usage() -> None:
    fake = FakeTransport(_ok_payload())
    backend = OpenAICompatibleBackend(
        OpenAICompatibleConfig("http://127.0.0.1:8000/v1", "model-a"), None, fake
    )
    backend.load("model-a")
    backend.generate_sync("hello")

    profile = backend.load("model-b", quant="q8")

    assert backend.model_id == "model-b"
    assert profile.model_id == "model-b"
    assert backend.profile() == profile
    assert profile.quant == "q8"
    assert backend.is_loaded() is True
    assert backend.last_provider_usage is None
    assert backend.last_token_count_source == "unavailable"


def test_failed_generation_clears_previous_provider_usage() -> None:
    fake = FakeTransport(_ok_payload())
    backend = OpenAICompatibleBackend(
        OpenAICompatibleConfig("http://127.0.0.1:8000/v1", "model-a"), None, fake
    )
    backend.setup()
    backend.generate_sync("successful call")
    assert backend.last_provider_usage is not None

    fake.error = RuntimeError("injected transport failure")
    with pytest.raises(RuntimeError, match="injected transport failure"):
        backend.generate_sync("failing call")

    assert backend.last_provider_usage is None
    assert backend.last_token_count_source == "unavailable"
