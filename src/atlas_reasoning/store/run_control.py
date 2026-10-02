"""SQL for Phase 18-A run orchestration (migration ``0600_run_control.sql``): orchestration passes, their atomic call budget, and the
retry lineage of resumed work. Every function takes a ``StoreTransaction``; the caller decides the transaction boundary.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from atlas_reasoning.enums import GateAction, WorkKind
from atlas_reasoning.store.repository import NotFound, StoreTransaction, WorkItemRow, _work_row


def new_pass_id() -> str:
    return f"rp_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


# --- passes -------------------------------------------------------------------------------------------------------------------


def interrupt_open_passes(tx: StoreTransaction, run_id: str) -> list[str]:
    """Close the run's passes left open by a process that died (called under the engine lock, so no live pass can be open)."""
    rows = tx._all("""UPDATE reasoning_run_passes SET outcome = 'interrupted', finished_at = now()
                      WHERE run_id = %s AND finished_at IS NULL RETURNING pass_id""", (run_id,))
    return [row["pass_id"] for row in rows]


def open_pass(tx: StoreTransaction, *, run_id: str, kind: str, policy_version: str, call_budget: int | None) -> str:
    """Start a pass. The partial unique index refuses a second open pass of the same run (a concurrent orchestrator)."""
    pass_id = new_pass_id()
    tx._exec("""INSERT INTO reasoning_run_passes (pass_id, run_id, kind, policy_version, call_budget) VALUES (%s, %s, %s, %s, %s)""",
             (pass_id, run_id, kind, policy_version, call_budget))
    return pass_id


def release_call(tx: StoreTransaction, pass_id: str) -> None:
    """Give back one unit whose call never reached the provider (refused by the breaker or a budget before any request)."""
    tx._exec("UPDATE reasoning_run_passes SET calls_used = calls_used - 1 WHERE pass_id = %s AND calls_used > 0", (pass_id,))


def acquire_call(tx: StoreTransaction, pass_id: str) -> bool:
    """Atomically spend one provider call of the pass's budget; False when it is exhausted (the CHECK makes overspending impossible)."""
    row = tx._one("""UPDATE reasoning_run_passes SET calls_used = calls_used + 1
                     WHERE pass_id = %s AND finished_at IS NULL AND (call_budget IS NULL OR calls_used < call_budget) RETURNING calls_used""",
                  (pass_id,))
    return row is not None


def remaining_calls(tx: StoreTransaction, pass_id: str) -> int | None:
    row = tx._one("SELECT call_budget, calls_used FROM reasoning_run_passes WHERE pass_id = %s", (pass_id,))
    if row is None:
        raise NotFound(f"pass {pass_id} does not exist")
    return None if row["call_budget"] is None else int(row["call_budget"]) - int(row["calls_used"])


def record_admission(tx: StoreTransaction, pass_id: str, *, admitted: int, deferred: int, retries: int) -> None:
    tx._exec("UPDATE reasoning_run_passes SET admitted = %s, deferred = %s, retries = %s WHERE pass_id = %s", (admitted, deferred, retries, pass_id))


def finish_pass(tx: StoreTransaction, pass_id: str, *, run_status: str, reasons: Sequence[str], counts: Mapping[str, Any]) -> None:
    tx._exec("""UPDATE reasoning_run_passes SET run_status = %s, reasons = %s, counts = %s::jsonb, outcome = 'finished', finished_at = now()
                WHERE pass_id = %s AND finished_at IS NULL""", (run_status, list(reasons), _json(counts), pass_id))


def set_run_status(tx: StoreTransaction, run_id: str, status: str, reasons: Sequence[str]) -> None:
    """The run's final status after a pass and its reason codes (cleared when there are none); the gate's counts are kept."""
    updated = tx._exec("UPDATE reasoning_runs SET status = %s, error = %s, finished_at = now() WHERE run_id = %s",
                       (status, ",".join(reasons) or None, run_id))
    if updated.rowcount != 1:
        raise NotFound(f"run {run_id} does not exist")


def passes(tx: StoreTransaction, run_id: str) -> list[dict[str, Any]]:
    return tx._all("SELECT * FROM reasoning_run_passes WHERE run_id = %s ORDER BY started_at, pass_id", (run_id,))


# --- work state ---------------------------------------------------------------------------------------------------------------


def latest_llm_items(tx: StoreTransaction, run_ids: Sequence[str]) -> list[WorkItemRow]:
    """Per case, the newest LLM work item belonging to one of ``run_ids`` (a resumed case's retry item supersedes its failed one)."""
    rows = tx._all("""SELECT DISTINCT ON (case_id) * FROM reasoning_work_items WHERE requires_llm AND run_id = ANY(%s)
                      ORDER BY case_id, created_at DESC, work_item_id DESC""", (list(run_ids),))
    return [_work_row(row) for row in rows]


def has_usable_result(tx: StoreTransaction, run_id: str) -> bool:
    """Whether any case the run observed has a usable (open) canonical result — what management can still rely on after a failure."""
    row = tx._one("""SELECT 1 FROM reasoning_case_observations o JOIN reasoning_results r ON r.case_id = o.case_id
                     WHERE o.run_id = %s AND r.lifecycle_status IN ('new', 'active', 'updated', 'cooling') LIMIT 1""", (run_id,))
    return row is not None


def memory_degraded(tx: StoreTransaction, run_id: str) -> bool:
    """Whether any reasoning call of the run (any pass) ran with degraded memory: those results were reasoned without it."""
    row = tx._one("""SELECT 1 FROM memory_injections WHERE run_id = %s AND memory_status IN ('degraded', 'unavailable') LIMIT 1""", (run_id,))
    return row is not None


def carried_reasons(tx: StoreTransaction, run_id: str, kept: Sequence[str]) -> set[str]:
    """Degradation reasons of earlier finished passes of the run that a later pass cannot repair (a committed follow-up failure)."""
    rows = tx._all("SELECT DISTINCT unnest(reasons) AS reason FROM reasoning_run_passes WHERE run_id = %s AND outcome = 'finished'", (run_id,))
    return {row["reason"] for row in rows} & set(kept)


def open_llm_items(tx: StoreTransaction, run_id: str) -> int:
    row = tx._one("SELECT count(*) AS n FROM reasoning_work_items WHERE run_id = %s AND requires_llm AND status IN ('pending', 'in_progress')", (run_id,))
    return int(row["n"]) if row else 0


# --- resume -------------------------------------------------------------------------------------------------------------------


def retry_candidates(tx: StoreTransaction, run_id: str, failed_work_item_id: str | None = None) -> list[dict[str, Any]]:
    """Present cases of ``run_id`` whose current evidence is not reasoned, with no open LLM work, whose latest LLM item (of any run)
    belongs to this run and failed on that same evidence state — the only work resume may retry. ``attempt`` = items so far for that
    evidence state (the first plus its retries: the lineage sequence); ``spent`` = those that failed after reaching the provider (a
    refusal — ``REFUSALS``: breaker or budget, no request sent — spends no attempt). The same predicate decides whether a run has
    resumable failures."""
    return tx._all("""
        SELECT w.*, c.last_evidence_fingerprint,
               1 + (SELECT count(*) FROM reasoning_work_retries r WHERE r.case_id = w.case_id AND r.evidence_fingerprint = w.fingerprint_after) AS attempt,
               (CASE WHEN w.last_error = ANY(%s) THEN 0 ELSE 1 END)
               + (SELECT count(*) FROM reasoning_work_retries r WHERE r.case_id = w.case_id AND r.evidence_fingerprint = w.fingerprint_after
                    AND NOT (r.failure = ANY(%s))) AS spent
        FROM reasoning_cases c
        JOIN LATERAL (SELECT * FROM reasoning_work_items i WHERE i.case_id = c.case_id AND i.requires_llm
                      ORDER BY i.created_at DESC, i.work_item_id DESC LIMIT 1) w ON true
        WHERE c.presence = 'present' AND w.run_id = %s AND w.status = 'failed' AND w.fingerprint_after = c.last_evidence_fingerprint
          AND NOT EXISTS (SELECT 1 FROM reasoning_work_retries r WHERE r.failed_work_item_id = w.work_item_id)
          AND NOT EXISTS (SELECT 1 FROM reasoning_work_items o WHERE o.case_id = c.case_id AND o.requires_llm AND o.status IN ('pending', 'in_progress'))
          AND NOT EXISTS (SELECT 1 FROM reasoning_results r JOIN reasoning_result_versions v ON v.result_id = r.result_id AND v.version = r.current_version
                          WHERE r.case_id = c.case_id AND r.lifecycle_status IN ('new', 'active', 'updated', 'cooling')
                            AND v.evidence_fingerprint = c.last_evidence_fingerprint)
          AND (%s::text IS NULL OR w.work_item_id = %s::text)
        ORDER BY w.case_id""", (list(REFUSALS), list(REFUSALS), run_id, failed_work_item_id, failed_work_item_id))


# Failures of calls refused before any provider request (Phase 18-B ``reliability.CallRefused``): they spend no retry attempt.
REFUSALS = ("provider:circuit_open", "provider:budget_exhausted")
# Hard bound on a lineage (refusals included), so repeated resumes during a long outage cannot grow without limit.
LINEAGE_FACTOR = 4


def eligible(row: Mapping[str, Any], max_attempts: int) -> bool:
    """Attempts left: fewer than ``max_attempts`` spent, and the lineage below its hard bound."""
    return int(row["spent"]) < max_attempts and int(row["attempt"]) < max_attempts * LINEAGE_FACTOR


def create_retry(tx: StoreTransaction, run_id: str, failed_work_item_id: str, *, max_attempts: int, pass_id: str) -> str | None:
    """A pending copy of a failed LLM work item (same run, case, kind, gate action, evidence state, base and case document) and its
    lineage row — or None when it is no longer eligible. Serialized with the Change Gate (its transaction lock) and re-checked inside
    this transaction, so a concurrent gate run can never be raced into stale or duplicate work; the unique constraints make a second
    retry of the same failed item, or of the same attempt, impossible."""
    tx.lock_gate()
    rows = retry_candidates(tx, run_id, failed_work_item_id)
    if not rows or not eligible(rows[0], max_attempts):
        return None
    failed = rows[0]
    attempt = int(failed["attempt"]) + 1
    item = _work_row(failed)
    work_item_id = tx.create_work_item(run_id=item.run_id, case_id=item.case_id, kind=WorkKind(item.kind), gate_action=GateAction(item.gate_action),
                                       result_id=item.result_id, base_result_version=item.base_result_version, fingerprint_before=item.fingerprint_before,
                                       fingerprint_after=item.fingerprint_after, material_delta=item.material_delta, case_document=item.case_document)
    tx._exec("""INSERT INTO reasoning_work_retries (retry_work_item_id, failed_work_item_id, case_id, evidence_fingerprint, attempt, failure, pass_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
             (work_item_id, item.work_item_id, item.case_id, item.fingerprint_after, attempt, failed["last_error"] or "unknown", pass_id))
    return work_item_id


def retries(tx: StoreTransaction, *, case_id: str | None = None) -> list[dict[str, Any]]:
    if case_id is None:
        return tx._all("SELECT * FROM reasoning_work_retries ORDER BY created_at, retry_work_item_id")
    return tx._all("SELECT * FROM reasoning_work_retries WHERE case_id = %s ORDER BY attempt", (case_id,))

