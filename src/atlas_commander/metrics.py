"""Deterministic Editor metrics derived from reconstructed work cycles.

* Deadline: ``delta_seconds = ready_for_approval_at - latest_requested_eta``. The result
  is ``early`` when the delta is negative, ``on_time`` only when it is exactly zero, and
  ``late`` when it is positive; there is no tolerance. A missing or date-only ETA yields
  no result. The Requested ETA values observed in the ingested evidence travel with the
  result, together with how complete that history is known to be.
* Speed: only the first completed cycle of each item, only within the exact Video Type
  cohort. The team benchmark is the descriptive median of every eligible cycle in that
  cohort. A faster/slower conclusion is made only when the configured minimum Editor
  sample size is set and met; otherwise raw values and sample sizes are reported with
  no conclusion.

Revisions never enter these calculations.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from statistics import median
from typing import Any

from atlas_commander.contracts import validate
from atlas_commander.cycles import COMPLETED, CycleRecord, parse_time
from atlas_commander.video_type import VideoTypeMapping, partition_by_cohort

CONTRACT_VERSION = "1.0.0"
DEADLINE_CONTRACT_VERSION = "1.1.0"
DEADLINE_SCHEMA = "deadline-metric-v1.1.schema.json"
EARLY = "early"
ON_TIME = "on_time"
LATE = "late"

COMPARABLE = "comparable"
THRESHOLD_NOT_CONFIGURED = "minimum_sample_size_not_configured"
INSUFFICIENT_SAMPLE = "insufficient_editor_sample"
COHORT_NOT_BENCHMARK_ELIGIBLE = "cohort_not_benchmark_eligible"
INSUFFICIENT_SAMPLE_CONCLUSION = "insufficient_sample"
NOT_COMPARABLE_CONCLUSION = "not_comparable"
NOT_CLASSIFIABLE_ETA_PRECISION = "not_classifiable_insufficient_eta_precision"
NOT_CLASSIFIABLE_MISSING_ETA = "not_classifiable_missing_eta"
NOT_EVALUATED = "not_evaluated"
FASTER = "faster_than_team_median"
SLOWER = "slower_than_team_median"
EQUAL = "equal_to_team_median"


@dataclass(frozen=True)
class MetricPolicy:
    deadline_rule_version: str
    speed_rule_version: str
    minimum_editor_sample_size: int | None
    status_column_id: str
    requested_eta_column_id: str
    video_type_column_id: str
    video_types: VideoTypeMapping | None = None
    benchmark_statistic: str = "median"

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> MetricPolicy:
        deadline = contract["deadline"]
        speed = contract["speed_benchmark"]
        if deadline.get("requested_eta_selection") != "latest-available-requested-eta":
            raise ValueError("deadline policy must select the latest available Requested ETA")
        if speed.get("cohort") != "exact-video-type-cohort-only":
            raise ValueError("speed benchmark must compare within the exact Video Type cohort only")
        minimum = speed.get("minimum_editor_sample_size")
        if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1):
            raise ValueError("minimum_editor_sample_size must be null or a positive integer")
        statistic = speed.get("benchmark_statistic", "median")
        if statistic != "median":
            raise ValueError("only the median benchmark statistic is implemented")
        board = contract["source_board"]
        return cls(deadline["rule_version"], speed["rule_version"], minimum, board["status_column_id"], board["requested_eta_column_id"],
                   board["video_type_column_id"], VideoTypeMapping.from_contract(contract), statistic)


def cohort_benchmark_eligibility(canonical_ids: Iterable[str], mapping: VideoTypeMapping | None) -> tuple[bool, list[str]]:
    """A cohort may be benchmarked only when every label is a confirmed base type or modifier and at
    least one is a confirmed base type. Returns (eligible, unconfirmed label IDs)."""
    ids = list(canonical_ids)
    classes = mapping.classification if mapping is not None else {}
    unconfirmed = [value for value in ids if value not in classes]
    return (bool(ids) and not unconfirmed and any(classes[value] == "base" for value in ids)), unconfirmed


def median_seconds(values: Iterable[int]) -> int | None:
    values = list(values)
    return math.floor(median(values)) if values else None


def speed_eligible(cycle: CycleRecord) -> bool:
    return cycle.state == COMPLETED and cycle.editor_id is not None and cycle.cohort_key is not None and not cycle.exclusions


def deadline_eligible(cycle: CycleRecord) -> bool:
    blocking = [reason for reason in cycle.exclusions if reason not in {"MISSING_VIDEO_TYPE_EVENT", "UNMAPPED_VIDEO_TYPE", "MISSING_VIDEO_TYPE",
                                                                         "DUPLICATE_VIDEO_TYPE", "VIDEO_TYPE_LABEL_ID_MISMATCH", "INVALID_VIDEO_TYPE_VALUE"}]
    return cycle.state == COMPLETED and cycle.editor_id is not None and cycle.requested_eta is not None and not blocking


def classify_deadline(delta_seconds: int) -> str:
    """Exact classification with no tolerance: <0 early, ==0 on time, >0 late."""
    if delta_seconds < 0:
        return EARLY
    return ON_TIME if delta_seconds == 0 else LATE


def deadline_result(cycle: CycleRecord, policy: MetricPolicy, calculated_at: str) -> dict[str, Any] | None:
    """Deadline result for one cycle, or None when it is not eligible (e.g. missing ETA)."""
    if not deadline_eligible(cycle):
        return None
    assert cycle.ready_for_approval_at is not None and cycle.requested_eta is not None and cycle.editor_id is not None
    ready = cycle.ready_for_approval_at
    delta = int((parse_time(ready) - parse_time(cycle.requested_eta)).total_seconds())
    event_ids = [cycle.ready_for_approval_event["event_id"]] if cycle.ready_for_approval_event else []
    if cycle.requested_eta_event_id and cycle.requested_eta_event_id not in event_ids:
        event_ids.append(cycle.requested_eta_event_id)
    metric = {
        "contract_version": DEADLINE_CONTRACT_VERSION,
        "metric_name": "deadline",
        "editor_id": cycle.editor_id,
        "ready_for_approval_at": ready,
        "requested_eta": cycle.requested_eta,
        "requested_eta_selection": "latest-available-requested-eta",
        "delta_seconds": delta,
        "result": classify_deadline(delta),
        "evidence": {
            "source": "monday",
            "monday_board_id": cycle.monday_board_id,
            "monday_item_id": cycle.monday_item_id,
            "column_ids": [policy.status_column_id, policy.requested_eta_column_id],
            "event_ids": event_ids,
            "source_timestamps": [ready],
            "source_values": {
                "ready_for_approval_at": ready,
                "latest_requested_eta": cycle.requested_eta,
                "requested_eta_source": cycle.requested_eta_source,
                "requested_eta_history": [{key: entry.get(key) for key in ("source", "event_id", "occurred_at", "source_changed_at", "retrieved_at",
                                                                           "requested_eta", "issue")}
                                          for entry in cycle.requested_eta_history],
                "requested_eta_history_coverage": dict(cycle.requested_eta_history_coverage),
            },
            "rule_version": policy.deadline_rule_version,
            "calculated_at": calculated_at,
        },
    }
    errors = validate(metric, DEADLINE_SCHEMA)
    if errors:
        raise ValueError(f"deadline metric violates contract: {errors}")
    return {"cycle_id": cycle.cycle_id, "monday_item_id": cycle.monday_item_id, "delta_seconds": delta, "metric": metric}


def _rate(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


def deadline_not_evaluated(cycle: CycleRecord) -> dict[str, Any]:
    """Explicit record for a cycle that gets no early/on-time/late result, with its reasons."""
    reasons = sorted(set(cycle.exclusions) | ({cycle.requested_eta_issue} if cycle.requested_eta_issue else set()))
    if cycle.requested_eta_issue == "REQUESTED_ETA_DATE_ONLY":
        classification = NOT_CLASSIFIABLE_ETA_PRECISION
    elif cycle.requested_eta_issue == "MISSING_REQUESTED_ETA":
        classification = NOT_CLASSIFIABLE_MISSING_ETA
    else:
        classification = NOT_EVALUATED
    return {"cycle_id": cycle.cycle_id, "monday_item_id": cycle.monday_item_id, "classification": classification, "reasons": reasons}


def deadline_summary(results: list[dict[str, Any]], excluded: list[CycleRecord]) -> dict[str, Any]:
    """Early / on-time / late counts and rates over evaluated cycles; exclusions keep their reasons.

    A date-only Requested ETA is never given a time: it is counted as
    ``not_classifiable_insufficient_eta_precision``, outside early / on-time / late.
    """
    deltas = [result["delta_seconds"] for result in results]
    not_evaluated = [deadline_not_evaluated(cycle) for cycle in excluded]
    counts = {label: sum(1 for delta in deltas if classify_deadline(delta) == label) for label in (EARLY, ON_TIME, LATE)}
    return {
        "evaluated": len(results),
        "early": counts[EARLY],
        "on_time": counts[ON_TIME],
        "late": counts[LATE],
        "early_rate": _rate(counts[EARLY], len(results)),
        "on_time_rate": _rate(counts[ON_TIME], len(results)),
        "late_rate": _rate(counts[LATE], len(results)),
        "on_time_tolerance": "none",
        "median_delta_seconds": median_seconds(deltas),
        "not_classifiable_insufficient_eta_precision": sum(1 for entry in not_evaluated if entry["classification"] == NOT_CLASSIFIABLE_ETA_PRECISION),
        "not_classifiable_missing_eta": sum(1 for entry in not_evaluated if entry["classification"] == NOT_CLASSIFIABLE_MISSING_ETA),
        "not_evaluated_other": sum(1 for entry in not_evaluated if entry["classification"] == NOT_EVALUATED),
        "not_evaluated": not_evaluated,
    }


def speed_metric(cycle: CycleRecord, cohort_median: int | None, policy: MetricPolicy, calculated_at: str) -> dict[str, Any]:
    assert cycle.in_progress_event is not None and cycle.ready_for_approval_event is not None and cycle.video_type is not None
    metric = {
        "contract_version": CONTRACT_VERSION,
        "metric_name": "speed",
        "editor_id": cycle.editor_id,
        "video_type": cycle.cohort_key,
        "duration_seconds": cycle.duration_seconds,
        "cohort_video_type": cycle.cohort_key,
        "cohort_median_seconds": cohort_median,
        "evidence": {
            "source": "monday",
            "monday_board_id": cycle.monday_board_id,
            "monday_item_id": cycle.monday_item_id,
            "column_ids": [policy.status_column_id, policy.video_type_column_id],
            "event_ids": [cycle.in_progress_event["event_id"], cycle.ready_for_approval_event["event_id"]]
            + ([cycle.video_type_event_id] if cycle.video_type_event_id else []),
            "source_timestamps": [cycle.in_progress_at, cycle.ready_for_approval_at],
            "source_values": {"start": "In Progress", "end": "Ready For Approval", "video_type": cycle.video_type.to_dict(),
                              "cycle_selection": "first-completed-cycle-only", "duration": "elapsed-clock-time"},
            "rule_version": policy.speed_rule_version,
            "calculated_at": calculated_at,
        },
    }
    errors = validate(metric, "speed-metric.schema.json")
    if errors:
        raise ValueError(f"speed metric violates contract: {errors}")
    return metric


def speed_benchmarks(editor_id: str, cycles: Iterable[CycleRecord], policy: MetricPolicy, calculated_at: str) -> dict[str, Any]:
    """Per-cohort Editor-vs-team speed comparison over first completed cycles only."""
    measured = [cycle for cycle in cycles if speed_eligible(cycle)]
    cohorts, _ = partition_by_cohort([{"video_type": cycle.cohort_key, "cycle": cycle} for cycle in measured])
    results: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    for key in sorted(cohorts):
        team = [entry["cycle"] for entry in cohorts[key]]
        mine = [cycle for cycle in team if cycle.editor_id == editor_id]
        if not mine:
            continue
        editor_median = median_seconds(cycle.duration_seconds for cycle in mine if cycle.duration_seconds is not None)
        assert editor_median is not None and mine[0].video_type is not None
        eligible, unconfirmed = cohort_benchmark_eligibility(mine[0].video_type.canonical_ids, policy.video_types)
        # The team population is every eligible Editor's first completed cycle in this exact cohort,
        # including the subject Editor (approved V1 rule); a cohort that is not a confirmed business
        # Video Type gets no team benchmark at all.
        team_median = median_seconds(cycle.duration_seconds for cycle in team if cycle.duration_seconds is not None) if eligible else None
        if not eligible:
            status, conclusion = COHORT_NOT_BENCHMARK_ELIGIBLE, NOT_COMPARABLE_CONCLUSION
        elif policy.minimum_editor_sample_size is None:
            status, conclusion = THRESHOLD_NOT_CONFIGURED, NOT_COMPARABLE_CONCLUSION
        elif len(mine) < policy.minimum_editor_sample_size:
            status, conclusion = INSUFFICIENT_SAMPLE, INSUFFICIENT_SAMPLE_CONCLUSION
        else:
            assert team_median is not None
            status = COMPARABLE
            conclusion = FASTER if editor_median < team_median else SLOWER if editor_median > team_median else EQUAL
        labels = mine[0].video_type.canonical_labels
        results.append({
            "cohort_key": key,
            "cohort_labels": list(labels),
            "video_type_mapping_version": mine[0].video_type.mapping_version if mine[0].video_type else None,
            "editor_sample_size": len(mine),
            "editor_median_seconds": editor_median,
            "team_sample_size": len(team) if eligible else None,
            "team_editor_count": len({cycle.editor_id for cycle in team}) if eligible else None,
            "team_median_seconds": team_median,
            "editor_minus_team_median_seconds": editor_median - team_median if team_median is not None else None,
            "team_includes_subject_editor": True,
            "benchmark_statistic": policy.benchmark_statistic,
            "benchmark_eligible": eligible,
            "unconfirmed_video_type_ids": unconfirmed,
            "minimum_editor_sample_size": policy.minimum_editor_sample_size,
            "comparison_status": status,
            "conclusion": conclusion,
            "editor_cycle_ids": [cycle.cycle_id for cycle in mine],
            "team_cycle_ids": [cycle.cycle_id for cycle in team] if eligible else [],
            "benchmark": "descriptive historical team median; not an SLA",
            "rule_version": policy.speed_rule_version,
        })
        metrics.extend(speed_metric(cycle, team_median, policy, calculated_at) for cycle in mine)
    return {"cohorts": results, "metrics": metrics}
