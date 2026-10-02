"""The reasoning engine: turns Change Gate work items into persisted reasoning (``REV/07``–``REV/09``), with the human context of
Phases 10–14 wired around every model call.

    engine = ReasoningEngine(store, gateway, context=HumanContext(store, backend_from_env()))
    report = engine.process_run(run_id)          # every pending LLM work item, each isolated from the others

``process_run`` holds a session advisory lock (one engine at a time; a second one finds the lock taken and does nothing), fails
abandoned claims, applies the deterministic lifecycle sweep, then runs every pending LLM work item through its own pipeline,
``gateway.settings.concurrency`` items at a time:

1. **claim** (own transaction): ``pending → in_progress`` just before the item's call, so a claim is never older than one call; the
   exact case comes from ``change_gate.case_for_work`` (with the previous result and exact material delta for an update). Work for a
   case that is no longer present is closed without a model call;
2. **context**: the case receives its scoped human context (``reasoning_context.ContextHooks.prepare``: manager notes, management
   answers, teachings and validated memory; never evidence) and the injected items are audited under the call's request ID;
3. **reason**: one gateway call (bounded concurrency, retries, ``llm_calls`` records); the gateway checks only that the answer is
   well formed (shape and contract) and retries malformed JSON;
4. **validate** (Phase 15): the complete candidate — the assembled version 1, or for an update the **merged** next version — passes
   the deterministic guardrails (``guardrails.validate_candidate``: identity, evidence, numbers, entities, metrics, causality, people,
   confidence, attribution) and, for configured high-impact cases, the optional reviewer. A refused candidate is recorded in
   ``reasoning_failed_candidates`` and never committed; the model is re-asked with the refusal's codes at most
   ``validation_retries`` times (default 1), then the item fails (``validation:<codes>``) and the previous valid result stays current;
5. **persist** (own transaction): the accepted result is created (or, Phase 08, patched) together with the work item's ``done``
   status — all or nothing. Any failure rolls the transaction back and the item is marked ``failed`` with a short error
   (``provider:<error class>``, ``validation:<codes>``, ``store:<error>``) in a separate transaction;
6. **follow up** (after the commit, never inside it; never for a refused candidate): the committed version's questions become canonical Atlas questions, then the
   result summary is copied to memory (``ContextHooks.after_commit``). A follow-up failure never touches the committed result.

A failure — provider error, invalid output, store conflict — affects only its own work item. The model never sets identity,
provenance or lifecycle (``analyst``), and the answering model must be the configured one (``settings.model_identity_matches``;
``validation:MODEL_SUBSTITUTED`` otherwise).
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import partial
from typing import Any, Protocol

from atlas_reasoning import analyst, guardrails, lifecycle, reviewer, updater
from atlas_reasoning.change_gate import case_for_work
from atlas_reasoning.contracts import ContractViolation, ReasoningCase, ReasoningResult, ReasoningUpdate, new_result_id
from atlas_reasoning.delta import material_delta
from atlas_reasoning.enums import LifecycleStatus, ResultChangeKind, WorkKind, WorkStatus
from atlas_reasoning.gateway import ReasoningGateway, new_request_id
from atlas_reasoning.provider import Message, ProviderError, ProviderRequest, ProviderResponse
from atlas_reasoning.reasoning_context import ContextHooks, FollowUp, HumanContext, PreparedCase
from atlas_reasoning.reviewer import CandidateReviewer
from atlas_reasoning.settings import validation_retries
from atlas_reasoning.store.db import DatabaseError
from atlas_reasoning.store.repository import ReasoningStore, StoreTransaction, WorkItemRow, WorkTransitionError

LOG = logging.getLogger("atlas_reasoning.engine")
ENGINE_VERSION = "reasoning-engine-v2"
# pg_try_advisory_lock key: one reasoning engine at a time ("atlas reasoning engine").
ENGINE_LOCK_KEY = 0x41746C6152454E47


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class WorkError(RuntimeError):
    """A work item cannot be completed; ``code`` is stored as its error."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class WorkOutcome:
    work_item_id: str
    case_id: str
    kind: str
    status: str
    result_id: str | None = None
    version: int | None = None
    change_kind: str | None = None
    error: str | None = None
    followup: dict[str, Any] | None = None       # questions and memory sync after the commit (``reasoning_context.FollowUp``)


@dataclass(frozen=True)
class EngineReport:
    run_id: str | None
    outcomes: tuple[WorkOutcome, ...]
    lifecycle: tuple[Any, ...] = field(default_factory=tuple)
    unreasoned: tuple[str, ...] = ()              # present cases whose open result is not on their current evidence (Phase 18 resumes them)
    skipped: str | None = None                    # set when another engine held the lock

    @property
    def failed(self) -> tuple[WorkOutcome, ...]:
        return tuple(row for row in self.outcomes if row.status == WorkStatus.FAILED)

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for row in self.outcomes:
            key = row.change_kind or row.status
            counts[key] = counts.get(key, 0) + 1
        return {"engine_version": ENGINE_VERSION, "run_id": self.run_id, "counts": counts, "work": [asdict(row) for row in self.outcomes],
                "lifecycle": [row.to_dict() if hasattr(row, "to_dict") else row for row in self.lifecycle],
                "unreasoned_cases": list(self.unreasoned), "skipped": self.skipped}


@dataclass(frozen=True)
class _Claimed:
    item: WorkItemRow
    case: ReasoningCase
    previous: ReasoningResult | None = None   # set for update reasoning: the open result's current version


def error_code(error: BaseException) -> str:
    """A short, content-free description of a failure for ``reasoning_work_items.last_error``."""
    if isinstance(error, ProviderError):
        return f"provider:{error.error_class}"
    if isinstance(error, guardrails.GuardrailError):
        return f"validation:{','.join(error.report.codes)}"
    if isinstance(error, ContractViolation):
        return f"contract:{','.join(error.codes)}"
    if isinstance(error, WorkError):
        return f"work:{error.code}"
    if isinstance(error, DatabaseError):
        return f"store:{type(error).__name__}"
    return f"internal:{type(error).__name__}"


class CallBudget(Protocol):
    """Phase 18: the provider-call budget of one orchestration pass (``run_control``). ``acquire`` reserves one reasoning call and
    returns False when the budget is spent; it must be safe to call from several worker threads."""

    def acquire(self) -> bool: ...


# A call the budget refused: the item fails with this code and stays resumable (``run_control.OrchestrationPolicy``).
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class EngineBusy(RuntimeError):
    """Another reasoning engine holds the engine lock."""


class ReasoningEngine:
    def __init__(self, store: ReasoningStore, gateway: ReasoningGateway, *, clock: Callable[[], str] = utc_now,
                 result_ids: Callable[[], str] = new_result_id, policy: lifecycle.LifecyclePolicy | None = None,
                 context: ContextHooks | None = None, reviewer: CandidateReviewer | None = None,
                 retries: int | None = None) -> None:
        self.store, self.gateway, self.clock, self.result_ids = store, gateway, clock, result_ids
        self.policy = policy or lifecycle.policy_from_env()
        # Without an explicit context the canonical human context (PostgreSQL only, no memory backend) is still injected and audited.
        self.context: ContextHooks = context if context is not None else HumanContext(store, None)
        # Phase 15: the optional second reviewer (None = off) and the bounded corrective re-asks after a refused candidate.
        self.reviewer = reviewer
        self.validation_retries = validation_retries() if retries is None else retries

    # --- public ---------------------------------------------------------------------------------------------------------------

    def process_run(self, run_id: str) -> EngineReport:
        """First the deterministic lifecycle of every case the gate observed in ``run_id`` (Phase 09: reactivation, cooling,
        resolution), then every pending LLM work item (of any run: older pending items are never skipped). One engine at a time:
        if another holds the engine lock, nothing is done and the report says so."""
        with self.store.session_lock(ENGINE_LOCK_KEY) as acquired:
            if not acquired:
                LOG.warning("another reasoning engine is running; run_id=%s skipped", run_id)
                return EngineReport(run_id, (), skipped="engine_busy")
            recovered = self.recover_stale_claims()
            changes = lifecycle.sweep(self.store, run_id, policy=self.policy, clock=self.clock)
            outcomes = recovered + self.process_work(self.pending_work())
            with self.store.transaction() as tx:
                unreasoned = tuple(row["case_id"] for row in tx.unreasoned_cases())
        return EngineReport(run_id, tuple(outcomes), tuple(changes), unreasoned)

    def pending_work(self) -> list[WorkItemRow]:
        items = self.store.work_items(open_only=True)
        return [item for item in items if item.status == WorkStatus.PENDING and item.kind in self.handled_kinds]

    handled_kinds: tuple[WorkKind, ...] = (WorkKind.NEW_RESULT, WorkKind.UPDATE_RESULT)

    def process_work(self, items: Sequence[WorkItemRow], *, budget: CallBudget | None = None) -> list[WorkOutcome]:
        """Each item through its own claim → context → call → persist → follow-up pipeline, ``concurrency`` items at a time. An
        item is claimed only when its own call is about to start and saved as soon as its answer arrives. With a ``budget`` (Phase 18),
        every provider call first reserves one unit; a refused reservation fails the item ``work:BUDGET_EXHAUSTED`` (resumable)."""
        if not items:
            return []
        workers = max(1, min(self.gateway.settings.concurrency, len(items)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="atlas-reasoning-work") as pool:
            results = list(pool.map(partial(self._run_item, budget=budget), items))
        return [outcome for outcome in results if outcome is not None]

    def recover_stale_claims(self) -> list[WorkOutcome]:
        """Fail LLM items left ``in_progress`` longer than ``stale_claim_seconds`` (a worker that died mid-call), so their cases are
        no longer blocked; the resume phase re-reasons them (``StoreTransaction.unreasoned_cases``)."""
        with self.store.transaction() as tx:
            stale = tx.stale_in_progress_work(self.stale_claim_seconds)
        return [self._fail(item, WorkError("STALE_CLAIM")) for item in stale]

    @property
    def stale_claim_seconds(self) -> float:
        """Longer than any single call may take: every attempt at its full timeout plus every capped backoff, plus a margin. A claim is
        taken just before its own call, so an older claim belongs to a worker that died."""
        limits = self.gateway.settings
        attempts = limits.max_retries + 1
        return attempts * limits.timeout_seconds + limits.max_retries * limits.max_backoff_seconds + 300.0

    # --- steps ----------------------------------------------------------------------------------------------------------------

    def _run_item(self, item: WorkItemRow, budget: CallBudget | None = None) -> WorkOutcome | None:
        try:
            ready = self._claim(item)
        except WorkTransitionError:
            return None   # another worker took it, or it was superseded or cancelled meanwhile
        except Exception as error:  # noqa: BLE001 - one bad item never stops the others
            return self._fail(item, error)
        if isinstance(ready, WorkOutcome):
            return ready
        finished = False
        try:
            outcome = self._reason(ready, budget)
            finished = True
            return outcome
        finally:
            if not finished:   # never leave a claimed item in progress (it would block its case)
                self._fail(item, WorkError("INTERRUPTED"))

    def _reason(self, ready: _Claimed, budget: CallBudget | None = None) -> WorkOutcome:
        item = ready.item
        try:
            prepared = self.context.prepare(ready.case)
            case = prepared.case
            if ready.previous is not None:
                request = updater.update_request(ready.previous, case, run_id=item.run_id, work_item_id=item.work_item_id)
            else:
                request = analyst.analyst_request(case, run_id=item.run_id, work_item_id=item.work_item_id)
        except Exception as error:  # noqa: BLE001 - recorded on the item
            return self._fail(item, error)
        ready = dataclasses.replace(ready, case=case)
        result_id = ready.previous.result_id if ready.previous is not None else self.result_ids()
        attempt = 0
        while True:
            attempt += 1
            if budget is not None and not budget.acquire():      # before the audit row: a refused call leaves no trace of a call
                return self._fail(item, WorkError(BUDGET_EXHAUSTED))
            try:
                request = dataclasses.replace(request, context=dataclasses.replace(request.context, request_id=new_request_id()))
                self.context.record(prepared, purpose=request.context.purpose, request_id=request.context.request_id, run_id=item.run_id,
                                    work_item_id=item.work_item_id, result_id=ready.previous.result_id if ready.previous else None)
            except Exception as error:  # noqa: BLE001
                return self._fail(item, error)
            try:
                response = self.gateway.call(request)
            except ProviderError as error:
                return self._fail(item, error)
            outcome, report = self._complete(ready, request, response, result_id, attempt, prepared)
            if outcome is not None:
                break
            assert report is not None
            if not report.retryable or attempt > self.validation_retries:
                return self._fail(item, guardrails.GuardrailError(report))
            # Bounded correction: the same request, the refused answer, and the refusal's codes and paths only.
            request = dataclasses.replace(request, messages=(*request.messages, Message("assistant", response.content),
                                                             Message("user", guardrails.correction_message(report))))
        if outcome.status == WorkStatus.DONE and outcome.result_id and outcome.version and outcome.change_kind:
            followup = self._follow_up(outcome, item.run_id)
            outcome = dataclasses.replace(outcome, followup=followup.to_dict())
        return outcome

    def _follow_up(self, outcome: WorkOutcome, run_id: str | None) -> FollowUp:
        assert outcome.result_id and outcome.version and outcome.change_kind
        try:
            return self.context.after_commit(result_id=outcome.result_id, version=outcome.version, change_kind=ResultChangeKind(outcome.change_kind),
                                             run_id=run_id)
        except Exception as error:  # noqa: BLE001 - the result is committed; a follow-up never undoes it
            LOG.error("follow-up failed work_item_id=%s result_id=%s error=%s", outcome.work_item_id, outcome.result_id, type(error).__name__)
            return FollowUp(errors=(f"followup:{type(error).__name__}",))

    def _claim(self, item: WorkItemRow) -> _Claimed | WorkOutcome:
        with self.store.transaction() as tx:
            tx.set_work_item_status(item.work_item_id, WorkStatus.IN_PROGRESS)
        try:
            with self.store.transaction() as tx:
                if tx.get_case(item.case_id).presence != "present":
                    # Pending work for a case that has since disappeared: no model call. Its card (if any) follows the lifecycle
                    # (cooling), never stale evidence.
                    tx.set_work_item_status(item.work_item_id, WorkStatus.DONE, error="case no longer present; not reasoned")
                    kept = tx.latest_result(item.case_id)
                    return WorkOutcome(item.work_item_id, item.case_id, item.kind.value, WorkStatus.DONE.value, kept.result_id if kept else None,
                                       kept.version if kept else None)
                current = tx.open_result(item.case_id)
                if current is not None:
                    previous = tx.get_result(current.result_id)
                else:
                    latest = tx.latest_result(item.case_id)
                    if latest is None or latest.lifecycle_status != LifecycleStatus.RESOLVED:
                        if item.kind == WorkKind.UPDATE_RESULT:
                            raise WorkError("NO_OPEN_RESULT", f"case {item.case_id} has no open result to update")
                        return _Claimed(item, case_for_work(tx, item))
                    # A resolved case observed again returns to its own card (normally already done by the lifecycle sweep).
                    previous, _ = lifecycle.apply(tx, latest, LifecycleStatus.ACTIVE, lifecycle.REAPPEARED_AFTER_RESOLUTION, policy=self.policy,
                                                  now=self.clock(), run_id=item.run_id, work_item_id=item.work_item_id, detail={"via": "work_item"})
                # The case already has a result: it is updated, never regenerated (also for a new_result item).
                update_case = self._update_case(tx, item, previous)
                if update_case is None:
                    tx.set_work_item_status(item.work_item_id, WorkStatus.DONE, error="evidence equals the open result's evidence")
                    return WorkOutcome(item.work_item_id, item.case_id, item.kind.value, WorkStatus.DONE.value, previous.result_id, previous.version)
            return _Claimed(item, update_case, previous)
        except Exception as error:  # noqa: BLE001
            return self._fail(item, error)

    @staticmethod
    def _update_case(tx: StoreTransaction, item: WorkItemRow, previous: ReasoningResult) -> ReasoningCase | None:
        """The work item's case with the previous result and the exact material delta from the evidence that result was reasoned on
        (equal to the gate's delta for an ``update_result`` item). None when the evidence is already the result's."""
        if item.fingerprint_after is None or item.case_document is None:
            raise WorkError("NO_EVIDENCE_STATE", f"work item {item.work_item_id} names no evidence state")
        if item.fingerprint_after == previous.evidence_fingerprint:
            return None
        before = tx.get_case_evidence(item.case_id, previous.evidence_fingerprint)["canonical_evidence"]
        after = tx.get_case_evidence(item.case_id, item.fingerprint_after)["canonical_evidence"]
        document = dict(item.case_document)
        document.update(previous_result_id=previous.result_id, previous_result_version=previous.version,
                        material_delta=material_delta(before, after, fingerprint_before=previous.evidence_fingerprint, fingerprint_after=item.fingerprint_after))
        return ReasoningCase.from_dict(document)

    def _complete(self, ready: _Claimed, request: ProviderRequest, response: ProviderResponse, result_id: str, attempt: int,
                  prepared: PreparedCase) -> tuple[WorkOutcome | None, guardrails.ValidationReport | None]:
        """Build the complete candidate, run the Phase 15 guardrails (and the optional reviewer) and commit only a candidate they accept.
        Returns ``(outcome, None)`` when the item is finished (committed or failed) or ``(None, report)`` for a refused candidate."""
        item, previous = ready.item, ready.previous
        provider = self.gateway.transport.provider_name
        try:
            case = ready.case.to_dict()
            if previous is None:
                candidate = analyst.candidate_from_response(ready.case, response, provider=provider, result_id=result_id, now=self.clock())
                patch: updater.UpdateCandidate | None = None
                extra: list[guardrails.Violation] = []
            else:
                patch = updater.candidate_from_response(previous, ready.case, response, provider=provider, now=self.clock(),
                                                        lifecycle_status=previous.lifecycle_status.value)
                candidate = patch.merged or {}
                extra = guardrails.patch_violations(patch.errors)
            # Expectations come from the work item and the request, never from the answer: the gated evidence state, the request ID.
            expected = guardrails.Expected(case_id=item.case_id, result_id=result_id, version=previous.version + 1 if previous else 1,
                                           source_snapshot_id=case["source_snapshot_id"],
                                           evidence_fingerprint=item.fingerprint_after or case["evidence_fingerprint"],
                                           prompt_version=updater.UPDATE_PROMPT_VERSION if previous else analyst.ANALYST_PROMPT_VERSION,
                                           model=self.gateway.model, request_id=request.context.request_id,
                                           previous=previous.to_dict() if previous is not None else None)
            report = guardrails.validate_candidate(candidate, case, expected, extra=extra)
            if report.ok and self.reviewer is not None and self.reviewer.applies(case):
                review_id = new_request_id()      # the reviewer sees the same human context: its call is audited like any other
                self.context.record(prepared, purpose=reviewer.REVIEW_PURPOSE, request_id=review_id, run_id=item.run_id,
                                    work_item_id=item.work_item_id, result_id=previous.result_id if previous else None)
                verdict = self.reviewer.review(case, candidate, run_id=item.run_id, work_item_id=item.work_item_id, request_id=review_id)
                if not verdict.approved:
                    report = guardrails.ValidationReport(verdict.violations)
            if not report.ok:
                self._record_refusal(ready, request, response, result_id, attempt, report, candidate, patch)
                return None, report
            if patch is not None and previous is not None:
                return self._persist_update(ready, previous, patch), None
            return self._persist_new(ready, ReasoningResult.from_dict(candidate)), None
        except Exception as error:  # noqa: BLE001 - rolled back; recorded on the item
            return self._fail(item, error), None

    def _record_refusal(self, ready: _Claimed, request: ProviderRequest, response: ProviderResponse, result_id: str, attempt: int,
                        report: guardrails.ValidationReport, candidate: Mapping[str, Any], patch: updater.UpdateCandidate | None) -> None:
        """Keep the refused candidate for debugging (its own transaction; never a result version, never on the dashboard)."""
        item = ready.item
        stored = {"result": candidate or None, "update": patch.update if patch is not None else None}
        LOG.warning("candidate refused work_item_id=%s case_id=%s attempt=%s codes=%s", item.work_item_id, item.case_id, attempt, ",".join(report.codes))
        try:
            with self.store.transaction() as tx:
                tx.record_failed_candidate(case_id=item.case_id, run_id=item.run_id, work_item_id=item.work_item_id, result_id=result_id,
                                           base_version=ready.previous.version if ready.previous else None, request_id=response.request_id,
                                           purpose=request.context.purpose, attempt=attempt, validator_version=report.validator_version,
                                           error_codes=report.codes, violations=[violation.to_dict() for violation in report.violations],
                                           candidate={key: value for key, value in stored.items() if value is not None}, model=response.model,
                                           prompt_version=request.context.prompt_version, evidence_fingerprint=ready.case.evidence_fingerprint)
        except DatabaseError as error:
            LOG.error("refused candidate not recorded work_item_id=%s error=%s", item.work_item_id, error_code(error))

    def _persist_new(self, ready: _Claimed, result: ReasoningResult) -> WorkOutcome:
        item = ready.item
        with self.store.transaction() as tx:
            tx.create_result(result, run_id=item.run_id, work_item_id=item.work_item_id)
            lifecycle.record_creation(tx, result, policy=self.policy, run_id=item.run_id, work_item_id=item.work_item_id)
            tx.set_work_item_status(item.work_item_id, WorkStatus.DONE)
        LOG.info("result created work_item_id=%s case_id=%s result_id=%s", item.work_item_id, item.case_id, result.result_id)
        return WorkOutcome(item.work_item_id, item.case_id, item.kind.value, WorkStatus.DONE.value, result.result_id, 1, ResultChangeKind.CREATED.value)

    def _persist_update(self, ready: _Claimed, previous: ReasoningResult, patch: updater.UpdateCandidate) -> WorkOutcome:
        item = ready.item
        assert patch.merged is not None
        update = ReasoningUpdate.from_dict(patch.update)
        result = ReasoningResult.from_dict(patch.merged)
        if patch.is_patch:   # Python decides the lifecycle: an accepted patch marks an open card updated; a review keeps its status
            status = lifecycle.after_patch(previous.lifecycle_status)
            result = ReasoningResult.from_dict({**result.to_dict(), "lifecycle_status": status.value})
        kind = ResultChangeKind.PATCHED if patch.is_patch else ResultChangeKind.NO_CHANGE_REVIEW
        reason = f"patch: {', '.join(update.changed_names)}" if patch.is_patch else "no_change_review"
        with self.store.transaction() as tx:
            tx.append_version_with_diff(result, previous=previous, change_kind=kind, update=update, run_id=item.run_id,
                                        work_item_id=item.work_item_id, reason=reason)
            lifecycle.record_patch(tx, previous, result, policy=self.policy, run_id=item.run_id, work_item_id=item.work_item_id)
            tx.set_work_item_status(item.work_item_id, WorkStatus.DONE)
        LOG.info("result %s work_item_id=%s case_id=%s result_id=%s version=%s", kind.value, item.work_item_id, item.case_id, previous.result_id,
                 result.version)
        return WorkOutcome(item.work_item_id, item.case_id, item.kind.value, WorkStatus.DONE.value, previous.result_id, result.version, kind.value)

    def fail(self, item: WorkItemRow, error: BaseException) -> WorkOutcome:
        """Mark ``item`` failed with the content-free code of ``error`` (its own transaction); never touches a committed result."""
        return self._fail(item, error)

    def _fail(self, item: WorkItemRow, error: BaseException) -> WorkOutcome:
        code = error_code(error)
        LOG.warning("work item failed work_item_id=%s case_id=%s error=%s", item.work_item_id, item.case_id, code)
        try:
            with self.store.transaction() as tx:
                tx.set_work_item_status(item.work_item_id, WorkStatus.FAILED, error=code)
        except DatabaseError as failure:
            LOG.error("work item status not recorded work_item_id=%s error=%s", item.work_item_id, error_code(failure))
        return WorkOutcome(item.work_item_id, item.case_id, item.kind.value, WorkStatus.FAILED.value, item.result_id, None, None, code)
