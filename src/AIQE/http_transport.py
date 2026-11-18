"""Bounded stdlib JSON-over-HTTP transport for AIQE.

This module deliberately does not know about model semantics.  It provides a
small, injectable transport with bounded timeout/response size/attempts and a
no-redirect policy so higher layers can keep endpoint provenance explicit.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class HttpTransportError(RuntimeError):
    """Base error for bounded HTTP transport failures."""


class HttpStatusError(HttpTransportError):
    """Raised for a non-2xx HTTP response."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP request failed with status {status}")
        self.status = status


class ResponseTooLargeError(HttpTransportError):
    """Raised when a response exceeds the configured byte limit."""


class InvalidJsonResponseError(HttpTransportError):
    """Raised when the bounded response is not a JSON object."""


@dataclass(frozen=True)
class HttpTransportConfig:
    timeout_seconds: float = 30.0
    max_response_bytes: int = 1_048_576
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 120.0:
            raise ValueError("timeout_seconds must be in (0, 120]")
        if not 1 <= self.max_response_bytes <= 8 * 1024 * 1024:
            raise ValueError("max_response_bytes must be in [1, 8 MiB]")
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be in [1, 3]")


@dataclass(frozen=True)
class JsonHttpResponse:
    status: int
    payload: dict[str, Any]
    attempts: int


class _ResponseLike(Protocol):
    status: int

    def read(self, amount: int = -1) -> bytes:
        ...

    def __enter__(self) -> "_ResponseLike":
        ...

    def __exit__(self, exc_type, exc, tb) -> None:
        ...


class _OpenerLike(Protocol):
    def open(self, req: urllib.request.Request, timeout: float) -> _ResponseLike:
        ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Disable urllib's implicit redirect following."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class StdlibJsonTransport:
    """Small JSON POST transport with explicit, bounded behavior.

    Retries are limited to transient transport failures and HTTP 5xx responses.
    Redirects are never followed.  Error messages intentionally omit response
    bodies and request headers so credentials/private prompts are not echoed.
    """

    def __init__(
        self,
        config: HttpTransportConfig | None = None,
        *,
        opener: _OpenerLike | None = None,
    ) -> None:
        self.config = config or HttpTransportConfig()
        self._opener: _OpenerLike = opener or urllib.request.build_opener(
            _NoRedirectHandler()
        )

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("HTTP URL must use http/https and include a host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("credentials must not be embedded in URL")
        if parsed.fragment:
            raise ValueError("HTTP URL fragments are not supported")

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> JsonHttpResponse:
        self._validate_url(url)
        body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        request_headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)

        last_error: BaseException | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            req = urllib.request.Request(
                url,
                data=body,
                headers=request_headers,
                method="POST",
            )
            try:
                with self._opener.open(req, timeout=self.config.timeout_seconds) as resp:
                    status = int(resp.status)
                    if not 200 <= status < 300:
                        if status >= 500 and attempt < self.config.max_attempts:
                            last_error = HttpStatusError(status)
                            continue
                        raise HttpStatusError(status)
                    raw = resp.read(self.config.max_response_bytes + 1)
            except urllib.error.HTTPError as exc:
                if exc.code >= 500 and attempt < self.config.max_attempts:
                    last_error = exc
                    continue
                raise HttpStatusError(int(exc.code)) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.config.max_attempts:
                    continue
                raise HttpTransportError(
                    f"HTTP request failed after {attempt} attempt(s)"
                ) from exc

            if len(raw) > self.config.max_response_bytes:
                raise ResponseTooLargeError("HTTP response exceeded configured byte limit")
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InvalidJsonResponseError("HTTP response is not valid JSON") from exc
            if not isinstance(decoded, dict):
                raise InvalidJsonResponseError("HTTP response JSON must be an object")
            return JsonHttpResponse(status=status, payload=decoded, attempts=attempt)

        # Defensive only: every loop path returns or raises.
        raise HttpTransportError("HTTP request failed") from last_error
