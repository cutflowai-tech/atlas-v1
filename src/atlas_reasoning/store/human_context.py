"""SQL for the human-context layer (Phases 11-14): memory injections, manager notes, questions, answers and teachings.

Every function takes a ``StoreTransaction``; the caller decides the transaction boundary. Canonical rows are written here and only
here; memory copies are written by ``memory_sync`` after the canonical transaction commits.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from atlas_reasoning.store.repository import NotFound, StoreTransaction


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# --- cases and results ------------------------------------------------------------------------------------------------------


def case_result_ids(tx: StoreTransaction, case_id: str) -> list[str]:
    """Every result ever produced for a case (open or closed), oldest first."""
    return [row["result_id"] for row in tx._all("SELECT result_id FROM reasoning_results WHERE case_id = %s ORDER BY created_at, result_id",
                                                (case_id,))]


def result_case(tx: StoreTransaction, result_id: str) -> dict[str, Any]:
    """The result's identity row joined with its case's subject; ``NotFound`` when the result does not exist."""
    row = tx._one("""SELECT r.result_id, r.case_id, r.current_version, r.lifecycle_status, c.subject_type, c.subject_id, c.case_type, c.video_type,
                            c.workflow_stage
                     FROM reasoning_results r JOIN reasoning_cases c USING (case_id) WHERE r.result_id = %s""", (result_id,))
    if row is None:
        raise NotFound(f"result {result_id} does not exist")
    return row


def live_sync_row(tx: StoreTransaction, memory_ref: str, session_key: str) -> dict[str, Any] | None:
    """The live (synced, not retired) sync-log row that produced a memory copy, if any."""
    return tx._one("""SELECT * FROM memory_sync_log WHERE external_ref = %s AND session_key = %s AND operation = 'write' AND status = 'synced'
                      AND retired_at IS NULL""", (memory_ref, session_key))


# --- memory injections (Phase 11) -------------------------------------------------------------------------------------------


def insert_injection(tx: StoreTransaction, *, case_id: str, result_id: str | None, run_id: str | None, work_item_id: str | None,
                     request_id: str | None, purpose: str, assembler_version: str, memory_status: str, degraded_reason: str | None,
                     sessions: Sequence[str], budget: Mapping[str, Any], selected: Sequence[Mapping[str, Any]], dropped: Mapping[str, Any],
                     context_sha256: str) -> str:
    injection_id = new_id("mi")
    tx._exec("""INSERT INTO memory_injections (injection_id, case_id, result_id, run_id, work_item_id, request_id, purpose, assembler_version,
                                               memory_status, degraded_reason, sessions, budget, selected, dropped, context_sha256)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)""",
             (injection_id, case_id, result_id, run_id, work_item_id, request_id, purpose, assembler_version, memory_status, degraded_reason,
              list(sessions), _json(budget), _json(list(selected)), _json(dropped), context_sha256))
    return injection_id


def injections(tx: StoreTransaction, *, case_id: str | None = None, request_id: str | None = None) -> list[dict[str, Any]]:
    if request_id is not None:
        return tx._all("SELECT * FROM memory_injections WHERE request_id = %s", (request_id,))
    return tx._all("SELECT * FROM memory_injections WHERE case_id = %s ORDER BY created_at, injection_id", (case_id,))


def iso(value: Any) -> str | None:
    """A timestamptz as ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` (UTC), the form every human-context API returns."""
    if value is None:
        return None
    from datetime import UTC

    return str(value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))


# --- manager notes (Phase 12) -------------------------------------------------------------------------------------------------


def insert_note(tx: StoreTransaction, *, result_id: str, case_id: str, author: str | None, body: str) -> dict[str, Any]:
    note_id = new_id("mn")
    row = tx._one("""INSERT INTO manager_notes (note_id, result_id, case_id, author, body) VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                  (note_id, result_id, case_id, author, body))
    assert row is not None
    tx._exec("INSERT INTO manager_note_revisions (note_id, revision, body, author, recorded_at) VALUES (%s, 1, %s, %s, %s)",
             (note_id, body, author, row["updated_at"]))
    return row


def update_note(tx: StoreTransaction, *, note_id: str, expected_revision: int, author: str | None, body: str) -> dict[str, Any] | None:
    """The updated row, or ``None`` when the note is not at ``expected_revision`` (a concurrent edit)."""
    row = tx._one("""UPDATE manager_notes SET body = %s, author = %s, revision = revision + 1, updated_at = greatest(now(), updated_at)
                     WHERE note_id = %s AND revision = %s RETURNING *""", (body, author, note_id, expected_revision))
    if row is not None:
        tx._exec("INSERT INTO manager_note_revisions (note_id, revision, body, author, recorded_at) VALUES (%s, %s, %s, %s, %s)",
                 (note_id, row["revision"], body, author, row["updated_at"]))
    return row


def get_note(tx: StoreTransaction, note_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = tx._one(f"SELECT * FROM manager_notes WHERE note_id = %s{' FOR UPDATE' if lock else ''}", (note_id,))
    if row is None:
        raise NotFound(f"note {note_id} does not exist")
    return row


def notes_for_results(tx: StoreTransaction, result_ids: Sequence[str]) -> list[dict[str, Any]]:
    return tx._all("SELECT * FROM manager_notes WHERE result_id = ANY(%s) ORDER BY created_at, note_id", (list(result_ids),))


def note_revisions(tx: StoreTransaction, note_id: str) -> list[dict[str, Any]]:
    return tx._all("SELECT * FROM manager_note_revisions WHERE note_id = %s ORDER BY revision", (note_id,))
