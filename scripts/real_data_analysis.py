"""Read-only analysis of an extracted Monday dataset through the Atlas pipeline.

Usage: PYTHONPATH=src python3 scripts/real_data_analysis.py <extract.json> [contract_version]

The extract is produced outside git by read-only Monday queries and has the shape
``{"retrieved_at", "activity": {"boards": [{"activity_logs": [...]}]}, "items": {"items": [...]}}``.
Output is aggregate JSON only (counts, durations, IDs); no item names or free text.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any

from atlas_commander.cycles import COMPLETED, CycleRecord
from atlas_commander.metrics import MetricPolicy, cohort_benchmark_eligibility, deadline_eligible, deadline_result, deadline_summary, speed_eligible
from atlas_commander.pipeline import reconstruct_cycles, reconstruct_quality
from atlas_commander.quality import revision_context_summary
from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION, load_contract_version

ROBUSTNESS_EXCLUSIONS = {"UNMAPPED_EDITOR", "MISSING_EDITOR_EVENT", "MISSING_EDITOR", "AMBIGUOUS_EDITOR", "EDITOR_CHANGED_WITHIN_CYCLE"}


def quantile(values: list[int], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def distribution(durations: list[int]) -> dict[str, Any]:
    hours = [value / 3600 for value in durations]
    n = len(hours)
    result: dict[str, Any] = {"n": n, "mean_h": round(mean(hours), 2), "median_h": round(median(hours), 2), "min_h": round(min(hours), 2), "max_h": round(max(hours), 2)}
    result["mean_over_median"] = round(result["mean_h"] / result["median_h"], 2) if result["median_h"] else None
    if n >= 3:
        result["p10_h"], result["p90_h"] = round(quantile(hours, 0.1), 2), round(quantile(hours, 0.9), 2)
        without_max = sorted(hours)[:-1]
        result["mean_without_max_h"] = round(mean(without_max), 2)
        result["median_without_max_h"] = round(median(without_max), 2)
        result["mean_shift_from_one_max_pct"] = round(100 * (result["mean_h"] - result["mean_without_max_h"]) / result["mean_without_max_h"], 1) if result["mean_without_max_h"] else None
        result["median_shift_from_one_max_pct"] = round(100 * (result["median_h"] - result["median_without_max_h"]) / result["median_without_max_h"], 1) if result["median_without_max_h"] else None
        result["over_3x_median"] = sum(1 for value in hours if result["median_h"] and value > 3 * result["median_h"])
    if n >= 10:
        trim = int(n * 0.1)
        trimmed = sorted(hours)[trim:n - trim]
        result["trimmed_mean_10pct_h"] = round(mean(trimmed), 2)
    return result


def cohort_table(cycles: list[CycleRecord]) -> list[dict[str, Any]]:
    groups: dict[str, list[CycleRecord]] = defaultdict(list)
    for cycle in cycles:
        assert cycle.cohort_key is not None
        groups[cycle.cohort_key].append(cycle)
    rows = []
    for key, members in sorted(groups.items(), key=lambda pair: -len(pair[1])):
        assert members[0].video_type is not None
        row = {"cohort_key": key, "labels": list(members[0].video_type.canonical_labels), "editors": len({m.editor_id for m in members if m.editor_id})}
        row.update(distribution([m.duration_seconds for m in members if m.duration_seconds is not None]))
        rows.append(row)
    return rows


def validation(result: Any, contract: dict[str, Any], calculated_at: str) -> dict[str, Any]:
    """Coverage of every metric family under one contract version (read-only, aggregate)."""
    policy = MetricPolicy.from_contract(contract)
    completed = [cycle for cycle in result.cycles if cycle.state == COMPLETED]
    measured = [cycle for cycle in completed if speed_eligible(cycle)]
    cohorts: dict[str, list[CycleRecord]] = defaultdict(list)
    for cycle in measured:
        assert cycle.cohort_key is not None
        cohorts[cycle.cohort_key].append(cycle)
    cohort_rows = []
    for key, members in sorted(cohorts.items(), key=lambda pair: -len(pair[1])):
        assert members[0].video_type is not None
        eligible, unconfirmed = cohort_benchmark_eligibility(members[0].video_type.canonical_ids, policy.video_types)
        per_editor = Counter(cycle.editor_id for cycle in members)
        cohort_rows.append({"cohort_key": key, "labels": list(members[0].video_type.canonical_labels), "benchmark_eligible": eligible,
                            "unconfirmed_ids": unconfirmed, "cycles": len(members), "editors": dict(per_editor),
                            "editors_with_at_least_minimum": sorted(editor for editor, n in per_editor.items()
                                                                    if eligible and n >= (policy.minimum_editor_sample_size or 0))})
    deadline_cycles = [cycle for cycle in completed if cycle.editor_id is not None]
    results = [r for r in (deadline_result(cycle, policy, calculated_at) for cycle in deadline_cycles) if r is not None]
    excluded = [cycle for cycle in deadline_cycles if not deadline_eligible(cycle)]
    summary = deadline_summary(results, excluded)
    summary.pop("not_evaluated")
    quality = reconstruct_quality(result, contract, calculated_at)
    editors = sorted({cycle.editor_id for cycle in completed if cycle.editor_id})
    return {
        "contract_version": contract["contract_version"],
        "completed_cycles": len(completed),
        "speed_eligible_cycles": len(measured),
        "exclusions_by_reason": dict(Counter(reason for cycle in completed for reason in cycle.exclusions).most_common()),
        "cohorts": cohort_rows,
        "benchmark_eligible_cohorts": [row["cohort_key"] for row in cohort_rows if row["benchmark_eligible"]],
        "editor_cohort_pairs_meeting_minimum": [(row["cohort_key"], editor) for row in cohort_rows for editor in row["editors_with_at_least_minimum"]],
        "resolved_editors": editors,
        "deadline": {"cycles_with_resolved_editor": len(deadline_cycles), **summary},
        "quality": {"occurrences": len(quality.occurrences), "by_editor": dict(Counter(m["editor_id"] for m in quality.occurrences)),
                    "quarantined_by_reason": dict(Counter(q["reason"] for q in quality.quarantined))},
        "revision_context": {editor: {k: v for k, v in revision_context_summary(editor, completed).items() if k != "monday_item_ids_with_client_revisions"}
                             for editor in editors},
    }


def main(path: str, version: str = ACTIVE_CONTRACT_VERSION) -> dict[str, Any]:
    data = json.load(open(path))
    contract = load_contract_version(version)
    ingestion = dict(data.get("ingestion") or {})  # an ingestion-command extract carries its coverage window
    ingestion.setdefault("retrieved_at", data.get("retrieved_at"))
    result = reconstruct_cycles(data["activity"], contract, items_payload=data.get("items"), ingestion=ingestion)
    completed = [cycle for cycle in result.cycles if cycle.state == COMPLETED]
    timing_valid = [cycle for cycle in completed if cycle.cohort_key and not (set(cycle.exclusions) - ROBUSTNESS_EXCLUSIONS)]
    fully_eligible = [cycle for cycle in completed if cycle.cohort_key and not cycle.exclusions]

    editor_labels: dict[str, Counter[str]] = defaultdict(Counter)
    for cycle in completed:
        exception = cycle.editor_exception or {}
        ids = tuple(exception.get("person_ids") or ([cycle.editor["monday_person_id"]] if cycle.editor else []))
        editor_labels[":".join(ids) or "(none)"][cycle.editor_exception["code"] if cycle.editor_exception else ("resolved" if cycle.editor else "|".join(cycle.exclusions))] += 1

    quarantined = Counter()
    for entry in result.quarantined_status_logs:
        raw = entry["raw_source"]
        value = raw.get("data", {}).get("value") if isinstance(raw.get("data"), dict) else None
        label = value.get("label", {}).get("text") if isinstance(value, dict) and isinstance(value.get("label"), dict) else None
        quarantined[(entry["reason"], label)] += 1

    transitions = Counter((event["raw_from_status"], event["raw_to_status"]) for event in result.status_events)
    actors: dict[tuple[str | None, str], Counter[str]] = defaultdict(Counter)
    for event in result.status_events:
        actors[(event["raw_from_status"], event["raw_to_status"])][str(event.get("actor_monday_id"))] += 1
    key_transitions = [("Create File", "In Progress"), ("Ready For Approval", "Ready To Send"), ("Ready For Approval", "Ready To Sent"),
                       ("Ready For Approval", "ready to sent"), ("Ready For Approval", "Sent"), ("Ready To Send", "Sent"), ("In Progress", "Ready For Approval")]

    return {
        "retrieved_at": data.get("retrieved_at"),
        "validation": validation(result, contract, str(data.get("retrieved_at"))),
        "status_events": len(result.status_events),
        "quarantined_status_logs": {f"{reason}:{label}": count for (reason, label), count in quarantined.most_common()},
        "cycles": dict(Counter(cycle.state for cycle in result.cycles)),
        "completed_exclusions": dict(Counter(reason for cycle in completed for reason in cycle.exclusions)),
        "completed_flags": dict(Counter(flag for cycle in completed for flag in cycle.flags)),
        "completed": len(completed),
        "fully_eligible_completed": len(fully_eligible),
        "timing_valid_completed_ignoring_editor_identity": len(timing_valid),
        "editor_label_outcomes_in_completed_cycles": {label: dict(outcomes) for label, outcomes in sorted(editor_labels.items(), key=lambda pair: -sum(pair[1].values()))},
        "benchmark_statistic_by_cohort_fully_eligible": cohort_table(fully_eligible),
        "benchmark_statistic_by_cohort_timing_valid": cohort_table(timing_valid),
        "transitions_into_in_progress": {f"{a} -> {b}": n for (a, b), n in transitions.most_common() if b == "In Progress"},
        "transitions_out_of_ready_for_approval": {f"{a} -> {b}": n for (a, b), n in transitions.most_common() if a == "Ready For Approval"},
        "actors_by_transition": {f"{a} -> {b}": dict(actors[(a, b)].most_common(6)) for a, b in key_transitions if (a, b) in actors},
    }


if __name__ == "__main__":
    json.dump(main(sys.argv[1], *sys.argv[2:3]), sys.stdout, indent=1)
    print()
