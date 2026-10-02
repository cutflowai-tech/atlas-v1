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


# --- Atlas questions and management answers (Phase 13) ------------------------------------------------------------------------


def latest_question(tx: StoreTransaction, case_id: str, dedup_key: str) -> dict[str, Any] | None:
    """The open question with this key if any, else the most recently resolved one."""
    return tx._one("""SELECT * FROM atlas_questions WHERE case_id = %s AND dedup_key = %s
                      ORDER BY (state = 'open') DESC, updated_at DESC, question_id LIMIT 1 FOR UPDATE""", (case_id, dedup_key))


def insert_question(tx: StoreTransaction, *, case_id: str, result_id: str, result_version: int, dedup_key: str, text: str, reason: str,
                    expected_context_type: str, run_id: str | None) -> dict[str, Any] | None:
    """A new open question, or ``None`` when an open question with the same key already exists (a concurrent run won)."""
    return tx._one("""INSERT INTO atlas_questions (question_id, case_id, result_id, result_version, dedup_key, question_text, reason,
                                                   expected_context_type, state, asked_in_run_id, last_asked_run_id)
                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'open', %s, %s)
                      ON CONFLICT (case_id, dedup_key) WHERE state = 'open' DO NOTHING RETURNING *""",
                   (new_id("aq"), case_id, result_id, result_version, dedup_key, text, reason, expected_context_type, run_id, run_id))


def repeat_question(tx: StoreTransaction, question_id: str, *, result_id: str, result_version: int, run_id: str | None) -> dict[str, Any]:
    row = tx._one("""UPDATE atlas_questions SET ask_count = ask_count + 1, result_id = %s, result_version = %s, last_asked_run_id = %s,
                            last_asked_at = now(), updated_at = now()
                     WHERE question_id = %s RETURNING *""", (result_id, result_version, run_id, question_id))
    assert row is not None
    return row


def record_ask(tx: StoreTransaction, *, case_id: str, result_id: str, result_version: int, run_id: str | None, dedup_key: str,
               question_id: str | None, outcome: str, text: str) -> bool:
    """One ask of one question by one result version; ``False`` when that version already recorded it (re-processing is a no-op)."""
    row = tx._one("""INSERT INTO atlas_question_asks (ask_id, case_id, result_id, result_version, run_id, dedup_key, question_id, outcome, question_text)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (result_id, result_version, dedup_key) DO NOTHING RETURNING ask_id""",
                  (f"qa_{uuid.uuid4().hex}", case_id, result_id, result_version, run_id, dedup_key, question_id, outcome, text))
    return row is not None


def version_asked(tx: StoreTransaction, result_id: str, result_version: int) -> bool:
    """Whether the questions of this result version were already processed (one ask row per question it asked)."""
    return tx._one("SELECT 1 AS found FROM atlas_question_asks WHERE result_id = %s AND result_version = %s LIMIT 1",
                   (result_id, result_version)) is not None


def asks(tx: StoreTransaction, case_id: str) -> list[dict[str, Any]]:
    return tx._all("SELECT * FROM atlas_question_asks WHERE case_id = %s ORDER BY asked_at, ask_id", (case_id,))


def supersede_open_questions(tx: StoreTransaction, case_id: str, keep: Sequence[str]) -> list[str]:
    rows = tx._all("""UPDATE atlas_questions SET state = 'superseded', resolved_at = now(), updated_at = now()
                      WHERE case_id = %s AND state = 'open' AND NOT (question_id = ANY(%s)) RETURNING question_id""", (case_id, list(keep)))
    return sorted(row["question_id"] for row in rows)


def get_question(tx: StoreTransaction, question_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = tx._one(f"SELECT * FROM atlas_questions WHERE question_id = %s{' FOR UPDATE' if lock else ''}", (question_id,))
    if row is None:
        raise NotFound(f"question {question_id} does not exist")
    return row


def questions(tx: StoreTransaction, *, case_ids: Sequence[str] | None = None, result_id: str | None = None,
              states: Sequence[str] | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if case_ids is not None:
        clauses.append("case_id = ANY(%s)")
        params.append(list(case_ids))
    if result_id is not None:
        clauses.append("result_id = %s")
        params.append(result_id)
    if states is not None:
        clauses.append("state = ANY(%s)")
        params.append(list(states))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return tx._all(f"SELECT * FROM atlas_questions {where} ORDER BY created_at, question_id", params)


def resolve_question(tx: StoreTransaction, question_id: str, *, state: str, by: str | None, dismiss_reason: str | None = None) -> None:
    tx._exec("""UPDATE atlas_questions SET state = %s, resolved_at = COALESCE(resolved_at, now()), resolved_by = COALESCE(%s, resolved_by),
                       dismiss_reason = %s, updated_at = now()
                WHERE question_id = %s""", (state, by, dismiss_reason, question_id))


def insert_answer(tx: StoreTransaction, *, question_id: str, body: str, author: str | None, conflicts_with: str | None) -> dict[str, Any]:
    row = tx._one("""INSERT INTO atlas_answers (answer_id, question_id, body, author, conflicts_with_answer_id) VALUES (%s, %s, %s, %s, %s)
                     RETURNING *""", (new_id("aa"), question_id, body, author, conflicts_with))
    assert row is not None
    return row


def answers(tx: StoreTransaction, question_ids: Sequence[str]) -> list[dict[str, Any]]:
    return tx._all("SELECT * FROM atlas_answers WHERE question_id = ANY(%s) ORDER BY created_at, answer_id", (list(question_ids),))


def get_answer(tx: StoreTransaction, answer_id: str) -> dict[str, Any]:
    row = tx._one("SELECT * FROM atlas_answers WHERE answer_id = %s", (answer_id,))
    if row is None:
        raise NotFound(f"answer {answer_id} does not exist")
    return row


# --- Teach Atlas (Phase 14) ---------------------------------------------------------------------------------------------------

TEACHING_FIELDS = ("body", "scope_type", "scope_id", "teaching_type", "validity_mode", "valid_from", "valid_until", "status", "author",
                   "affects_source_data")


def _snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    return {name: (iso(row[name]) if name in ("valid_from", "valid_until") else row[name]) for name in TEACHING_FIELDS}


def insert_teaching(tx: StoreTransaction, values: Mapping[str, Any]) -> dict[str, Any]:
    row = tx._one("""INSERT INTO teachings (teaching_id, body, scope_type, scope_id, teaching_type, validity_mode, valid_from, valid_until, status,
                                            author, affects_source_data)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s) RETURNING *""",
                  (new_id("tch"), values["body"], values["scope_type"], values["scope_id"], values["teaching_type"], values["validity_mode"],
                   values["valid_from"], values["valid_until"], values["author"], values["affects_source_data"]))
    assert row is not None
    tx._exec("INSERT INTO teaching_revisions (teaching_id, revision, snapshot, author, recorded_at) VALUES (%s, 1, %s::jsonb, %s, %s)",
             (row["teaching_id"], _json(_snapshot(row)), values["author"], row["updated_at"]))
    return row


def update_teaching(tx: StoreTransaction, teaching_id: str, *, expected_revision: int, changes: Mapping[str, Any], by: str | None,
                    status_change: bool = False) -> dict[str, Any] | None:
    """Apply ``changes`` as the next revision; ``None`` when the teaching is not at ``expected_revision``."""
    allowed = {"body", "teaching_type", "validity_mode", "valid_from", "valid_until", "status", "author", "affects_source_data"}
    assert set(changes) <= allowed
    sets = [f"{name} = %s" for name in changes] + ["revision = revision + 1", "updated_at = greatest(now(), updated_at)"]
    params: list[Any] = list(changes.values())
    if status_change:
        sets += ["status_changed_by = %s", "status_changed_at = now()"]
        params.append(by)
    row = tx._one(f"UPDATE teachings SET {', '.join(sets)} WHERE teaching_id = %s AND revision = %s RETURNING *",
                  (*params, teaching_id, expected_revision))
    if row is not None:
        tx._exec("INSERT INTO teaching_revisions (teaching_id, revision, snapshot, author, recorded_at) VALUES (%s, %s, %s::jsonb, %s, %s)",
                 (teaching_id, row["revision"], _json(_snapshot(row)), by, row["updated_at"]))
    return row


def get_teaching(tx: StoreTransaction, teaching_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = tx._one(f"SELECT * FROM teachings WHERE teaching_id = %s{' FOR UPDATE' if lock else ''}", (teaching_id,))
    if row is None:
        raise NotFound(f"teaching {teaching_id} does not exist")
    return row


def teachings(tx: StoreTransaction, *, statuses: Sequence[str] | None = None, scope_type: str | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if statuses is not None:
        clauses.append("status = ANY(%s)")
        params.append(list(statuses))
    if scope_type is not None:
        clauses.append("scope_type = %s")
        params.append(scope_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return tx._all(f"SELECT * FROM teachings {where} ORDER BY created_at, teaching_id", params)


def teaching_revisions(tx: StoreTransaction, teaching_id: str) -> list[dict[str, Any]]:
    return tx._all("SELECT * FROM teaching_revisions WHERE teaching_id = %s ORDER BY revision", (teaching_id,))


def raise_review_flag(tx: StoreTransaction, *, teaching_id: str, revision: int, summary: str, raised_by: str | None) -> dict[str, Any] | None:
    """Open an engineering review flag for a teaching unless one is already open; returns the new flag or ``None``."""
    return tx._one("""INSERT INTO engineering_review_flags (flag_id, source_type, source_id, source_revision, summary, raised_by)
                      VALUES (%s, 'management_teaching', %s, %s, %s, %s)
                      ON CONFLICT (source_type, source_id) WHERE status <> 'resolved' DO NOTHING RETURNING *""",
                   (f"erf_{uuid.uuid4().hex}", teaching_id, revision, summary, raised_by))


def review_flags(tx: StoreTransaction, *, open_only: bool = False, teaching_id: str | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if open_only:
        clauses.append("status <> 'resolved'")
    if teaching_id is not None:
        clauses.append("source_id = %s")
        params.append(teaching_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return tx._all(f"SELECT * FROM engineering_review_flags {where} ORDER BY created_at, flag_id", params)
