import json
import urllib.error

import pytest

from AIQE.http_transport import (
    HttpStatusError,
    HttpTransportConfig,
    HttpTransportError,
    InvalidJsonResponseError,
    ResponseTooLargeError,
    StdlibJsonTransport,
)


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def read(self, amount: int = -1) -> bytes:
        return self.payload if amount < 0 else self.payload[:amount]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeOpener:
    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = []

    def open(self, req, timeout):
        self.calls.append((req, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_post_json_encodes_request_and_returns_object() -> None:
    opener = FakeOpener(FakeResponse(b'{"ok": true}'))
    transport = StdlibJsonTransport(HttpTransportConfig(timeout_seconds=2), opener=opener)

    result = transport.post_json("http://127.0.0.1:9999/v1/test", {"hello": "world"})

    assert result.status == 200
    assert result.payload == {"ok": True}
    assert result.attempts == 1
    req, timeout = opener.calls[0]
    assert timeout == 2
    assert req.full_url == "http://127.0.0.1:9999/v1/test"
    assert json.loads(req.data.decode("utf-8")) == {"hello": "world"}


def test_transport_retries_only_within_configured_attempt_bound() -> None:
    opener = FakeOpener(
        urllib.error.URLError("offline"),
        FakeResponse(b'{"ok": true}'),
    )
    transport = StdlibJsonTransport(HttpTransportConfig(max_attempts=2), opener=opener)

    result = transport.post_json("http://127.0.0.1:9999/v1/test", {})

    assert result.attempts == 2
    assert len(opener.calls) == 2


def test_transport_does_not_retry_client_error() -> None:
    opener = FakeOpener(FakeResponse(b"{}", status=400))
    transport = StdlibJsonTransport(HttpTransportConfig(max_attempts=3), opener=opener)

    with pytest.raises(HttpStatusError) as exc:
        transport.post_json("http://127.0.0.1:9999/v1/test", {})

    assert exc.value.status == 400
    assert len(opener.calls) == 1


def test_transport_rejects_redirect_response_instead_of_following() -> None:
    opener = FakeOpener(FakeResponse(b"{}", status=302))
    transport = StdlibJsonTransport(opener=opener)

    with pytest.raises(HttpStatusError) as exc:
        transport.post_json("http://127.0.0.1:9999/v1/test", {})

    assert exc.value.status == 302
    assert len(opener.calls) == 1


def test_transport_rejects_oversized_response() -> None:
    opener = FakeOpener(FakeResponse(b"12345"))
    transport = StdlibJsonTransport(HttpTransportConfig(max_response_bytes=4), opener=opener)

    with pytest.raises(ResponseTooLargeError):
        transport.post_json("http://127.0.0.1:9999/v1/test", {})


def test_transport_rejects_malformed_json() -> None:
    opener = FakeOpener(FakeResponse(b"not-json"))
    transport = StdlibJsonTransport(opener=opener)

    with pytest.raises(InvalidJsonResponseError):
        transport.post_json("http://127.0.0.1:9999/v1/test", {})


def test_transport_rejects_embedded_url_credentials() -> None:
    transport = StdlibJsonTransport(opener=FakeOpener())

    with pytest.raises(ValueError):
        transport.post_json("http://user:pass@127.0.0.1:9999/v1/test", {})


def test_transport_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        HttpTransportConfig(max_attempts=4)
    with pytest.raises(ValueError):
        HttpTransportConfig(timeout_seconds=0)
    with pytest.raises(ValueError):
        HttpTransportConfig(max_response_bytes=0)


def test_transport_failure_message_does_not_include_payload_or_headers() -> None:
    opener = FakeOpener(urllib.error.URLError("offline"))
    transport = StdlibJsonTransport(opener=opener)

    with pytest.raises(HttpTransportError) as exc:
        transport.post_json(
            "http://127.0.0.1:9999/v1/test",
            {"private": "do-not-echo"},
            headers={"X-Private": "do-not-echo"},
        )

    assert "do-not-echo" not in str(exc.value)
