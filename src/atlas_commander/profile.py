"""Editor Profile (evidence API) built only from deterministic Atlas results.

The builder assembles what the metric engine already computed. It adds no score, no
weighting and no inferred fact. Anything that could not be measured appears in
``coverage`` and in the per-project rows with its reason, instead of being hidden.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from atlas_commander.contracts import validate
from atlas_commander.cycles import COMPLETED, ETA_AT_READY_FOR_APPROVAL, LATEST_ETA, CyclePolicy, CycleRecord, parse_time
from atlas_commander.intelligence import (
    IntelligencePolicy,
    deadline_component,
    evaluation_cohort,
    overall_status,
    quality_component,
    quality_rates,
    recent_change,
    speed_benchmarks_v15,
    speed_component,
)
from atlas_commander.metrics import (
    MetricPolicy,
    classify_deadline,
    cohort_benchmark_eligibility,
    deadline_eligible,
    deadline_result,
    deadline_summary,
    median_seconds,
    speed_benchmarks,
    speed_eligible,
)
from atlas_commander.monday_source import dropdown_value_ids
from atlas_commander.pipeline import CycleReconstruction, reconstruct_quality
from atlas_commander.publication import build_publication_view
from atlas_commander.quality import QualityResult, quality_summary, revision_context_summary

CONTRACT_VERSION = "1.4.0"
SCHEMA = "editor-profile-v1.4.schema.json"
# Profile contract per Requested ETA selection rule, so an earlier executable contract reproduces its original profile.
PROFILE_CONTRACTS = {
    "1.3.0": "editor-profile-v1.3.schema.json",
    "1.4.0": SCHEMA,
    "1.5.0": "editor-profile-v1.5.schema.json",
}
OVERALL_NOTE = ("No overall performance status rule is approved for Atlas V1. The Editor's picture is the speed, deadline "
                "and quality sections below, each with its own sample size and Monday evidence.")
POSITIVE_NOTE = "No approved positive quality signal exists in V1; For Bonus is context only and does not affect quality."
REVISION_NOTE = "Revision activity is context only. It does not imply Editor fault and never affects any metric or conclusion."
ACTIVE_WORK_STATUSES = ("In Progress", "Revisions", "Internal Revisions")
AWAITING_APPROVAL_STATUS = "Ready For Approval"
NON_ACTIVE_STATUSES = (
    "Waiting", "Create File", "Captions In Progress", "Captions Revisions", "Waiting For Captions", "Captions Done",
    "TOPAZ", "Ready To Send", "Sent", "Done",
)
CAIRO = ZoneInfo("Africa/Cairo")


class ProfileError(ValueError):
    pass


def _editor_cycles(cycles: list[CycleRecord], editor_id: str) -> list[CycleRecord]:
    return [cycle for cycle in cycles if cycle.editor_id == editor_id]


def _for_bonus_context(result: CycleReconstruction, contract: Mapping[str, Any], item_ids: set[str]) -> dict[str, Any]:
    column = contract["quality_labels"].get("for_bonus", {}).get("column_id")
    snapshots = result.item_snapshots.get(column, {}) if column else {}
    projects = sorted(item for item in item_ids if dropdown_value_ids((snapshots.get(item) or {}).get("value")))
    if str(contract.get("contract_version")) == "1.5.0":
        return {"affects_quality": "per-label", "classification": "per-label-registry", "column_id": column, "projects": projects,
                "note": "For Bonus is a storage column. Each label is classified independently as Positive or Context; On Time Delivery remains visible but is not scored in Quality."}
    return {"affects_quality": False, "classification": "context-unclassified", "column_id": column, "projects": projects,
            "note": "For Bonus labels are shown as context only in V1 (approved decision); they are neither positive nor negative quality signals."}


def _current_editor(snapshot: Mapping[str, Any] | None, policy: CyclePolicy) -> str | None:
    """Editor for an item's *current* Editor Name value (current state only, never used for past work)."""
    ids = dropdown_value_ids((snapshot or {}).get("value"))
    if len(ids) != 1:
        return None
    names = [name.strip() for name in str((snapshot or {}).get("text") or "").split(",") if name.strip()]
    if policy.identity.strict_name_key and len(names) != 1:
        return None
    candidates = policy.identity.candidates(ids[0], names[0] if policy.identity.strict_name_key else None)
    if len(candidates) != 1:
        return None
    entry = candidates[0]
    if entry.label_names and (len(names) != 1 or names[0] not in entry.label_names):
        return None
    return entry.editor_id


def _current_workload(result: CycleReconstruction, contract: Mapping[str, Any], editor_id: str, *, v15: bool = False) -> dict[str, Any]:
    board = contract["source_board"]
    policy = CyclePolicy.from_contract(contract)
    editors = result.item_snapshots.get(board["editor_column_id"], {})
    statuses = result.item_snapshots.get(board["status_column_id"], {})
    by_status: dict[str, list[str]] = {}
    status_evidence: dict[str, str] = {}
    for item_id, snapshot in sorted(editors.items()):
        if _current_editor(snapshot, policy) != editor_id:
            continue
        status_snapshot = statuses.get(item_id) or {}
        label = str(status_snapshot.get("text") or "(no status)")
        by_status.setdefault(label, []).append(item_id)
        if status_snapshot.get("evidence_id"):
            status_evidence[item_id] = str(status_snapshot["evidence_id"])
    if not v15:
        return {"as_of": result.ingestion.get("retrieved_at"), "basis": "current Monday Editor Name and Status values of each item",
                "by_current_status": by_status,
                "note": "Descriptive only. Which statuses count as the Editor's active workload is not defined in V1, so no capacity judgement is made."}

    active = {status: list(by_status.get(status, [])) for status in ACTIVE_WORK_STATUSES}
    awaiting = list(by_status.get(AWAITING_APPROVAL_STATUS, []))
    excluded = {status: list(items) for status, items in sorted(by_status.items())
                if status not in ACTIVE_WORK_STATUSES and status != AWAITING_APPROVAL_STATUS}
    active_ids = sorted(item for items in active.values() for item in items)
    return {
        "as_of": result.ingestion.get("retrieved_at"),
        "basis": "current Monday Editor Name and exact Status values of each item",
        # Compatibility summary for existing dashboard consumers. In 1.5 this contains Active Work only.
        "by_current_status": active,
        "active_work": {
            "count": len(active_ids), "by_status": active, "monday_item_ids": active_ids,
            "evidence_refs": [status_evidence[item_id] for item_id in active_ids if item_id in status_evidence],
        },
        "awaiting_approval": {
            "count": len(awaiting), "status": AWAITING_APPROVAL_STATUS, "monday_item_ids": awaiting,
            "evidence_refs": [status_evidence[item_id] for item_id in awaiting if item_id in status_evidence],
        },
        "excluded_from_active": {
            "count": sum(len(items) for items in excluded.values()), "by_status": excluded,
            "approved_non_active_statuses": list(NON_ACTIVE_STATUSES),
            "reason": "current status is not approved as Active Work",
        },
        "capacity_classification": {
            "value": None, "availability": "rule_not_approved",
            "reason": "No capacity threshold is approved; only factual project counts are shown.",
        },
        "note": ("Active Work is limited to In Progress, Revisions and Internal Revisions. Ready For Approval is Awaiting Approval. "
                 "All other statuses are excluded, and no capacity judgement is made."),
    }


def _revision_context(editor_id: str, cycles: list[CycleRecord], *, v15: bool) -> dict[str, Any]:
    summary = revision_context_summary(editor_id, cycles)
    if not v15:
        return {**summary, "note": REVISION_NOTE}
    mine = [cycle for cycle in cycles if cycle.state == COMPLETED and cycle.editor_id == editor_id]

    def kind(name: str) -> dict[str, Any]:
        count_key = f"{name}_revision_events"
        selected = [cycle for cycle in mine if cycle.revision_context.get(count_key, 0)]
        event_ids = sorted(event_id for cycle in selected for event_id in cycle.revision_context.get(f"{name}_revision_event_ids", []))
        return {
            "projects": len(selected),
            "events": sum(cycle.revision_context.get(count_key, 0) for cycle in selected),
            "monday_item_ids": sorted(cycle.monday_item_id for cycle in selected),
            "evidence_event_ids": event_ids,
            "affects_scoring": False,
        }

    client, internal = kind("client"), kind("internal")
    return {
        **summary,
        "client": client,
        "internal": internal,
        "total_revision_activity": {
            "projects": len(set(client["monday_item_ids"]) | set(internal["monday_item_ids"])),
            "events": client["events"] + internal["events"],
            "affects_scoring": False,
        },
        "note": REVISION_NOTE,
    }


def _metric_coverage(completed: list[CycleRecord], deadline_results: list[dict[str, Any]], policy: MetricPolicy,
                     quality: QualityResult) -> dict[str, Any]:
    def benchmark_eligible(cycle: CycleRecord) -> bool:
        return bool(
            speed_eligible(cycle)
            and cycle.video_type is not None
            and cohort_benchmark_eligibility(cycle.video_type.canonical_ids, policy.video_types)[0]
        )

    speed_included = [cycle for cycle in completed if benchmark_eligible(cycle)]
    speed_reasons: Counter[str] = Counter()
    for cycle in completed:
        if cycle in speed_included:
            continue
        reasons = list(cycle.exclusions)
        if speed_eligible(cycle) and (cycle.video_type is None or not cohort_benchmark_eligibility(cycle.video_type.canonical_ids, policy.video_types)[0]):
            reasons.append("cohort_not_benchmark_eligible")
        for reason in reasons or ["NOT_SPEED_ELIGIBLE"]:
            speed_reasons[reason] += 1
    deadline_included = {result["cycle_id"] for result in deadline_results}
    deadline_reasons: Counter[str] = Counter()
    for cycle in completed:
        if cycle.cycle_id in deadline_included:
            continue
        reasons = list(cycle.exclusions)
        if cycle.requested_eta_issue:
            reasons.append(cycle.requested_eta_issue)
        for reason in reasons or ["NOT_DEADLINE_CLASSIFIABLE"]:
            deadline_reasons[reason] += 1

    def block(included: int, reasons: Counter[str]) -> dict[str, Any]:
        eligible = len(completed)
        return {
            "eligible_records": eligible,
            "included_records": included,
            "excluded_records": eligible - included,
            "exclusion_reasons": dict(sorted(reasons.items())),
            "coverage_ratio": round(included / eligible, 4) if eligible else None,
        }

    item_ids = {cycle.monday_item_id for cycle in completed}
    quality_quarantine = [entry for entry in quality.quarantined if entry.get("monday_item_id") in item_ids]
    quality_reasons = Counter(str(entry.get("reason") or "UNKNOWN_QUALITY_QUARANTINE") for entry in quality_quarantine)
    quality_coverage = block(len(completed), Counter())
    quality_coverage.update({
        "availability": "available",
        "reason": "Every eligible completed project is retained in the Quality denominator, including projects with no quality labels.",
        "quarantined_label_occurrences": len(quality_quarantine),
        "quarantined_label_reasons": dict(sorted(quality_reasons.items())),
    })
    return {
        "speed": block(len(speed_included), speed_reasons),
        "deadline": block(len(deadline_results), deadline_reasons),
        "quality": quality_coverage,
        "classification": {
            "overall_status": {
                "value": None,
                "availability": "rule_not_approved",
                "reason": "Contract 1.5 thresholds remain unapproved; factual component results stay visible.",
            }
        },
        "rule_versions": {"speed": policy.speed_rule_version, "deadline": policy.deadline_rule_version},
    }


def _share(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


def _trend(cycles: list[CycleRecord], deadline_results: list[dict[str, Any]], policy: MetricPolicy, *, cairo: bool = False) -> dict[str, Any]:
    def month(value: str) -> str:
        return parse_time(value).astimezone(CAIRO).strftime("%Y-%m") if cairo else value[:7]

    speed: dict[tuple[str, str], list[int]] = {}
    not_eligible = 0
    for cycle in cycles:
        if not (speed_eligible(cycle) and cycle.ready_for_approval_at and cycle.cohort_key and cycle.video_type and cycle.duration_seconds is not None):
            continue
        if not cohort_benchmark_eligibility(cycle.video_type.canonical_ids, policy.video_types)[0]:
            not_eligible += 1
            continue
        speed.setdefault((cycle.cohort_key, month(cycle.ready_for_approval_at)), []).append(cycle.duration_seconds)
    deadline: dict[str, Counter[str]] = {}
    for result in deadline_results:
        result_month = month(result["metric"]["ready_for_approval_at"])
        deadline.setdefault(result_month, Counter())[classify_deadline(result["delta_seconds"])] += 1
    deadline_rows = []
    for month_key, counts in sorted(deadline.items()):
        evaluated = sum(counts.values())
        deadline_rows.append({"month": month_key, "evaluated": evaluated, "early": counts["early"], "on_time": counts["on_time"], "late": counts["late"],
                              "early_rate": _share(counts["early"], evaluated), "on_time_rate": _share(counts["on_time"], evaluated),
                              "late_rate": _share(counts["late"], evaluated)})
    return {
        "speed_by_cohort_month": [{"cohort_key": key, "month": month, "projects": len(values), "median_seconds": median_seconds(values)}
                                  for (key, month), values in sorted(speed.items())],
        "speed_projects_not_shown": {"cohort_not_benchmark_eligible": not_eligible},
        "deadline_by_month": deadline_rows,
        "note": (("Monthly figures (Africa/Cairo month of Ready For Approval)" if cairo else "Monthly figures (UTC month of Ready For Approval)")
                 + " with their sample sizes. Speed is shown only per exact benchmark-eligible "
                 "Video Type cohort, never pooled across cohorts. No trend conclusion or judgement is drawn."),
    }


def _quality_class_result(result: QualityResult, label_class: str, item_ids: set[str]) -> QualityResult:
    return QualityResult(
        occurrences=[
            metric for metric in result.occurrences
            if metric["editor_id"] and metric["evidence"]["monday_item_id"] in item_ids
            and metric["evidence"]["source_values"].get("label_class", "Negative") == label_class
        ],
        quarantined=list(result.quarantined),
    )


def _v15_intelligence(result: CycleReconstruction, contract: Mapping[str, Any], editor_id: str, generated_at: str,
                      quality: QualityResult, metric_policy: MetricPolicy) -> dict[str, Any]:
    """Build the language-neutral D23--D45 blocks from the real 1.5 contract."""
    policy = IntelligencePolicy.from_contract(contract)
    cohorts = evaluation_cohort(result.cycles, generated_at, policy.window_days, policy.window_rule_version)
    current = cohorts["current"]
    comparison = cohorts["comparison"]
    current_facts = quality_rates(editor_id, quality.occurrences, current)
    comparison_facts = quality_rates(editor_id, quality.occurrences, comparison)
    quality_state = quality_component(current_facts, policy.quality)
    speed_facts = speed_benchmarks_v15(editor_id, current, metric_policy.video_types, policy.speed, generated_at)
    speed_state = speed_component(speed_facts["cohorts"], policy.speed)

    def deadline_rows(cycles: list[CycleRecord]) -> list[dict[str, Any]]:
        return [row for row in (deadline_result(cycle, metric_policy, generated_at) for cycle in cycles) if row is not None]

    current_deadlines = deadline_rows(current)
    comparison_deadlines = deadline_rows(comparison)
    deadline_state = deadline_component(editor_id, current_deadlines, policy.deadline)
    components = {"quality": quality_state, "speed": speed_state, "deadline": deadline_state}
    overall = overall_status(components, policy.overall)
    if policy.overall and policy.overall.get("threshold_status") == "rule_not_approved":
        overall = {**overall, "status": "Not enough approved logic to classify", "reason": "rule_not_approved"}

    def editor_late_rate(rows: list[dict[str, Any]]) -> float | None:
        mine = [row for row in rows if row["metric"]["editor_id"] == editor_id]
        return round(sum(row["metric"]["result"] == "late" for row in mine) / len(mine), 4) if mine else None

    current_editor_cycles = [cycle for cycle in current if cycle.editor_id == editor_id]
    comparison_editor_cycles = [cycle for cycle in comparison if cycle.editor_id == editor_id]
    current_deadline_sample = sum(row["metric"]["editor_id"] == editor_id for row in current_deadlines)
    comparison_deadline_sample = sum(row["metric"]["editor_id"] == editor_id for row in comparison_deadlines)
    changes: dict[str, Any] = {
        "positive_quality_rate": recent_change(current_facts["positive_rate"], comparison_facts["positive_rate"],
                                               "positive_quality_rate", policy.trend,
                                               current_sample=current_facts["eligible_completed_projects"],
                                               comparison_sample=comparison_facts["eligible_completed_projects"]),
        "negative_quality_rate": recent_change(current_facts["negative_rate"], comparison_facts["negative_rate"],
                                               "negative_quality_rate", policy.trend,
                                               current_sample=current_facts["eligible_completed_projects"],
                                               comparison_sample=comparison_facts["eligible_completed_projects"]),
        "late_rate": recent_change(editor_late_rate(current_deadlines), editor_late_rate(comparison_deadlines),
                                   "late_rate", policy.trend, current_sample=current_deadline_sample,
                                   comparison_sample=comparison_deadline_sample),
    }

    def speed_values(cycles: list[CycleRecord]) -> dict[str, list[int]]:
        values: dict[str, list[int]] = {}
        for cycle in cycles:
            if not (cycle.editor_id == editor_id and speed_eligible(cycle) and cycle.video_type is not None and cycle.cohort_key
                    and cycle.duration_seconds is not None
                    and cohort_benchmark_eligibility(cycle.video_type.canonical_ids, metric_policy.video_types)[0]):
                continue
            values.setdefault(cycle.cohort_key, []).append(cycle.duration_seconds)
        return values

    current_speed, comparison_speed = speed_values(current_editor_cycles), speed_values(comparison_editor_cycles)
    speed_trend_rule = {**(policy.trend or {}), "lower_is_better": True}
    changes["speed_by_video_type"] = [
        {
            "cohort_key": cohort_key,
            "current_median_seconds": median_seconds(current_speed.get(cohort_key, [])),
            "comparison_median_seconds": median_seconds(comparison_speed.get(cohort_key, [])),
            "current_projects": len(current_speed.get(cohort_key, [])),
            "comparison_projects": len(comparison_speed.get(cohort_key, [])),
            "change": recent_change(
                median_seconds(current_speed.get(cohort_key, [])), median_seconds(comparison_speed.get(cohort_key, [])),
                "median_speed_seconds", speed_trend_rule,
                current_sample=len(current_speed.get(cohort_key, [])), comparison_sample=len(comparison_speed.get(cohort_key, [])),
            ),
        }
        for cohort_key in sorted(set(current_speed) | set(comparison_speed))
    ]
    return {
        "window": cohorts["windows"],
        "coverage": cohorts["coverage"],
        "quality_facts": current_facts,
        "speed_facts": speed_facts,
        "components": components,
        "overall": overall,
        "recent_change": changes,
        "current_cycles": current,
    }


def build_editor_profile(result: CycleReconstruction, contract: Mapping[str, Any], editor_id: str, generated_at: str) -> dict[str, Any]:
    """Contract-valid Editor Profile for one Editor from a cycle reconstruction.

    editor-profile 1.4.0 under the frozen-ETA deadline rule (contract 1.4.0); 1.3.0 under the
    earlier latest-ETA rule, so contract 1.3.0 still reproduces its original output."""
    policy = MetricPolicy.from_contract(contract)
    frozen = policy.requested_eta_selection == ETA_AT_READY_FOR_APPROVAL
    if contract["contract_version"] == "1.5.0":
        profile_version = "1.5.0"
    else:
        profile_version = "1.3.0" if policy.requested_eta_selection == LATEST_ETA else CONTRACT_VERSION
    profile_schema = PROFILE_CONTRACTS[profile_version]
    v15 = profile_version == "1.5.0"
    cycles = _editor_cycles(result.cycles, editor_id)
    if not cycles:
        raise ProfileError(f"no cycle is attributed to {editor_id}; unresolved Editors have no profile")
    identity = next(cycle.editor for cycle in cycles if cycle.editor)
    completed = [cycle for cycle in cycles if cycle.state == COMPLETED]

    quality = reconstruct_quality(result, contract, generated_at)
    intelligence = _v15_intelligence(result, contract, editor_id, generated_at, quality, policy) if v15 else None
    metric_cycles = ([cycle for cycle in intelligence["current_cycles"] if cycle.editor_id == editor_id]
                     if intelligence is not None else completed)
    if v15 and intelligence is not None:
        raw_speed = intelligence["speed_facts"]
        labels_by_cohort = {
            cycle.cohort_key: list(cycle.video_type.canonical_labels)
            for cycle in intelligence["current_cycles"] if cycle.cohort_key and cycle.video_type
        }
        speed_rows = []
        for row in raw_speed["cohorts"]:
            verdict = row["verdict"]
            conclusion = {"Faster": "faster_than_team_median", "Similar": "equal_to_team_median",
                          "Slower": "slower_than_team_median"}.get(verdict, "not_comparable")
            speed_rows.append({
                "cohort_key": row["cohort_key"], "cohort_labels": labels_by_cohort.get(row["cohort_key"], []),
                "video_type_mapping_version": policy.video_types.mapping_version if policy.video_types else None,
                "editor_sample_size": row["editor_sample_size"], "editor_median_seconds": row["editor_median_seconds"],
                "team_sample_size": row["comparator_sample_size"], "team_editor_count": row["comparator_editor_count"],
                "team_median_seconds": row["comparator_median_seconds"],
                "editor_minus_team_median_seconds": row["editor_minus_comparator_seconds"],
                "editor_vs_team_median_pct": row["editor_vs_comparator_pct"], "team_typical_range_seconds": None,
                "editor_range_seconds": None, "team_includes_subject_editor": False, "benchmark_statistic": "median",
                "benchmark_eligible": True, "unconfirmed_video_type_ids": [],
                "minimum_editor_sample_size": None,
                "comparison_status": ("minimum_sample_size_not_configured" if row["reason"] == "rule_not_approved"
                                      else row["reason"] or "comparable"),
                "conclusion": conclusion, "editor_cycle_ids": list(row["evidence"]["editor_cycle_ids"]),
                "team_cycle_ids": list(row["evidence"]["comparator_cycle_ids"]),
                "benchmark": "descriptive leave-one-out median of other eligible Editors; not an SLA",
                "rule_version": row["rule_version"],
            })
        speed = {"cohorts": speed_rows, "metrics": []}
    else:
        speed = speed_benchmarks(editor_id, result.cycles, policy, generated_at)
    deadline_results = [r for r in (deadline_result(cycle, policy, generated_at) for cycle in metric_cycles) if r is not None]
    not_deadline = [cycle for cycle in metric_cycles if not deadline_eligible(cycle)]
    positive: dict[str, Any] | None
    context: dict[str, Any] | None
    if v15:
        item_ids = {cycle.monday_item_id for cycle in metric_cycles}
        negative = quality_summary(editor_id, _quality_class_result(quality, "Negative", item_ids), metric_cycles)
        positive = quality_summary(editor_id, _quality_class_result(quality, "Positive", item_ids), metric_cycles)
        context = quality_summary(editor_id, _quality_class_result(quality, "Context", item_ids), metric_cycles)
    else:
        negative = quality_summary(editor_id, quality, result.cycles)
        positive = context = None
    deltas = {r["cycle_id"]: r for r in deadline_results}
    labels_by_item: dict[str, list[str]] = {}
    metric_item_ids = {cycle.monday_item_id for cycle in metric_cycles}
    for metric in quality.occurrences:
        if metric["editor_id"] == editor_id and (not v15 or metric["evidence"]["monday_item_id"] in metric_item_ids):
            labels_by_item.setdefault(metric["evidence"]["monday_item_id"], []).append(metric["performance_label"])

    projects = []
    for cycle in sorted(cycles, key=lambda c: (c.ready_for_approval_at or "", c.monday_item_id)):
        deadline = deltas.get(cycle.cycle_id)
        row = {
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
        }
        if frozen:
            row["requested_eta_observed_at"] = cycle.requested_eta_observed_at
            row["requested_eta_changes_ignored_after_ready_for_approval"] = len(cycle.requested_eta_ignored_after_ready_for_approval)
        projects.append(row)

    deadline_block = deadline_summary(deadline_results, not_deadline)
    states: Counter[str] = Counter()
    for cohort in speed["cohorts"]:
        states[cohort["comparison_status"]] += 1
    states["deadline_not_classifiable_insufficient_eta_precision"] = deadline_block["not_classifiable_insufficient_eta_precision"]
    states["deadline_not_classifiable_missing_eta"] = deadline_block["not_classifiable_missing_eta"]
    profile = {
        "contract_version": profile_version,
        "subject_type": "editor",
        "editor": identity,
        "generated_at": generated_at,
        "executable_contract_version": contract["contract_version"],
        "source": {"system": "monday", "board_ids": sorted({cycle.monday_board_id for cycle in cycles}),
                   "retrieved_at": result.ingestion.get("retrieved_at"),
                   "history_coverage": {"activity_log_window": result.ingestion.get("activity_log_window"),
                                        "statement": "Metrics use only Monday evidence present in this ingestion."}},
        "overall": ({**intelligence["overall"], "note": OVERALL_NOTE} if intelligence is not None
                    else {"status": None, "rule_version": None, "note": OVERALL_NOTE}),
        "speed": {"rule_version": policy.speed_rule_version, "benchmark_statistic": policy.benchmark_statistic,
                  "minimum_editor_sample_size": policy.minimum_editor_sample_size, "cohorts": speed["cohorts"], "metrics": speed["metrics"],
                  **({"leave_one_out": True, "minimum_comparator_sample_size": None,
                      "component": intelligence["components"]["speed"]} if intelligence is not None else {})},
        "deadline": {"rule_version": policy.deadline_rule_version, "summary": deadline_block, "results": [r["metric"] for r in deadline_results],
                     **({"requested_eta_selection": policy.requested_eta_selection} if frozen else {}),
                     **({"component": intelligence["components"]["deadline"]} if intelligence is not None else {})},
        "quality": {"rule_version": contract["quality_labels"]["rule_version"], "negative": negative,
                    "positive": ({**positive, "count": positive["total_occurrences"], "note": "Positive labels are Monday evidence; deadline labels are visible but not scored in Quality."}
                                 if positive is not None else {"source": None, "count": 0, "note": POSITIVE_NOTE}),
                    **({"context": context, "rates": intelligence["quality_facts"],
                        "component": intelligence["components"]["quality"]} if intelligence is not None else {}),
                    "for_bonus_context": _for_bonus_context(result, contract, {cycle.monday_item_id for cycle in completed}),
                    "occurrences": [m for m in quality.occurrences if m["editor_id"] == editor_id
                                    and (not v15 or m["evidence"]["monday_item_id"] in metric_item_ids)]},
        "revisions": _revision_context(editor_id, result.cycles, v15=v15),
        "current_workload": _current_workload(result, contract, editor_id, v15=v15),
        "trend": {**_trend(metric_cycles, deadline_results, policy, cairo=v15),
                  **({"window": intelligence["window"], "recent_change": intelligence["recent_change"],
                      "classification": {"value": None, "availability": "rule_not_approved"}}
                     if intelligence is not None else {})},
        "coverage": {
            "completed_projects": len(completed),
            "open_projects": sum(1 for cycle in cycles if cycle.state != COMPLETED),
            "speed_eligible_projects": sum(
                1 for cycle in completed
                if speed_eligible(cycle) and cycle.video_type is not None
                and cohort_benchmark_eligibility(cycle.video_type.canonical_ids, policy.video_types)[0]
            ) if v15 else sum(1 for cycle in completed if speed_eligible(cycle)),
            "exclusions_by_reason": dict(Counter(reason for cycle in cycles for reason in cycle.exclusions).most_common()),
            "states": dict(states),
            "not_attributed_note": ("Projects whose Editor is unverified, unrecorded at Ready For Approval, or changed during the work are not "
                                    "attributed to any Editor and so do not appear in this profile."),
        },
        "projects": projects,
        "ai_annotation": None,
    }
    if v15:
        assert intelligence is not None
        profile["publication"] = build_publication_view(result, contract, generated_at)
        profile["coverage"]["metrics"] = _metric_coverage(metric_cycles, deadline_results, policy, quality)
        profile["coverage"]["window"] = intelligence["coverage"]
    errors = validate(profile, profile_schema)
    if errors:
        raise ProfileError(f"profile violates {profile_schema}: {errors}")
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
