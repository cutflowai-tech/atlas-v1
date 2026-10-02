"""Seeded canonical state for the human-context tests (Phases 10-14): runs, cases, evidence states and results in PostgreSQL."""

from __future__ import annotations

import copy
import uuid
from typing import Any

import reasoning_factory as factory

from atlas_reasoning.contracts import ReasoningResult, new_result_id
from atlas_reasoning.store.repository import ReasoningStore

CANONICAL = {"evidence_schema": "test", "findings": {"a": 1}}


def editor_case(editor_id: str = "editor-label-12", topic: str = "deadline") -> dict[str, Any]:
    """The factory's Editor case, re-subjected to ``editor_id`` (identity and fingerprint recomputed)."""
    case = factory.case_dict()
    case = copy.deepcopy(case)
    case["subject_id"] = editor_id
    case["topic_key"] = topic
    case["scope"]["affected_editor_ids"] = [editor_id]
    for ref in case["current_evidence"]["references"]:
        ref["editor_id"] = editor_id
    return factory.seal_case(case)


def team_case(editor_ids: list[str] | None = None) -> dict[str, Any]:
    case = copy.deepcopy(factory.case_dict())
    case.update(subject_type="team", subject_id="team", case_type="team_pattern")
    case["scope"]["affected_editor_ids"] = list(editor_ids or [])
    return factory.seal_case(case)


def seed_case(store: ReasoningStore, case: dict[str, Any]) -> str:
    with store.transaction() as tx:
        run_id = tx.create_run(source_snapshot_id=case["source_snapshot_id"], release_id="release-1", upstream_contract_version="1.5.0",
                               intelligence_version="intelligence-v2.0.0", boundary_version="reasoning-input-v1", identity_version="case-identity-v1",
                               fingerprint_version="evidence-fingerprint-v1")
        tx.insert_case(case_id=case["case_id"], identity_version=case["identity_version"], identity_key=case["identity_key"], case_type=case["case_type"],
                       subject_type=case["subject_type"], subject_id=case["subject_id"], topic_key=case["topic_key"], dimensions=case["identity_dimensions"],
                       run_id=run_id, evidence_fingerprint=case["evidence_fingerprint"])
        tx.put_case_evidence(case_id=case["case_id"], evidence_fingerprint=case["evidence_fingerprint"], fingerprint_version="evidence-fingerprint-v1",
                             canonical_evidence={**CANONICAL, "case": case["case_id"]}, case_document=case, run_id=run_id)
    return run_id


def seed_result(store: ReasoningStore, case: dict[str, Any] | None = None, *, questions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A case with one open result; returns the result document."""
    case = case or editor_case()
    run_id = seed_case(store, case)
    result = factory.result_dict(case)
    result["result_id"] = new_result_id()
    result["title"] = f"{case['subject_id']} {case['topic_key']}: {result['title']}"
    if questions is not None:
        result["questions_for_management"] = questions
    with store.transaction() as tx:
        tx.create_result(ReasoningResult.from_dict(result), run_id=run_id)
    result["_run_id"] = run_id
    return result


def unique_editor() -> str:
    return f"editor-{uuid.uuid4().hex[:8]}"
