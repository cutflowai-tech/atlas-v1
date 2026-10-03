"""A scripted, offline ``Transport`` for tests and dry runs (``REV/06`` #10). Never touches the network.

    fake = FakeProvider(default=FakeReply({"ok": True}))
    fake.script("rc1_...", FakeError(ProviderRateLimited("busy", retry_after=1)), FakeReply({...}))   # per case: outcomes in order
    gateway = ReasoningGateway(fake, settings, recorder=MemoryRecorder(), sleep=lambda s: None)

Outcomes are consumed per key (the request's ``case_id``, else its ``purpose``); when a key's script is exhausted the default is
used. ``FakeReply.content`` may be a JSON-ready value (serialized) or a raw string (to simulate malformed output). ``delay``
simulates latency, so tests can observe the gateway's concurrency limit through ``peak_in_flight``.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from atlas_reasoning.provider import ProviderError, ProviderRequest, ProviderResponse

FAKE_PROVIDER = "fake"


@dataclass(frozen=True)
class FakeReply:
    content: Any
    input_tokens: int = 100
    output_tokens: int = 50
    delay: float = 0.0
    model: str | None = None


@dataclass(frozen=True)
class FakeError:
    error: ProviderError
    delay: float = 0.0


@dataclass
class FakeProvider:
    default: FakeReply | FakeError | None = None
    provider_name: str = FAKE_PROVIDER
    requests: list[ProviderRequest] = field(default_factory=list)
    peak_in_flight: int = 0
    _scripts: dict[str, deque[FakeReply | FakeError]] = field(default_factory=dict)
    _in_flight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def script(self, key: str, *outcomes: FakeReply | FakeError) -> FakeProvider:
        with self._lock:
            self._scripts.setdefault(key, deque()).extend(outcomes)
        return self

    def complete(self, request: ProviderRequest, *, model: str, timeout: float) -> ProviderResponse:
        key = request.context.case_id or request.context.purpose
        with self._lock:
            self.requests.append(request)
            queue = self._scripts.get(key)
            outcome = queue.popleft() if queue else self.default
            self._in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        try:
            if outcome is None:
                raise AssertionError(f"FakeProvider has no outcome for {key!r}")
            if outcome.delay:
                time.sleep(outcome.delay)
            if isinstance(outcome, FakeError):
                raise outcome.error
            content = outcome.content if isinstance(outcome.content, str) else json.dumps(outcome.content)
            return ProviderResponse(request_id=request.context.request_id, model=outcome.model or model, content=content,
                                    input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens,
                                    provider_response_id=f"fake-{len(self.requests)}", provider_status="200", finish_reason="stop")
        finally:
            with self._lock:
                self._in_flight -= 1
