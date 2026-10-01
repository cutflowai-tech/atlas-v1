"""The Change Gate (``REV/05`` #5–#10): decide, before any LLM call, what each case needs.

For one snapshot (``ReasoningInput``) the gate maps findings to cases (``case_mapping``), builds each case's document and evidence
fingerprint (``case_builder``, ``fingerprint``) and compares it with the case's last observed evidence state in PostgreSQL:

| Decision | When | Work created |
|---|---|---|
| ``new`` | the case_id has never been observed | a ``new_result`` work item (LLM) |
| ``unchanged`` | same fingerprint as last observed | **none** (zero LLM work), also when the case reappears after an absence |
| ``updated`` | different fingerprint | an ``update_result`` work item carrying the exact material delta from the evidence the open result was reasoned on; a ``new_result`` item when the case has no open result yet; nothing when the evidence returned to exactly the open result's state |
| ``disappeared`` | a known case is not in this snapshot | a ``lifecycle`` work item the first time (no LLM; the result is never deleted or resolved here); later absent runs record ``still_absent`` with the count |

Every decision is persisted with its reason code and detail for every known case in every run (``reasoning_case_observations``),
in one transaction with the run, the case and evidence rows and the work items, under an advisory lock so two gates never
interleave. At most one open LLM work item exists per case: newer evidence supersedes a still-pending item (which keeps the
older base, so the delta always starts from what the open result says). Running the same snapshot twice creates no work at all
on the second run.

Phase 07+ use ``case_for_work`` to obtain the exact ``ReasoningCase`` (with previous result and material delta) for a work item.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from atlas_reasoning.case_builder import build_case_document
from atlas_reasoning.case_identity import IDENTITY_VERSION
from atlas_reasoning.case_mapping import CaseMapping, map_cases
from atlas_reasoning.contracts import ContractViolation, ReasoningCase, case_errors
from atlas_reasoning.delta import material_delta, summary
from atlas_reasoning.enums import GateAction, RunStatus, WorkKind, WorkStatus
from atlas_reasoning.fingerprint import FINGERPRINT_VERSION, canonical_evidence
from atlas_reasoning.reasoning_input_boundary import ReasoningInput
from atlas_reasoning.store.repository import ReasoningStore, StoreTransaction, WorkItemRow

GATE_VERSION = "change-gate-v1"

# Reason codes (reasoning_case_observations.reason_code).
FIRST_OBSERVATION = "first_observation"
SAME_EVIDENCE = "same_evidence_fingerprint"
REAPPEARED_SAME_EVIDENCE = "reappeared_same_evidence"
EVIDENCE_CHANGED = "evidence_changed"
REAPPEARED_CHANGED = "reappeared_evidence_changed"
NOT_IN_SNAPSHOT = "not_in_snapshot"
STILL_ABSENT = "still_absent"


@dataclass(frozen=True)
class GateDecision:
    case_id: str
    identity_key: str
    action: GateAction
    reason_code: str
    evidence_fingerprint: str | None
    previous_fingerprint: str | None
    work_item_id: str | None
    work_kind: WorkKind | None
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GateReport:
    run_id: str
    source_snapshot_id: str
    decisions: tuple[GateDecision, ...]
    unmapped: tuple[Mapping[str, str], ...]
    warnings: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        counts = {action.value: 0 for action in GateAction}
        for decision in self.decisions:
            counts[decision.action.value] += 1
        counts["llm_work_items"] = len(self.llm_work_item_ids)
        counts["lifecycle_work_items"] = sum(1 for d in self.decisions if d.work_kind == WorkKind.LIFECYCLE)
        counts["unmapped_findings"] = len(self.unmapped)
        return counts

    @property
    def llm_work_item_ids(self) -> tuple[str, ...]:
        return tuple(d.work_item_id for d in self.decisions if d.work_item_id and d.work_kind in (WorkKind.NEW_RESULT, WorkKind.UPDATE_RESULT))

    def to_dict(self) -> dict[str, Any]:
        return {"gate_version": GATE_VERSION, "run_id": self.run_id, "source_snapshot_id": self.source_snapshot_id, "counts": self.counts,
                "decisions": [{"case_id": d.case_id, "identity_key": d.identity_key, "action": d.action.value, "reason_code": d.reason_code,
                               "evidence_fingerprint": d.evidence_fingerprint, "previous_fingerprint": d.previous_fingerprint,
                               "work_item_id": d.work_item_id, "work_kind": d.work_kind.value if d.work_kind else None, "detail": dict(d.detail)}
                              for d in self.decisions],
                "unmapped": [dict(row) for row in self.unmapped], "warnings": list(self.warnings)}


@dataclass(frozen=True)
class PreparedCase:
    """A case of this snapshot, ready for the gate: base document, canonical evidence and fingerprint."""

    document: Mapping[str, Any]
    canonical: Mapping[str, Any]

    @property
    def case_id(self) -> str:
        return str(self.document["case_id"])

    @property
    def fingerprint(self) -> str:
        return str(self.document["evidence_fingerprint"])


def prepare_cases(payload: ReasoningInput, created_at: str) -> tuple[CaseMapping, dict[str, PreparedCase]]:
    """Map and build every case of a snapshot (no database). Each document is validated against reasoning-v1."""
    mapping = map_cases(payload)
    prepared = {}
    for candidate in mapping.candidates:
        document = build_case_document(candidate, payload, created_at)
        errors = case_errors(document)
        if errors:
            raise ContractViolation("ReasoningCase", errors)
        prepared[candidate.case_id] = PreparedCase(document, canonical_evidence(document))
    return mapping, prepared


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _changed_work(tx: StoreTransaction, run_id: str, case: PreparedCase, gate_action: GateAction) -> tuple[str | None, WorkKind | None, dict[str, Any]]:
    """Work for a case whose evidence moved: relative to what its open result says, superseding a still-pending item."""
    pending = tx.open_work_item(case.case_id, requires_llm=True)
    result = tx.open_result(case.case_id)
    if result is None:
        kind, base_fp, base_version, result_id = WorkKind.NEW_RESULT, None, None, None
    else:
        kind, base_fp, base_version, result_id = WorkKind.UPDATE_RESULT, result.evidence_fingerprint, result.version, result.result_id
    if pending is not None and pending.status == WorkStatus.IN_PROGRESS:
        # Never pull work out from under a running worker: the resume phase picks up the newer evidence afterwards
        # (StoreTransaction.unreasoned_cases).
        return None, None, {"work": "deferred: an item for this case is in progress", "in_progress_work_item_id": pending.work_item_id}
    if base_fp == case.fingerprint:
        if pending is not None:
            tx.set_work_item_status(pending.work_item_id, WorkStatus.CANCELLED, error="evidence returned to the open result's state")
        return None, None, {"work": "none: evidence equals the open result's evidence", "result_id": result_id}
    delta = None
    if base_fp is not None:
        base = tx.get_case_evidence(case.case_id, base_fp)["canonical_evidence"]
        delta = material_delta(base, case.canonical, fingerprint_before=base_fp, fingerprint_after=case.fingerprint)
    work_item_id = tx.create_work_item(run_id=run_id, case_id=case.case_id, kind=kind, gate_action=gate_action, result_id=result_id,
                                       base_result_version=base_version, fingerprint_before=base_fp, fingerprint_after=case.fingerprint,
                                       material_delta=delta, supersedes=pending.work_item_id if pending else None, case_document=case.document)
    detail = {"work": kind.value, "result_id": result_id, "base_fingerprint": base_fp}
    if pending is not None:
        detail["superseded_work_item_id"] = pending.work_item_id
    return work_item_id, kind, detail


def run_gate(payload: ReasoningInput, store: ReasoningStore, *, now: str | None = None, run_id: str | None = None) -> GateReport:
    """Run the Change Gate for one snapshot and persist every decision. Deterministic for a given snapshot and stored state."""
    created_at = now or _now()
    mapping, prepared = prepare_cases(payload, created_at)
    decisions: list[GateDecision] = []
    with store.transaction() as tx:
        tx.lock_gate()
        run_id = tx.create_run(source_snapshot_id=payload.snapshot.source_snapshot_id, release_id=payload.snapshot.release_id,
                               upstream_contract_version=payload.contract.executable_contract_version,
                               intelligence_version=payload.contract.intelligence_version, boundary_version=payload.contract.boundary_version,
                               identity_version=IDENTITY_VERSION, fingerprint_version=FINGERPRINT_VERSION, run_id=run_id)
        known = tx.known_cases()
        for case_id, case in sorted(prepared.items()):
            row = known.get(case_id)
            identity = case.document
            if row is None:
                tx.insert_case(case_id=case_id, identity_version=identity["identity_version"], identity_key=identity["identity_key"],
                               case_type=identity["case_type"], subject_type=identity["subject_type"], subject_id=identity["subject_id"],
                               topic_key=identity["topic_key"], dimensions=identity["identity_dimensions"], run_id=run_id,
                               evidence_fingerprint=case.fingerprint)
                tx.put_case_evidence(case_id=case_id, evidence_fingerprint=case.fingerprint, fingerprint_version=FINGERPRINT_VERSION,
                                     canonical_evidence=case.canonical, case_document=case.document, run_id=run_id)
                work_item_id, kind, detail = _changed_work(tx, run_id, case, GateAction.NEW)
                decision = GateDecision(case_id, identity["identity_key"], GateAction.NEW, FIRST_OBSERVATION, case.fingerprint, None, work_item_id, kind, detail)
            elif row.identity_key != identity["identity_key"]:
                raise ContractViolation("ReasoningCase", [f"CASE_ID_MISMATCH: {case_id} is stored with identity {row.identity_key!r}"])
            else:
                tx.put_case_evidence(case_id=case_id, evidence_fingerprint=case.fingerprint, fingerprint_version=FINGERPRINT_VERSION,
                                     canonical_evidence=case.canonical, case_document=case.document, run_id=run_id)
                reappeared = row.presence == "absent"
                previous = row.last_evidence_fingerprint
                if previous == case.fingerprint:
                    detail = {"absent_runs": row.consecutive_absent_runs} if reappeared else {}
                    decision = GateDecision(case_id, row.identity_key, GateAction.UNCHANGED, REAPPEARED_SAME_EVIDENCE if reappeared else SAME_EVIDENCE,
                                            case.fingerprint, previous, None, None, detail)
                else:
                    observed = tx.get_case_evidence(case_id, previous)["canonical_evidence"]
                    delta = material_delta(observed, case.canonical, fingerprint_before=previous, fingerprint_after=case.fingerprint)
                    work_item_id, kind, detail = _changed_work(tx, run_id, case, GateAction.UPDATED)
                    detail = {**detail, "delta": summary(delta), **({"absent_runs": row.consecutive_absent_runs} if reappeared else {})}
                    decision = GateDecision(case_id, row.identity_key, GateAction.UPDATED, REAPPEARED_CHANGED if reappeared else EVIDENCE_CHANGED,
                                            case.fingerprint, previous, work_item_id, kind, {**detail, "material_delta": delta})
                tx.mark_case_present(case_id, run_id, case.fingerprint)
                stale = tx.open_work_item(case_id, requires_llm=False)
                if stale is not None and stale.status == WorkStatus.PENDING:
                    tx.set_work_item_status(stale.work_item_id, WorkStatus.CANCELLED, error=f"case present again in run {run_id}")
                    decision = dataclasses.replace(decision, detail={**decision.detail, "cancelled_lifecycle_work_item_id": stale.work_item_id})
            _record(tx, run_id, decision)
            decisions.append(decision)
        for case_id, row in sorted(known.items()):
            if case_id in prepared:
                continue
            absent_runs = tx.mark_case_absent(case_id, run_id)
            work_item_id, kind = None, None
            if row.presence == "present":
                reason = NOT_IN_SNAPSHOT
                if tx.open_work_item(case_id, requires_llm=False) is None:
                    result = tx.open_result(case_id)
                    work_item_id = tx.create_work_item(run_id=run_id, case_id=case_id, kind=WorkKind.LIFECYCLE, gate_action=GateAction.DISAPPEARED,
                                                       result_id=result.result_id if result else None,
                                                       base_result_version=result.version if result else None, fingerprint_before=None,
                                                       fingerprint_after=None, material_delta=None)
                    kind = WorkKind.LIFECYCLE
            else:
                reason = STILL_ABSENT
            decision = GateDecision(case_id, row.identity_key, GateAction.DISAPPEARED, reason, None, row.last_evidence_fingerprint, work_item_id, kind,
                                    {"absent_runs": absent_runs})
            _record(tx, run_id, decision)
            decisions.append(decision)
        report = GateReport(run_id, payload.snapshot.source_snapshot_id, tuple(decisions), mapping.unmapped, mapping.warnings)
        tx.set_run_status(run_id, RunStatus.GATED, counts=report.counts)
    return report


def _record(tx: StoreTransaction, run_id: str, decision: GateDecision) -> None:
    detail = {key: value for key, value in decision.detail.items() if key != "material_delta"}
    tx.record_observation(run_id=run_id, case_id=decision.case_id, action=decision.action, reason_code=decision.reason_code, reason_detail=detail,
                          evidence_fingerprint=decision.evidence_fingerprint, previous_fingerprint=decision.previous_fingerprint,
                          material_delta=decision.detail.get("material_delta"), work_item_id=decision.work_item_id)


def case_for_work(tx: StoreTransaction, work_item: WorkItemRow) -> ReasoningCase:
    """The exact ReasoningCase a work item asks to reason about: the evidence state it targets, with the previous result and the
    material delta from the evidence that result was reasoned on (Phase 07 analyst / Phase 08 update input). The document is the
    one built in the run that created the item, so its snapshot ID and finding IDs resolve in that run's Intelligence V2 document."""
    if work_item.fingerprint_after is None or work_item.case_document is None:
        raise ValueError(f"work item {work_item.work_item_id} ({work_item.kind}) has no evidence state to reason about")
    document = dict(work_item.case_document)   # this run's document: its snapshot and Intelligence V2 finding IDs
    document["previous_result_id"] = work_item.result_id
    document["previous_result_version"] = work_item.base_result_version
    document["material_delta"] = dict(work_item.material_delta) if work_item.material_delta is not None else None
    return ReasoningCase.from_dict(document)
