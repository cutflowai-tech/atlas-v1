"""Deterministic, fixture-only normalization of Monday activity records."""
from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .contracts import schema_errors

STATUSES = {"Backlog", "In Progress", "Ready For Approval", "Revision", "Approved", "Delivered"}


@dataclass
class NormalizationResult:
    """Unpacks as (accepted, quarantined); raw_sources retains every input record.

    Quarantine entries contain input_index, event_id, reason and raw_source.
    Accepted events contain only contract fields. Neither inputs nor mappings are
    mutated; raw_sources is a separate deep copy in original input order.
    """

    accepted: list[dict[str, Any]]
    quarantined: list[dict[str, Any]]
    raw_sources: list[Any]

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        yield self.accepted
        yield self.quarantined


def _id(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _status(value: Any, mapping: dict[str, str], *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    # Monday activity data wraps status text in value/previous_value.label.text.
    if isinstance(value, dict):
        value = value.get("label")
        if isinstance(value, dict):
            value = value.get("text")
    if not isinstance(value, str) or value not in mapping:
        raise ValueError("UNKNOWN_STATUS")
    return mapping[value]


def _normalize(raw: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    data = raw.get("data", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError) as exc:
            raise ValueError("INVALID_ACTIVITY_DATA") from exc
    if not isinstance(data, dict):
        raise TypeError("INVALID_ACTIVITY_DATA")
    if "event" in raw and raw["event"] != "update_column_value":
        raise ValueError("UNSUPPORTED_EVENT")
    # Prefer explicit canonical fields, never substitute display names for IDs.
    event = {
        "contract_version": "1.0.0",
        "event_id": _id(raw.get("event_id", raw.get("id"))),
        "monday_board_id": _id(raw.get("monday_board_id", raw.get("board_id", data.get("board_id")))),
        "monday_item_id": _id(raw.get("monday_item_id", data.get("pulse_id", data.get("item_id")))),
        "status_column_id": _id(raw.get("status_column_id", data.get("column_id"))),
        "occurred_at": raw.get("occurred_at", raw.get("created_at")),
        "from_status": _status(raw.get("from_status", data.get("previous_value")), mapping, optional=True),
        "to_status": _status(raw.get("to_status", data.get("value")), mapping),
        "actor_monday_id": _id(raw.get("actor_monday_id", raw.get("user_id"))),
        "actor_id": None,
        "mapping_version": None,
        "actor_resolution": "unresolved_waset_co",
    }
    if (raw.get("actor_resolution") == "canonical_monday_id"
            and event["actor_monday_id"] and _id(raw.get("actor_id")) and _id(raw.get("mapping_version"))):
        event.update(actor_resolution="canonical_monday_id", actor_id=_id(raw["actor_id"]), mapping_version=_id(raw["mapping_version"]))
    if schema_errors(event, "normalized-status-event.schema.json"):
        raise ValueError("INVALID_EVENT")
    return event


def normalize_events(raw_events: Any, status_mapping: dict[str, str]) -> NormalizationResult:
    """Normalize an array (or JSON-encoded array) using exact source-label keys.

    Mapping values must be contract statuses. No identity/status inference occurs.
    Existing actor mappings require explicit canonical resolution and a version.
    Timestamps must be RFC3339 strings and are preserved verbatim; ambiguous
    numeric timestamps are quarantined rather than assigned an inferred unit.
    Duplicate identity compares the entire raw JSON record (object order ignored).
    All conflicting occurrences are quarantined; identical repeats keep the first
    and quarantine subsequent occurrences. Output order follows input order.
    Invalid batch/mapping configuration raises ValueError or TypeError before processing.
    """
    if (not isinstance(status_mapping, dict)
            or any(not isinstance(k, str) or not isinstance(v, str) or v not in STATUSES for k, v in status_mapping.items())):
        raise ValueError("status_mapping must map exact source labels to contract statuses")
    if isinstance(raw_events, str):
        raw_events = json.loads(raw_events)
    if not isinstance(raw_events, list):
        raise TypeError("raw_events must be a JSON array")
    sources = deepcopy(raw_events)
    fingerprints: dict[str, set[str]] = {}
    for raw in sources:
        event_id = _id(raw.get("event_id", raw.get("id"))) if isinstance(raw, dict) else None
        if event_id:
            fingerprints.setdefault(event_id, set()).add(json.dumps(raw, sort_keys=True, separators=(",", ":")))
    accepted: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(sources):
        event_id = _id(raw.get("event_id", raw.get("id"))) if isinstance(raw, dict) else None
        try:
            if not isinstance(raw, dict) or event_id is None:
                raise ValueError("INVALID_EVENT")
            if len(fingerprints[event_id]) > 1:
                raise ValueError("CONFLICTING_DUPLICATE_EVENT")
            if event_id in seen:
                raise ValueError("DUPLICATE_EVENT")
            seen.add(event_id)
            accepted.append(_normalize(raw, status_mapping))
        except (ValueError, TypeError) as exc:
            quarantined.append({"input_index": index, "event_id": event_id, "reason": str(exc), "raw_source": deepcopy(raw)})
    return NormalizationResult(accepted, quarantined, sources)
