"""Read-only SQL for the reasoning-first dashboard (Phase 16).

Every function takes a ``StoreTransaction`` and only reads canonical tables: results and their versions, evidence links, case
evidence states, work items, lifecycle transitions, diffs, memory injections and the memory sync log. Nothing here writes, and
nothing reads ``reasoning_failed_candidates`` (Phase 15 keeps refused candidates for debugging only; they are never a card).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from atlas_reasoning.store.repository import NotFound, StoreTransaction

_RESULT = """SELECT r.result_id, r.case_id, r.current_version, r.lifecycle_status, r.superseded_by_result_id, r.superseded_by_case_id,
                    r.created_at, v.document, v.change_kind, v.created_at AS version_created_at, v.evidence_fingerprint,
                    c.subject_type, c.subject_id, c.topic_key, c.case_type, c.last_evidence_fingerprint, c.presence
             FROM reasoning_results r
             JOIN reasoning_result_versions v ON v.result_id = r.result_id AND v.version = r.current_version
             JOIN reasoning_cases c ON c.case_id = r.case_id"""


def results(tx: StoreTransaction) -> list[dict[str, Any]]:
    """Every result at its current (canonical) version, with its case identity; newest version first."""
    return tx._all(f"{_RESULT} ORDER BY v.created_at DESC, r.result_id")


def result(tx: StoreTransaction, result_id: str) -> dict[str, Any]:
    row = tx._one(f"{_RESULT} WHERE r.result_id = %s", (result_id,))
    if row is None:
        raise NotFound(f"result {result_id} does not exist")
    return row


def version_document(tx: StoreTransaction, result_id: str, version: int) -> dict[str, Any]:
    row = tx._one("""SELECT version, change_kind, lifecycle_status, evidence_fingerprint, created_at, document, update_document, work_item_id
                     FROM reasoning_result_versions WHERE result_id = %s AND version = %s""", (result_id, version))
    if row is None:
        raise NotFound(f"result {result_id} has no version {version}")
    return row


def versions(tx: StoreTransaction, result_id: str) -> list[dict[str, Any]]:
    """Every version's provenance (not its document), oldest first; ``changed_fields`` from its stored ReasoningUpdate."""
    return tx._all("""SELECT version, change_kind, lifecycle_status, evidence_fingerprint, source_snapshot_id, provider, model, prompt_version,
                             run_id, work_item_id, reason, created_at, update_document ->> 'change_rationale' AS change_rationale,
                             COALESCE((SELECT array_agg(change ->> 'field' ORDER BY change ->> 'field')
                                       FROM jsonb_array_elements(update_document -> 'changed_fields') AS change), '{}') AS changed_fields
                      FROM reasoning_result_versions WHERE result_id = %s ORDER BY version""", (result_id,))


def replaced_results(tx: StoreTransaction, result_id: str) -> list[str]:
    """Results that ``result_id`` superseded (the reverse of ``superseded_by``)."""
    return [row["result_id"] for row in tx._all("SELECT result_id FROM reasoning_results WHERE superseded_by_result_id = %s ORDER BY result_id",
                                                (result_id,))]


def work_item_delta(tx: StoreTransaction, work_item_id: str | None) -> dict[str, Any] | None:
    if work_item_id is None:
        return None
    row = tx._one("SELECT material_delta FROM reasoning_work_items WHERE work_item_id = %s", (work_item_id,))
    delta: dict[str, Any] | None = row["material_delta"] if row else None
    return delta


def latest_llm_work(tx: StoreTransaction, case_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Per case, its most recent LLM work item (status and the short, content-free ``last_error``)."""
    rows = tx._all("""SELECT DISTINCT ON (case_id) case_id, work_item_id, kind, status, last_error, created_at, updated_at
                      FROM reasoning_work_items WHERE requires_llm AND case_id = ANY(%s)
                      ORDER BY case_id, created_at DESC, work_item_id DESC""", (list(case_ids),))
    return {row["case_id"]: row for row in rows}


def latest_memory_status(tx: StoreTransaction, case_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Per case, the memory status recorded for its most recent reasoning call (Phase 11 injection audit)."""
    rows = tx._all("""SELECT DISTINCT ON (case_id) case_id, memory_status, degraded_reason, created_at
                      FROM memory_injections WHERE case_id = ANY(%s) ORDER BY case_id, created_at DESC, injection_id DESC""", (list(case_ids),))
    return {row["case_id"]: row for row in rows}


def memory_backlog(tx: StoreTransaction) -> int:
    """Memory copies not yet in Honcho (pending or failed); the canonical rows they copy are already committed."""
    row = tx._one("SELECT count(*) AS n FROM memory_sync_log WHERE status IN ('pending', 'failed')")
    return int(row["n"]) if row else 0


def unreasoned_cases(tx: StoreTransaction) -> dict[str, int]:
    """Present cases that have no result yet, by the state of their latest LLM work item: ``failed`` (provider failure, guardrail refusal,
    other) or ``pending`` (pending / in progress). Status and the error *class* only; never candidate content."""
    rows = tx._all("""SELECT w.status, split_part(coalesce(w.last_error, ''), ':', 1) AS error_class, count(*) AS n
                      FROM reasoning_cases c
                      JOIN LATERAL (SELECT status, last_error FROM reasoning_work_items i WHERE i.case_id = c.case_id AND i.requires_llm
                                    ORDER BY i.created_at DESC, i.work_item_id DESC LIMIT 1) w ON true
                      WHERE c.presence = 'present' AND NOT EXISTS (SELECT 1 FROM reasoning_results r WHERE r.case_id = c.case_id)
                      GROUP BY w.status, error_class""")
    counts = {"failed": 0, "failed_provider": 0, "failed_validation": 0, "pending": 0}
    for row in rows:
        if row["status"] == "failed":
            counts["failed"] += int(row["n"])
            if row["error_class"] in ("provider", "validation"):
                counts[f"failed_{row['error_class']}"] += int(row["n"])
        elif row["status"] in ("pending", "in_progress"):
            counts["pending"] += int(row["n"])
    return counts


def result_states(tx: StoreTransaction, result_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Per existing result: its current version, lifecycle and replacement (``superseded_by``)."""
    rows = tx._all("""SELECT result_id, current_version, lifecycle_status, superseded_by_result_id FROM reasoning_results
                      WHERE result_id = ANY(%s)""", (list(result_ids),))
    return {row["result_id"]: row for row in rows}
