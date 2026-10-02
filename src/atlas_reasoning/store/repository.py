"""Data access for the canonical Reasoning V3 state. All SQL of Reasoning V3 lives in ``atlas_reasoning.store``.

``ReasoningStore.transaction()`` yields a ``StoreTransaction``: every write happens inside one, and everything written in it is
committed together or not at all. Readers on ``ReasoningStore`` open their own short read transaction.

Guarantees enforced here and again by the database (``migrations/0001_reasoning_core.sql``):

- a case's identity (``case_id``, ``identity_key``, dimensions) never changes, and two identity keys never share a ``case_id``;
- each evidence state of a case is stored once; the same fingerprint with different content is refused;
- a result is created together with its first version and evidence links; a new version is appended only on top of the version
  the writer read (optimistic concurrency: a concurrent writer gets ``VersionConflict``, never a lost or duplicated version);
- every stored result version satisfies the reasoning-v1 contract and cites only evidence of its case's stored evidence state;
- history tables are append-only.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from atlas_reasoning import case_identity as identity
from atlas_reasoning.contracts import (
    CLAIM_FIELDS,
    CLAIM_LIST_FIELDS,
    PATCHABLE_FIELDS,
    ContractViolation,
    ReasoningResult,
    ReasoningUpdate,
    result_case_errors,
    update_case_errors,
    update_result_errors,
)
from atlas_reasoning.enums import OPEN_LIFECYCLE, OPEN_WORK, GateAction, LifecycleStatus, ResultChangeKind, RunStatus, WorkKind, WorkStatus
from atlas_reasoning.store.db import Database, DatabaseError

# pg_advisory_xact_lock key serializing Change Gate runs ("atlas reasoning gate").
GATE_LOCK_KEY = 0x41746C6152474154


class StoreError(DatabaseError):
    pass


class NotFound(StoreError):
    pass


class VersionConflict(StoreError):
    """The result moved on since the writer read it; re-read and retry (or drop the stale write)."""


class ResultConflict(StoreError):
    """The case already has an open result."""


class CaseIdentityCollision(StoreError, identity.CaseIdentityCollision):
    """The database already holds this case_id with another identity key, or this identity key under another case_id."""


class EvidenceCollision(StoreError):
    """The same evidence fingerprint was stored with different canonical evidence."""


def _unique_violation() -> type[Exception]:
    import psycopg

    error: type[Exception] = psycopg.errors.UniqueViolation
    return error


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex}"


def new_work_item_id() -> str:
    return f"wi_{uuid.uuid4().hex}"


def new_call_id() -> str:
    return f"call_{uuid.uuid4().hex}"


def _param(value: Any) -> Any:
    """Enums are stored as their values; lists of enums likewise."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, list):
        return [_param(item) for item in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class CaseRow:
    case_id: str
    identity_key: str
    case_type: str
    subject_type: str
    subject_id: str
    topic_key: str
    dimensions: Mapping[str, str]
    last_evidence_fingerprint: str
    presence: str
    consecutive_absent_runs: int
    last_seen_run_id: str
    last_observed_run_id: str


@dataclass(frozen=True)
class WorkItemRow:
    work_item_id: str
    run_id: str
    case_id: str
    kind: WorkKind
    gate_action: GateAction
    status: WorkStatus
    requires_llm: bool
    result_id: str | None
    base_result_version: int | None
    fingerprint_before: str | None
    fingerprint_after: str | None
    material_delta: Mapping[str, Any] | None
    case_document: Mapping[str, Any] | None = None


# Allowed work-item status transitions: new status -> statuses it may come from. Anything else is refused (WorkTransitionError).
WORK_TRANSITIONS = {
    WorkStatus.IN_PROGRESS: (WorkStatus.PENDING,),
    WorkStatus.PENDING: (WorkStatus.IN_PROGRESS,),
    WorkStatus.DONE: (WorkStatus.PENDING, WorkStatus.IN_PROGRESS),
    WorkStatus.FAILED: (WorkStatus.PENDING, WorkStatus.IN_PROGRESS),
    WorkStatus.CANCELLED: (WorkStatus.PENDING,),
}


class WorkTransitionError(StoreError):
    """A work item cannot move to the requested status from its current one."""


@dataclass(frozen=True)
class OpenResult:
    result_id: str
    case_id: str
    version: int
    lifecycle_status: LifecycleStatus
    evidence_fingerprint: str


def _case_row(row: Mapping[str, Any]) -> CaseRow:
    dims = {name: row[name] for name in ("video_type", "workflow_stage", "detector_family", "signal") if row.get(name) is not None}
    return CaseRow(row["case_id"], row["identity_key"], row["case_type"], row["subject_type"], row["subject_id"], row["topic_key"], dims,
                   row["last_evidence_fingerprint"], row["presence"], row["consecutive_absent_runs"], row["last_seen_run_id"], row["last_observed_run_id"])


def _work_row(row: Mapping[str, Any]) -> WorkItemRow:
    return WorkItemRow(row["work_item_id"], row["run_id"], row["case_id"], WorkKind(row["kind"]), GateAction(row["gate_action"]), WorkStatus(row["status"]),
                       row["requires_llm"], row["result_id"], row["base_result_version"], row["fingerprint_before"], row["fingerprint_after"],
                       row["material_delta"], row.get("case_document"))


def citations(result: Mapping[str, Any]) -> dict[str, list[str]]:
    """ref_id -> the result fields citing it."""
    cited: dict[str, set[str]] = {}
    for name in CLAIM_FIELDS:
        for ref in result[name]["evidence_refs"]:
            cited.setdefault(ref, set()).add(name)
    for name in (*CLAIM_LIST_FIELDS, "alternative_explanations", "suggested_investigations"):
        for row in result[name]:
            for ref in row["evidence_refs"]:
                cited.setdefault(ref, set()).add(name)
    return {ref: sorted(fields) for ref, fields in cited.items()}


def version_change_errors(previous: Mapping[str, Any], new: Mapping[str, Any], change_kind: ResultChangeKind,
                          update: Mapping[str, Any] | None) -> list[str]:
    """What a new version may change relative to the previous one, by change kind. Identity and creation never change; a patch
    changes exactly the fields it lists (to exactly the values it carries) and preserves every other patchable field byte for
    byte; a no-change review and a lifecycle version change no patchable field."""
    errors = []
    for name in ("result_id", "case_id", "created_at", "contract_version"):
        if new[name] != previous[name]:
            errors.append(f"IMMUTABLE_FIELD: {name} changed between versions")
    if new["version"] != previous["version"] + 1:
        errors.append(f"VERSION_SEQUENCE: version {new['version']} does not follow {previous['version']}")
    changed = {row["field"]: row["value"] for row in (update or {}).get("changed_fields", [])} if change_kind == ResultChangeKind.PATCHED else {}
    for name in PATCHABLE_FIELDS:
        if name in changed:
            if new[name] != changed[name]:
                errors.append(f"PATCH_NOT_APPLIED: {name} differs from the patch value")
        elif new[name] != previous[name]:
            errors.append(f"UNPATCHED_FIELD_CHANGED: {name} changed without being listed in the update")
    if change_kind == ResultChangeKind.NO_CHANGE_REVIEW and (new["lifecycle_status"], new["superseded_by"]) != (previous["lifecycle_status"], previous["superseded_by"]):
        errors.append("LIFECYCLE_IN_REVIEW: a no-change review does not change the lifecycle")
    return errors


class StoreTransaction:
    """Reads and writes inside one database transaction."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def _exec(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return self.conn.execute(sql, [_param(value) for value in params] if params else None)

    def _one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        row: dict[str, Any] | None = self._exec(sql, params).fetchone()
        return row

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return list(self._exec(sql, params).fetchall())

    # --- runs -------------------------------------------------------------------------------------------------------------

    def create_run(self, *, source_snapshot_id: str, release_id: str | None, upstream_contract_version: str, intelligence_version: str,
                   boundary_version: str, identity_version: str, fingerprint_version: str, run_id: str | None = None) -> str:
        run_id = run_id or new_run_id()
        self._exec("""INSERT INTO reasoning_runs (run_id, source_snapshot_id, release_id, upstream_contract_version, intelligence_version,
                                                         boundary_version, identity_version, fingerprint_version, status)
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                          (run_id, source_snapshot_id, release_id, upstream_contract_version, intelligence_version, boundary_version, identity_version,
                           fingerprint_version, RunStatus.STARTED))
        return run_id

    def set_run_status(self, run_id: str, status: RunStatus, *, counts: Mapping[str, Any] | None = None, error: str | None = None) -> None:
        gated = "now()" if status == RunStatus.GATED else "gated_at"
        finished = "now()" if status in (RunStatus.COMPLETE, RunStatus.PARTIAL, RunStatus.DEGRADED, RunStatus.FAILED) else "finished_at"
        updated = self._exec(f"""UPDATE reasoning_runs SET status = %s, gated_at = {gated}, finished_at = {finished},
                                               counts = COALESCE(%s::jsonb, counts), error = COALESCE(%s, error) WHERE run_id = %s""",
                                    (status, _json(counts) if counts is not None else None, error, run_id))
        if updated.rowcount != 1:
            raise NotFound(f"run {run_id} does not exist")

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM reasoning_runs WHERE run_id = %s", (run_id,))
        if row is None:
            raise NotFound(f"run {run_id} does not exist")
        return row

    def lock_gate(self) -> None:
        """Serialize Change Gate runs for the rest of this transaction."""
        self._exec("SELECT pg_advisory_xact_lock(%s)", (GATE_LOCK_KEY,))

    # --- cases and their evidence ---------------------------------------------------------------------------------------------

    def known_cases(self) -> dict[str, CaseRow]:
        return {row["case_id"]: _case_row(row) for row in self._all("SELECT * FROM reasoning_cases ORDER BY case_id")}

    def get_case(self, case_id: str) -> CaseRow:
        row = self._one("SELECT * FROM reasoning_cases WHERE case_id = %s", (case_id,))
        if row is None:
            raise NotFound(f"case {case_id} does not exist")
        return _case_row(row)

    def insert_case(self, *, case_id: str, identity_version: str, identity_key: str, case_type: str, subject_type: str, subject_id: str, topic_key: str,
                    dimensions: Mapping[str, str], run_id: str, evidence_fingerprint: str) -> None:
        """Register a new case. Refuses a case_id or identity_key that already exists with different identity (collision)."""
        clash = self._one("SELECT case_id, identity_key FROM reasoning_cases WHERE case_id = %s OR identity_key = %s", (case_id, identity_key))
        if clash is not None:
            raise CaseIdentityCollision(f"case {case_id} / identity {identity_key!r} collides with case {clash['case_id']} / {clash['identity_key']!r}")
        self._exec("""INSERT INTO reasoning_cases (case_id, identity_version, identity_key, case_type, subject_type, subject_id, topic_key,
                                                          video_type, workflow_stage, detector_family, signal, first_seen_run_id, last_seen_run_id,
                                                          last_observed_run_id, last_evidence_fingerprint, presence)
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'present')""",
                          (case_id, identity_version, identity_key, case_type, subject_type, subject_id, topic_key, dimensions.get("video_type"),
                           dimensions.get("workflow_stage"), dimensions.get("detector_family"), dimensions.get("signal"), run_id, run_id, run_id,
                           evidence_fingerprint))

    def mark_case_present(self, case_id: str, run_id: str, evidence_fingerprint: str) -> None:
        self._exec("""UPDATE reasoning_cases SET last_seen_run_id = %s, last_observed_run_id = %s, last_evidence_fingerprint = %s,
                                    presence = 'present', absent_since_run_id = NULL, consecutive_absent_runs = 0, updated_at = now()
                             WHERE case_id = %s""", (run_id, run_id, evidence_fingerprint, case_id))

    def mark_case_absent(self, case_id: str, run_id: str) -> int:
        """Record one more run without the case; returns the number of consecutive runs it has been absent."""
        row = self._one("""UPDATE reasoning_cases SET last_observed_run_id = %s, presence = 'absent',
                                  absent_since_run_id = COALESCE(absent_since_run_id, %s), consecutive_absent_runs = consecutive_absent_runs + 1,
                                  updated_at = now()
                           WHERE case_id = %s RETURNING consecutive_absent_runs""", (run_id, run_id, case_id))
        if row is None:
            raise NotFound(f"case {case_id} does not exist")
        return int(row["consecutive_absent_runs"])

    def put_case_evidence(self, *, case_id: str, evidence_fingerprint: str, fingerprint_version: str, canonical_evidence: Mapping[str, Any],
                          case_document: Mapping[str, Any], run_id: str) -> bool:
        """Store one evidence state of a case once; returns True when it was new. The same fingerprint with other content is refused."""
        existing = self._one("SELECT canonical_evidence FROM reasoning_case_evidence WHERE case_id = %s AND evidence_fingerprint = %s",
                             (case_id, evidence_fingerprint))
        if existing is not None:
            if existing["canonical_evidence"] != json.loads(_json(canonical_evidence)):
                raise EvidenceCollision(f"case {case_id}: fingerprint {evidence_fingerprint} already stored with different evidence")
            return False
        self._exec("""INSERT INTO reasoning_case_evidence (case_id, evidence_fingerprint, fingerprint_version, canonical_evidence, case_document,
                                                                  first_seen_run_id)
                             VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)""",
                          (case_id, evidence_fingerprint, fingerprint_version, _json(canonical_evidence), _json(case_document), run_id))
        return True

    def get_case_evidence(self, case_id: str, evidence_fingerprint: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM reasoning_case_evidence WHERE case_id = %s AND evidence_fingerprint = %s", (case_id, evidence_fingerprint))
        if row is None:
            raise NotFound(f"case {case_id} has no evidence state {evidence_fingerprint}")
        return row

    # --- Change Gate decisions and work items ------------------------------------------------------------------------------

    def record_observation(self, *, run_id: str, case_id: str, action: GateAction, reason_code: str, reason_detail: Mapping[str, Any],
                           evidence_fingerprint: str | None, previous_fingerprint: str | None, material_delta: Mapping[str, Any] | None,
                           work_item_id: str | None) -> None:
        self._exec("""INSERT INTO reasoning_case_observations (run_id, case_id, action, reason_code, reason_detail, evidence_fingerprint,
                                                                      previous_fingerprint, material_delta, work_item_id)
                             VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s)""",
                          (run_id, case_id, action, reason_code, _json(reason_detail), evidence_fingerprint, previous_fingerprint,
                           _json(material_delta) if material_delta is not None else None, work_item_id))

    def observations(self, *, run_id: str | None = None, case_id: str | None = None) -> list[dict[str, Any]]:
        if run_id is not None:
            return self._all("SELECT * FROM reasoning_case_observations WHERE run_id = %s ORDER BY case_id", (run_id,))
        return self._all("""SELECT o.* FROM reasoning_case_observations o JOIN reasoning_runs r USING (run_id)
                            WHERE o.case_id = %s ORDER BY r.started_at, o.observed_at""", (case_id,))

    def open_work_item(self, case_id: str, *, requires_llm: bool) -> WorkItemRow | None:
        row = self._one("""SELECT * FROM reasoning_work_items WHERE case_id = %s AND requires_llm = %s AND status = ANY(%s)
                           FOR UPDATE""", (case_id, requires_llm, list(OPEN_WORK)))
        return _work_row(row) if row else None

    def create_work_item(self, *, run_id: str, case_id: str, kind: WorkKind, gate_action: GateAction, result_id: str | None,
                         base_result_version: int | None, fingerprint_before: str | None, fingerprint_after: str | None,
                         material_delta: Mapping[str, Any] | None, supersedes: str | None = None,
                         case_document: Mapping[str, Any] | None = None) -> str:
        """Create a pending work item. LLM work carries the exact case document of the run that created it (its snapshot and
        Intelligence V2 finding IDs). ``supersedes`` closes an older *pending* item of the same case in the same transaction; an
        item already in progress is never superseded."""
        work_item_id = new_work_item_id()
        if supersedes is not None:
            # One open item per case and kind of work (partial unique index): close the old one before inserting its replacement.
            # The superseded_by foreign key is deferred, so it may name the replacement before the replacement row exists.
            closed = self._exec("""UPDATE reasoning_work_items SET status = 'superseded', superseded_by = %s, updated_at = now()
                                   WHERE work_item_id = %s AND status = 'pending'""", (work_item_id, supersedes))
            if closed.rowcount != 1:
                raise WorkTransitionError(f"work item {supersedes} is not pending and cannot be superseded")
        self._exec("""INSERT INTO reasoning_work_items (work_item_id, run_id, case_id, kind, gate_action, status, requires_llm, result_id,
                                                               base_result_version, fingerprint_before, fingerprint_after, material_delta,
                                                               case_document)
                             VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)""",
                          (work_item_id, run_id, case_id, kind, gate_action, kind in (WorkKind.NEW_RESULT, WorkKind.UPDATE_RESULT), result_id,
                           base_result_version, fingerprint_before, fingerprint_after, _json(material_delta) if material_delta is not None else None,
                           _json(case_document) if case_document is not None else None))
        return work_item_id

    def set_work_item_status(self, work_item_id: str, status: WorkStatus, *, error: str | None = None) -> None:
        """Move a work item along ``WORK_TRANSITIONS`` (superseding is only done by ``create_work_item``)."""
        allowed = WORK_TRANSITIONS.get(status)
        if allowed is None:
            raise WorkTransitionError(f"a work item cannot be set to {status} directly")
        updated = self._exec("""UPDATE reasoning_work_items SET status = %s, last_error = COALESCE(%s, last_error),
                                       attempts = attempts + CASE WHEN %s IN ('done', 'failed') THEN 1 ELSE 0 END, updated_at = now()
                                WHERE work_item_id = %s AND status = ANY(%s)""", (status, error, status, work_item_id, list(allowed)))
        if updated.rowcount != 1:
            row = self._one("SELECT status FROM reasoning_work_items WHERE work_item_id = %s", (work_item_id,))
            if row is None:
                raise NotFound(f"work item {work_item_id} does not exist")
            raise WorkTransitionError(f"work item {work_item_id} is {row['status']}; it cannot become {status}")

    def unreasoned_cases(self) -> list[dict[str, Any]]:
        """Present cases whose current evidence has neither an open result reasoned on it nor open LLM work — for example after a
        failed or cancelled work item. The Change Gate never re-creates such work for unchanged evidence (zero LLM work); the
        resume / reliability phase uses this list."""
        return self._all("""SELECT c.case_id, c.last_evidence_fingerprint, r.result_id, v.evidence_fingerprint AS result_fingerprint
                            FROM reasoning_cases c
                            LEFT JOIN reasoning_results r ON r.case_id = c.case_id AND r.lifecycle_status = ANY(%s)
                            LEFT JOIN reasoning_result_versions v ON v.result_id = r.result_id AND v.version = r.current_version
                            WHERE c.presence = 'present'
                              AND v.evidence_fingerprint IS DISTINCT FROM c.last_evidence_fingerprint
                              AND NOT EXISTS (SELECT 1 FROM reasoning_work_items w WHERE w.case_id = c.case_id AND w.requires_llm
                                              AND w.status = ANY(%s))
                            ORDER BY c.case_id""", (list(OPEN_LIFECYCLE), list(OPEN_WORK)))

    def stale_in_progress_work(self, older_than_seconds: float) -> list[WorkItemRow]:
        """LLM work items in progress whose last status change is older than ``older_than_seconds`` (abandoned claims)."""
        return [_work_row(row) for row in self._all("""SELECT * FROM reasoning_work_items WHERE status = 'in_progress' AND requires_llm
                                                         AND updated_at < now() - make_interval(secs => %s) ORDER BY updated_at""",
                                                      (older_than_seconds,))]

    def work_items(self, *, run_id: str | None = None, case_id: str | None = None, open_only: bool = False) -> list[WorkItemRow]:
        clauses: list[str] = []
        params: list[Any] = []
        if run_id is not None:
            clauses.append("run_id = %s")
            params.append(run_id)
        if case_id is not None:
            clauses.append("case_id = %s")
            params.append(case_id)
        if open_only:
            clauses.append("status = ANY(%s)")
            params.append(list(OPEN_WORK))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return [_work_row(row) for row in self._all(f"SELECT * FROM reasoning_work_items {where} ORDER BY created_at, work_item_id", params)]

    # --- results ----------------------------------------------------------------------------------------------------------

    def open_result(self, case_id: str) -> OpenResult | None:
        row = self._one("""SELECT r.result_id, r.case_id, r.current_version, r.lifecycle_status, v.evidence_fingerprint
                           FROM reasoning_results r JOIN reasoning_result_versions v ON v.result_id = r.result_id AND v.version = r.current_version
                           WHERE r.case_id = %s AND r.lifecycle_status = ANY(%s)""", (case_id, list(OPEN_LIFECYCLE)))
        if row is None:
            return None
        return OpenResult(row["result_id"], row["case_id"], row["current_version"], LifecycleStatus(row["lifecycle_status"]), row["evidence_fingerprint"])

    def _validated(self, result: ReasoningResult) -> tuple[dict[str, Any], dict[str, Any]]:
        document = result.to_dict()
        errors = ReasoningResult.errors(document)
        evidence = self._one("SELECT case_document FROM reasoning_case_evidence WHERE case_id = %s AND evidence_fingerprint = %s",
                             (result.case_id, result.evidence_fingerprint))
        if evidence is None:
            raise NotFound(f"case {result.case_id} has no stored evidence state {result.evidence_fingerprint}")
        case_document: dict[str, Any] = evidence["case_document"]
        errors += result_case_errors(document, case_document)
        if errors:
            raise ContractViolation("ReasoningResult", errors)
        return document, case_document

    def _insert_version(self, document: Mapping[str, Any], case_document: Mapping[str, Any], change_kind: ResultChangeKind,
                        update_document: Mapping[str, Any] | None, run_id: str | None, work_item_id: str | None, reason: str | None) -> None:
        meta = document["model_metadata"]
        self._exec("""INSERT INTO reasoning_result_versions (result_id, version, change_kind, document, update_document, lifecycle_status,
                                                                    evidence_fingerprint, source_snapshot_id, provider, model, prompt_version, run_id,
                                                                    work_item_id, reason, created_at)
                             VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                          (document["result_id"], document["version"], change_kind, _json(document),
                           _json(update_document) if update_document is not None else None, document["lifecycle_status"],
                           document["evidence_fingerprint"], document["source_snapshot_id"], meta["provider"], meta["model"],
                           document["prompt_version"], run_id, work_item_id, reason, document["updated_at"]))
        references = {ref["ref_id"]: ref for ref in case_document["current_evidence"]["references"]}
        for ref_id, cited_in in sorted(citations(document).items()):
            ref = references[ref_id]
            self._exec("""INSERT INTO reasoning_evidence_links (result_id, version, ref_id, case_id, evidence_fingerprint, member_key, finding_id,
                                                                       role, evidence_code, monday_item_id, cycle_id, event_ids, cited_in)
                                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                              (document["result_id"], document["version"], ref_id, document["case_id"], document["evidence_fingerprint"],
                               ref["member_key"], ref["finding_id"], ref["role"], ref["evidence_code"], ref["monday_item_id"], ref["cycle_id"],
                               list(ref["event_ids"]), cited_in))

    def create_result(self, result: ReasoningResult, *, run_id: str | None = None, work_item_id: str | None = None) -> None:
        """Insert a new result with its version 1 and evidence links, atomically. The case may have no other open result."""
        document, case_document = self._validated(result)
        if result.version != 1:
            raise ContractViolation("ReasoningResult", [f"VERSION_SEQUENCE: a new result starts at version 1, not {result.version}"])
        self._exec("SELECT case_id FROM reasoning_cases WHERE case_id = %s FOR UPDATE", (result.case_id,))   # serialize creators per case
        if self.open_result(result.case_id) is not None:
            raise ResultConflict(f"case {result.case_id} already has an open result")
        superseded = document["superseded_by"] or {}
        try:
            with self.conn.transaction():
                self._exec("""INSERT INTO reasoning_results (result_id, case_id, current_version, lifecycle_status, superseded_by_case_id,
                                                                    superseded_by_result_id, created_at, updated_at)
                                     VALUES (%s, %s, 1, %s, %s, %s, %s, %s)""",
                                  (result.result_id, result.case_id, result.lifecycle_status, superseded.get("case_id"), superseded.get("result_id"),
                                   result.created_at, result.updated_at))
        except _unique_violation() as error:
            raise ResultConflict(f"case {result.case_id} already has an open result, or result {result.result_id} exists") from error
        self._insert_version(document, case_document, ResultChangeKind.CREATED, None, run_id, work_item_id, "created")

    def append_result_version(self, result: ReasoningResult, *, expected_version: int, change_kind: ResultChangeKind,
                              update: ReasoningUpdate | None = None, run_id: str | None = None, work_item_id: str | None = None,
                              reason: str | None = None) -> None:
        """Append ``result`` as the version after ``expected_version``. Raises ``VersionConflict`` when another writer got there first."""
        if change_kind == ResultChangeKind.CREATED:
            raise ContractViolation("ReasoningResult", ["VERSION_SEQUENCE: use create_result for version 1"])
        if change_kind == ResultChangeKind.LIFECYCLE and update is not None:
            raise ContractViolation("ReasoningUpdate", ["ACTION_MISMATCH: a lifecycle version records no ReasoningUpdate"])
        if change_kind in (ResultChangeKind.PATCHED, ResultChangeKind.NO_CHANGE_REVIEW) and update is None:
            raise ContractViolation("ReasoningUpdate", ["ACTION_MISMATCH: a patched or reviewed version records its ReasoningUpdate"])
        document, case_document = self._validated(result)
        previous_row = self._one("SELECT document FROM reasoning_result_versions WHERE result_id = %s AND version = %s",
                                 (result.result_id, expected_version))
        if previous_row is None:
            raise NotFound(f"result {result.result_id} has no version {expected_version}")
        previous = previous_row["document"]
        update_document = update.to_dict() if update is not None else None
        errors = version_change_errors(previous, document, change_kind, update_document)
        if update_document is not None:
            errors += update_result_errors(update_document, previous) + update_case_errors(update_document, case_document)
            if (change_kind == ResultChangeKind.NO_CHANGE_REVIEW) != (update_document["action"] == "no_change"):
                errors.append("ACTION_MISMATCH: a no-change review records a no_change update; a patch records a patch")
        if errors:
            raise ContractViolation("ReasoningResult", errors)
        superseded = document["superseded_by"] or {}
        moved = self._exec("""UPDATE reasoning_results SET current_version = %s, lifecycle_status = %s, superseded_by_case_id = %s,
                                            superseded_by_result_id = %s, updated_at = %s
                                     WHERE result_id = %s AND current_version = %s""",
                                  (result.version, result.lifecycle_status, superseded.get("case_id"), superseded.get("result_id"), result.updated_at,
                                   result.result_id, expected_version))
        if moved.rowcount != 1:
            raise VersionConflict(f"result {result.result_id} is no longer at version {expected_version}")
        self._insert_version(document, case_document, change_kind, update_document, run_id, work_item_id, reason)

    def append_version_with_diff(self, result: ReasoningResult, *, previous: ReasoningResult, change_kind: ResultChangeKind,
                                 update: ReasoningUpdate | None = None, run_id: str | None = None, work_item_id: str | None = None,
                                 reason: str | None = None) -> dict[str, Any]:
        """Append ``result`` on top of ``previous`` (``append_result_version``) and persist its before/after diff
        (``reasoning_result_diffs``, Phase 08) in the same transaction. Returns the diff."""
        self.append_result_version(result, expected_version=previous.version, change_kind=change_kind, update=update, run_id=run_id,
                                   work_item_id=work_item_id, reason=reason)
        return self.record_result_diff(previous.to_dict(), result.to_dict(), change_kind=change_kind, run_id=run_id, work_item_id=work_item_id)

    def record_result_diff(self, previous: Mapping[str, Any], new: Mapping[str, Any], *, change_kind: ResultChangeKind, run_id: str | None,
                           work_item_id: str | None) -> dict[str, Any]:
        from atlas_reasoning.patch import diff

        changes = diff(previous, new)
        self._exec("""INSERT INTO reasoning_result_diffs (result_id, from_version, to_version, change_kind, changed_fields, field_diffs,
                                                                 provenance_diffs, patch_version, run_id, work_item_id, created_at)
                             VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)""",
                          (new["result_id"], previous["version"], new["version"], change_kind, changes["changed_fields"], _json(changes["fields"]),
                           _json(changes["provenance"]), changes["patch_version"], run_id, work_item_id, new["updated_at"]))
        return changes

    def result_diffs(self, result_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM reasoning_result_diffs WHERE result_id = %s ORDER BY to_version", (result_id,))

    # --- lifecycle (Phase 09) ----------------------------------------------------------------------------------------------

    def record_lifecycle_transition(self, *, transition_id: str, result_id: str, case_id: str, result_version: int, from_status: str | None,
                                    to_status: str, reason_code: str, reason_detail: Mapping[str, Any], policy_version: str, created_at: str,
                                    run_id: str | None = None, work_item_id: str | None = None,
                                    superseded_by: Mapping[str, str] | None = None) -> None:
        """Append one transition to ``reasoning_lifecycle_transitions`` (the database re-checks the transition table)."""
        version = self._one("SELECT lifecycle_status FROM reasoning_result_versions WHERE result_id = %s AND version = %s", (result_id, result_version))
        if version is None or version["lifecycle_status"] != to_status:
            raise ContractViolation("ReasoningResult", [f"LIFECYCLE_MISMATCH: version {result_version} of {result_id} does not carry status {to_status}"])
        self._exec("""INSERT INTO reasoning_lifecycle_transitions (transition_id, result_id, case_id, result_version, from_status, to_status,
                                                                          reason_code, reason_detail, policy_version, run_id, work_item_id,
                                                                          superseded_by_case_id, superseded_by_result_id, created_at)
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)""",
                          (transition_id, result_id, case_id, result_version, from_status, to_status, reason_code, _json(reason_detail), policy_version,
                           run_id, work_item_id, (superseded_by or {}).get("case_id"), (superseded_by or {}).get("result_id"), created_at))

    def lifecycle_transitions(self, *, result_id: str | None = None, case_id: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        column, value = ("result_id", result_id) if result_id is not None else ("case_id", case_id) if case_id is not None else ("run_id", run_id)
        return self._all(f"SELECT * FROM reasoning_lifecycle_transitions WHERE {column} = %s ORDER BY created_at, result_version, transition_id", (value,))

    def latest_result(self, case_id: str) -> ReasoningResult | None:
        """The case's most recent result that is not superseded (open or resolved): the card a reappearing case returns to."""
        row = self._one("""SELECT result_id FROM reasoning_results WHERE case_id = %s AND lifecycle_status <> 'superseded'
                           ORDER BY created_at DESC, result_id DESC LIMIT 1""", (case_id,))
        return self.get_result(row["result_id"]) if row else None

    def version_run_id(self, result_id: str, version: int) -> str | None:
        row = self._one("SELECT run_id FROM reasoning_result_versions WHERE result_id = %s AND version = %s", (result_id, version))
        if row is None:
            raise NotFound(f"result {result_id} has no version {version}")
        run_id: str | None = row["run_id"]
        return run_id

    def get_result(self, result_id: str, version: int | None = None) -> ReasoningResult:
        if version is None:
            row = self._one("""SELECT v.document FROM reasoning_results r JOIN reasoning_result_versions v
                               ON v.result_id = r.result_id AND v.version = r.current_version WHERE r.result_id = %s""", (result_id,))
        else:
            row = self._one("SELECT document FROM reasoning_result_versions WHERE result_id = %s AND version = %s", (result_id, version))
        if row is None:
            raise NotFound(f"result {result_id} (version {version or 'current'}) does not exist")
        return ReasoningResult.from_dict(row["document"])

    def result_history(self, result_id: str) -> list[dict[str, Any]]:
        return self._all("""SELECT version, change_kind, lifecycle_status, evidence_fingerprint, source_snapshot_id, provider, model, prompt_version,
                                   run_id, work_item_id, reason, created_at, document, update_document
                            FROM reasoning_result_versions WHERE result_id = %s ORDER BY version""", (result_id,))

    def evidence_links(self, result_id: str, version: int) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM reasoning_evidence_links WHERE result_id = %s AND version = %s ORDER BY ref_id", (result_id, version))

    # --- provider calls ----------------------------------------------------------------------------------------------------

    def record_llm_call(self, *, request_id: str, provider: str, model: str, purpose: str, status: str, attempts: int, latency_ms: int,
                        started_at: str, finished_at: str, run_id: str | None = None, case_id: str | None = None, work_item_id: str | None = None,
                        prompt_version: str | None = None, source_snapshot_id: str | None = None, evidence_fingerprint: str | None = None,
                        provider_status: str | None = None, error_class: str | None = None, input_tokens: int | None = None,
                        output_tokens: int | None = None, provider_response_id: str | None = None) -> str:
        call_id = new_call_id()
        self._exec("""INSERT INTO llm_calls (call_id, request_id, run_id, case_id, work_item_id, provider, model, prompt_version, source_snapshot_id,
                                                    evidence_fingerprint, purpose, status, provider_status, error_class, attempts, retries, latency_ms,
                                                    input_tokens, output_tokens, provider_response_id, started_at, finished_at)
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                          (call_id, request_id, run_id, case_id, work_item_id, provider, model, prompt_version, source_snapshot_id, evidence_fingerprint,
                           purpose, status, provider_status, error_class, attempts, attempts - 1, latency_ms, input_tokens, output_tokens,
                           provider_response_id, started_at, finished_at))
        return call_id

    def llm_calls(self, *, run_id: str | None = None, request_id: str | None = None) -> list[dict[str, Any]]:
        if request_id is not None:
            return self._all("SELECT * FROM llm_calls WHERE request_id = %s", (request_id,))
        return self._all("SELECT * FROM llm_calls WHERE run_id IS NOT DISTINCT FROM %s ORDER BY started_at, call_id", (run_id,))


class ReasoningStore:
    """The canonical Reasoning V3 state in PostgreSQL."""

    def __init__(self, db: Database) -> None:
        self.db = db

    @contextmanager
    def transaction(self) -> Iterator[StoreTransaction]:
        with self.db.transaction() as conn:
            yield StoreTransaction(conn)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.transaction() as tx:
            return tx.get_run(run_id)

    @contextmanager
    def session_lock(self, key: int) -> Iterator[bool]:
        """A PostgreSQL session advisory lock held for the block on its own connection (no transaction stays open). Yields whether it
        was acquired; never waits. The lock ends with the connection, so a crashed holder never blocks the next one."""
        conn = self.db.connect()
        try:
            conn.autocommit = True
            row = conn.execute("SELECT pg_try_advisory_lock(%s) AS locked", (key,)).fetchone()
            acquired = bool(row and row["locked"])
            try:
                yield acquired
            finally:
                if acquired:
                    conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
        finally:
            conn.close()

    def get_case(self, case_id: str) -> CaseRow:
        with self.transaction() as tx:
            return tx.get_case(case_id)

    def known_cases(self) -> dict[str, CaseRow]:
        with self.transaction() as tx:
            return tx.known_cases()

    def get_result(self, result_id: str, version: int | None = None) -> ReasoningResult:
        with self.transaction() as tx:
            return tx.get_result(result_id, version)

    def result_history(self, result_id: str) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.result_history(result_id)

    def observations(self, *, run_id: str | None = None, case_id: str | None = None) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.observations(run_id=run_id, case_id=case_id)

    def result_diffs(self, result_id: str) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.result_diffs(result_id)

    def lifecycle_transitions(self, *, result_id: str | None = None, case_id: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.lifecycle_transitions(result_id=result_id, case_id=case_id, run_id=run_id)

    def work_items(self, *, run_id: str | None = None, case_id: str | None = None, open_only: bool = False) -> list[WorkItemRow]:
        with self.transaction() as tx:
            return tx.work_items(run_id=run_id, case_id=case_id, open_only=open_only)

    def case_debug(self, case_id: str) -> dict[str, Any]:
        """Everything stored about one case, for the ``case`` debug command."""
        with self.transaction() as tx:
            case = tx.get_case(case_id)
            evidence = tx._all("""SELECT evidence_fingerprint, fingerprint_version, first_seen_run_id, created_at
                                  FROM reasoning_case_evidence WHERE case_id = %s ORDER BY created_at""", (case_id,))
            results = tx._all("SELECT * FROM reasoning_results WHERE case_id = %s ORDER BY created_at", (case_id,))
            return {"case": case.__dict__, "evidence_states": evidence, "observations": tx.observations(case_id=case_id),
                    "work_items": [item.__dict__ for item in tx.work_items(case_id=case_id)], "results": results}
