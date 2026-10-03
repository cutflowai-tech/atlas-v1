"""Read-only SQL for the Reasoning V3 evaluation harness (Phase 19, ``atlas_reasoning.evaluation.capture``). Nothing here writes.

One ``REPEATABLE READ READ ONLY`` transaction per capture, so a state comes from a single consistent snapshot. Result documents and
work-item case documents are read only so ``evaluation.capture`` can hash patchable fields and re-run the Phase 15 grounding checks;
they never leave that function. Prompts, responses, refused candidates, notes, answers, teachings and memory text are never read.
"""

from __future__ import annotations

from typing import Any

from atlas_reasoning.store.repository import ReasoningStore


def canonical_rows(store: ReasoningStore) -> dict[str, list[dict[str, Any]]]:
    with store.transaction() as tx:
        tx._exec("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return {
            "cases": tx._all("""SELECT c.case_id, c.identity_key, c.presence, c.last_evidence_fingerprint AS evidence_fingerprint,
                                       jsonb_array_length(coalesce(e.case_document -> 'contradicting_findings', '[]'::jsonb)) AS contradicting
                                FROM reasoning_cases c
                                LEFT JOIN reasoning_case_evidence e ON e.case_id = c.case_id AND e.evidence_fingerprint = c.last_evidence_fingerprint
                                ORDER BY c.case_id"""),
            "results": tx._all("SELECT result_id, case_id, current_version, lifecycle_status FROM reasoning_results ORDER BY result_id"),
            # The previous version's document rides along for the update path of the grounding re-check (numbers of the delta).
            # For a patch, the canonical evidence of the previous version's and this version's fingerprints too: the engine validated the
            # patch against the case with the material delta between exactly these two states (``ReasoningEngine._update_case``).
            "versions": tx._all("""SELECT v.result_id, v.version, v.change_kind, v.evidence_fingerprint, v.document, v.update_document,
                                          v.model, v.prompt_version, r.case_id, w.case_document, p.document AS previous_document,
                                          eb.canonical_evidence AS evidence_before, ea.canonical_evidence AS evidence_after
                                   FROM reasoning_result_versions v
                                   JOIN reasoning_results r ON r.result_id = v.result_id
                                   LEFT JOIN reasoning_work_items w ON w.work_item_id = v.work_item_id
                                   LEFT JOIN reasoning_result_versions p ON p.result_id = v.result_id AND p.version = v.version - 1
                                   LEFT JOIN reasoning_case_evidence eb ON v.change_kind = 'patched' AND eb.case_id = r.case_id
                                                                        AND eb.evidence_fingerprint = p.evidence_fingerprint
                                   LEFT JOIN reasoning_case_evidence ea ON v.change_kind = 'patched' AND ea.case_id = r.case_id
                                                                        AND ea.evidence_fingerprint = v.evidence_fingerprint
                                   ORDER BY v.result_id, v.version"""),
            "transitions": tx._all("""SELECT transition_id, result_id, result_version, from_status, to_status FROM reasoning_lifecycle_transitions
                                      ORDER BY result_id, result_version"""),
            "questions": tx._all("SELECT question_id, case_id, dedup_key, state FROM atlas_questions ORDER BY question_id"),
            "calls": tx._all("""SELECT request_id, case_id, purpose, status, coalesce(input_tokens, 0) + coalesce(output_tokens, 0) AS tokens
                                FROM llm_calls ORDER BY request_id"""),
            "refusals": tx._all("SELECT candidate_id, case_id, error_codes FROM reasoning_failed_candidates ORDER BY candidate_id"),
            "work": tx._all("SELECT work_item_id, case_id, status, requires_llm FROM reasoning_work_items ORDER BY work_item_id"),
            "injections": tx._all("""SELECT injection_id, case_id, purpose, memory_status,
                                            ARRAY(SELECT DISTINCT s ->> 'source_type' FROM jsonb_array_elements(selected) s
                                                  WHERE s ->> 'source_type' IS NOT NULL ORDER BY 1) AS sources
                                     FROM memory_injections ORDER BY injection_id"""),
            "observations": tx._all("SELECT run_id, case_id, action FROM reasoning_case_observations ORDER BY observed_at, run_id, case_id"),
            "synced_memory": tx._all("""SELECT source_type, source_id, session_key, content_sha256 FROM memory_sync_log
                                        WHERE status = 'synced' AND operation = 'write' ORDER BY 1, 2, 3, 4"""),
        }
