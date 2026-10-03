"""Read-only audit-consistency SQL for the Phase 19-B evaluation runner (``evaluation_runner.CaseRunner._audit``). Nothing here writes.

Phase 19-A's metrics assume a consistent audit trail; the runner checks the invariants they rely on **before** counting, so an
inconsistent state stops the evaluation (``EVALUATION_AUDIT_INCONSISTENCY``) instead of producing a value. Only identifiers are read.
"""

from __future__ import annotations

from atlas_reasoning.store.repository import ReasoningStore


def refusals_without_call(store: ReasoningStore) -> list[str]:
    """Refused candidates (``reasoning_failed_candidates``) without their answered provider call: no ``llm_calls`` row with the request ID,
    or one that did not succeed (a candidate is only ever refused after the provider answered)."""
    with store.transaction() as tx:
        tx._exec("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows = tx._all("""SELECT f.candidate_id FROM reasoning_failed_candidates f
                          LEFT JOIN llm_calls c ON c.request_id = f.request_id AND c.status = 'succeeded'
                          WHERE c.request_id IS NULL ORDER BY f.candidate_id""")
    return [str(row["candidate_id"]) for row in rows]
