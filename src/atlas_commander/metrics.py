"""Pure deterministic derivation of speed, deadline, and quality metrics.

Inputs are contract-valid WorkCycles plus the Monday source evidence needed to
cite them. No clock reads, no AI, no fallbacks: callers pass ``calculated_at``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

from atlas_commander.contracts import assert_valid, schema_errors, semantic_codes

CONTRACT_VERSION = "1.0.0"
SPEED_RULE_VERSION = "speed-v1"
DEADLINE_RULE_VERSION = "deadline-v1"
QUALITY_RULE_VERSION = "quality-v1"

WORK_CYCLE_SCHEMA = "work-cycle.schema.json"
# A null Requested ETA is a valid WorkCycle state; it only suppresses the deadline metric.
_TOLERATED_CYCLE_CODES = {"MISSING_REQUESTED_ETA"}


class MetricError(ValueError):
    """Explicit refusal to derive a metric from unsupported or inconsistent input."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CycleSource:
    """A contract-valid WorkCycle and the Monday column IDs it was read from."""

    cycle: Mapping[str, Any]
    status_column_id: str
    video_type_column_id: str
    requested_eta_column_id: str


@dataclass(frozen=True)
class PerformanceLabelObservation:
    """A Monday Performance Label value as observed on a board item."""

    monday_board_id: str
    monday_item_id: str
    column_id: str
    event_id: str
    observed_at: str
    label: str | None


@dataclass(frozen=True)
class QualityLabelMapping:
    """Explicit, versioned mapping from Monday label values to approved performance labels."""

    version: str
    label_column_id: str
    approved: bool
    labels: Mapping[str, str] = field(default_factory=dict)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise MetricError("NAIVE_TIMESTAMP", f"timestamp {value!r} has no UTC offset")
    return parsed


def _require_timestamp(value: str, name: str) -> None:
    try:
        _timestamp(value)
    except ValueError as error:
        if isinstance(error, MetricError):
            raise
        raise MetricError("INVALID_TIMESTAMP", f"{name} {value!r} is not an ISO-8601 date-time") from error


def _validate_cycle(source: CycleSource) -> Mapping[str, Any]:
    cycle = source.cycle
    errors = schema_errors(cycle, WORK_CYCLE_SCHEMA)
    if errors:
        raise MetricError("SCHEMA_INVALID", "; ".join(errors))
    codes = [code for code in semantic_codes(cycle, WORK_CYCLE_SCHEMA) if code not in _TOLERATED_CYCLE_CODES]
    if codes:
        raise MetricError(codes[0], f"work cycle {cycle['cycle_id']!r} violates {', '.join(codes)}")
    for name in ("status_column_id", "video_type_column_id", "requested_eta_column_id"):
        if not getattr(source, name):
            raise MetricError("MISSING_SOURCE_COLUMN", f"{name} is required for cycle {cycle['cycle_id']!r}")
    return cycle


def _validate_cycles(sources: Sequence[CycleSource]) -> list[CycleSource]:
    seen: set[str] = set()
    for source in sources:
        cycle_id = _validate_cycle(source)["cycle_id"]
        if cycle_id in seen:
            raise MetricError("DUPLICATE_CYCLE", f"cycle {cycle_id!r} supplied more than once")
        seen.add(cycle_id)
    return sorted(sources, key=lambda source: source.cycle["cycle_id"])


def _cohort_median(durations: Sequence[int]) -> Fraction:
    ordered = sorted(durations)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return Fraction(ordered[middle])
    return Fraction(ordered[middle - 1] + ordered[middle], 2)


def _exact_decimal(value: Fraction) -> str:
    return str(Decimal(value.numerator) / Decimal(value.denominator))


def _cohort_source(source: CycleSource) -> dict[str, Any]:
    cycle = source.cycle
    return {
        "cycle_id": cycle["cycle_id"],
        "editor_id": cycle["editor_id"],
        "monday_board_id": cycle["monday_board_id"],
        "monday_item_id": cycle["monday_item_id"],
        "in_progress_event_id": cycle["in_progress_event_id"],
        "ready_for_approval_event_id": cycle["ready_for_approval_event_id"],
        "duration_seconds": cycle["duration_seconds"],
    }


def derive_speed_metrics(sources: Sequence[CycleSource], calculated_at: str) -> list[dict[str, Any]]:
    """One SpeedMetric per cycle, benchmarked only against cycles of the identical canonical Video Type.

    A fractional median cannot be represented by the integer contract field, so
    ``cohort_median_seconds`` is null and the exact value is kept in evidence.
    """
    _require_timestamp(calculated_at, "calculated_at")
    ordered = _validate_cycles(sources)
    cohorts: dict[str, list[CycleSource]] = {}
    for source in ordered:
        cohorts.setdefault(source.cycle["video_type"], []).append(source)

    metrics = []
    for source in ordered:
        cycle = source.cycle
        video_type = cycle["video_type"]
        cohort = cohorts[video_type]
        median = _cohort_median([member.cycle["duration_seconds"] for member in cohort])
        if median.denominator == 1:
            cohort_median_seconds: int | None = int(median)
            median_status = "exact_integer"
        else:
            cohort_median_seconds = None
            median_status = "unsupported_fractional"
        metric = {
            "contract_version": CONTRACT_VERSION,
            "metric_name": "speed",
            "editor_id": cycle["editor_id"],
            "video_type": video_type,
            "duration_seconds": cycle["duration_seconds"],
            "cohort_video_type": video_type,
            "cohort_median_seconds": cohort_median_seconds,
            "evidence": {
                "source": "monday",
                "monday_board_id": cycle["monday_board_id"],
                "monday_item_id": cycle["monday_item_id"],
                "column_ids": _unique([source.status_column_id, source.video_type_column_id]),
                "event_ids": [cycle["in_progress_event_id"], cycle["ready_for_approval_event_id"]],
                "source_timestamps": [cycle["in_progress_at"], cycle["ready_for_approval_at"]],
                "source_values": {
                    "start": cycle["start_status"],
                    "end": cycle["end_status"],
                    "video_type": video_type,
                    "cycle_id": cycle["cycle_id"],
                    "cohort_size": len(cohort),
                    "cohort_median_status": median_status,
                    "cohort_median_exact": _exact_decimal(median),
                    "cohort_sources": [_cohort_source(member) for member in cohort],
                },
                "rule_version": SPEED_RULE_VERSION,
                "calculated_at": calculated_at,
            },
        }
        assert_valid(metric, "speed-metric.schema.json")
        metrics.append(metric)
    return metrics


def derive_deadline_metric(source: CycleSource, calculated_at: str) -> dict[str, Any] | None:
    """DeadlineMetric from Ready For Approval vs Requested ETA; ``None`` when the ETA is missing."""
    _require_timestamp(calculated_at, "calculated_at")
    cycle = _validate_cycle(source)
    requested_eta = cycle["requested_eta"]
    if requested_eta is None:
        return None
    ready_at = cycle["ready_for_approval_at"]
    result = "on_time" if _timestamp(ready_at) <= _timestamp(requested_eta) else "late"
    metric = {
        "contract_version": CONTRACT_VERSION,
        "metric_name": "deadline",
        "editor_id": cycle["editor_id"],
        "ready_for_approval_at": ready_at,
        "requested_eta": requested_eta,
        "result": result,
        "evidence": {
            "source": "monday",
            "monday_board_id": cycle["monday_board_id"],
            "monday_item_id": cycle["monday_item_id"],
            "column_ids": _unique([source.status_column_id, source.requested_eta_column_id]),
            "event_ids": [cycle["ready_for_approval_event_id"]],
            "source_timestamps": [ready_at],
            "source_values": {
                "ready_for_approval_at": ready_at,
                "requested_eta": requested_eta,
                "cycle_id": cycle["cycle_id"],
            },
            "rule_version": DEADLINE_RULE_VERSION,
            "calculated_at": calculated_at,
        },
    }
    assert_valid(metric, "deadline-metric.schema.json")
    return metric


def derive_deadline_metrics(sources: Sequence[CycleSource], calculated_at: str) -> list[dict[str, Any]]:
    metrics = (derive_deadline_metric(source, calculated_at) for source in _validate_cycles(sources))
    return [metric for metric in metrics if metric is not None]


def derive_quality_metric(
    source: CycleSource,
    observation: PerformanceLabelObservation,
    mapping: QualityLabelMapping,
    calculated_at: str,
) -> dict[str, Any] | None:
    """QualityMetric from an approved Monday Performance Label only; ``None`` when no label is set.

    Revision context is copied for display and never consulted for the value.
    """
    _require_timestamp(calculated_at, "calculated_at")
    _require_timestamp(observation.observed_at, "observed_at")
    cycle = _validate_cycle(source)
    if not mapping.approved:
        raise MetricError("UNAPPROVED_LABEL_MAPPING", f"label mapping {mapping.version!r} is not approved")
    if not mapping.version or not mapping.label_column_id:
        raise MetricError("UNVERSIONED_LABEL_MAPPING", "label mapping requires a version and label column ID")
    if observation.column_id != mapping.label_column_id:
        raise MetricError(
            "LABEL_COLUMN_MISMATCH",
            f"observation column {observation.column_id!r} is not mapping column {mapping.label_column_id!r}",
        )
    if (observation.monday_board_id, observation.monday_item_id) != (cycle["monday_board_id"], cycle["monday_item_id"]):
        raise MetricError("LABEL_ITEM_MISMATCH", f"label observation is not for the item of cycle {cycle['cycle_id']!r}")
    if observation.label is None or observation.label == "":
        return None
    if observation.label not in mapping.labels:
        raise MetricError(
            "UNSUPPORTED_PERFORMANCE_LABEL",
            f"label {observation.label!r} is not in approved mapping {mapping.version!r}",
        )
    revision_context = cycle.get("revision_context")
    metric = {
        "contract_version": CONTRACT_VERSION,
        "metric_name": "quality",
        "editor_id": cycle["editor_id"],
        "performance_label": mapping.labels[observation.label],
        "label_column_id": mapping.label_column_id,
        "label_mapping_version": mapping.version,
        "revision_context": dict(revision_context) if revision_context is not None else None,
        "evidence": {
            "source": "monday",
            "monday_board_id": observation.monday_board_id,
            "monday_item_id": observation.monday_item_id,
            "column_ids": [observation.column_id],
            "event_ids": [observation.event_id],
            "source_timestamps": [observation.observed_at],
            "source_values": {"performance_label": observation.label, "cycle_id": cycle["cycle_id"]},
            "rule_version": QUALITY_RULE_VERSION,
            "calculated_at": calculated_at,
        },
    }
    assert_valid(metric, "quality-metric.schema.json")
    return metric


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))
