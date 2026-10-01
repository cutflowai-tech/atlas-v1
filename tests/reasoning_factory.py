"""Valid Reasoning V3 example objects (reasoning-v1) for tests and for the examples under ``fixtures/reasoning/``.

``python3 tests/reasoning_factory.py --write`` regenerates the example files; ``tests/test_reasoning_contracts.py`` fails when they
drift from this factory. The example case is a hand-written Editor deadline case; identity and fingerprint come from the real
deterministic functions, so the examples always satisfy every contract check.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas_reasoning.contracts import evidence_ref_id

FIXTURES = ROOT / "fixtures" / "reasoning"
CREATED_AT = "2026-09-28T00:05:00Z"
SNAPSHOT = "snapshot-2d34f7d8a849219ee08b"
FP_BEFORE = "ef1_" + "1" * 64
RESULT_ID = "rr1_" + "a" * 32

MEMBER_CHANGE = "change.editor|kind=editor;editor_id=editor-label-12|late_rate_comparison,late_rate_current|late_rate_changed"
MEMBER_MIX = "person.mix_adjusted_deadline|kind=editor;editor_id=editor-label-12|mix_adjusted_late_rate|mix_adjusted_late_rate"
MEMBER_ON_TIME = "concentration.positive|kind=editor;editor_id=editor-label-12;cohort_key=4|not_late_delivery_by_video_type|editor_outcome_concentrated"


def _ref(member: str, finding_id: str, role: str, code: str, item: str, values: dict[str, Any], cohort: str = "4") -> dict[str, Any]:
    cycle = f"cycle:5091110326:{item}"
    return {"ref_id": evidence_ref_id(member, role, code, item, cycle), "member_key": member, "finding_id": finding_id, "role": role,
            "evidence_code": code, "monday_item_id": item, "cycle_id": cycle, "editor_id": "editor-label-12", "video_type_key": cohort,
            "event_ids": [f"{item}-start", f"{item}-ready", f"{item}-eta"], "source_timestamps": ["2026-09-01T08:00:00Z", "2026-09-02T10:00:00Z"],
            "values": values}


def _finding(member: str, finding_id: str, finding_type: str, direction: str, category: str, level: str, confidence: str, sample: int, rank: int) -> dict[str, Any]:
    return {"finding_id": finding_id, "member_key": member, "finding_type": finding_type, "direction": direction, "category": category,
            "evidence_level": level, "confidence": confidence, "sample_size": sample, "rank": rank}


def case_dict() -> dict[str, Any]:
    """A valid ReasoningCase: Editor editor-label-12, deadline topic, one contradicting favourable finding."""
    references = [
        _ref(MEMBER_CHANGE, "change.editor:1f35caa3e91fe30c", "supporting", "late_rate_current", "1101", {"deadline_result": "late", "delta_seconds": 14400}),
        _ref(MEMBER_CHANGE, "change.editor:1f35caa3e91fe30c", "supporting", "late_rate_current", "1102", {"deadline_result": "late", "delta_seconds": 3600}),
        _ref(MEMBER_CHANGE, "change.editor:1f35caa3e91fe30c", "supporting", "late_rate_comparison", "1001", {"deadline_result": "on_time", "delta_seconds": 0}),
        _ref(MEMBER_MIX, "person.mix_adjusted_deadline:5b9e0d1c2a3f4e6d", "supporting", "mix_adjusted_late_rate", "1101", {"deadline_result": "late", "expected_probability": 0.36}),
        _ref(MEMBER_ON_TIME, "concentration.positive:0c1d2e3f4a5b6c7d", "supporting", "not_late_delivery_by_video_type", "1003",
             {"deadline_result": "early", "outcome": True}),
    ]
    statements = [
        {"member_key": MEMBER_CHANGE, "level": "metric", "kind": "deterministic_derived_value", "code": "late_rate_changed",
         "params": {"measure": "late_rate", "against": "comparison", "current": 0.6875, "baseline": 0.5, "difference": 0.1875}},
        {"member_key": MEMBER_CHANGE, "level": "pattern", "kind": "deterministic_derived_value", "code": "change_deteriorating", "params": {"status": "deteriorating"}},
        {"member_key": MEMBER_CHANGE, "level": "interpretation", "kind": "upstream_interpretation", "code": "change_differs_from_team", "params": {}},
        {"member_key": MEMBER_MIX, "level": "pattern", "kind": "deterministic_derived_value", "code": "mix_adjusted_late_rate",
         "params": {"observed_rate": 0.6, "expected_rate": 0.3626}},
        {"member_key": MEMBER_ON_TIME, "level": "pattern", "kind": "deterministic_derived_value", "code": "editor_outcome_concentrated",
         "params": {"outcome": "not_late_delivery", "group": "4", "share_ratio": 1.4}},
    ]
    case = {
        "contract_version": "reasoning-v1",
        "case_id": "rc1_" + "0" * 32,
        "case_type": "editor_pattern",
        "identity_version": "case-identity-v1",
        "identity_key": "editor:editor-label-12:deadline",
        "subject_type": "editor",
        "subject_id": "editor-label-12",
        "topic_key": "deadline",
        "identity_dimensions": {},
        "scope": {"affected_editor_ids": ["editor-label-12"], "affected_video_type_keys": ["4", "5"], "affected_project_count": 4,
                  "windows": ["all_history", "current"]},
        "source_snapshot_id": SNAPSHOT,
        "upstream_contract_version": "1.5.0",
        "upstream": {"intelligence_version": "intelligence-v2.0.0", "intelligence_document_version": "2.0.0", "boundary_version": "reasoning-input-v1"},
        "orientation": "adverse",
        "supporting_findings": [
            _finding(MEMBER_CHANGE, "change.editor:1f35caa3e91fe30c", "change.editor", "adverse", "needs_attention", "pattern", "moderate", 26, 2),
            _finding(MEMBER_MIX, "person.mix_adjusted_deadline:5b9e0d1c2a3f4e6d", "person.mix_adjusted_deadline", "adverse", "editor_specific_pattern",
                     "pattern", "moderate", 30, 14),
        ],
        "contradicting_findings": [
            _finding(MEMBER_ON_TIME, "concentration.positive:0c1d2e3f4a5b6c7d", "concentration.positive", "favourable", "editor_specific_pattern",
                     "pattern", "moderate", 18, 27),
        ],
        "current_evidence": {"statements": statements, "references": references},
        "previous_result_id": RESULT_ID,
        "previous_result_version": 1,
        "evidence_fingerprint": "ef1_" + "2" * 64,
        "material_delta": None,
        "manager_context": [{"source_type": "manager_interpretation", "source_id": "note-1", "body": "Class A projects were reassigned to Ahmed in September.",
                             "author": "manager@example.com", "recorded_at": "2026-09-20T09:00:00Z"}],
        "memory_context": {"status": "not_requested", "items": []},
        "created_at": CREATED_AT,
    }
    return seal_case(case)


def seal_case(case: dict[str, Any]) -> dict[str, Any]:
    """Recompute the deterministic fields a case derives from its own content (identity, fingerprint)."""
    from atlas_reasoning.case_identity import build_identity

    identity = build_identity(case["subject_type"], case["subject_id"], case["topic_key"], case["case_type"], case["identity_dimensions"])
    case.update({key: value for key, value in identity.to_dict().items() if key in case})
    return case


def result_dict(case: dict[str, Any] | None = None) -> dict[str, Any]:
    """A valid ReasoningResult citing only ``case``'s evidence."""
    case = case or case_dict()
    refs = [ref["ref_id"] for ref in case["current_evidence"]["references"]]
    change, change2, _, mix, on_time = refs
    return {
        "contract_version": "reasoning-v1",
        "result_id": RESULT_ID,
        "case_id": case["case_id"],
        "version": 1,
        "title": "Ahmed's late deliveries rose in the current window",
        "observation": {"statement": "11 of 16 deadline-classifiable projects in the current window were late, against 5 of 10 before.",
                        "evidence_refs": [change, change2]},
        "reasoning_summary": ("The late rate rose by 19 points while the other Editors improved, and the gap remains after matching the Video Type "
                              "and runway mix; on-time work concentrates in Class A, so the issue is not uniform."),
        "supporting_evidence": [{"statement": "The late rate rose from 50% to 69%.", "evidence_refs": [change, change2]},
                                {"statement": "On the same mix the other Editors were late about 36% of the time.", "evidence_refs": [mix]}],
        "counter_evidence": [{"statement": "Class A projects are mostly delivered on time.", "evidence_refs": [on_time]}],
        "interpretation": {"statement": "The deterioration appears specific to non-Class-A work rather than general.", "evidence_refs": [change, on_time]},
        "alternative_explanations": [{"explanation": "Class B briefs may have arrived with shorter runway this month.", "evidence_refs": [],
                                      "requires_context": True}],
        "confidence": {"level": "moderate", "rationale": "Moderate upstream evidence; the sample is small for the current window."},
        "limitations": ["Video Type is the only complexity control."],
        "management_significance": {"statement": "Worth a conversation about Class B scheduling before drawing conclusions.", "evidence_refs": [change]},
        "questions_for_management": [{"text": "Did Class B assignments change in September?", "reason": "Runway and assignment context are not in Monday.",
                                      "expected_context_type": "assignment_context"}],
        "suggested_investigations": [{"text": "Compare runway of the late Class B projects with earlier months.", "evidence_refs": [change]}],
        "lifecycle_status": "active",
        "superseded_by": None,
        "source_snapshot_id": case["source_snapshot_id"],
        "evidence_fingerprint": case["evidence_fingerprint"],
        "model_metadata": {"provider": "openrouter", "model": "openai/gpt-5.6-sol", "request_ids": ["req-0001"]},
        "prompt_version": "analyst-v1",
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
    }


def update_dict(result: dict[str, Any] | None = None, case: dict[str, Any] | None = None) -> dict[str, Any]:
    """A valid ReasoningUpdate changing only the confidence and the observation of ``result``."""
    case = case or case_dict()
    result = result or result_dict(case)
    from atlas_reasoning.contracts import PATCHABLE_FIELDS

    changed = {"confidence": {"level": "weak", "rationale": "The newest window adds only two projects."},
               "observation": {"statement": "12 of 18 deadline-classifiable projects in the current window were late.",
                               "evidence_refs": result["observation"]["evidence_refs"]}}
    return {
        "contract_version": "reasoning-v1",
        "case_id": result["case_id"],
        "result_id": result["result_id"],
        "base_version": result["version"],
        "action": "patch",
        "changed_fields": [{"field": name, "value": value} for name, value in changed.items()],
        "preserved_fields": [name for name in PATCHABLE_FIELDS if name not in changed],
        "change_rationale": "Two more late projects arrived; the direction is unchanged, the sample is still small.",
        "evidence_fingerprint_before": result["evidence_fingerprint"],
        "evidence_fingerprint_after": case["evidence_fingerprint"],
    }


def invalid_examples() -> dict[str, tuple[str, str, dict[str, Any]]]:
    """name -> (contract, expected error code, payload)."""
    case, result = case_dict(), result_dict()
    examples: dict[str, tuple[str, str, dict[str, Any]]] = {}

    bad = copy.deepcopy(case)
    bad["chain_of_thought"] = "..."
    examples["case-unknown-field"] = ("ReasoningCase", "UNKNOWN_FIELD", bad)
    bad = copy.deepcopy(case)
    bad["subject_type"] = "employee"
    examples["case-bad-subject-type"] = ("ReasoningCase", "INVALID_ENUM", bad)
    bad = copy.deepcopy(result)
    bad["observation"]["evidence_refs"] = []
    examples["result-observation-without-evidence"] = ("ReasoningResult", "MISSING_EVIDENCE", bad)
    bad = copy.deepcopy(result)
    bad["supporting_evidence"] = []
    examples["result-without-supporting-evidence"] = ("ReasoningResult", "MISSING_EVIDENCE", bad)
    bad = copy.deepcopy(result)
    bad["raw_reasoning"] = "hidden chain of thought"
    examples["result-raw-reasoning-field"] = ("ReasoningResult", "UNKNOWN_FIELD", bad)
    bad = copy.deepcopy(result)
    bad["lifecycle_status"] = "deleted"
    examples["result-bad-lifecycle"] = ("ReasoningResult", "INVALID_ENUM", bad)
    update = update_dict()
    bad = copy.deepcopy(update)
    bad["changed_fields"].append({"field": "case_id", "value": "rc1_" + "f" * 32})
    examples["update-patches-case-id"] = ("ReasoningUpdate", "IMMUTABLE_FIELD", bad)
    bad = copy.deepcopy(update)
    bad["preserved_fields"] = bad["preserved_fields"][1:]
    examples["update-missing-field-accounting"] = ("ReasoningUpdate", "FIELD_ACCOUNTING", bad)
    return examples


def write() -> None:
    (FIXTURES / "valid").mkdir(parents=True, exist_ok=True)
    (FIXTURES / "invalid").mkdir(parents=True, exist_ok=True)
    case = case_dict()
    result = result_dict(case)
    for name, payload in (("case", case), ("result", result), ("update", update_dict(result, case))):
        (FIXTURES / "valid" / f"{name}.json").write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    manifest = {}
    for name, (contract, code, payload) in sorted(invalid_examples().items()):
        (FIXTURES / "invalid" / f"{name}.json").write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
        manifest[f"invalid/{name}.json"] = {"contract": contract, "code": code}
    (FIXTURES / "manifest.json").write_text(json.dumps({"valid": {"valid/case.json": "ReasoningCase", "valid/result.json": "ReasoningResult",
                                                                  "valid/update.json": "ReasoningUpdate"}, "invalid": manifest}, indent=1) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        write()
    else:
        print(json.dumps({"case": case_dict(), "result": result_dict(), "update": update_dict()}, indent=1))
