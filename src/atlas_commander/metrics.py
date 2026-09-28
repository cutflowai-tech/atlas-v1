"""Pure fixture metrics; callers supply canonical cycles and Monday evidence.

Cohorts contain explicit (cycle, evidence) pairs. The caller decides membership,
including whether to include the evaluated cycle. No implicit global cohort exists.
Evidence calculated_at is supplied by the caller; no clock or network is used.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .contracts import assert_valid, schema_errors


class MetricInputError(ValueError):
    """Inputs cannot support a metric under the frozen contracts."""


@dataclass(frozen=True)
class QualityMapping:
    """Approved Monday label ID/value -> display label, scoped to a source column."""

    monday_board_id: str
    column_id: str
    version: str
    labels: Mapping[str, str]
    approved: bool


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))


def _cycle(cycle: dict[str, Any]) -> None:
    errors = schema_errors(cycle, "work-cycle.schema.json")
    if errors:
        raise MetricInputError("Invalid work cycle: " + "; ".join(errors))
    delta = _time(cycle["ready_for_approval_at"]) - _time(cycle["in_progress_at"])
    # Compare exact microseconds, never truncate a fractional duration.
    micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    if micros != cycle["duration_seconds"] * 1_000_000 or micros <= 0:
        raise MetricInputError("Duration must equal the positive, whole-second status interval")


def _base(cycle: dict[str, Any], name: str) -> dict[str, Any]:
    return {"contract_version": "1.0.0", "metric_name": name, "editor_id": cycle["editor_id"]}


def _evidence(cycle: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    # Reuse the frozen evidence reference rather than reimplement its schema.
    probe = {**_base(cycle, "speed"), "video_type": cycle["video_type"],
             "cohort_video_type": cycle["video_type"], "duration_seconds": cycle["duration_seconds"],
             "cohort_median_seconds": None, "evidence": evidence}
    errors = schema_errors(probe, "speed-metric.schema.json")
    if errors:
        raise MetricInputError("Invalid source evidence: " + "; ".join(errors))
    for key in ("monday_board_id", "monday_item_id"):
        if evidence[key] != cycle[key]:
            raise MetricInputError("Source evidence does not match cycle " + key)
    return deepcopy(evidence)


def _record(cycle: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    return {"work_cycle": deepcopy(cycle), "source_evidence": deepcopy(evidence)}


def derive_speed(
    cycle: dict[str, Any], evidence: dict[str, Any],
    cohort: Iterable[tuple[dict[str, Any], dict[str, Any]]] = (),
) -> dict[str, Any]:
    """Median of supplied matching canonical Video Types; fractional medians fail."""
    _cycle(cycle)
    result_evidence = _evidence(cycle, evidence)
    members = []
    seen = set()
    for member, source in cohort:
        _cycle(member)
        if member["video_type"] != cycle["video_type"]:
            continue
        identity = (member["monday_board_id"], member["monday_item_id"], member["cycle_id"])
        if identity in seen:
            raise MetricInputError("Duplicate cohort cycle")
        seen.add(identity)
        members.append(_record(member, _evidence(member, source)))
    members.sort(key=lambda entry: tuple(entry["work_cycle"][key] for key in
                                       ("monday_board_id", "monday_item_id", "cycle_id")))
    durations = sorted(entry["work_cycle"]["duration_seconds"] for entry in members)
    median = None
    if durations:
        middle = len(durations) // 2
        numerator = durations[middle] * 2 if len(durations) % 2 else durations[middle - 1] + durations[middle]
        if numerator % 2:
            raise MetricInputError("Fractional cohort median is unsupported by speed contract 1.0.0")
        median = numerator // 2
    result_evidence["source_values"] = {
        "subject": _record(cycle, evidence), "cohort": members,
        "cohort_policy": "explicit_members_same_canonical_video_type",
    }
    result_evidence["rule_version"] = "speed-v1"
    result = {**_base(cycle, "speed"), "video_type": cycle["video_type"],
              "duration_seconds": cycle["duration_seconds"], "cohort_video_type": cycle["video_type"],
              "cohort_median_seconds": median, "evidence": result_evidence}
    assert_valid(result, "speed-metric.schema.json")
    return result


def derive_deadline(cycle: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any] | None:
    """Missing Requested ETA has no metric; equal instants are on time."""
    _cycle(cycle)
    if cycle["requested_eta"] is None:
        return None
    result_evidence = _evidence(cycle, evidence)
    result_evidence["source_values"] = {"subject": _record(cycle, evidence)}
    result_evidence["rule_version"] = "deadline-v1"
    result = {**_base(cycle, "deadline"), "ready_for_approval_at": cycle["ready_for_approval_at"],
              "requested_eta": cycle["requested_eta"],
              "result": "on_time" if _time(cycle["ready_for_approval_at"]) <= _time(cycle["requested_eta"]) else "late",
              "evidence": result_evidence}
    assert_valid(result, "deadline-metric.schema.json")
    return result


def derive_quality(
    cycle: dict[str, Any], evidence: dict[str, Any], mapping: QualityMapping,
) -> dict[str, Any]:
    """Read only the approved Performance Label column; revisions stay context."""
    _cycle(cycle)
    result_evidence = _evidence(cycle, evidence)
    if (mapping.approved is not True or not mapping.version.strip() or not mapping.column_id.strip()
            or mapping.monday_board_id != cycle["monday_board_id"]):
        raise MetricInputError("Quality requires an approved, versioned, board-scoped mapping")
    if mapping.column_id not in evidence["column_ids"]:
        raise MetricInputError("Approved Performance Label column is absent from evidence")
    raw = evidence["source_values"].get(mapping.column_id)
    if not isinstance(raw, str) or raw not in mapping.labels:
        raise MetricInputError("Missing or unmapped Monday Performance Label")
    label = mapping.labels[raw]
    if not isinstance(label, str) or not label.strip():
        raise MetricInputError("Mapped Performance Label must be nonempty")
    result_evidence["source_values"] = {
        "subject": _record(cycle, evidence),
        "quality_mapping": {"monday_board_id": mapping.monday_board_id, "column_id": mapping.column_id,
                            "version": mapping.version, "approved": True, "source_label": raw, "performance_label": label},
    }
    result_evidence["rule_version"] = "quality-v1"
    result = {**_base(cycle, "quality"), "performance_label": label, "label_column_id": mapping.column_id,
              "label_mapping_version": mapping.version, "revision_context": deepcopy(cycle.get("revision_context")),
              "evidence": result_evidence}
    assert_valid(result, "quality-metric.schema.json")
    return result
