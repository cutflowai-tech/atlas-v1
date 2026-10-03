"""Optional live mode of the Phase 19 evaluation runner (Phase 19-B): the golden cases against the real pinned model through the
existing OpenRouter gateway. **Never** automatic: never because a credential exists, never in CI, never from ``make test``.

    ATLAS_REASONING_EVALUATION_LIVE=on \\
    ATLAS_REASONING_EVALUATION_DATABASE_URL=postgresql://.../atlas_reasoning_eval_test \\
    OPENROUTER_API_KEY_FILE=/run/secrets/openrouter \\
    python -m atlas_reasoning evaluate run --live --max-calls 400 --max-executive-calls 0

Every one of these must hold, or the evaluation refuses to start (``EVALUATION_CONFIGURATION_INVALID``, before any provider call):

* the operator opts in twice: ``--live`` **and** ``ATLAS_REASONING_EVALUATION_LIVE=on``;
* no CI environment (``CI`` / ``GITHUB_ACTIONS`` / ``BUILDKITE`` / ``GITLAB_CI`` / ``JENKINS_URL`` / ``TF_BUILD``);
* explicit budgets: ``--max-calls`` (total provider requests, every retry included, 1..``MAX_LIVE_CALLS``) and
  ``--max-executive-calls`` (requests of the ``executive`` purpose, 0..``MAX_LIVE_CALLS``);
* the pinned model (``ATLAS_REASONING_MODEL`` override refused, whatever ``ATLAS_REASONING_ALLOW_MODEL_OVERRIDE`` says);
* a disposable test database (``evaluation_runner.check_disposable``), never the canonical Reasoning V3 database;
* the existing OpenRouter credential handling (``settings.openrouter_settings``: ``OPENROUTER_API_KEY`` or ``_FILE``) and the existing
  ``OpenRouterTransport``, which only the operator command wires (``__main__``).

Only the synthetic golden dataset is sent. Contextual memory is always the offline ``FakeHoncho`` (no Honcho workspace is read or
written). Gateway timeouts, retries and backoff are the operator's ``ATLAS_REASONING_LLM_*`` settings; concurrency and the circuit
breaker are the Phase 18 ``ProviderControls`` each golden case declares. The scripted faults of a case (provider outage, authentication
refusal, overclaim) are injected locally and never reach the provider.

The budget is charged per provider request, below the gateway (so every retry and every gateway view counts). A request over budget is
refused before any network I/O, the transport is marked exhausted, and the runner stops at the end of that step with
``EVALUATION_BUDGET_EXHAUSTED``: no report, no metric. The key is never printed: it is passed to the gateway for redaction only, the
transport is not representable with it, and the run's output carries counters, never headers or request bodies.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from atlas_reasoning import settings
from atlas_reasoning.evaluation_offline_model import ScriptedTransport, request_input
from atlas_reasoning.evaluation_runner import (
    EvaluationConfigurationError,
    EvaluationPlan,
    ModelSetup,
    evaluation_database_url,
)
from atlas_reasoning.evaluation_types import EvaluationCase
from atlas_reasoning.provider import ProviderError, ProviderRequest, ProviderResponse, Transport
from atlas_reasoning.reliability import EXECUTIVE_PURPOSE

LIVE_ENV = "ATLAS_REASONING_EVALUATION_LIVE"
CI_ENVS = ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI", "JENKINS_URL", "TF_BUILD", "CIRCLECI", "TEAMCITY_VERSION", "CODEBUILD_BUILD_ID",
           "TRAVIS", "BITBUCKET_BUILD_NUMBER", "DRONE")
MAX_LIVE_CALLS = 5000
ProviderFactory = Callable[[settings.OpenRouterSettings], Transport]


class LiveBudgetExhausted(ProviderError):
    """A live request refused by the evaluation budget before any network I/O. Never retryable."""

    error_class = "evaluation_budget_exhausted"
    retryable = False


class LiveBudget:
    """The whole live evaluation's provider-request budget (every case, every retry). Thread-safe; refusing marks it exhausted."""

    def __init__(self, max_calls: int, max_executive_calls: int) -> None:
        self.max_calls, self.max_executive_calls = max_calls, max_executive_calls
        self._lock = threading.Lock()
        self.used = self.executive_used = self.refused = 0
        self.exhausted = False

    def acquire(self, purpose: str) -> bool:
        with self._lock:
            executive = purpose == EXECUTIVE_PURPOSE
            if self.exhausted or self.used >= self.max_calls or (executive and self.executive_used >= self.max_executive_calls):
                self.exhausted = True
                self.refused += 1
                return False
            self.used += 1
            self.executive_used += executive
            return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"max_calls": self.max_calls, "used": self.used, "max_executive_calls": self.max_executive_calls,
                    "executive_used": self.executive_used, "refused": self.refused, "exhausted": self.exhausted}


class LiveTransport(ScriptedTransport):
    """The scripted faults of a golden case in front of the real provider transport, charged to the shared ``LiveBudget``."""

    def __init__(self, provider: Transport, budget: LiveBudget) -> None:
        super().__init__()
        self._provider, self._budget = provider, budget
        self.provider_name = provider.provider_name

    def __repr__(self) -> str:
        return f"LiveTransport(provider={self.provider_name!r})"

    def complete(self, request: ProviderRequest, *, model: str, timeout: float) -> ProviderResponse:
        with self._lock:
            self.requests.append(request)
        scripted = self.scripted(request)
        if scripted is not None:                       # a local fault: nothing reaches the provider, nothing is charged
            return self.response(request, scripted, request_input(request))
        if not self._budget.acquire(request.context.purpose):
            raise LiveBudgetExhausted("the live evaluation call budget is exhausted; no request was sent")
        return self._provider.complete(request, model=model, timeout=timeout)


def in_ci(env: Mapping[str, str]) -> bool:
    return any(env.get(name, "").strip().lower() not in ("", "0", "false", "no", "off") for name in CI_ENVS)


def _budget_value(name: str, value: int | None, minimum: int) -> int:
    if value is None:
        raise EvaluationConfigurationError(f"live mode needs an explicit {name}")
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= MAX_LIVE_CALLS:
        raise EvaluationConfigurationError(f"{name} must be an integer in {minimum}..{MAX_LIVE_CALLS}")
    return value


def check_live_opt_in(env: Mapping[str, str], *, live: bool) -> None:
    """Refuse anything but an explicit operator run outside CI."""
    if not live:
        raise EvaluationConfigurationError("live mode needs --live")
    if not settings.flag(env, LIVE_ENV):
        raise EvaluationConfigurationError(f"live mode needs {LIVE_ENV}=on (a credential alone never enables it)")
    if in_ci(env):
        raise EvaluationConfigurationError("live mode is refused in CI")


def live_plan(env: Mapping[str, str], *, live: bool, max_calls: int | None, max_executive_calls: int | None, case_ids: Sequence[str] = (),
              transport: ProviderFactory | None = None) -> EvaluationPlan:
    """The live evaluation plan, or ``EvaluationConfigurationError`` before any provider call. ``transport`` builds the provider transport
    from the OpenRouter settings: the operator command (``__main__``, the only module that wires OpenRouter) passes the real one."""
    check_live_opt_in(env, live=live)
    budget = LiveBudget(_budget_value("--max-calls", max_calls, 1), _budget_value("--max-executive-calls", max_executive_calls, 0))
    if env.get(settings.MODEL_ENV, "").strip() not in ("", settings.PINNED_MODEL):
        raise EvaluationConfigurationError(f"live evaluation runs the pinned model {settings.PINNED_MODEL} only")
    database_url = evaluation_database_url(env)
    try:
        limits = settings.gateway_settings(env)
        provider_settings = settings.openrouter_settings(env)
    except settings.ReasoningConfigError as error:
        raise EvaluationConfigurationError(str(error)) from None
    if transport is None:
        raise EvaluationConfigurationError("live mode runs only from the operator command (python -m atlas_reasoning evaluate run --live)")
    provider = transport(provider_settings)
    secrets = (provider_settings.api_key,)

    def model(case: EvaluationCase) -> ModelSetup:
        concurrency = case.runtime.get("gateway_concurrency", limits.concurrency)
        transport = LiveTransport(provider, budget)
        return ModelSetup(transport, dataclasses.replace(limits, concurrency=concurrency), sleep=time.sleep, secrets=secrets,
                          exhausted=lambda: budget.exhausted)

    return EvaluationPlan(database_url=database_url, case_ids=tuple(case_ids), model=model, mode="live",
                          environment={"provider": provider.provider_name, "model": limits.model}, budget_snapshot=budget.snapshot)

