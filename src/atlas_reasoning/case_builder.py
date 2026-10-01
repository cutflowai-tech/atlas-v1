"""Case documents (``REV/05``): one ``ReasoningCase`` document per case candidate per evidence state.

``build_case_document`` turns one case candidate into the *base* ``ReasoningCase`` document of its evidence state: no previous
result and no material delta (the Change Gate attaches history per work item, ``change_gate.case_for_work``). Its
``evidence_fingerprint`` is computed from the document itself (``fingerprint``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from atlas_reasoning.case_mapping import CaseCandidate, Contribution
from atlas_reasoning.contracts import OPPOSITE, evidence_ref_id
from atlas_reasoning.enums import CONFIDENCE_ORDER, CONTRACT_VERSION, ConfidenceLevel, Direction, MemoryStatus
from atlas_reasoning.fingerprint import EvidenceError, canonical_evidence, evidence_fingerprint
from atlas_reasoning.frozen import thaw
from atlas_reasoning.reasoning_input_boundary import STATEMENT_KINDS, EvidenceBlockRef, ReasoningInput

DIRECTIONAL = (Direction.ADVERSE, Direction.FAVOURABLE)


def orientation(contributions: Iterable[Contribution]) -> Direction:
    """The case's direction: adverse or favourable, whichever side has more findings (then the stronger best upstream
    confidence); ``mixed`` when the two sides tie or only mixed findings exist, ``neutral`` otherwise. It depends only on the
    findings' own direction and confidence — never on Intelligence V2 ranks or finding IDs, which move with the window."""
    rows = list(contributions)
    strength = {}
    for side in DIRECTIONAL:
        levels = [CONFIDENCE_ORDER.index(ConfidenceLevel(row.finding.confidence_level)) for row in rows if row.finding.direction == side
                  and row.finding.confidence_level in {level.value for level in ConfidenceLevel}]
        count = sum(1 for row in rows if row.finding.direction == side)
        strength[side] = (count, max(levels, default=-1))
    adverse, favourable = strength[Direction.ADVERSE], strength[Direction.FAVOURABLE]
    if adverse != favourable:
        return Direction.ADVERSE if adverse > favourable else Direction.FAVOURABLE
    if adverse[0] or any(row.finding.direction == Direction.MIXED for row in rows):
        return Direction.MIXED
    return Direction.NEUTRAL


def _finding_ref(row: Contribution) -> dict[str, Any]:
    finding = row.finding
    return {"finding_id": finding.finding_id, "member_key": row.member_key, "finding_type": finding.finding_type, "direction": finding.direction,
            "category": finding.category, "evidence_level": finding.evidence_level, "confidence": finding.confidence_level,
            "sample_size": finding.sample_size, "rank": finding.rank, "limitations": sorted(set(finding.limitations))}


def _references(row: Contribution, block: EvidenceBlockRef) -> list[dict[str, Any]]:
    references: dict[str, dict[str, Any]] = {}
    for record in block.records:
        ref_id = evidence_ref_id(row.member_key, block.role, block.code, record.monday_item_id, record.cycle_id)
        reference = {"ref_id": ref_id, "member_key": row.member_key, "finding_id": row.finding.finding_id, "role": block.role,
                     "evidence_code": block.code, "monday_item_id": record.monday_item_id, "cycle_id": record.cycle_id, "editor_id": record.editor_id,
                     "video_type_key": record.cohort_key, "event_ids": list(record.event_ids), "source_timestamps": list(record.source_timestamps),
                     "values": thaw(record.values)}
        existing = references.setdefault(ref_id, reference)
        if existing != reference:
            raise EvidenceError(f"{row.member_key}: two different records for item {record.monday_item_id} in block {block.code}")
    return list(references.values())


def build_case_document(candidate: CaseCandidate, payload: ReasoningInput, created_at: str) -> dict[str, Any]:
    """The base ``ReasoningCase`` document of one candidate in one snapshot (no previous result, no delta), with its fingerprint."""
    direction = orientation(candidate.contributions)
    supporting: list[dict[str, Any]] = []
    contradicting: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    for row in candidate.contributions:
        finding = row.finding
        opposed = direction in OPPOSITE and finding.direction == OPPOSITE[direction]
        (contradicting if opposed else supporting).append(_finding_ref(row))
        statements += [{"member_key": row.member_key, "level": s.level, "kind": STATEMENT_KINDS[s.level], "code": s.code, "params": thaw(s.params)}
                       for s in finding.statements]
        for block in finding.evidence_blocks:
            blocks.append({"member_key": row.member_key, "role": block.role, "evidence_code": block.code, "sample": thaw(block.sample),
                           "comparison": thaw(block.comparison), "exclusions": thaw(block.exclusions)})
            references += _references(row, block)
    findings = [row.finding for row in candidate.contributions]
    identity = candidate.identity.to_dict()
    document: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "case_id": identity["case_id"],
        "case_type": identity["case_type"],
        "identity_version": identity["identity_version"],
        "identity_key": identity["identity_key"],
        "subject_type": identity["subject_type"],
        "subject_id": identity["subject_id"],
        "topic_key": identity["topic_key"],
        "identity_dimensions": identity["identity_dimensions"],
        "scope": {"affected_editor_ids": sorted({e for f in findings for e in f.affected_editors}),
                  "affected_video_type_keys": sorted({v for f in findings for v in f.affected_video_types}),
                  "affected_project_count": len({p for f in findings for p in f.affected_projects}),
                  "windows": sorted({str(f.time_window.get("window")) for f in findings if f.time_window and f.time_window.get("window")})},
        "source_snapshot_id": payload.snapshot.source_snapshot_id,
        "upstream_contract_version": payload.contract.executable_contract_version,
        "upstream": {"intelligence_version": payload.contract.intelligence_version,
                     "intelligence_document_version": payload.contract.intelligence_document_version,
                     "boundary_version": payload.contract.boundary_version},
        "orientation": direction.value,
        "supporting_findings": supporting,
        "contradicting_findings": contradicting,
        "current_evidence": {"statements": statements, "blocks": blocks, "references": sorted(references, key=lambda ref: ref["ref_id"])},
        "previous_result_id": None,
        "previous_result_version": None,
        "evidence_fingerprint": "",
        "material_delta": None,
        "manager_context": [],
        "memory_context": {"status": MemoryStatus.NOT_REQUESTED.value, "items": []},
        "created_at": created_at,
    }
    document["evidence_fingerprint"] = evidence_fingerprint(canonical_evidence(document))
    return document


