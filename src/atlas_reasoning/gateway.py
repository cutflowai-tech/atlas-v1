"""The provider gateway (``REV/06``): one place where Reasoning V3 talks to an LLM provider.

``ReasoningGateway`` wraps a ``Transport`` (``openrouter_client.OpenRouterTransport`` in production, ``fake_provider.FakeProvider``
in tests) with:

- **request IDs**: every call gets ``req_<32 hex>`` unless its context names one;
- **timeouts** per attempt and **bounded retries** with **exponential backoff** (base × 2^(retry−1), capped, plus jitter); a rate
  limit's ``Retry-After`` is honoured up to the cap; only retryable errors are retried;
- **structured output**: the response is parsed as JSON and validated locally against the requested schema, whatever the provider
  claims; an invalid response is a retryable ``StructuredOutputError``;
- **a concurrency limit**: at most ``concurrency`` provider attempts in flight (a slot is released while waiting to retry);
- **call metadata**: one ``CallRecord`` per call (request, run, case, work item, model, prompt version, snapshot, fingerprint,
  status, provider status, error class, attempts, latency, tokens) handed to a ``CallRecorder`` — ``store.calls.StoreCallRecorder``
  persists it to ``llm_calls``; a recorder failure is logged and never loses the call's result;
- **safe logs**: request ID, purpose, model, attempt, error class and status only — never prompts, responses or credentials;
- **failure isolation**: ``call_many`` runs independent requests concurrently and returns one ``CallOutcome`` per request; one
  failing case never affects another;
- **Phase 18 admission** (``reliability``): before any attempt, an optional circuit breaker and an optional per-run ``CallBudget`` may
  refuse the call (a non-retryable ``reliability.CallRefused``: nothing sent, nothing spent, no ``llm_calls`` row); gateways built with
  the same ``ProviderControls`` share one capacity semaphore and one breaker. Without controls or a budget the gateway behaves exactly
  as before.

No domain logic here: the gateway neither builds prompts nor interprets results.
"""

from __future__ import annotations

import copy
import json
import logging
import random
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from atlas_reasoning.enums import LLMCallStatus
from atlas_reasoning.provider import (
    CallContext,
    ProviderError,
    ProviderInternalError,
    ProviderRequest,
    ProviderResponse,
    StructuredOutputError,
    Transport,
    redact,
)
from atlas_reasoning.reliability import Admission, CallBudget, ProviderControls, raise_for
from atlas_reasoning.settings import GatewaySettings

LOG = logging.getLogger("atlas_reasoning.gateway")


@dataclass(frozen=True)
class CallRecord:
    """Metadata of one call (all attempts), exactly what ``llm_calls`` stores. Never content or credentials."""

    request_id: str
    provider: str
    model: str
    purpose: str
    status: LLMCallStatus
    attempts: int
    latency_ms: int
    started_at: str
    finished_at: str
    run_id: str | None = None
    case_id: str | None = None
    work_item_id: str | None = None
    prompt_version: str | None = None
    source_snapshot_id: str | None = None
    evidence_fingerprint: str | None = None
    provider_status: str | None = None
    error_class: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_response_id: str | None = None

    @property
    def retries(self) -> int:
        return self.attempts - 1


class CallRecorder(Protocol):
    def record(self, call: CallRecord) -> None: ...


class MemoryRecorder:
    """Keeps call records in memory (tests and dry runs)."""

    def __init__(self) -> None:
        self.calls: list[CallRecord] = []
        self._lock = threading.Lock()

    def record(self, call: CallRecord) -> None:
        with self._lock:
            self.calls.append(call)


@dataclass(frozen=True)
class CallOutcome:
    """The result of one request in ``call_many``: a response or an error, never both."""

    request: ProviderRequest
    response: ProviderResponse | None = None
    error: ProviderError | None = None

    @property
    def ok(self) -> bool:
        return self.response is not None


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class ReasoningGateway:
    def __init__(self, transport: Transport, settings: GatewaySettings | None = None, *, recorder: CallRecorder | None = None,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic,
                 jitter: Callable[[], float] = random.random, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 secrets: Sequence[str] = (), controls: ProviderControls | None = None, budget: CallBudget | None = None) -> None:
        self.transport = transport
        self.settings = settings or GatewaySettings()
        self.recorder = recorder
        self._sleep, self._monotonic, self._jitter, self._clock = sleep, monotonic, jitter, clock
        # Shared controls (Phase 18): one capacity semaphore (and breaker) for every gateway of the process that uses them; without
        # them this gateway has its own capacity, as before.
        self.controls = controls
        self._slots: threading.BoundedSemaphore = controls.capacity if controls is not None else threading.BoundedSemaphore(self.settings.concurrency)
        self.budget = budget
        self._secrets = tuple(secret for secret in secrets if secret)

    def with_budget(self, budget: CallBudget | None) -> ReasoningGateway:
        """The same gateway (transport, settings, recorder, capacity, breaker) charging ``budget`` for each logical call."""
        view = copy.copy(self)
        view.budget = budget
        return view

    def _admit(self, context: CallContext) -> Admission | None:
        """Breaker, then budget; both before any provider request. Raises ``reliability.CallRefused`` (never retryable)."""
        breaker = self.controls.breaker if self.controls is not None else None
        admission = breaker.admit() if breaker is not None else None
        if self.budget is not None:
            decision = self.budget.acquire(context.purpose)
            try:
                raise_for(decision)
            except ProviderError:
                if breaker is not None and admission is not None:
                    breaker.release(admission)
                raise
        return admission

    @property
    def model(self) -> str:
        return self.settings.model

    def backoff(self, retry: int, retry_after: float | None = None) -> float:
        """Seconds to wait before retry number ``retry`` (1-based)."""
        base = self.settings.backoff_seconds * (2 ** (retry - 1))
        wait = base + base * 0.25 * self._jitter()
        if retry_after is not None:
            wait = max(wait, retry_after)
        return min(wait, self.settings.max_backoff_seconds)

    def call(self, request: ProviderRequest) -> ProviderResponse:
        """One logical call (with retries). Returns the response or raises the last ``ProviderError``; recorded either way. A call refused
        before any attempt (breaker, budget: ``reliability.CallRefused``) makes no request and writes no record."""
        context = request.context if request.context.request_id else replace(request.context, request_id=new_request_id())
        request = replace(request, context=context)
        try:
            admission = self._admit(context)
        except ProviderError as refused:
            self._log(logging.WARNING, "call refused before any attempt", context, error_class=refused.error_class)
            raise
        started_at, start = self._clock(), self._monotonic()
        attempts, response, error = 0, None, None
        while True:
            attempts += 1
            try:
                with self._slots:
                    response = self._attempt(request)
                error = None
                break
            except ProviderError as failure:
                error = failure
            except Exception as failure:  # noqa: BLE001 - a transport bug is contained like any provider failure
                error = ProviderInternalError(redact(f"{type(failure).__name__}: {failure}", self._secrets))
            self._log(logging.WARNING, "attempt failed", context, attempt=attempts, error_class=error.error_class, status=error.provider_status)
            if not error.retryable or attempts > self.settings.max_retries:
                break
            self._sleep(self.backoff(attempts, error.retry_after))
        breaker = self.controls.breaker if self.controls is not None else None
        if breaker is not None and admission is not None:
            breaker.record(admission, None if response is not None else (error.error_class if error else "internal_error"))
        latency_ms = round((self._monotonic() - start) * 1000)
        self._record(CallRecord(
            request_id=context.request_id, provider=self.transport.provider_name, model=response.model if response else self.model, purpose=context.purpose,
            status=LLMCallStatus.SUCCEEDED if response else LLMCallStatus.FAILED, attempts=attempts, latency_ms=max(latency_ms, 0),
            started_at=_iso(started_at), finished_at=_iso(self._clock()), run_id=context.run_id, case_id=context.case_id,
            work_item_id=context.work_item_id, prompt_version=context.prompt_version, source_snapshot_id=context.source_snapshot_id,
            evidence_fingerprint=context.evidence_fingerprint,
            provider_status=response.provider_status if response else (error.provider_status if error else None),
            error_class=error.error_class if error and not response else None,
            input_tokens=response.input_tokens if response else None, output_tokens=response.output_tokens if response else None,
            provider_response_id=response.provider_response_id if response else None))
        if response is None:
            assert error is not None
            self._log(logging.ERROR, "call failed", context, attempts=attempts, error_class=error.error_class, status=error.provider_status)
            raise error
        self._log(logging.INFO, "call succeeded", context, attempts=attempts, latency_ms=latency_ms, input_tokens=response.input_tokens,
                  output_tokens=response.output_tokens)
        return response

    def call_many(self, requests: Sequence[ProviderRequest]) -> list[CallOutcome]:
        """Independent requests, concurrently (bounded by the concurrency limit). One outcome per request, in request order."""
        def run(request: ProviderRequest) -> CallOutcome:
            try:
                return CallOutcome(request, response=self.call(request))
            except ProviderError as error:
                return CallOutcome(request, error=error)

        if not requests:
            return []
        with ThreadPoolExecutor(max_workers=min(self.settings.concurrency, len(requests)), thread_name_prefix="atlas-reasoning-llm") as pool:
            return list(pool.map(run, requests))

    def _attempt(self, request: ProviderRequest) -> ProviderResponse:
        response = self.transport.complete(request, model=self.model, timeout=self.settings.timeout_seconds)
        if request.output is None:
            return response
        try:
            parsed = json.loads(response.content)
        except (TypeError, ValueError):
            raise StructuredOutputError(f"{request.output.name}: the response is not JSON", provider_status=response.provider_status) from None
        problems = request.output.validate(parsed)
        if problems:
            raise StructuredOutputError(f"{request.output.name}: the response does not match the schema: {problems[:3]}",
                                        provider_status=response.provider_status)
        return replace(response, parsed=parsed, request_id=request.context.request_id)

    def _record(self, call: CallRecord) -> None:
        if self.recorder is None:
            return
        try:
            self.recorder.record(call)
        except Exception as error:  # noqa: BLE001 - losing call metadata must never lose the call's result
            LOG.error("call metadata not recorded request_id=%s error=%s", call.request_id, redact(f"{type(error).__name__}: {error}", self._secrets))

    def _log(self, level: int, message: str, context: CallContext, **fields: object) -> None:
        details = " ".join(f"{key}={value}" for key, value in {"request_id": context.request_id, "purpose": context.purpose, "model": self.model,
                                                              "case_id": context.case_id, **fields}.items() if value is not None)
        LOG.log(level, redact(f"{message} {details}", self._secrets))
