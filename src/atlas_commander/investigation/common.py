"""Helpers shared by detectors: limitation codes, profile evidence conversion and small formatting of groups."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from fractions import Fraction
from typing import Any

from atlas_commander.investigation.baselines import Baselines
from atlas_commander.investigation.facts import ProjectFact
from atlas_commander.investigation.models import EvidenceRecord
from atlas_commander.investigation.stats import shown

# Limitation codes (Task 59); wording in ``narrative.LIMITATIONS``.
ELAPSED_TIME = "elapsed_clock_time_not_effort"
VIDEO_TYPE_ONLY = "video_type_is_the_only_complexity_control"
LABELS_LOWER_BOUND = "labels_are_hand_applied_lower_bound"
ASSOCIATION_NOT_CAUSE = "association_not_causation"
WORKLOAD_LOWER_BOUND = "concurrency_counts_attributed_completed_first_cycles_only"
ATTRIBUTED_ONLY = "unattributed_projects_excluded"
ETA_AFTER_START = "some_etas_first_observed_after_work_started"
NO_REVISION_CAUSE = "revision_cause_not_recorded"
INGEST_WINDOW = "history_limited_to_ingest_window"
NO_PERSON_FOR_STAGE = "stage_owner_not_identifiable_shared_account"
TYPICAL_WHOLE_HISTORY = "typical_execution_uses_whole_ingested_history"
NOT_MIX_ADJUSTED = "not_adjusted_for_video_type_mix"
CURRENT_SNAPSHOT = "current_snapshot_only"
MULTIPLE_COMPARISONS = "several_combinations_tested"
NO_CAUSE_EVIDENCE = "no_evidence_of_actual_cause"
PARTIAL_PERIOD = "includes_a_partial_period"
SMALL_SAMPLE = "sample_near_minimum"
PROPOSED_PARAMETERS = "uses_proposed_parameters_not_approved"


def records_from_block(block: Mapping[str, Any], editor_id: str | None = None) -> list[EvidenceRecord]:
    """Engine (contract 1.5) evidence records as V2 evidence records, optionally only the named Editor's."""
    rows = []
    for record in block.get("records") or []:
        values = dict(record.get("source_values") or {})
        if editor_id is not None and values.get("editor_id") != editor_id:
            continue
        rows.append(EvidenceRecord(str(record["monday_item_id"]), record.get("cycle_id"), tuple(record.get("event_ids") or ()),
                                   tuple(record.get("source_timestamps") or ()), values, values.get("editor_id"), values.get("cohort_key")))
    return rows


def labels_of(projects: Iterable[ProjectFact]) -> list[str]:
    return sorted({label for project in projects for label in project.cohort_labels})


def cohort_name(projects: Sequence[ProjectFact], key: str | None) -> str:
    for project in projects:
        if project.cohort_key == key and project.cohort_labels:
            return " + ".join(project.cohort_labels)
    return str(key)


def fraction_dict(count: int, total: int) -> dict[str, Any]:
    return {"count": count, "total": total, "rate": shown(Fraction(count, total)) if total else None}


def short_runway(project: ProjectFact, baselines: Baselines) -> bool | None:
    """Runway below the other Editors' typical execution time in the same exact Video Type (runway.short_rule).

    None when the project has no timed ETA, its Video Type is not benchmark-eligible, or the typical time is not valid at the
    approved D52 comparator minimums."""
    if project.runway_seconds is None or not project.cohort_key or not project.speed_measurable:
        return None
    typical = baselines.typical(project.cohort_key, project.editor_id)
    if not typical.valid or typical.median_seconds is None:
        return None
    return project.runway_seconds < typical.median_seconds


def typical_seconds(project: ProjectFact, baselines: Baselines) -> int | None:
    if not project.cohort_key or not project.speed_measurable:
        return None
    typical = baselines.typical(project.cohort_key, project.editor_id)
    return typical.median_seconds if typical.valid else None


def hours(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 3600, 1)
