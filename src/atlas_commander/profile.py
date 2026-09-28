"""Editor Profile (evidence API) built only from deterministic Atlas results.

The builder assembles what the metric engine already computed. It adds no score, no
weighting and no inferred fact. Anything that could not be measured appears in
``coverage`` and in the per-project rows with its reason, instead of being hidden.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from atlas_commander.contracts import validate
from atlas_commander.cycles import COMPLETED, CyclePolicy, CycleRecord
from atlas_commander.metrics import (
    MetricPolicy,
    classify_deadline,
    deadline_eligible,
    deadline_result,
    deadline_summary,
    median_seconds,
    speed_benchmarks,
    speed_eligible,
)
from atlas_commander.monday_source import dropdown_value_ids
from atlas_commander.pipeline import CycleReconstruction, reconstruct_quality
from atlas_commander.quality import quality_summary, revision_context_summary

CONTRACT_VERSION = "1.2.0"
SCHEMA = "editor-profile-v1.2.schema.json"
OVERALL_NOTE = ("No overall performance status rule is approved for Atlas V1. The Editor's picture is the speed, deadline "
                "and quality sections below, each with its own sample size and Monday evidence.")
POSITIVE_NOTE = "No approved positive quality signal exists in V1; For Bonus is context only and does not affect quality."
REVISION_NOTE = "Revision activity is context only. It does not imply Editor fault and never affects any metric or conclusion."


class ProfileError(ValueError):
    pass


def _editor_cycles(cycles: list[CycleRecord], editor_id: str) -> list[CycleRecord]:
    return [cycle for cycle in cycles if cycle.editor_id == editor_id]


def _for_bonus_context(result: CycleReconstruction, contract: Mapping[str, Any], item_ids: set[str]) -> dict[str, Any]:
    column = contract["quality_labels"].get("for_bonus", {}).get("column_id")
    snapshots = result.item_snapshots.get(column, {}) if column else {}
    projects = sorted(item for item in item_ids if dropdown_value_ids((snapshots.get(item) or {}).get("value")))
    return {"affects_quality": False, "classification": "context-unclassified", "column_id": column, "projects": projects,
            "note": "For Bonus labels are shown as context only in V1 (approved decision); they are neither positive nor negative quality signals."}


def _current_editor(snapshot: Mapping[str, Any] | None, policy: CyclePolicy) -> str | None:
    """Editor for an item's *current* Editor Name value (current state only, never used for past work)."""
    ids = dropdown_value_ids((snapshot or {}).get("value"))
    if len(ids) != 1:
        return None
    candidates = policy.identity.candidates(ids[0])
    if len(candidates) != 1:
        return None
    entry = candidates[0]
    names = [name.strip() for name in str((snapshot or {}).get("text") or "").split(",") if name.strip()]
    if entry.label_names and (len(names) != 1 or names[0] not in entry.label_names):
        return None
    return entry.editor_id


def _current_workload(result: CycleReconstruction, contract: Mapping[str, Any], editor_id: str) -> dict[str, Any]:
    board = contract["source_board"]
    policy = CyclePolicy.from_contract(contract)
    editors = result.item_snapshots.get(board["editor_column_id"], {})
    statuses = result.item_snapshots.get(board["status_column_id"], {})
    by_status: dict[str, list[str]] = {}
    for item_id, snapshot in sorted(editors.items()):
        if _current_editor(snapshot, policy) != editor_id:
            continue
        label = str((statuses.get(item_id) or {}).get("text") or "(no status)")
        by_status.setdefault(label, []).append(item_id)
    return {"as_of": result.ingestion.get("retrieved_at"), "basis": "current Monday Editor Name and Status values of each item",
            "by_current_status": by_status,
            "note": "Descriptive only. Which statuses count as the Editor's active workload is not defined in V1, so no capacity judgement is made."}


def _trend(cycles: list[CycleRecord], deadline_results: list[dict[str, Any]]) -> dict[str, Any]:
    speed: dict[tuple[str, str], list[int]] = {}
    for cycle in cycles:
        if speed_eligible(cycle) and cycle.ready_for_approval_at and cycle.cohort_key and cycle.duration_seconds is not None:
            speed.setdefault((cycle.cohort_key, cycle.ready_for_approval_at[:7]), []).append(cycle.duration_seconds)
    deadline: dict[str, Counter[str]] = {}
    for result in deadline_results:
        month = result["metric"]["ready_for_approval_at"][:7]
        deadline.setdefault(month, Counter())[classify_deadline(result["delta_seconds"])] += 1
    return {
        "speed_by_cohort_month": [{"cohort_key": key, "month": month, "projects": len(values), "median_seconds": median_seconds(values)}
                                  for (key, month), values in sorted(speed.items())],
        "deadline_by_month": [{"month": month, "evaluated": sum(counts.values()), "early": counts["early"], "on_time": counts["on_time"], "late": counts["late"]}
                              for month, counts in sorted(deadline.items())],
        "note": "Monthly figures (UTC month of Ready For Approval) with their sample sizes. Speed is shown per exact Video Type cohort only. No trend conclusion is drawn.",
    }


def build_editor_profile(result: CycleReconstruction, contract: Mapping[str, Any], editor_id: str, generated_at: str) -> dict[str, Any]:
    """Contract-valid editor-profile 1.1.0 for one Editor from a cycle reconstruction."""
    policy = MetricPolicy.from_contract(contract)
    cycles = _editor_cycles(result.cycles, editor_id)
    if not cycles:
        raise ProfileError(f"no cycle is attributed to {editor_id}; unresolved Editors have no profile")
    identity = next(cycle.editor for cycle in cycles if cycle.editor)
    completed = [cycle for cycle in cycles if cycle.state == COMPLETED]

    speed = speed_benchmarks(editor_id, result.cycles, policy, generated_at)
    deadline_results = [r for r in (deadline_result(cycle, policy, generated_at) for cycle in completed) if r is not None]
    not_deadline = [cycle for cycle in completed if not deadline_eligible(cycle)]
    quality = reconstruct_quality(result, contract, generated_at)
    negative = quality_summary(editor_id, quality, result.cycles)
    deltas = {r["cycle_id"]: r for r in deadline_results}
    labels_by_item: dict[str, list[str]] = {}
    for metric in quality.occurrences:
        if metric["editor_id"] == editor_id:
            labels_by_item.setdefault(metric["evidence"]["monday_item_id"], []).append(metric["performance_label"])

    projects = []
    for cycle in sorted(cycles, key=lambda c: (c.ready_for_approval_at or "", c.monday_item_id)):
        deadline = deltas.get(cycle.cycle_id)
        projects.append({
            "monday_item_id": cycle.monday_item_id,
            "cycle_id": cycle.cycle_id,
            "state": cycle.state,
            "in_progress_at": cycle.in_progress_at,
            "ready_for_approval_at": cycle.ready_for_approval_at,
            "duration_seconds": cycle.duration_seconds,
            "cohort_key": cycle.cohort_key,
            "cohort_labels": list(cycle.video_type.canonical_labels) if cycle.video_type else [],
            "speed_eligible": speed_eligible(cycle),
            "requested_eta": cycle.requested_eta,
            "requested_eta_issue": cycle.requested_eta_issue,
            "deadline_result": deadline["metric"]["result"] if deadline else None,
            "deadline_delta_seconds": deadline["delta_seconds"] if deadline else None,
            "quality_labels": sorted(labels_by_item.get(cycle.monday_item_id, [])),
            "client_revision_events": cycle.revision_context.get("client_revision_events", 0),
            "exclusions": list(cycle.exclusions),
            "flags": list(cycle.flags),
            "evidence_event_ids": {"in_progress": cycle.in_progress_event["event_id"] if cycle.in_progress_event else None,
                                   "ready_for_approval": cycle.ready_for_approval_event["event_id"] if cycle.ready_for_approval_event else None,
                                   "editor": cycle.editor_event_id, "video_type": cycle.video_type_event_id, "requested_eta": cycle.requested_eta_event_id},
        })

    deadline_block = deadline_summary(deadline_results, not_deadline)
    states: Counter[str] = Counter()
    for cohort in speed["cohorts"]:
        states[cohort["comparison_status"]] += 1
    states["deadline_not_classifiable_insufficient_eta_precision"] = deadline_block["not_classifiable_insufficient_eta_precision"]
    states["deadline_not_classifiable_missing_eta"] = deadline_block["not_classifiable_missing_eta"]
    profile = {
        "contract_version": CONTRACT_VERSION,
        "subject_type": "editor",
        "editor": identity,
        "generated_at": generated_at,
        "executable_contract_version": contract["contract_version"],
        "source": {"system": "monday", "board_ids": sorted({cycle.monday_board_id for cycle in cycles}),
                   "retrieved_at": result.ingestion.get("retrieved_at"),
                   "history_coverage": {"activity_log_window": result.ingestion.get("activity_log_window"),
                                        "statement": "Metrics use only Monday evidence present in this ingestion."}},
        "overall": {"status": None, "rule_version": None, "note": OVERALL_NOTE},
        "speed": {"rule_version": policy.speed_rule_version, "benchmark_statistic": policy.benchmark_statistic,
                  "minimum_editor_sample_size": policy.minimum_editor_sample_size, "cohorts": speed["cohorts"], "metrics": speed["metrics"]},
        "deadline": {"rule_version": policy.deadline_rule_version, "summary": deadline_block, "results": [r["metric"] for r in deadline_results]},
        "quality": {"rule_version": contract["quality_labels"]["rule_version"], "negative": negative,
                    "positive": {"source": None, "count": 0, "note": POSITIVE_NOTE},
                    "for_bonus_context": _for_bonus_context(result, contract, {cycle.monday_item_id for cycle in completed}),
                    "occurrences": [m for m in quality.occurrences if m["editor_id"] == editor_id]},
        "revisions": {**revision_context_summary(editor_id, result.cycles), "note": REVISION_NOTE},
        "current_workload": _current_workload(result, contract, editor_id),
        "trend": _trend(completed, deadline_results),
        "coverage": {
            "completed_projects": len(completed),
            "open_projects": sum(1 for cycle in cycles if cycle.state != COMPLETED),
            "speed_eligible_projects": sum(1 for cycle in completed if speed_eligible(cycle)),
            "exclusions_by_reason": dict(Counter(reason for cycle in cycles for reason in cycle.exclusions).most_common()),
            "states": dict(states),
            "not_attributed_note": ("Projects whose Editor is unverified, unrecorded at Ready For Approval, or changed during the work are not "
                                    "attributed to any Editor and so do not appear in this profile."),
        },
        "projects": projects,
        "ai_annotation": None,
    }
    errors = validate(profile, SCHEMA)
    if errors:
        raise ProfileError(f"profile violates {SCHEMA}: {errors}")
    return profile


def profiled_editors(result: CycleReconstruction) -> list[dict[str, Any]]:
    """Editors that have at least one attributed cycle, with their completed-project counts."""
    counts: Counter[str] = Counter()
    identities: dict[str, dict[str, Any]] = {}
    for cycle in result.cycles:
        if cycle.editor_id and cycle.editor:
            identities[cycle.editor_id] = cycle.editor
            counts[cycle.editor_id] += cycle.state == COMPLETED
    return [{"editor_id": editor, "display_name": identities[editor]["display_name"], "completed_projects": counts[editor]} for editor in sorted(identities)]
