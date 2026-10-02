"""Shared fixtures for the Reasoning V3 engine tests (Phases 07–09): simulated later snapshots, factory cases with a previous
result, and an engine wired to an offline model."""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import reasoning_factory as factory
import reasoning_snapshots as snapshots
from reasoning_fakes import ScriptedAnalyst, analyst_answer, gateway

from atlas_reasoning import analyst
from atlas_reasoning.contracts import ReasoningCase, ReasoningResult
from atlas_reasoning.delta import material_delta
from atlas_reasoning.engine import ReasoningEngine
from atlas_reasoning.fingerprint import canonical_evidence
from atlas_reasoning.provider import ProviderResponse
from atlas_reasoning.reasoning_input_boundary import ReasoningInput, upstream_finding
from atlas_reasoning.settings import PINNED_MODEL
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.repository import ReasoningStore

DEADLINE_12 = "case-identity-v1|editor|editor-label-12|deadline"
NOW = "2026-09-28T00:20:00.000000Z"
LATER = "2026-09-29T00:20:00.000000Z"
RESULT_ID = "rr1_" + "b" * 32


def times(n: int) -> list[str]:
    return [f"2026-09-{28 + i // 24:02d}T{i % 24:02d}:10:00Z" for i in range(n)]


def rows() -> list[dict[str, Any]]:
    return snapshots.intelligence_copy()["findings"]


def payload_with(findings: list[dict[str, Any]], snapshot_id: str | None = None) -> ReasoningInput:
    base = snapshots.reasoning_input()
    snapshot = dataclasses.replace(base.snapshot, source_snapshot_id=snapshot_id) if snapshot_id else base.snapshot
    return dataclasses.replace(base, findings=tuple(upstream_finding(row) for row in findings), snapshot=snapshot)


def first_change_editor(findings: list[dict[str, Any]], editor: str = "editor-label-12") -> dict[str, Any]:
    return next(r for r in findings if r["finding_type"] == "change.editor" and r["scope"]["editor_id"] == editor
                and r["statements"][0]["params"].get("measure") == "late_rate")


def changed_rows(current: float = 0.8125) -> list[dict[str, Any]]:
    """The showcase findings with Editor editor-label-12's current late rate moved (one material value change)."""
    changed = rows()
    for statement in first_change_editor(changed)["statements"]:
        statement["params"]["current"] = current
    return changed


def without_deadline_12() -> list[dict[str, Any]]:
    return [r for r in rows() if r["scope"].get("editor_id") != "editor-label-12" or r["finding_type"] in ("editor.speed_pattern", "contradiction.hidden_risk")]


def with_new_topic() -> list[dict[str, Any]]:
    added = rows()
    extra = copy.deepcopy(next(r for r in added if r["finding_type"] == "editor.speed_pattern"))
    extra["scope"]["editor_id"] = "editor-label-99"
    added.append(extra)
    return added


def engine(store: ReasoningStore, transport: ScriptedAnalyst | None = None) -> tuple[ReasoningEngine, ScriptedAnalyst]:
    transport = transport or ScriptedAnalyst()
    return ReasoningEngine(store, gateway(transport, recorder=StoreCallRecorder(store))), transport


# --- factory objects (no database) -------------------------------------------------------------------------------------------


def new_case() -> ReasoningCase:
    case = factory.case_dict()
    case.update(previous_result_id=None, previous_result_version=None)
    return ReasoningCase.from_dict(factory.seal_case(case))


def first_result(case: ReasoningCase) -> ReasoningResult:
    answer = analyst_answer(analyst.analyst_input(case))
    answer["observation"]["statement"] = "11 of 16 projects in the current window were late, against 5 of 10 before (69% against 50%)."
    response = ProviderResponse(request_id="req_" + "1" * 32, model=PINNED_MODEL, content="", parsed=answer)
    return analyst.result_from_response(case, response, provider="fake", result_id=RESULT_ID, now=NOW)


def changed_case(previous: ReasoningResult, mutate=None) -> ReasoningCase:
    """The factory case after an upstream change (default: the current late rate rose to 12 of 16), continuing ``previous``."""
    before = new_case().to_dict()
    after = copy.deepcopy(before)
    if mutate is None:
        after["current_evidence"]["statements"][0]["params"].update(current=0.75, difference=0.25)
        after["current_evidence"]["blocks"][0]["comparison"].update(late=12, late_rate=0.75)
    else:
        mutate(after)
    after = factory.seal_case(after)
    after.update(previous_result_id=previous.result_id, previous_result_version=previous.version,
                 material_delta=material_delta(canonical_evidence(before), canonical_evidence(after), fingerprint_before=before["evidence_fingerprint"],
                                               fingerprint_after=after["evidence_fingerprint"]))
    return ReasoningCase.from_dict(after)
