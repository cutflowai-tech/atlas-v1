"""Deterministic result lifecycle (``REV/09``): ``new``, ``active``, ``updated``, ``cooling``, ``resolved``, ``superseded``.

Python alone decides lifecycle transitions, from the Change Gate's persisted observations and this policy; the model can neither
see nor set a lifecycle status (``analyst``, ``updater``). Every transition is checked against ``TRANSITIONS`` (anything else is an
``InvalidTransition``), written as a result version (``change_kind = lifecycle``, or the patched version for ``patch_accepted``),
and recorded in ``reasoning_lifecycle_transitions`` with its reason code, detail, run, work item and policy version.

| From → to | Reason code | When |
|---|---|---|
| — → new | ``created`` | the analyst's result is stored (version 1) |
| new → active | ``observed_again`` | the case is present in a later run than the one that created the result |
| new/active → updated | ``patch_accepted`` | an update patch is accepted (Phase 08) |
| updated → active | ``update_settled`` | the case is present in a later run than the one that patched the result |
| new/active/updated → cooling | ``not_in_snapshot`` | the case disappeared from the snapshot (never deleted; resolved at once only as a direct fact, below) |
| cooling → active | ``reappeared`` | the case is present again: the same result is reactivated (same ``case_id``, same ``result_id``) |
| cooling → resolved | ``absent_for_configured_runs`` | the case has been absent for ``cooling_runs_to_resolve`` consecutive runs |
| new/active/updated/cooling → resolved | ``direct_fact_no_longer_true`` | only for case types an operator approved as direct facts (none by default): the observed condition (an open-work signal, a data warning) is no longer reported |
| resolved → active | ``reappeared_after_resolution`` | a resolved case is present again: its result is reopened, never duplicated |
| new/active/updated/cooling → superseded | ``superseded`` | a deterministic replacement (``supersede``) names the replacing case and result |

A no-change review and a patch of a result already ``updated`` keep the status (no transition). ``superseded`` is final.

Policy (``LifecyclePolicy``, environment ``ATLAS_REASONING_COOLING_RUNS`` (2–100, default 3) and
``ATLAS_REASONING_DIRECT_FACT_CASE_TYPES`` (comma-separated case types or ``none``; default none: every disappeared case cools; the
candidates are ``open_work_risk`` and ``data_quality``, whose cases report an observed condition rather than a statistical pattern).
A cooling result resolves on a later run in which its case reaches ``cooling_runs_to_resolve`` consecutive absent runs, so a case
that flickers out for fewer runs comes back to the same, never-resolved card.

The sweep applies a run's observations only while that run is the case's latest observation (re-processing an older run never
moves a card backwards), and a card never cools and resolves in the same run (sweeping a run twice changes nothing more).
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas_reasoning.contracts import ReasoningResult
from atlas_reasoning.enums import CaseType, GateAction, LifecycleStatus, ResultChangeKind, WorkKind, WorkStatus
from atlas_reasoning.settings import ReasoningConfigError
from atlas_reasoning.store.repository import NotFound, ReasoningStore, StoreTransaction

LOG = logging.getLogger("atlas_reasoning.lifecycle")

LIFECYCLE_POLICY_VERSION = "lifecycle-v1"

CREATED = "created"
OBSERVED_AGAIN = "observed_again"
PATCH_ACCEPTED = "patch_accepted"
UPDATE_SETTLED = "update_settled"
NOT_IN_SNAPSHOT = "not_in_snapshot"
REAPPEARED = "reappeared"
ABSENT_FOR_CONFIGURED_RUNS = "absent_for_configured_runs"
DIRECT_FACT_NO_LONGER_TRUE = "direct_fact_no_longer_true"
REAPPEARED_AFTER_RESOLUTION = "reappeared_after_resolution"
SUPERSEDED = "superseded"

NEW, ACTIVE, UPDATED, COOLING, RESOLVED, SUPERSEDED_STATUS = (LifecycleStatus.NEW, LifecycleStatus.ACTIVE, LifecycleStatus.UPDATED,
                                                             LifecycleStatus.COOLING, LifecycleStatus.RESOLVED, LifecycleStatus.SUPERSEDED)

# (from, to) -> the reason codes that may cause it. ``None`` is "no result yet". Mirrored by a CHECK in 0101_result_lifecycle.sql.
TRANSITIONS: Mapping[tuple[LifecycleStatus | None, LifecycleStatus], frozenset[str]] = {
    (None, NEW): frozenset({CREATED}),
    (NEW, ACTIVE): frozenset({OBSERVED_AGAIN}),
    (NEW, UPDATED): frozenset({PATCH_ACCEPTED}),
    (ACTIVE, UPDATED): frozenset({PATCH_ACCEPTED}),
    (UPDATED, ACTIVE): frozenset({UPDATE_SETTLED}),
    (NEW, COOLING): frozenset({NOT_IN_SNAPSHOT}),
    (ACTIVE, COOLING): frozenset({NOT_IN_SNAPSHOT}),
    (UPDATED, COOLING): frozenset({NOT_IN_SNAPSHOT}),
    (COOLING, ACTIVE): frozenset({REAPPEARED}),
    (COOLING, RESOLVED): frozenset({ABSENT_FOR_CONFIGURED_RUNS, DIRECT_FACT_NO_LONGER_TRUE}),
    (NEW, RESOLVED): frozenset({DIRECT_FACT_NO_LONGER_TRUE}),
    (ACTIVE, RESOLVED): frozenset({DIRECT_FACT_NO_LONGER_TRUE}),
    (UPDATED, RESOLVED): frozenset({DIRECT_FACT_NO_LONGER_TRUE}),
    (RESOLVED, ACTIVE): frozenset({REAPPEARED_AFTER_RESOLUTION}),
    (NEW, SUPERSEDED_STATUS): frozenset({SUPERSEDED}),
    (ACTIVE, SUPERSEDED_STATUS): frozenset({SUPERSEDED}),
    (UPDATED, SUPERSEDED_STATUS): frozenset({SUPERSEDED}),
    (COOLING, SUPERSEDED_STATUS): frozenset({SUPERSEDED}),
}
# The lifecycle a patched version takes (patches never move a cooling, resolved or superseded result).
AFTER_PATCH = {NEW: UPDATED, ACTIVE: UPDATED, UPDATED: UPDATED}

COOLING_RUNS_ENV = "ATLAS_REASONING_COOLING_RUNS"
DIRECT_FACT_ENV = "ATLAS_REASONING_DIRECT_FACT_CASE_TYPES"
# Case types that may be approved as direct facts; none is approved unless an operator lists it.
DIRECT_FACT_CANDIDATES = frozenset({CaseType.OPEN_WORK_RISK, CaseType.DATA_QUALITY})
DEFAULT_DIRECT_FACT_CASE_TYPES: frozenset[CaseType] = frozenset()


class InvalidTransition(ValueError):
    """A lifecycle transition that ``TRANSITIONS`` does not allow (or allows only for other reasons)."""


@dataclass(frozen=True)
class LifecyclePolicy:
    cooling_runs_to_resolve: int = 3
    direct_fact_case_types: frozenset[CaseType] = field(default_factory=lambda: DEFAULT_DIRECT_FACT_CASE_TYPES)
    version: str = LIFECYCLE_POLICY_VERSION

    def __post_init__(self) -> None:
        if not 2 <= self.cooling_runs_to_resolve <= 100:
            raise ReasoningConfigError(f"{COOLING_RUNS_ENV} must be between 2 and 100: a disappeared case always cools first")

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "cooling_runs_to_resolve": self.cooling_runs_to_resolve,
                "direct_fact_case_types": sorted(case_type.value for case_type in self.direct_fact_case_types)}


def policy_from_env(env: Mapping[str, str] | None = None) -> LifecyclePolicy:
    env = os.environ if env is None else env
    raw_runs = env.get(COOLING_RUNS_ENV, "").strip()
    try:
        runs = int(raw_runs) if raw_runs else 3
    except ValueError:
        raise ReasoningConfigError(f"{COOLING_RUNS_ENV} must be a whole number, not {raw_runs!r}") from None
    raw_types = env.get(DIRECT_FACT_ENV)
    if raw_types is None or not raw_types.strip():
        types = DEFAULT_DIRECT_FACT_CASE_TYPES
    elif raw_types.strip().lower() == "none":
        types = frozenset()
    else:
        try:
            types = frozenset(CaseType(part.strip()) for part in raw_types.split(",") if part.strip())
        except ValueError:
            raise ReasoningConfigError(f"{DIRECT_FACT_ENV} must list case types ({', '.join(t.value for t in CaseType)}) or none") from None
    return LifecyclePolicy(runs, types)


def check_transition(before: LifecycleStatus | None, after: LifecycleStatus, reason: str) -> None:
    allowed = TRANSITIONS.get((before, after))
    if allowed is None:
        raise InvalidTransition(f"{before.value if before else '(none)'} -> {after.value} is not a lifecycle transition")
    if reason not in allowed:
        raise InvalidTransition(f"{before.value if before else '(none)'} -> {after.value} cannot happen for {reason!r} (allowed: {sorted(allowed)})")


@dataclass(frozen=True)
class Decision:
    to: LifecycleStatus
    reason: str
    detail: Mapping[str, Any] = field(default_factory=dict)


def decide(status: LifecycleStatus, action: GateAction, *, case_type: CaseType | str, absent_runs: int, changed_in_this_run: bool,
           policy: LifecyclePolicy) -> Decision | None:
    """The transition one Change Gate observation causes for a result in ``status`` (None: stay). Pure and deterministic.

    ``changed_in_this_run``: the result's current version was written for this run (created or patched): a ``new`` / ``updated``
    badge then stays for this run and settles on the next one."""
    direct = CaseType(case_type) in policy.direct_fact_case_types
    if action == GateAction.DISAPPEARED:
        if direct and (status in (NEW, ACTIVE, UPDATED) or (status == COOLING and not changed_in_this_run)):
            return Decision(RESOLVED, DIRECT_FACT_NO_LONGER_TRUE, {"case_type": str(case_type), "absent_runs": absent_runs})
        if status in (NEW, ACTIVE, UPDATED):
            return Decision(COOLING, NOT_IN_SNAPSHOT, {"absent_runs": absent_runs})
        if status == COOLING and absent_runs >= policy.cooling_runs_to_resolve and not changed_in_this_run:
            return Decision(RESOLVED, ABSENT_FOR_CONFIGURED_RUNS, {"absent_runs": absent_runs, "cooling_runs_to_resolve": policy.cooling_runs_to_resolve})
        return None
    # The case is present (new, unchanged or updated evidence).
    if status == COOLING:
        return Decision(ACTIVE, REAPPEARED, {"gate_action": action.value})
    if status == RESOLVED:
        return Decision(ACTIVE, REAPPEARED_AFTER_RESOLUTION, {"gate_action": action.value})
    if status == NEW and not changed_in_this_run:
        return Decision(ACTIVE, OBSERVED_AGAIN, {})
    if status == UPDATED and not changed_in_this_run:
        return Decision(ACTIVE, UPDATE_SETTLED, {})
    return None


def _later(now: str, previous: str) -> str:
    instant = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    return now if instant(now) >= instant(previous) else previous


def transition_version(result: ReasoningResult, to: LifecycleStatus, *, now: str, superseded_by: Mapping[str, str] | None = None) -> ReasoningResult:
    """The next version of ``result`` carrying only a lifecycle change (every other field identical)."""
    document = result.to_dict()
    document.update(version=result.version + 1, lifecycle_status=to.value, updated_at=_later(now, result.updated_at),
                    superseded_by=dict(superseded_by) if superseded_by is not None else None)
    return ReasoningResult.from_dict(document)


def new_transition_id() -> str:
    return f"lt_{uuid.uuid4().hex}"


# --- applying transitions -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleChange:
    case_id: str
    result_id: str
    from_status: str | None
    to_status: str
    reason: str
    version: int
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "result_id": self.result_id, "from": self.from_status, "to": self.to_status, "reason": self.reason,
                "version": self.version, "detail": dict(self.detail)}


def _record(tx: StoreTransaction, result: ReasoningResult, before: LifecycleStatus | None, reason: str, detail: Mapping[str, Any], policy: LifecyclePolicy,
            run_id: str | None, work_item_id: str | None) -> LifecycleChange:
    check_transition(before, result.lifecycle_status, reason)
    superseded = result.superseded_by
    tx.record_lifecycle_transition(transition_id=new_transition_id(), result_id=result.result_id, case_id=result.case_id, result_version=result.version,
                                   from_status=before.value if before else None, to_status=result.lifecycle_status.value, reason_code=reason,
                                   reason_detail=detail, policy_version=policy.version, created_at=result.updated_at, run_id=run_id,
                                   work_item_id=work_item_id,
                                   superseded_by={"case_id": superseded.case_id, "result_id": superseded.result_id} if superseded else None)
    return LifecycleChange(result.case_id, result.result_id, before.value if before else None, result.lifecycle_status.value, reason, result.version, detail)


def record_creation(tx: StoreTransaction, result: ReasoningResult, *, policy: LifecyclePolicy, run_id: str | None = None,
                    work_item_id: str | None = None) -> LifecycleChange:
    """The ``— → new`` transition of a result just created (version 1)."""
    return _record(tx, result, None, CREATED, {}, policy, run_id, work_item_id)


def record_patch(tx: StoreTransaction, previous: ReasoningResult, patched: ReasoningResult, *, policy: LifecyclePolicy, run_id: str | None = None,
                 work_item_id: str | None = None) -> LifecycleChange | None:
    """The ``→ updated`` transition carried by an accepted patch, when the status changed."""
    if previous.lifecycle_status == patched.lifecycle_status:
        return None
    return _record(tx, patched, previous.lifecycle_status, PATCH_ACCEPTED, {"from_version": previous.version}, policy, run_id, work_item_id)


def after_patch(status: LifecycleStatus) -> LifecycleStatus:
    return AFTER_PATCH.get(status, status)


def apply(tx: StoreTransaction, result: ReasoningResult, to: LifecycleStatus, reason: str, *, policy: LifecyclePolicy, now: str,
          run_id: str | None = None, work_item_id: str | None = None, detail: Mapping[str, Any] | None = None,
          superseded_by: Mapping[str, str] | None = None) -> tuple[ReasoningResult, LifecycleChange]:
    """Move ``result`` to ``to``: a lifecycle version (content unchanged), its diff and the transition record, in ``tx``."""
    check_transition(result.lifecycle_status, to, reason)
    new = transition_version(result, to, now=now, superseded_by=superseded_by)
    tx.append_version_with_diff(new, previous=result, change_kind=ResultChangeKind.LIFECYCLE, run_id=run_id, work_item_id=work_item_id,
                                reason=f"lifecycle: {reason}")
    return new, _record(tx, new, result.lifecycle_status, reason, detail or {}, policy, run_id, work_item_id)


def sweep(store: ReasoningStore, run_id: str, *, policy: LifecyclePolicy, clock: Callable[[], str]) -> list[LifecycleChange]:
    """Apply the lifecycle policy to every case the Change Gate observed in ``run_id`` (one transaction per case, so one case's
    failure never affects another), and close the run's lifecycle work items. Idempotent: sweeping a run twice changes nothing more."""
    changes: list[LifecycleChange] = []
    for observation in store.observations(run_id=run_id):
        case_id = observation["case_id"]
        try:
            with store.transaction() as tx:
                change = _sweep_case(tx, case_id, run_id, observation, policy, clock)
                for item in tx.work_items(case_id=case_id, open_only=True):
                    if item.kind == WorkKind.LIFECYCLE and item.status == WorkStatus.PENDING:
                        tx.set_work_item_status(item.work_item_id, WorkStatus.DONE)
            if change is not None:
                changes.append(change)
        except Exception as error:  # noqa: BLE001 - one case never blocks the others; the next sweep retries it
            LOG.error("lifecycle sweep failed run_id=%s case_id=%s error=%s", run_id, case_id, type(error).__name__)
    return changes


def _sweep_case(tx: StoreTransaction, case_id: str, run_id: str, observation: Mapping[str, Any], policy: LifecyclePolicy,
                clock: Callable[[], str]) -> LifecycleChange | None:
    result = tx.latest_result(case_id)
    if result is None:
        return None
    case = tx.get_case(case_id)
    if case.last_observed_run_id != run_id:
        return None   # a later run has observed the case since: its observation, not this one, decides
    action = GateAction(observation["action"])
    absent_runs = int(observation["reason_detail"].get("absent_runs", 0)) if action == GateAction.DISAPPEARED else 0
    decision = decide(result.lifecycle_status, action, case_type=case.case_type, absent_runs=absent_runs,
                      changed_in_this_run=tx.version_run_id(result.result_id, result.version) == run_id, policy=policy)
    if decision is None:
        return None
    detail = {**decision.detail, "gate_reason": observation["reason_code"]}
    return apply(tx, result, decision.to, decision.reason, policy=policy, now=clock(), run_id=run_id,
                 work_item_id=observation["work_item_id"] if action == GateAction.DISAPPEARED else None, detail=detail)[1]


def supersede(store: ReasoningStore, result_id: str, *, by_result_id: str, policy: LifecyclePolicy, clock: Callable[[], str], run_id: str | None = None,
              detail: Mapping[str, Any] | None = None) -> LifecycleChange:
    """Retire ``result_id`` in favour of an open replacement result (of another case): a deterministic, explicit operation —
    never a model decision. The superseded version names the replacing case and result."""
    with store.transaction() as tx:
        result = tx.get_result(result_id)
        try:
            replacement = tx.get_result(by_result_id)
        except NotFound:
            raise InvalidTransition(f"replacement result {by_result_id} does not exist") from None
        if replacement.result_id == result.result_id:
            raise InvalidTransition("a result cannot supersede itself")
        if replacement.lifecycle_status in (RESOLVED, SUPERSEDED_STATUS):
            raise InvalidTransition(f"replacement result {by_result_id} is {replacement.lifecycle_status.value}, not open")
        return apply(tx, result, SUPERSEDED_STATUS, SUPERSEDED, policy=policy, now=clock(), run_id=run_id, detail=detail or {},
                     superseded_by={"case_id": replacement.case_id, "result_id": replacement.result_id})[1]
