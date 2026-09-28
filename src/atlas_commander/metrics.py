"""Pure fixture metric derivation from contract-valid, canonical Monday inputs.

Callers supply source evidence (including calculation time) and canonical IDs;
this module never resolves display names, reads a clock, or invents source facts.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any


class UnsupportedMetricValue(ValueError):
    """An exact result cannot be represented by the frozen integer contract."""


@dataclass(frozen=True)
class QualityMapping:
    """Explicit approval for a board's Monday Performance Label column.

    labels maps canonical Monday label IDs to approved display values.
    """

    board_id: str
    column_id: str
    version: str
    labels: Mapping[str, str]
    approved: bool


@dataclass(frozen=True)
class CycleSource:
    cycle: Mapping[str, Any]
    evidence: Mapping[str, Any]


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("Timezone-aware source timestamps required")
    return result


def _cycle(cycle: Mapping[str, Any]) -> None:
    if cycle["start_status"] != "In Progress" or cycle["end_status"] != "Ready For Approval":
        raise ValueError("Unsupported work duration boundaries")
    delta = _time(cycle["ready_for_approval_at"]) - _time(cycle["in_progress_at"])
    if delta.microseconds:
        raise UnsupportedMetricValue("Fractional work duration is unsupported")
    seconds = delta.days * 86400 + delta.seconds
    if seconds <= 0 or seconds != cycle["duration_seconds"]:
        raise ValueError("Work duration must equal In Progress to Ready For Approval")


def _evidence(cycle: Mapping[str, Any], evidence: Mapping[str, Any], rule: str) -> dict[str, Any]:
    if evidence["source"] != "monday":
        raise ValueError("Only Monday source evidence is supported")
    for key in ("monday_board_id", "monday_item_id"):
        if evidence[key] != cycle[key]:
            raise ValueError(f"Source evidence {key} does not match work cycle")
    for key in ("column_ids", "event_ids", "source_timestamps", "source_values"):
        if not evidence[key]:
            raise ValueError(f"Source evidence requires {key}")
    _time(evidence["calculated_at"])
    result = deepcopy(dict(evidence))
    result["rule_version"] = rule
    return result


def _duration_source(source: CycleSource) -> dict[str, Any]:
    _cycle(source.cycle)
    evidence = _evidence(source.cycle, source.evidence, "speed-v1")
    for key in ("in_progress_event_id", "ready_for_approval_event_id"):
        if source.cycle[key] not in evidence["event_ids"]:
            raise ValueError("Duration evidence must include both boundary events")
    return evidence


def derive_speed(
    cycle: Mapping[str, Any], evidence: Mapping[str, Any], cohort: Sequence[CycleSource] = (),
) -> dict[str, Any]:
    """Use only explicitly supplied, same canonical Video Type cohort members.

    The target is included only if supplied in cohort. Empty cohorts yield null;
    duplicate cycle IDs and fractional medians fail explicitly without rounding.
    """
    result_evidence = _duration_source(CycleSource(cycle, evidence))
    members = sorted(
        (member for member in cohort if member.cycle["video_type"] == cycle["video_type"]),
        key=lambda member: member.cycle["cycle_id"],
    )
    ids = [member.cycle["cycle_id"] for member in members]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate cohort cycle_id")
    sources = []
    for member in members:
        member_evidence = _duration_source(member)
        sources.append({"work_cycle": deepcopy(dict(member.cycle)), "evidence": member_evidence})
    durations = sorted(member.cycle["duration_seconds"] for member in members)
    median = None
    if durations:
        middle = len(durations) // 2
        numerator = durations[middle] + durations[(len(durations) - 1) // 2]
        if numerator % 2:
            raise UnsupportedMetricValue("Fractional cohort median is unsupported by speed contract 1.0.0")
        median = numerator // 2
    result_evidence["source_values"] = {
        "source": result_evidence["source_values"], "work_cycle": deepcopy(dict(cycle)), "cohort": sources,
    }
    return {
        "contract_version": "1.0.0", "metric_name": "speed", "editor_id": cycle["editor_id"],
        "video_type": cycle["video_type"], "duration_seconds": cycle["duration_seconds"],
        "cohort_video_type": cycle["video_type"], "cohort_median_seconds": median, "evidence": result_evidence,
    }


def derive_deadline(cycle: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any] | None:
    """Missing Requested ETA means no deadline observation; equality is on time."""
    _cycle(cycle)
    if cycle["requested_eta"] is None:
        return None
    result_evidence = _evidence(cycle, evidence, "deadline-v1")
    if cycle["ready_for_approval_event_id"] not in result_evidence["event_ids"]:
        raise ValueError("Deadline evidence must include Ready For Approval event")
    result_evidence["source_values"] = {
        "source": result_evidence["source_values"], "work_cycle": deepcopy(dict(cycle)),
    }
    return {
        "contract_version": "1.0.0", "metric_name": "deadline", "editor_id": cycle["editor_id"],
        "ready_for_approval_at": cycle["ready_for_approval_at"], "requested_eta": cycle["requested_eta"],
        "result": "on_time" if _time(cycle["ready_for_approval_at"]) <= _time(cycle["requested_eta"]) else "late",
        "evidence": result_evidence,
    }


def derive_quality(
    cycle: Mapping[str, Any], evidence: Mapping[str, Any], mapping: QualityMapping,
) -> dict[str, Any]:
    """Read a canonical label ID from evidence.source_values[mapping.column_id].

    Unknown labels or unapproved mappings fail closed; revisions are copied only.
    """
    if mapping.approved is not True or not mapping.version or not mapping.column_id:
        raise ValueError("An explicitly approved versioned quality mapping is required")
    if mapping.board_id != cycle["monday_board_id"]:
        raise ValueError("Quality mapping board mismatch")
    result_evidence = _evidence(cycle, evidence, "quality-v1")
    if mapping.column_id not in evidence["column_ids"]:
        raise ValueError("Missing approved Performance Label column evidence")
    label_id = evidence["source_values"].get(mapping.column_id)
    if not isinstance(label_id, str) or label_id not in mapping.labels or not mapping.labels[label_id]:
        raise ValueError("Unknown approved Monday Performance Label ID")
    label = mapping.labels[label_id]
    result_evidence["source_values"] = {
        "source": result_evidence["source_values"],
        "quality_mapping": {"board_id": mapping.board_id, "column_id": mapping.column_id,
                            "version": mapping.version, "approved": True, "label_id": label_id, "label": label},
    }
    return {
        "contract_version": "1.0.0", "metric_name": "quality", "editor_id": cycle["editor_id"],
        "performance_label": label, "label_column_id": mapping.column_id, "label_mapping_version": mapping.version,
        "revision_context": deepcopy(cycle.get("revision_context")), "evidence": result_evidence,
    }
