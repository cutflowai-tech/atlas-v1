"""Run orchestration for Reasoning V3 (``REV/18`` #2-#7, #9; Phase 18-A): priority, per-pass call budget, run status, bounded
idempotent resume, duplicate-work protection and failure isolation around the existing ``ReasoningEngine``.

    orchestrator = RunOrchestrator(engine, policy=OrchestrationPolicy(max_calls_per_pass=40))
    report = orchestrator.run(run_id)        # after the Change Gate: lifecycle sweep, then prioritized, budgeted LLM work
    report = orchestrator.resume(run_id)     # later: interrupted claims recovered, eligible failures retried (bounded), pending work

A **pass** is one orchestration over one run (``reasoning_run_passes``). Each pass, under the engine's session advisory lock (one engine
at a time) and with at most one open pass per run (a partial unique index):

1. **checks the run** is gated (a run the Change Gate never finished is ``failed``: no usable reasoning run);
2. **recovers interrupted claims**: every LLM item still ``in_progress`` belongs to a dead worker (the lock proves no engine is live), so
   it fails ``work:INTERRUPTED`` — resumable — instead of waiting for the stale-claim timeout;
3. **sweeps the lifecycle** (Phase 09, idempotent, no model call);
4. on **resume** only, **creates retry work**: for each present case of the run whose current evidence is still unreasoned, has no open
   LLM work, and whose latest LLM item failed on that same evidence with a retryable error, a pending copy of the failed item — at most
   ``max_attempts`` attempts per (case, evidence state), each failed item retried at most once (``reasoning_work_retries`` unique keys);
5. **admits** pending LLM work in ``work_priority`` order, at most as many items as the budget has calls left; the rest stays
   ``pending`` (deferred, resumable, never failed);
6. **processes** the admitted items through the engine; every provider call reserves one unit of the pass's budget atomically in
   PostgreSQL (``calls_used <= call_budget`` is a CHECK), so a corrective re-ask beyond the budget fails ``work:BUDGET_EXHAUSTED``
   (resumable) and nothing can overspend;
7. **classifies the run** and stores the status in ``reasoning_runs.status`` and on the pass (with reason codes).

Run status (``RunStatus``), by precedence:

========  =================================================================================================================
failed    no usable reasoning run: the run was never gated, the pass hit an orchestration error (lifecycle sweep or store), or
          every reasoning attempt of the run in this pass failed at the provider, none committed, and none of the run's cases
          has a usable (open) result to fall back on (an outage on a run with nothing to show)
partial   useful state kept but work remains resumable: LLM work of the run still pending (budget, interruption) or a failure
          the policy will retry (attempts left)
degraded  all the run's work was attempted, but a case's latest work failed for good (not retryable or out of attempts), a
          committed result's follow-up (questions / memory) failed, or memory was degraded during the pass
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
from atlas_reasoning.engine import BUDGET_EXHAUSTED, ENGINE_LOCK_KEY, ReasoningEngine, WorkError, WorkOutcome
from atlas_reasoning.enums import GateAction, RunStatus, WorkStatus
from atlas_reasoning.store import run_control as sql
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.work_priority import PRIORITY_VERSION, prioritize, priority

LOG = logging.getLogger("atlas_reasoning.run_control")
POLICY_VERSION = f"run-control-v1/{PRIORITY_VERSION}"

# Failures worth another attempt on the same evidence: transient provider classes (``provider.ProviderError.error_class``), a worker that
# died or was interrupted, a budget that ran out, and transient store errors. Never: validation refusals (the guardrails already
# re-asked; Phase 15), authentication / quota / bad request / content filter / truncation / configuration (an operator must act),
# contract or internal errors (bugs).
DEFAULT_RETRYABLE = frozenset({"provider:timeout", "provider:rate_limited", "provider:provider_unavailable", "provider:network_error",
                               "provider:malformed_response", "provider:invalid_structured_output", f"work:{BUDGET_EXHAUSTED}", "work:INTERRUPTED",
                               "work:STALE_CLAIM", "store:"})


class ReliabilityPolicy(Protocol):
    """What orchestration needs from the reliability configuration (Phase 18-B owns the configuration itself). ``None`` = no limit."""

    def reasoning_call_budget(self) -> int | None: ...


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
        """Runs whose last status is ``partial`` (work remains resumable), oldest first."""
        with self.store.transaction() as tx:
            return [row["run_id"] for row in tx._all("SELECT run_id FROM reasoning_runs WHERE status = 'partial' ORDER BY started_at, run_id")]

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
        if run["status"] == RunStatus.STARTED:
            return self._finish(run_id, kind, pass_id, _Classification(RunStatus.FAILED, ["not_gated"]))
        recovered: list[WorkOutcome] = []
        changes: list[Any] = []
        retries: list[str] = []
        outcomes: list[WorkOutcome] = []
        admitted: list[Any] = []
        deferred: list[Any] = []
        try:
            with self.store.transaction() as tx:
                interrupted = sql.interrupted_claims(tx)
            recovered = [self.engine.fail(item, WorkError("INTERRUPTED")) for item in interrupted]
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

    def _create_retries(self, run_id: str, pass_id: str) -> list[str]:
        created = []
        with self.store.transaction() as tx:
            candidates = sql.retry_candidates(tx, run_id)
        for row in candidates:
            attempt = int(row["attempt"]) + 1
            if not self.policy.is_retryable(row["last_error"]) or attempt > self.policy.max_attempts:
                continue
            try:
                with self.store.transaction() as tx:
                    created.append(sql.create_retry(tx, row, attempt=attempt, pass_id=pass_id))
            except Exception as error:  # noqa: BLE001 - a concurrent resume or a new gate item won: no duplicate, nothing lost
                LOG.warning("retry not created work_item_id=%s error=%s", row["work_item_id"], type(error).__name__)
        return created

    # --- status --------------------------------------------------------------------------------------------------------------

    def _attempts(self, tx: Any, case_id: str, fingerprint: str | None) -> int:
        row = tx._one("SELECT count(*) AS n FROM reasoning_work_retries WHERE case_id = %s AND evidence_fingerprint = %s", (case_id, fingerprint))
        return 1 + int(row["n"]) if row else 1

    def _classify(self, run_id: str, pass_id: str, outcomes: Sequence[WorkOutcome]) -> _Classification:
        with self.store.transaction() as tx:
            items = sql.latest_llm_items(tx, [run_id])
            attempts = {item.work_item_id: self._attempts(tx, item.case_id, item.fingerprint_after) for item in items if item.status == WorkStatus.FAILED}
            memory = sql.memory_degraded(tx, [run_id], sql.pass_started_at(tx, pass_id))
            usable = sql.has_usable_result(tx, run_id)
            run_items = {item.work_item_id for item in tx.work_items(run_id=run_id)}
        mine = [row for row in outcomes if row.work_item_id in run_items]
        attempted = [row for row in mine if row.status == WorkStatus.FAILED or row.change_kind is not None]
        if attempted and not usable and all(row.status == WorkStatus.FAILED and (row.error or "").startswith("provider:") for row in attempted):
            return _Classification(RunStatus.FAILED, ["provider_outage"])     # nothing reasoned and nothing usable: no usable run
        reasons = []
        if any(item.status in (WorkStatus.PENDING, WorkStatus.IN_PROGRESS) for item in items):
            reasons.append("work_deferred")
        failed = [item for item in items if item.status == WorkStatus.FAILED]
        resumable = [item for item in failed if self.policy.is_retryable(self._error(item)) and attempts[item.work_item_id] < self.policy.max_attempts]
        if resumable:
            reasons.append("resumable_failures")
        if reasons:
            return _Classification(RunStatus.PARTIAL, reasons)
        if failed:
            reasons.append("unresolved_failures")
        if any((row.followup or {}).get("errors") for row in mine):
            reasons.append("followup_failed")
        if memory:
            reasons.append("memory_degraded")
        return _Classification(RunStatus.DEGRADED if reasons else RunStatus.COMPLETE, reasons)

    def _error(self, item: Any) -> str | None:
        with self.store.transaction() as tx:
            row = tx._one("SELECT last_error FROM reasoning_work_items WHERE work_item_id = %s", (item.work_item_id,))
        return row["last_error"] if row else None

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
