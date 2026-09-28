"""Pure fixture metrics. Callers supply canonical cycles and Monday evidence.

Cohorts are explicit (the target is included only if supplied). Quality mappings
are approved configuration, never inferred from labels or revision counts.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Any

from .contracts import schema_errors

Record = dict[str, Any]


class MetricInputError(ValueError):
    """An input cannot support a contract-valid, evidence-backed metric."""


@dataclass(frozen=True)
class QualityMapping:
    board_id: str
    column_id: str
    version: str
    labels: Mapping[str, str]
    approved: bool = False


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _cycle(cycle: Record) -> None:
    errors = schema_errors(cycle, "work-cycle.schema.json")
    if errors:
        raise MetricInputError("Invalid work cycle: " + "; ".join(errors))
    delta = _time(cycle["ready_for_approval_at"]) - _time(cycle["in_progress_at"])
    if delta.total_seconds() != cycle["duration_seconds"]:
        raise MetricInputError("Duration must exactly equal In Progress to Ready For Approval")


def _evidence(cycle: Record, evidence: Record, events: Sequence[str]) -> Record:
    if any(evidence.get(key) != cycle[key] for key in ("monday_board_id", "monday_item_id")):
        raise MetricInputError("Evidence must belong to the cycle's Monday board and item")
    if not set(events).issubset(evidence.get("event_ids", [])):
        raise MetricInputError("Evidence is missing required cycle events")
    return deepcopy(evidence)


def _result(name: str, cycle: Record, evidence: Record, **values: Any) -> Record:
    result = dict(contract_version="1.0.0", metric_name=name, editor_id=cycle["editor_id"], evidence=evidence, **values)
    errors = schema_errors(result, name + "-metric.schema.json")
    if errors:
        raise MetricInputError("Invalid metric evidence/output: " + "; ".join(errors))
    return result


def derive_speed(cycle: Record, evidence: Record, cohort: Sequence[tuple[Record, Record]] = ()) -> Record:
    """Median of supplied same-type cycles; empty cohort gives null, never fallback.

    Fractional medians raise MetricInputError rather than rounding or silently
    hiding available data. Duplicate cohort cycle identities are rejected.
    """
    _cycle(cycle)
    events = [cycle["in_progress_event_id"], cycle["ready_for_approval_event_id"]]
    source = _evidence(cycle, evidence, events)
    _result("speed", cycle, source, video_type=cycle["video_type"], duration_seconds=cycle["duration_seconds"],
            cohort_video_type=cycle["video_type"], cohort_median_seconds=None)
    contributors = []
    identities: set[tuple[str, str, str]] = set()
    for peer, peer_evidence in cohort:
        _cycle(peer)
        if peer["video_type"] != cycle["video_type"]:
            continue
        identity = (peer["monday_board_id"], peer["monday_item_id"], peer["cycle_id"])
        if identity in identities:
            raise MetricInputError("Duplicate cohort cycle")
        identities.add(identity)
        # Validate each contributing source independently before embedding it.
        validated = derive_speed(peer, peer_evidence)
        contributors.append({"cycle": deepcopy(peer), "evidence": validated["evidence"]})
    contributors.sort(key=lambda entry: (entry["cycle"]["monday_board_id"], entry["cycle"]["monday_item_id"], entry["cycle"]["cycle_id"]))
    durations = sorted(entry["cycle"]["duration_seconds"] for entry in contributors)
    median = None
    if durations:
        middle = len(durations) // 2
        exact = Fraction(durations[middle]) if len(durations) % 2 else Fraction(durations[middle - 1] + durations[middle], 2)
        if exact.denominator != 1:
            raise MetricInputError("Fractional cohort median is unsupported by speed contract 1.0.0")
        median = int(exact)
    source.setdefault("source_values", {})["speed_derivation"] = {"cycle": deepcopy(cycle), "cohort": contributors}
    return _result("speed", cycle, source, video_type=cycle["video_type"], duration_seconds=cycle["duration_seconds"],
                   cohort_video_type=cycle["video_type"], cohort_median_seconds=median)


def derive_deadline(cycle: Record, evidence: Record) -> Record | None:
    """Missing Requested ETA produces no metric; equality is on time."""
    _cycle(cycle)
    if cycle["requested_eta"] is None:
        return None
    source = _evidence(cycle, evidence, [cycle["ready_for_approval_event_id"]])
    for key in ("ready_for_approval_at", "requested_eta"):
        if source.get("source_values", {}).get(key) != cycle[key]:
            raise MetricInputError("Deadline source values must match the cycle: " + key)
    result = "on_time" if _time(cycle["ready_for_approval_at"]) <= _time(cycle["requested_eta"]) else "late"
    return _result("deadline", cycle, source, ready_for_approval_at=cycle["ready_for_approval_at"], requested_eta=cycle["requested_eta"], result=result)


def derive_quality(cycle: Record, evidence: Record, mapping: QualityMapping) -> Record:
    """Use only the approved Monday Performance Label mapping; revisions display only."""
    _cycle(cycle)
    if mapping.approved is not True or not all((mapping.board_id, mapping.column_id, mapping.version)):
        raise MetricInputError("Quality requires an explicitly approved versioned mapping")
    if mapping.board_id != cycle["monday_board_id"] or mapping.column_id not in evidence.get("column_ids", []):
        raise MetricInputError("Quality mapping must match the Monday board and source column")
    source = _evidence(cycle, evidence, [])
    raw_label = source.get("source_values", {}).get(mapping.column_id)
    if not isinstance(raw_label, str) or raw_label not in mapping.labels:
        raise MetricInputError("Missing or unapproved Monday Performance Label")
    label = mapping.labels[raw_label]
    if not isinstance(label, str) or not label.strip():
        raise MetricInputError("Approved label must be a nonempty string")
    source["source_values"]["quality_mapping"] = {"version": mapping.version, "column_id": mapping.column_id, "raw_label": raw_label, "performance_label": label}
    return _result("quality", cycle, source, performance_label=label, label_column_id=mapping.column_id,
                   label_mapping_version=mapping.version, revision_context=deepcopy(cycle.get("revision_context")))
