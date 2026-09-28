"""Deterministic normalization of Monday activity-log status changes.

Input is Monday activity data (``activity_logs`` entries) plus an explicit,
versioned status mapping. Output is contract-shaped normalized status events,
quarantined records with a reason code, and the untouched raw source kept
separately for evidence. Nothing is guessed: unmapped labels, non-status
events, malformed payloads and conflicting duplicate IDs are quarantined.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from atlas_commander.contracts import schema_errors

CONTRACT_VERSION = "1.0.0"
SCHEMA_NAME = "normalized-status-event.schema.json"
CANONICAL_STATUSES = frozenset({"Backlog", "In Progress", "Ready For Approval", "Revision", "Approved", "Delivered"})
STATUS_EVENT_TYPE = "update_column_value"
STATUS_COLUMN_TYPE = "color"
# Monday activity-log ``created_at`` is an integer string in 100-nanosecond units since the Unix epoch.
MONDAY_TICKS_PER_SECOND = 10_000_000

MALFORMED = "MALFORMED_EVENT"
MISSING_EVENT_ID = "MISSING_EVENT_ID"
NON_STATUS_EVENT = "NON_STATUS_EVENT"
UNKNOWN_STATUS = "UNKNOWN_STATUS"
INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
DUPLICATE_EVENT_CONFLICT = "DUPLICATE_EVENT_CONFLICT"
SCHEMA_INVALID = "SCHEMA_INVALID"


class QuarantineError(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class NormalizationResult:
    accepted: list[dict[str, Any]]
    quarantined: list[dict[str, Any]]
    raw_sources: dict[str, dict[str, Any]]
    duplicate_event_ids: list[str] = field(default_factory=list)
    unresolved_actor_event_ids: list[str] = field(default_factory=list)
    status_mapping_version: str = ""
    actor_mapping_version: str | None = None
    raw_input_snapshots: tuple[Any, ...] = ()


def _validated_status_mapping(status_mapping: dict[str, Any]) -> tuple[str, dict[str, frozenset[str]], dict[str, str]]:
    if not isinstance(status_mapping, dict):
        raise ValueError("status_mapping must be an object")  # noqa: TRY004 - all invalid configuration uses ValueError
    version = status_mapping.get("version")
    column_ids = status_mapping.get("status_column_ids")
    labels = status_mapping.get("labels")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("status_mapping.version must be a non-empty string")
    if not isinstance(column_ids, dict) or not column_ids:
        raise ValueError("status_mapping.status_column_ids must map board IDs to column ID lists")
    for board_id, columns in column_ids.items():
        if not isinstance(board_id, str) or not board_id.strip() or not isinstance(columns, list) or not columns:
            raise ValueError("status_mapping.status_column_ids requires nonblank board IDs and nonempty column lists")
        if not all(isinstance(column, str) and column.strip() for column in columns):
            raise ValueError("status_mapping.status_column_ids requires nonblank column IDs")
    if not isinstance(labels, dict) or not labels:
        raise ValueError("status_mapping.labels must map Monday label text to canonical statuses")
    if not all(isinstance(key, str) and key.strip() and isinstance(value, str) for key, value in labels.items()):
        raise ValueError("status_mapping.labels must contain string labels and statuses")
    unknown = sorted(value for value in labels.values() if value not in CANONICAL_STATUSES)
    if unknown:
        raise ValueError(f"status_mapping.labels targets non-canonical statuses: {unknown}")
    return version, {board: frozenset(columns) for board, columns in column_ids.items()}, dict(labels)


def _validated_actor_mapping(actor_mapping: dict[str, Any] | None) -> tuple[str | None, dict[str, str]]:
    if actor_mapping is None:
        return None, {}
    if not isinstance(actor_mapping, dict):
        raise ValueError("actor_mapping must be an object")  # noqa: TRY004 - all invalid configuration uses ValueError
    version = actor_mapping.get("version")
    actors = actor_mapping.get("actors")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("actor_mapping.version must be a non-empty string")
    if not isinstance(actors, dict) or not all(isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip() for key, value in actors.items()):
        raise ValueError("actor_mapping.actors must map canonical Monday person IDs to canonical actor IDs")
    return version, dict(actors)


def _decoded(raw: Any) -> dict[str, Any]:
    """Return the activity entry with its ``data`` JSON decoded; the caller's object is never mutated."""
    if not isinstance(raw, dict):
        raise QuarantineError(MALFORMED, "activity entry is not a JSON object")
    entry = copy.deepcopy(raw)
    data = entry.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise QuarantineError(MALFORMED, f"activity data is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise QuarantineError(MALFORMED, "activity data is missing or not an object")
    entry["data"] = data
    return entry


def _id(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    if isinstance(value, int) and value < 0:
        return None
    return str(value) if str(value).strip() else None


def _event_id(raw: Any) -> str | None:
    return _id(raw.get("id")) if isinstance(raw, dict) else None


def _freeze_raw(value: Any) -> Any:
    """Keep each JSON input occurrence as a detached, recursively immutable snapshot."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_raw(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_raw(item) for item in value)
    return copy.deepcopy(value)


def _typed_fingerprint(value: Any) -> Any:
    """Compare decoded JSON structurally without bool/int/float equality coercion."""
    if isinstance(value, dict):
        return ("object", frozenset((_typed_fingerprint(key), _typed_fingerprint(item)) for key, item in value.items()))
    if isinstance(value, list):
        return ("array", tuple(_typed_fingerprint(item) for item in value))
    return (type(value).__name__, value)


ISO_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$")


def _utc_z(whole_seconds: datetime, fraction_digits: str) -> str:
    """Render UTC with the exact source sub-second digits (trailing zeros dropped), never rounded."""
    fraction = fraction_digits.rstrip("0")
    return whole_seconds.astimezone(timezone.utc).isoformat(timespec="seconds")[:-6] + (f".{fraction}" if fraction else "") + "Z"


def _occurred_at(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0 or value >= 253402300800 * MONDAY_TICKS_PER_SECOND:
            raise QuarantineError(INVALID_TIMESTAMP, "created_at is outside the supported timestamp range")
        value = str(value)
    if not isinstance(value, str) or not value:
        raise QuarantineError(INVALID_TIMESTAMP, "created_at is missing")
    if value.isascii() and value.isdigit():
        try:
            seconds, ticks = divmod(int(value), MONDAY_TICKS_PER_SECOND)
            return _utc_z(datetime.fromtimestamp(seconds, tz=timezone.utc), f"{ticks:07d}")
        except (ValueError, OverflowError, OSError) as exc:
            raise QuarantineError(INVALID_TIMESTAMP, "created_at is outside the supported timestamp range") from exc
    match = ISO_TIMESTAMP.match(value)
    if match is None:
        raise QuarantineError(INVALID_TIMESTAMP, f"created_at {value!r} is not a Monday tick value or timezone-qualified ISO-8601 timestamp")
    whole, fraction, offset = match.groups()
    if offset != "Z" and (int(offset[1:3]) > 23 or int(offset[4:6]) > 59):
        raise QuarantineError(INVALID_TIMESTAMP, "created_at has an invalid UTC offset")
    try:
        moment = datetime.fromisoformat(whole + ("+00:00" if offset == "Z" else offset))
        return _utc_z(moment, fraction or "")
    except (ValueError, OverflowError, OSError) as exc:
        raise QuarantineError(INVALID_TIMESTAMP, "created_at is not a valid supported timestamp") from exc


def _instant(timestamp: str) -> tuple[datetime, int]:
    """Exact ordering key for a normalized UTC timestamp (whole seconds, nanoseconds)."""
    match = ISO_TIMESTAMP.match(timestamp)
    if match is None:
        raise ValueError(timestamp)
    whole, fraction, _ = match.groups()
    return datetime.fromisoformat(whole + "+00:00"), int((fraction or "").ljust(9, "0"))


def _label_text(value: Any, side: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise QuarantineError(MALFORMED, f"{side} is not a status column value object")
    label = value.get("label")
    if label is None:
        return None
    if not isinstance(label, dict) or not isinstance(label.get("text"), str):
        raise QuarantineError(MALFORMED, f"{side}.label.text is missing")
    return str(label["text"])


def _canonical_status(label: str, labels: dict[str, str], side: str) -> str:
    if label not in labels:
        raise QuarantineError(UNKNOWN_STATUS, f"{side} label {label!r} is not in the status mapping")
    return labels[label]


def _required_id(data: dict[str, Any], key: str) -> str:
    value = _id(data.get(key))
    if value is None:
        raise QuarantineError(MALFORMED, f"activity data.{key} is missing")
    return value


def _normalize_one(
    entry: dict[str, Any],
    event_id: str,
    column_ids: dict[str, frozenset[str]],
    labels: dict[str, str],
    actor_version: str | None,
    actors: dict[str, str],
) -> dict[str, Any]:
    data = entry["data"]
    if entry.get("event") != STATUS_EVENT_TYPE:
        raise QuarantineError(NON_STATUS_EVENT, f"event type {entry.get('event')!r} is not {STATUS_EVENT_TYPE}")
    board_id = _required_id(data, "board_id")
    column_id = _required_id(data, "column_id")
    if column_id not in column_ids.get(board_id, frozenset()):
        raise QuarantineError(NON_STATUS_EVENT, f"column {column_id!r} is not a mapped status column for board {board_id!r}")
    if data.get("column_type", STATUS_COLUMN_TYPE) != STATUS_COLUMN_TYPE:
        raise QuarantineError(NON_STATUS_EVENT, f"column type {data.get('column_type')!r} is not a status column")
    item_id = _required_id(data, "pulse_id")
    occurred_at = _occurred_at(entry.get("created_at"))

    to_label = _label_text(data.get("value"), "value")
    if to_label is None:
        raise QuarantineError(UNKNOWN_STATUS, "status was cleared; no destination status to map")
    to_status = _canonical_status(to_label, labels, "value")
    from_label = _label_text(data.get("previous_value"), "previous_value")
    from_status = None if from_label is None else _canonical_status(from_label, labels, "previous_value")

    user_id = entry.get("user_id")
    actor_monday_id = _id(user_id)
    if user_id is not None and user_id != "" and actor_monday_id is None:
        raise QuarantineError(MALFORMED, "activity user_id must be a string or integer ID")
    actor_id = actors.get(actor_monday_id) if actor_monday_id is not None else None

    return {
        "contract_version": CONTRACT_VERSION,
        "event_id": event_id,
        "monday_board_id": board_id,
        "monday_item_id": item_id,
        "status_column_id": column_id,
        "occurred_at": occurred_at,
        "from_status": from_status,
        "to_status": to_status,
        "actor_resolution": "canonical_monday_id" if actor_id is not None else "unresolved_waset_co",
        "actor_monday_id": actor_monday_id,
        "actor_id": actor_id,
        "mapping_version": actor_version,
    }


def _quarantine(index: int, event_id: str | None, reason: str, detail: str, raw: Any) -> dict[str, Any]:
    return {"input_index": index, "event_id": event_id, "reason": reason, "detail": detail, "raw": copy.deepcopy(raw)}


def normalize_events(
    raw_events: Iterable[Any],
    status_mapping: dict[str, Any],
    actor_mapping: dict[str, Any] | None = None,
) -> NormalizationResult:
    """Normalize Monday activity-log status changes into contract events.

    ``status_mapping``: ``{"version", "status_column_ids": {board_id: [column_id]}, "labels": {monday_label_text: canonical_status}}``.
    ``actor_mapping``: optional ``{"version", "actors": {monday_person_id: canonical_actor_id}}``.
    Actors without a mapping entry stay explicit as ``unresolved_waset_co`` with their Monday ID preserved.
    """
    status_version, column_ids, labels = _validated_status_mapping(status_mapping)
    actor_version, actors = _validated_actor_mapping(actor_mapping)

    quarantined: list[dict[str, Any]] = []
    by_id: dict[str, list[tuple[int, Any]]] = {}
    raw_input_snapshots: list[Any] = []
    for index, raw in enumerate(raw_events):
        raw = copy.deepcopy(raw)
        raw_input_snapshots.append(_freeze_raw(raw))
        event_id = _event_id(raw)
        if event_id is None:
            quarantined.append(_quarantine(index, None, MISSING_EVENT_ID, "activity entry has no id", raw))
            continue
        by_id.setdefault(event_id, []).append((index, raw))

    accepted: list[dict[str, Any]] = []
    raw_sources: dict[str, dict[str, Any]] = {}
    duplicate_event_ids: list[str] = []
    for event_id, occurrences in by_id.items():
        decoded: list[tuple[int, Any, dict[str, Any] | None, QuarantineError | None]] = []
        for index, raw in occurrences:
            try:
                decoded.append((index, raw, _decoded(raw), None))
            except QuarantineError as exc:
                decoded.append((index, raw, None, exc))

        if len(occurrences) > 1:
            first = decoded[0][2]
            if first is None or any(_typed_fingerprint(entry) != _typed_fingerprint(first) for _, _, entry, _ in decoded[1:]):
                for index, raw, _, _ in decoded:
                    quarantined.append(_quarantine(index, event_id, DUPLICATE_EVENT_CONFLICT, f"{len(occurrences)} records share id with differing content", raw))
                continue
            duplicate_event_ids.append(event_id)

        index, raw, entry, error = decoded[0]
        if error is not None or entry is None:
            reason, detail = (error.reason, error.detail) if error is not None else (MALFORMED, "undecodable entry")
            quarantined.append(_quarantine(index, event_id, reason, detail, raw))
            continue
        try:
            event = _normalize_one(entry, event_id, column_ids, labels, actor_version, actors)
        except QuarantineError as exc:
            quarantined.append(_quarantine(index, event_id, exc.reason, exc.detail, raw))
            continue
        errors = schema_errors(event, SCHEMA_NAME)
        if errors:
            quarantined.append(_quarantine(index, event_id, SCHEMA_INVALID, "; ".join(errors), raw))
            continue
        accepted.append(event)
        raw_sources[event_id] = copy.deepcopy(raw)

    accepted.sort(key=lambda event: (_instant(event["occurred_at"]), event["monday_board_id"], event["monday_item_id"], event["event_id"]))
    quarantined.sort(key=lambda record: record["input_index"])
    return NormalizationResult(
        accepted=accepted,
        quarantined=quarantined,
        raw_sources=raw_sources,
        duplicate_event_ids=sorted(duplicate_event_ids),
        unresolved_actor_event_ids=sorted(event["event_id"] for event in accepted if event["actor_resolution"] == "unresolved_waset_co"),
        status_mapping_version=status_version,
        actor_mapping_version=actor_version,
        raw_input_snapshots=tuple(raw_input_snapshots),
    )
