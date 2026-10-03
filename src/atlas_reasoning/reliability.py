"""Provider reliability and budget controls (``REV/18`` #1, #10): shared capacity, a per-run call budget, and a circuit breaker.

    controls = ProviderControls.from_settings(gateway_settings(), reliability_settings())      # one per process
    reasoning = ReasoningGateway(transport, gw_settings, controls=controls, ...)
    budget = CallBudget.from_settings(reliability_settings())                                  # one per run
    ReasoningEngine(store, reasoning.with_budget(budget), ...).process_run(run_id)
    ExecutiveSynthesizer(executive_store, reasoning, budget=budget).synthesize(run_id)

Everything here happens **before** a provider call starts and stores nothing but counters, a state name and a timestamp: no prompt, no
response, no credential, no candidate.

**Admission order** (``ReasoningGateway.call``): (1) the circuit breaker may refuse (``CircuitOpen``); (2) the budget may refuse
(``BudgetExhausted`` / ``ExecutiveBudgetExhausted``) — a breaker probe reserved in (1) is then released; (3) only then do the attempts
start, each holding one slot of the shared capacity. A refused call makes no provider request, consumes no budget unit, writes no
``llm_calls`` row (there was no attempt) and is a ``ProviderError`` that is not retryable, so the engines fail only that work item
(``provider:circuit_open`` / ``provider:budget_exhausted``) and keep the last valid result; resuming is the orchestration's.

**Budget accounting.** One unit per *logical* call (one ``gateway.call``). The gateway's transport retries inside that call are not extra
units; they are bounded by ``GatewaySettings.max_retries`` (worst case ``units × (1 + max_retries)`` provider attempts). A Phase 15
corrective re-ask after a refused candidate is a new logical call and costs a unit. An executive call (purpose ``executive``) costs one
unit of the run budget **and** one of the executive budget. A refusal costs nothing.

**Circuit breaker.** Counts consecutive *outage* failures of logical calls (``OUTAGE_CLASSES``: timeout, rate limit, provider
unavailable, network, malformed provider envelope, quota, authentication) after the gateway's retries are exhausted. ``threshold`` of them
open the circuit: every call is refused for ``cooldown_seconds``; then one half-open probe is let through (others are refused while it is
in flight); its success — or any answer that is not an outage (a bad request, a content filter, a truncation: the provider is reachable) —
closes the circuit, an outage re-opens it for another cooldown. Validation refusals never reach the breaker: the provider answered.
State is per process (``ProviderControls``); there are no cross-process semantics.

**Concurrency.** ``ProviderControls.capacity`` bounds provider *attempts* in flight across every gateway that shares the controls, in one
process — e.g. case reasoning and executive synthesis together. A slot is released while waiting to retry. Separate processes each have
their own bound.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from atlas_reasoning.provider import ProviderError
from atlas_reasoning.settings import GatewaySettings, ReliabilitySettings

LOG = logging.getLogger("atlas_reasoning.reliability")

EXECUTIVE_PURPOSE = "executive"
# Failure classes of a logical call that indicate the provider is unreachable or refusing service (``provider.ProviderError.error_class``).
OUTAGE_CLASSES = frozenset({"timeout", "rate_limited", "provider_unavailable", "network_error", "malformed_response", "quota_exceeded",
                            "authentication"})


class CallRefused(ProviderError):
    """A call refused before any provider request: nothing was sent, nothing was spent. Never retryable."""

    error_class = "call_refused"
    retryable = False
    provider_called = False


class CircuitOpen(CallRefused):
    error_class = "circuit_open"


class BudgetExhausted(CallRefused):
    error_class = "budget_exhausted"


class ExecutiveBudgetExhausted(BudgetExhausted):
    error_class = "executive_budget_exhausted"


# --- budget --------------------------------------------------------------------------------------------------------------------------


class BudgetDecision(StrEnum):
    ALLOWED = "allowed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    EXECUTIVE_BUDGET_EXHAUSTED = "executive_budget_exhausted"


class CallBudget:
    """A thread-safe count of logical provider calls one run may start. ``limit`` / ``executive_limit`` of ``None`` = unlimited."""

    def __init__(self, limit: int | None = None, *, executive_limit: int | None = None) -> None:
        for name, value in (("limit", limit), ("executive_limit", executive_limit)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
        self.limit, self.executive_limit = limit, executive_limit
        self._lock = threading.Lock()
        self._used = self._executive_used = 0
        self._refused: dict[str, int] = {decision.value: 0 for decision in BudgetDecision if decision != BudgetDecision.ALLOWED}

    @classmethod
    def from_settings(cls, settings: ReliabilitySettings) -> CallBudget:
        return cls(settings.run_call_budget, executive_limit=settings.executive_call_budget)

    def acquire(self, purpose: str) -> BudgetDecision:
        """Take one unit for one logical call of ``purpose`` (checked and taken atomically), or refuse without taking anything."""
        with self._lock:
            if self.limit is not None and self._used >= self.limit:
                decision = BudgetDecision.BUDGET_EXHAUSTED
            elif purpose == EXECUTIVE_PURPOSE and self.executive_limit is not None and self._executive_used >= self.executive_limit:
                decision = BudgetDecision.EXECUTIVE_BUDGET_EXHAUSTED
            else:
                self._used += 1
                self._executive_used += purpose == EXECUTIVE_PURPOSE
                return BudgetDecision.ALLOWED
            self._refused[decision.value] += 1
            return decision

    def check(self, purpose: str) -> BudgetDecision:
        """What ``acquire`` would decide now, without taking a unit (for planning only; ``acquire`` is the authority)."""
        with self._lock:
            if self.limit is not None and self._used >= self.limit:
                return BudgetDecision.BUDGET_EXHAUSTED
            if purpose == EXECUTIVE_PURPOSE and self.executive_limit is not None and self._executive_used >= self.executive_limit:
                return BudgetDecision.EXECUTIVE_BUDGET_EXHAUSTED
            return BudgetDecision.ALLOWED

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int | None:
        with self._lock:
            return None if self.limit is None else max(0, self.limit - self._used)

    def snapshot(self) -> dict[str, Any]:
        """Counters only (for run metrics): limits, units used, executive units used, refusals by kind."""
        with self._lock:
            return {"limit": self.limit, "used": self._used, "executive_limit": self.executive_limit, "executive_used": self._executive_used,
                    "refused": dict(self._refused)}


def raise_for(decision: BudgetDecision) -> None:
    if decision == BudgetDecision.BUDGET_EXHAUSTED:
        raise BudgetExhausted("the run's provider call budget is exhausted; no call was made")
    if decision == BudgetDecision.EXECUTIVE_BUDGET_EXHAUSTED:
        raise ExecutiveBudgetExhausted("the executive synthesis call budget is exhausted; no call was made")


# --- circuit breaker -------------------------------------------------------------------------------------------------------------------


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class Admission:
    """A breaker admission: ``probe`` when this call is the single half-open probe."""

    probe: bool = False


class CircuitBreaker:
    """Pauses provider calls after ``threshold`` consecutive outage failures; bounded state, no content."""

    def __init__(self, threshold: int = 5, cooldown_seconds: float = 60.0, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
            raise ValueError("threshold must be a positive integer")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self.threshold, self.cooldown_seconds, self._monotonic = threshold, float(cooldown_seconds), monotonic
        self._lock = threading.Lock()
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._opened_count = 0

    @property
    def state(self) -> BreakerState:
        with self._lock:
            return self._current()

    def _current(self) -> BreakerState:
        if self._state == BreakerState.OPEN and self._opened_at is not None and self._monotonic() - self._opened_at >= self.cooldown_seconds:
            self._state = BreakerState.HALF_OPEN
            LOG.warning("circuit half-open after %.0fs", self.cooldown_seconds)
        return self._state

    def admit(self) -> Admission:
        """Let a call through, or raise ``CircuitOpen``. In half-open state exactly one probe at a time is admitted."""
        with self._lock:
            state = self._current()
            if state == BreakerState.CLOSED:
                return Admission()
            if state == BreakerState.HALF_OPEN and not self._probe_in_flight:
                self._probe_in_flight = True
                return Admission(probe=True)
        raise CircuitOpen("provider calls are paused after repeated provider failures; no call was made")

    def release(self, admission: Admission) -> None:
        """Give back an admission that never reached the provider (e.g. the budget refused the call)."""
        if admission.probe:
            with self._lock:
                self._probe_in_flight = False

    def record(self, admission: Admission, error_class: str | None) -> None:
        """The final outcome of an admitted logical call: ``None`` on success, else its error class."""
        with self._lock:
            if admission.probe:
                self._probe_in_flight = False
            if error_class is not None and error_class in OUTAGE_CLASSES:
                self._failures += 1
                if admission.probe or (self._state == BreakerState.CLOSED and self._failures >= self.threshold):
                    if self._state != BreakerState.OPEN:
                        self._opened_count += 1
                    self._state, self._opened_at = BreakerState.OPEN, self._monotonic()
                    LOG.warning("circuit open consecutive_failures=%s last_error_class=%s cooldown=%.0fs", self._failures, error_class,
                                self.cooldown_seconds)
                return
            if self._state != BreakerState.CLOSED:
                LOG.warning("circuit closed after a successful probe")
            self._state, self._failures, self._opened_at = BreakerState.CLOSED, 0, None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"state": self._current().value, "consecutive_failures": self._failures, "threshold": self.threshold,
                    "cooldown_seconds": self.cooldown_seconds, "times_opened": self._opened_count}


# --- shared controls ---------------------------------------------------------------------------------------------------------------------


class ProviderControls:
    """What every gateway of one process shares: provider capacity (attempts in flight) and, optionally, a circuit breaker."""

    def __init__(self, concurrency: int, *, breaker: CircuitBreaker | None = None) -> None:
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
            raise ValueError("concurrency must be a positive integer")
        self.concurrency = concurrency
        self.capacity = threading.BoundedSemaphore(concurrency)
        self.breaker = breaker

    @classmethod
    def from_settings(cls, gateway: GatewaySettings, reliability: ReliabilitySettings, *,
                      monotonic: Callable[[], float] = time.monotonic) -> ProviderControls:
        return cls(gateway.concurrency, breaker=CircuitBreaker(reliability.breaker_threshold, reliability.breaker_cooldown_seconds,
                                                               monotonic=monotonic))

    def snapshot(self) -> dict[str, Any]:
        return {"concurrency": self.concurrency, "breaker": self.breaker.snapshot() if self.breaker is not None else None}
