"""OpenRouter transport for GPT-5.6 Sol (``REV/06``). The only module that knows OpenRouter's API.

One attempt = one ``POST {base_url}/chat/completions`` with:

- ``model``: the pinned model (``settings.PINNED_MODEL``, ``openai/gpt-5.6-sol``) chosen by the gateway;
- ``response_format: {type: json_schema, json_schema: {name, strict, schema}}`` when structured output is requested, and
  ``provider: {require_parameters: true}`` so only providers that honour it are used;
- ``reasoning: {exclude: true}`` (with the requested effort): the model's raw reasoning is never returned, stored or shown;
- ``usage: {include: true}`` for token counts.

HTTP and OpenRouter errors map to the provider-neutral taxonomy (``provider``): 400/404/422 bad request, 401 authentication,
402 quota, 403 content filtered (moderation), 408 timeout, 429 rate limited (``Retry-After`` honoured by the gateway), 5xx provider
unavailable; socket timeouts and connection failures are timeouts and network errors; a 2xx body that is not a completion is a
malformed response; ``finish_reason`` ``length`` is truncation and ``content_filter`` a filtered response. Error messages are
redacted; the API key is sent only in the ``Authorization`` header and never logged.

Live calls happen only when explicitly requested (``python -m atlas_reasoning provider-health``, later reasoning runs); tests use
``fake_provider`` or an injected ``http`` function.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from atlas_reasoning.frozen import freeze, thaw
from atlas_reasoning.provider import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderContentFiltered,
    ProviderError,
    ProviderNetworkError,
    ProviderQuotaExceeded,
    ProviderRateLimited,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseError,
    ProviderTimeout,
    ProviderTruncated,
    ProviderUnavailable,
    redact,
)
from atlas_reasoning.settings import OpenRouterSettings

PROVIDER_NAME = "openrouter"
APP_TITLE = "Waset Atlas Reasoning"


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


Http = Callable[[str, Mapping[str, str], bytes, float], HttpResult]


def urllib_http(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> HttpResult:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResult(response.status, {k.lower(): v for k, v in response.headers.items()}, response.read())
    except urllib.error.HTTPError as error:
        return HttpResult(error.code, {k.lower(): v for k, v in (error.headers or {}).items()}, error.read() or b"")


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("retry-after")
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


class OpenRouterTransport:
    provider_name = PROVIDER_NAME

    def __init__(self, settings: OpenRouterSettings, *, http: Http = urllib_http) -> None:
        self._settings = settings
        self._http = http

    def __repr__(self) -> str:
        return f"OpenRouterTransport(base_url={self._settings.base_url!r})"

    def body(self, request: ProviderRequest, model: str) -> dict[str, Any]:
        body: dict[str, Any] = {"model": model, "messages": [{"role": m.role, "content": m.content} for m in request.messages],
                                "usage": {"include": True}, "reasoning": {"exclude": True}}
        if request.reasoning_effort:
            body["reasoning"]["effort"] = request.reasoning_effort
        if request.max_output_tokens:
            body["max_tokens"] = request.max_output_tokens
        if request.output is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": request.output.name, "strict": request.output.strict,
                                                                              "schema": thaw(request.output.schema)}}
            body["provider"] = {"require_parameters": True}
        return body

    def complete(self, request: ProviderRequest, *, model: str, timeout: float) -> ProviderResponse:
        headers = {"Authorization": f"Bearer {self._settings.api_key}", "Content-Type": "application/json", "X-Title": APP_TITLE,
                   "X-Request-Id": request.context.request_id}
        payload = json.dumps(self.body(request, model)).encode()
        try:
            result = self._http(f"{self._settings.base_url}/chat/completions", headers, payload, timeout)
        except TimeoutError as error:
            raise ProviderTimeout(f"no response within {timeout:g}s") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise ProviderTimeout(f"no response within {timeout:g}s") from None
            raise ProviderNetworkError(self._clean(f"cannot reach OpenRouter: {error.reason}")) from None
        except OSError as error:
            raise ProviderNetworkError(self._clean(f"cannot reach OpenRouter: {type(error).__name__}: {error}")) from None
        return self._response(request, model, result)

    def _clean(self, text: str) -> str:
        return redact(text, (self._settings.api_key,))[:500]

    def _response(self, request: ProviderRequest, model: str, result: HttpResult) -> ProviderResponse:
        document: Any
        try:
            document = json.loads(result.body or b"{}")
        except ValueError:
            document = None
        if not 200 <= result.status < 300 or (isinstance(document, Mapping) and document.get("error")):
            raise self._error(result, document)
        if not isinstance(document, Mapping):
            raise ProviderResponseError("OpenRouter returned a body that is not JSON", status=result.status)
        choices = document.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise ProviderResponseError("OpenRouter returned no completion choice", status=result.status)
        choice = choices[0]
        message: Any = choice.get("message") if isinstance(choice.get("message"), Mapping) else {}
        content = message.get("content")
        finish = choice.get("finish_reason")
        if finish == "length":
            raise ProviderTruncated("the completion stopped at the token limit", status=result.status, provider_status="finish_reason=length")
        if finish == "content_filter":
            raise ProviderContentFiltered("the completion was filtered", status=result.status, provider_status="finish_reason=content_filter")
        if finish == "error":
            raise ProviderUnavailable("the provider failed while generating", status=result.status, provider_status="finish_reason=error")
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError("OpenRouter returned an empty completion", status=result.status)
        usage: Any = document.get("usage") if isinstance(document.get("usage"), Mapping) else {}
        return ProviderResponse(request_id=request.context.request_id, model=str(document.get("model") or model), content=content,
                                input_tokens=_int(usage.get("prompt_tokens")), output_tokens=_int(usage.get("completion_tokens")),
                                provider_response_id=str(document["id"]) if document.get("id") else None, provider_status=str(result.status),
                                finish_reason=str(finish) if finish else None,
                                metadata=freeze({"upstream_provider": str(document.get("provider"))} if document.get("provider") else {}))

    def _error(self, result: HttpResult, document: Any) -> ProviderError:
        error: Any = document.get("error") if isinstance(document, Mapping) and isinstance(document.get("error"), Mapping) else {}
        code = _int(error.get("code")) or result.status
        message = self._clean(str(error.get("message") or f"HTTP {result.status}"))
        status = code if 400 <= code < 600 else result.status
        kwargs: dict[str, Any] = {"status": status}
        if status == 429:
            return ProviderRateLimited(f"rate limited: {message}", retry_after=_retry_after(result.headers), **kwargs)
        if status == 408:
            return ProviderTimeout(f"provider timeout: {message}", **kwargs)
        if status == 401:
            return ProviderAuthError("OpenRouter rejected the API key", **kwargs)
        if status == 402:
            return ProviderQuotaExceeded(f"insufficient credits: {message}", **kwargs)
        if status == 403:
            return ProviderContentFiltered(f"refused by moderation: {message}", **kwargs)
        if status in (400, 404, 413, 422):
            return ProviderBadRequest(f"request refused: {message}", **kwargs)
        if status >= 500:
            return ProviderUnavailable(f"provider unavailable: {message}", retry_after=_retry_after(result.headers), **kwargs)
        return ProviderResponseError(f"unexpected response: {message}", **kwargs)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
