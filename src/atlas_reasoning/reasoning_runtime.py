"""One process's Reasoning V3 runtime (Phase 18 integration): one shared provider control, one call path per budget.

    runtime = build_runtime(store, transport, recorder=StoreCallRecorder(store), secrets=(key,), context=HumanContext(...),
                            reviewer_factory=reviewer_from_env)
    report = runtime.orchestrator.run(run_id)            # or .resume(run_id)
    if report.executive_ready:
        outcome = runtime.synthesize(run_id)

- **Settings are read once** (``settings.gateway_settings`` / ``reliability_settings``) when the runtime is built, so a malformed Phase 18
  variable fails the command at start instead of failing every work item later.
- **One ``reliability.ProviderControls`` per process** (``from_settings``): every gateway — case reasoning, the optional Phase 15 reviewer
  and executive synthesis — is the same ``ReasoningGateway`` (or a ``with_budget`` view of it), so they share one capacity bound and one
  circuit breaker.
- **One budget per call path**: case reasoning (and the reviewer) is charged only by the orchestration pass budget
  (``run_control.PassBudget``, sized by ``ReliabilitySettings.run_call_budget``); executive synthesis only by a fresh
  ``reliability.CallBudget`` holding the executive limit (``run_control.executive_call_budget``) per synthesis. No call is charged twice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from atlas_reasoning import settings
from atlas_reasoning.engine import ReasoningEngine
from atlas_reasoning.executive import ExecutiveSynthesizer, SynthesisOutcome
from atlas_reasoning.gateway import CallRecorder, ReasoningGateway
from atlas_reasoning.provider import Transport
from atlas_reasoning.reasoning_context import ContextHooks
from atlas_reasoning.reliability import ProviderControls
from atlas_reasoning.reviewer import CandidateReviewer
from atlas_reasoning.run_control import OrchestrationPolicy, RunOrchestrator, SettingsReliability, executive_call_budget
from atlas_reasoning.settings import GatewaySettings, ReliabilitySettings
from atlas_reasoning.store.executive import ExecutiveStore
from atlas_reasoning.store.repository import ReasoningStore


@dataclass(frozen=True)
class ReasoningRuntime:
    store: ReasoningStore
    limits: GatewaySettings
    reliability: ReliabilitySettings
    controls: ProviderControls
    gateway: ReasoningGateway
    engine: ReasoningEngine
    orchestrator: RunOrchestrator

    def synthesize(self, run_id: str) -> SynthesisOutcome:
        """Executive synthesis for ``run_id`` on the shared gateway, charged only to a fresh executive budget."""
        return ExecutiveSynthesizer(ExecutiveStore(self.store), self.gateway, budget=executive_call_budget(self.reliability)).synthesize(run_id)

    def snapshot(self) -> dict[str, Any]:
        """Content-free counters: the shared capacity and breaker, the configured limits (no credential)."""
        return {"controls": self.controls.snapshot(), "reliability": self.reliability.to_dict()}


def build_runtime(store: ReasoningStore, transport: Transport, *, env: Mapping[str, str] | None = None, recorder: CallRecorder | None = None,
                  secrets: Sequence[str] = (), context: ContextHooks | None = None,
                  reviewer_factory: Callable[[ReasoningGateway], CandidateReviewer | None] | None = None,
                  policy: OrchestrationPolicy | None = None, controls: ProviderControls | None = None) -> ReasoningRuntime:
    limits, reliability = settings.gateway_settings(env), settings.reliability_settings(env)      # validated once: fail fast
    shared = controls or ProviderControls.from_settings(limits, reliability)
    gateway = ReasoningGateway(transport, limits, recorder=recorder, secrets=secrets, controls=shared)
    reviewer = reviewer_factory(gateway) if reviewer_factory is not None else None               # the same gateway: same controls
    engine = ReasoningEngine(store, gateway, context=context, reviewer=reviewer)
    orchestrator = RunOrchestrator(engine, policy=policy, reliability=SettingsReliability(reliability))
    return ReasoningRuntime(store, limits, reliability, shared, gateway, engine, orchestrator)
