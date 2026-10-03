"""Run orchestration for Reasoning V3 (``REV/18`` #2-#7, #9; Phase 18-A): priority, per-pass call budget, run status, bounded
idempotent resume, duplicate-work protection and failure isolation around the existing ``ReasoningEngine``.

    orchestrator = RunOrchestrator(engine, policy=OrchestrationPolicy(max_calls_per_pass=40))
    report = orchestrator.run(run_id)        # after the Change Gate: lifecycle sweep, then prioritized, budgeted LLM work
    report = orchestrator.resume(run_id)     # later: interrupted claims recovered, eligible failures retried (bounded), pending work

A **pass** is one orchestration over one run (``reasoning_run_passes``). Each pass, under the engine's session advisory lock (one engine
at a time) and with at most one open pass per run (a partial unique index):

1. **checks the run** is gated (a run the Change Gate never finished is ``failed``: no usable reasoning run);
2. **recovers abandoned claims**: an LLM item ``in_progress`` longer than the longest possible call belongs to a dead worker and fails
   ``work:STALE_CLAIM`` — resumable (a younger claim may still be live and is never taken over);
3. **sweeps the lifecycle** (Phase 09, idempotent, no model call);
4. on **resume** only, **creates retry work**: for each present case of the run whose current evidence is still unreasoned, has no open
   LLM work, and whose latest LLM item failed on that same evidence with a retryable error, a pending copy of the failed item — at most
   ``max_attempts`` attempts per (case, evidence state), each failed item retried at most once (``reasoning_work_retries`` unique keys);
5. **admits** pending LLM work in ``work_priority`` order, at most as many items as the budget has calls left; the rest stays
   ``pending`` (deferred, resumable, never failed);
6. **processes** the admitted items through the engine; every provider call reserves one unit of the pass's budget atomically in
   PostgreSQL (``calls_used <= call_budget`` is a CHECK; the optional reviewer's call too), so nothing can overspend; a call the
   budget refuses (a corrective re-ask beyond it) returns its item to ``pending`` — deferred, no attempt spent;
7. **classifies the run** and stores the status in ``reasoning_runs.status`` and on the pass (with reason codes).

Run status (``RunStatus``), by precedence:

========  =================================================================================================================
failed    no usable reasoning run: the run was never gated, the pass hit an orchestration error (lifecycle sweep or store), or
          every reasoning attempt of the run in this pass failed at the provider, none committed, and none of the run's cases
          has a usable (open) result to fall back on (an outage on a run with nothing to show)
partial   useful state kept but work remains resumable: LLM work of the run still pending (budget, interruption) or a failure
          resume will retry (the same predicate resume uses: still eligible, retryable, attempts left)
degraded  all the run's work was attempted, but a case's latest work failed for good (not retryable, out of attempts or no
          longer eligible), a committed result's follow-up (questions / memory) failed in any pass, or a reasoning call of the run
          ran with degraded memory
complete  every LLM item of the run is done (or legitimately closed) — including a run with zero work (all cases unchanged)
========  =================================================================================================================

Nothing here changes reasoning: a failure never touches a committed result (the previous valid card stays current), unchanged cases
never get work (the Change Gate creates none; resume retries only unreasoned evidence), and stable case and result IDs are the engine's.
Executive synthesis is not run here; ``PassReport.executive_ready`` says when the run's reasoning is settled for it (Phase 18
integration schedules it).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from atlas_reasoning import lifecycle
from atlas_reasoning.engine import BUDGET_EXHAUSTED, ENGINE_LOCK_KEY, ReasoningEngine, WorkOutcome
from atlas_reasoning.enums import GateAction, RunStatus, WorkStatus
from atlas_reasoning.reliability import CallBudget
from atlas_reasoning.settings import ReliabilitySettings
from atlas_reasoning.store import run_control as sql
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.work_priority import PRIORITY_VERSION, prioritize, priority

LOG = logging.getLogger("atlas_reasoning.run_control")
POLICY_VERSION = f"run-control-v1/{PRIORITY_VERSION}"

# Failures worth another attempt on the same evidence: transient provider classes (``provider.ProviderError.error_class``), calls the
# Phase 18-B controls refused before any request (``circuit_open``, ``budget_exhausted``: they spend no attempt, ``sql.REFUSALS``), a
# worker that died or was interrupted, a budget that ran out, and transient store errors. Never: validation refusals (the guardrails already
# re-asked; Phase 15), authentication / quota / bad request / content filter / truncation / configuration (an operator must act),
# contract or internal errors (bugs).
DEFAULT_RETRYABLE = frozenset({"provider:timeout", "provider:rate_limited", "provider:provider_unavailable", "provider:network_error",
                               "provider:malformed_response", "provider:invalid_structured_output", "provider:circuit_open", "provider:budget_exhausted",
                               f"work:{BUDGET_EXHAUSTED}", "work:INTERRUPTED", "work:STALE_CLAIM", "store:"})


class ReliabilityPolicy(Protocol):
    """What orchestration needs from the reliability configuration (Phase 18-B owns the configuration itself). ``None`` = no limit."""

    def reasoning_call_budget(self) -> int | None: ...


@dataclass(frozen=True)
class SettingsReliability:
    """``ReliabilityPolicy`` over Phase 18-B's ``settings.ReliabilitySettings``: the pass budget is ``run_call_budget``
    (``ATLAS_REASONING_RUN_CALL_BUDGET``; unset = unlimited). The executive limit is not used here (``executive_call_budget``)."""

    settings: ReliabilitySettings

    def reasoning_call_budget(self) -> int | None:
        return self.settings.run_call_budget


def executive_call_budget(settings: ReliabilitySettings) -> CallBudget:
    """The Phase 18-B ``CallBudget`` for executive synthesis only: its executive limit, and no run limit (case reasoning is charged by the
    pass budget, so no provider call is ever charged twice)."""
    return CallBudget(None, executive_limit=settings.executive_call_budget)


@dataclass(frozen=True)
class OrchestrationPolicy:
    """Orchestration limits. ``max_calls_per_pass`` is used only when no ``ReliabilityPolicy`` is injected."""

    max_calls_per_pass: int | None = None
    max_attempts: int = 3                         # attempts per (case, evidence state), the first included
    retryable: frozenset[str] = DEFAULT_RETRYABLE  # exact error codes; an entry ending in ":" matches that whole class

    def __post_init__(self) -> None:
        if self.max_calls_per_pass is not None and self.max_calls_per_pass < 0:
            raise ValueError("max_calls_per_pass must be >= 0")
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be 1-10")

    def reasoning_call_budget(self) -> int | None:
        return self.max_calls_per_pass

    def is_retryable(self, error: str | None) -> bool:
        code = error or ""
        return any(code == entry or (entry.endswith(":") and code.startswith(entry)) for entry in self.retryable)


class PassBudget:
    """The pass's call budget, spent atomically in PostgreSQL (one short transaction per reservation; safe across threads and processes)."""

    def __init__(self, store: ReasoningStore, pass_id: str) -> None:
        self.store, self.pass_id = store, pass_id

    def acquire(self) -> bool:
        with self.store.transaction() as tx:
            return sql.acquire_call(tx, self.pass_id)

    def release(self) -> None:
        with self.store.transaction() as tx:
            sql.release_call(tx, self.pass_id)


@dataclass(frozen=True)
class PassReport:
    run_id: str
    kind: str
    pass_id: str | None = None
    status: str | None = None                    # the run's status after the pass (RunStatus), None when skipped
    reasons: tuple[str, ...] = ()
    admitted: tuple[str, ...] = ()               # work item IDs, in priority order
    deferred: tuple[str, ...] = ()               # pending work left for a later pass (budget)
    retries: tuple[str, ...] = ()                # retry work items created by this pass
    recovered: tuple[str, ...] = ()              # interrupted claims failed (and later resumable)
    calls_used: int = 0
    outcomes: tuple[WorkOutcome, ...] = ()
    lifecycle: tuple[Any, ...] = ()
    executive_ready: bool = False
    skipped: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**{key: value for key, value in asdict(self).items() if key not in ("outcomes", "lifecycle")},
                "outcomes": [asdict(row) for row in self.outcomes], "lifecycle": [row.to_dict() if hasattr(row, "to_dict") else row for row in self.lifecycle]}


@dataclass
class _Classification:
    status: RunStatus
    reasons: list[str] = field(default_factory=list)


class RunOrchestrator:
    def __init__(self, engine: ReasoningEngine, *, policy: OrchestrationPolicy | None = None, reliability: ReliabilityPolicy | None = None) -> None:
        # One budget per call path: case reasoning is charged by the pass budget, so the engine's gateway must not also carry a Phase 18-B
        # ``CallBudget`` (every call would be charged twice). Executive synthesis uses ``executive_call_budget``.
        if getattr(engine.gateway, "budget", None) is not None:
            raise ValueError("the engine's gateway carries a CallBudget; case reasoning is charged by the orchestration pass budget only")
        self.engine = engine
        self.store: ReasoningStore = engine.store
        self.policy = policy or OrchestrationPolicy()
        self.reliability: ReliabilityPolicy = reliability or self.policy

    # --- public ----------------------------------------------------------------------------------------------------------------

    def run(self, run_id: str) -> PassReport:
        """The initial pass of a gated run."""
        return self._pass(run_id, "initial")

    def resume(self, run_id: str) -> PassReport:
        """A later pass: interrupted claims, eligible failures (bounded) and pending work. Idempotent: nothing left to do → zero calls."""
        return self._pass(run_id, "resume")

    def incomplete_runs(self) -> list[str]:
        """Gated runs ``partial`` or ``failed`` that ``resume`` can still advance (pending work of the run, or eligible failures), oldest
        first. A run ``failed`` by a provider outage is listed; a ``degraded`` one is not (its failures are final)."""
        with self.store.transaction() as tx:
            runs = [row["run_id"] for row in tx._all("""SELECT run_id FROM reasoning_runs WHERE status IN ('partial', 'failed') AND gated_at IS NOT NULL
                                                        ORDER BY started_at, run_id""")]
            pending = {run_id for run_id in runs if sql.open_llm_items(tx, run_id)}
        return [run_id for run_id in runs if run_id in pending or self._eligible(run_id)]

    # --- the pass --------------------------------------------------------------------------------------------------------------

    def _pass(self, run_id: str, kind: str) -> PassReport:
        with self.store.session_lock(ENGINE_LOCK_KEY) as acquired:
            if not acquired:
                LOG.warning("another reasoning engine is running; run_id=%s %s pass skipped", run_id, kind)
                return PassReport(run_id, kind, skipped="engine_busy")
            return self._locked_pass(run_id, kind)

    def _locked_pass(self, run_id: str, kind: str) -> PassReport:
        budget = self.reliability.reasoning_call_budget()
        with self.store.transaction() as tx:
            run = tx.get_run(run_id)
            sql.interrupt_open_passes(tx, run_id)
            pass_id = sql.open_pass(tx, run_id=run_id, kind=kind, policy_version=POLICY_VERSION, call_budget=budget)
        if run["gated_at"] is None:
            return self._finish(run_id, kind, pass_id, _Classification(RunStatus.FAILED, ["not_gated"]))
        recovered: list[WorkOutcome] = []
        changes: list[Any] = []
        retries: list[str] = []
        outcomes: list[WorkOutcome] = []
        admitted: list[Any] = []
        deferred: list[Any] = []
        try:
            # Claims older than the longest possible call belong to a dead worker (``work:STALE_CLAIM``, resumable). A younger claim may
            # still be live (e.g. a worker whose engine-lock connection dropped), so it is never taken over early.
            recovered = self.engine.recover_stale_claims()
            changes = lifecycle.sweep(self.store, run_id, policy=self.engine.policy, clock=self.engine.clock)
            if kind == "resume":
                retries = self._create_retries(run_id, pass_id)
            pending = prioritize(self.engine.pending_work())
            with self.store.transaction() as tx:
                remaining = sql.remaining_calls(tx, pass_id)
            admitted = pending if remaining is None else pending[:remaining]
            deferred = pending[len(admitted):]
            with self.store.transaction() as tx:
                sql.record_admission(tx, pass_id, admitted=len(admitted), deferred=len(deferred), retries=len(retries))
            outcomes = self.engine.process_work(admitted, budget=PassBudget(self.store, pass_id))
        except Exception as error:  # noqa: BLE001 - the pass fails; committed results are untouched, work stays resumable
            LOG.error("orchestration pass failed run_id=%s kind=%s error=%s", run_id, kind, type(error).__name__)
            return self._finish(run_id, kind, pass_id, _Classification(RunStatus.FAILED, [f"orchestration_error:{type(error).__name__}"]),
                                recovered=recovered, outcomes=outcomes, changes=changes, retries=retries)
        classification = self._classify(run_id, pass_id, recovered + outcomes)
        for other in sorted({item.run_id for item in admitted} - {run_id}):     # older runs whose pending work this pass finished
            self._reclassify(other, pass_id)
        return self._finish(run_id, kind, pass_id, classification, recovered=recovered, outcomes=outcomes, changes=changes, retries=retries,
                            admitted=[item.work_item_id for item in admitted], deferred=[item.work_item_id for item in deferred],
                            high_priority=sum(1 for item in admitted if priority(item).tier < 3))

    def _eligible(self, run_id: str) -> list[dict[str, Any]]:
        """Failures of the run that resume will retry: the shared candidate predicate, a retryable error and attempts left."""
        with self.store.transaction() as tx:
            candidates = sql.retry_candidates(tx, run_id)
        return [row for row in candidates if self.policy.is_retryable(row["last_error"]) and sql.eligible(row, self.policy.max_attempts)]

    def _create_retries(self, run_id: str, pass_id: str) -> list[str]:
        created = []
        for row in self._eligible(run_id):
            try:
                with self.store.transaction() as tx:
                    work_item_id = sql.create_retry(tx, run_id, row["work_item_id"], max_attempts=self.policy.max_attempts, pass_id=pass_id)
                if work_item_id is not None:
                    created.append(work_item_id)
            except Exception as error:  # noqa: BLE001 - a concurrent resume or a new gate item won: no duplicate, nothing lost
                LOG.warning("retry not created work_item_id=%s error=%s", row["work_item_id"], type(error).__name__)
        return created

    # --- status --------------------------------------------------------------------------------------------------------------

    def _classify(self, run_id: str, pass_id: str, outcomes: Sequence[WorkOutcome]) -> _Classification:
        with self.store.transaction() as tx:
            items = sql.latest_llm_items(tx, [run_id])
            memory = sql.memory_degraded(tx, run_id)
            usable = sql.has_usable_result(tx, run_id)
            carried = sql.carried_reasons(tx, run_id, ("followup_failed",))
            run_items = {item.work_item_id for item in tx.work_items(run_id=run_id)}
        eligible = {row["work_item_id"] for row in self._eligible(run_id)}
        mine = [row for row in outcomes if row.work_item_id in run_items]
        attempted = [row for row in mine if row.status == WorkStatus.FAILED or row.change_kind is not None]
        if attempted and not usable and all(row.status == WorkStatus.FAILED and (row.error or "").startswith("provider:")
                                            and row.error != "provider:budget_exhausted" for row in attempted):     # a budget is no outage
            return _Classification(RunStatus.FAILED, ["provider_outage"])     # nothing reasoned and nothing usable: no usable run
        reasons = []
        if any(item.status in (WorkStatus.PENDING, WorkStatus.IN_PROGRESS) for item in items):
            reasons.append("work_deferred")
        failed = [item for item in items if item.status == WorkStatus.FAILED]
        if any(item.work_item_id in eligible for item in failed):
            reasons.append("resumable_failures")
        if reasons:
            return _Classification(RunStatus.PARTIAL, reasons)
        if failed:
            reasons.append("unresolved_failures")
        if any((row.followup or {}).get("errors") for row in mine) or "followup_failed" in carried:
            reasons.append("followup_failed")
        if memory:
            reasons.append("memory_degraded")
        return _Classification(RunStatus.DEGRADED if reasons else RunStatus.COMPLETE, reasons)

    def _reclassify(self, run_id: str, pass_id: str) -> None:
        try:
            classification = self._classify(run_id, pass_id, ())
            with self.store.transaction() as tx:
                sql.set_run_status(tx, run_id, classification.status.value, classification.reasons)
        except Exception as error:  # noqa: BLE001 - another run's status is advisory here; its own pass recomputes it
            LOG.warning("run status not recomputed run_id=%s error=%s", run_id, type(error).__name__)

    def _finish(self, run_id: str, kind: str, pass_id: str, classification: _Classification, *, recovered: Iterable[WorkOutcome] = (),
                outcomes: Iterable[WorkOutcome] = (), changes: Iterable[Any] = (), retries: Iterable[str] = (), admitted: Iterable[str] = (),
                deferred: Iterable[str] = (), high_priority: int = 0) -> PassReport:
        recovered, outcomes, admitted, deferred = tuple(recovered), tuple(outcomes), tuple(admitted), tuple(deferred)
        with self.store.transaction() as tx:
            row = tx._one("SELECT calls_used FROM reasoning_run_passes WHERE pass_id = %s", (pass_id,))
            calls = int(row["calls_used"]) if row else 0
            unchanged = tx._one("SELECT count(*) AS n FROM reasoning_case_observations WHERE run_id = %s AND action = %s", (run_id, GateAction.UNCHANGED))
            counts = {"admitted": len(admitted), "deferred": len(deferred), "retries": len(tuple(retries)), "recovered": len(recovered),
                      "calls_used": calls, "done": sum(1 for o in outcomes if o.status == WorkStatus.DONE),
                      "failed": sum(1 for o in outcomes if o.status == WorkStatus.FAILED), "unchanged_cases": int(unchanged["n"]) if unchanged else 0,
                      "high_priority_admitted": high_priority}
            sql.finish_pass(tx, pass_id, run_status=classification.status.value, reasons=classification.reasons, counts=counts)
            sql.set_run_status(tx, run_id, classification.status.value, classification.reasons)
            open_work = tx._one("SELECT 1 FROM reasoning_work_items WHERE requires_llm AND status IN ('pending', 'in_progress') LIMIT 1")
        ready = classification.status in (RunStatus.COMPLETE, RunStatus.DEGRADED) and open_work is None
        LOG.info("orchestration pass run_id=%s kind=%s status=%s reasons=%s calls=%s", run_id, kind, classification.status.value,
                 ",".join(classification.reasons), calls)
        return PassReport(run_id, kind, pass_id, classification.status.value, tuple(classification.reasons), admitted, deferred, tuple(retries),
                          tuple(row.work_item_id for row in recovered), calls, outcomes, tuple(changes), ready)


def admitted_priorities(items: Iterable[Any]) -> list[dict[str, Any]]:
    """Debug view: each item's priority (tier, best V2 rank, high importance)."""
    return [{"work_item_id": item.work_item_id, "case_id": item.case_id, **priority(item).to_dict()} for item in items]
