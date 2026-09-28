"""Deterministic normalization of Monday activity records, without inferred facts.

status_mapping is {"version": str, "statuses": {source_label: canonical_label}}.
Input records use Monday activity fields id, board_id, created_at, user_id and
 data (an object or JSON object string) containing pulse_id, column_id,
previous_value and value. Status values may be strings or {"label": {"text": str}}.
Canonical contract-shaped records are also accepted, but still require the map.
Actor mappings are preserved only when all canonical mapping fields are supplied.
"""

import json
import re
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

STATUSES = {"Backlog", "In Progress", "Ready For Approval", "Revision", "Approved", "Delivered", "Create File", "Internal Revisions", "Revisions", "TOPAZ", "Ready To Send", "Sent", "Done", "Waiting", "Captions Revisions", "Captions In Progress", "Waiting For Captions", "Captions Done"}
PHASES = {"pre-cycle", "active-production", "internal-rework", "external-client-rework", "delivery-preparation", "delivered", "approval-terminal"}


@dataclass
class NormalizationResult:
    accepted: list[dict[str, Any]]
    quarantined: list[dict[str, Any]]
    raw_sources: list[Any]
    status_mapping_version: str

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        """Support accepted, quarantined = normalize_events(...)."""
        yield self.accepted
        yield self.quarantined


def _id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError("INVALID_ID")
    return str(value)


def _label(value: Any) -> Any:
    if isinstance(value, dict):
        if "label" not in value:
            raise ValueError("UNKNOWN_STATUS")
        value = value["label"]
        if isinstance(value, dict):
            if "text" not in value or not isinstance(value["text"], str):
                raise ValueError("UNKNOWN_STATUS")
            value = value["text"]
    if value is not None and not isinstance(value, str):
        raise ValueError("UNKNOWN_STATUS")
    return value


def _normalize(raw: dict[str, Any], statuses: dict[str, str], version: str) -> dict[str, Any]:
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
    timestamp = raw.get("occurred_at", raw.get("created_at"))
    if not isinstance(timestamp, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", timestamp):
        raise ValueError("INVALID_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None:
        raise ValueError("INVALID_TIMESTAMP")
    before = _label(raw.get("from_status", data.get("previous_value")))
    after = _label(raw.get("to_status", data.get("value")))
    if after not in statuses or (before is not None and before not in statuses):
        raise ValueError("UNKNOWN_STATUS")
    event = {
        "contract_version": "1.0.0",
        "event_id": _id(raw.get("event_id", raw.get("id"))),
        "monday_board_id": _id(raw.get("monday_board_id", raw.get("board_id"))),
        "monday_item_id": _id(raw.get("monday_item_id", data.get("pulse_id"))),
        "status_column_id": _id(raw.get("status_column_id", data.get("column_id"))),
        "occurred_at": timestamp,
        "from_status": statuses[before] if before is not None and statuses[before] in STATUSES else before,
        "to_status": statuses[after] if statuses[after] in STATUSES else after,
        "raw_from_status": before,
        "raw_to_status": after,
        "status_phase_from": statuses.get(before) if before is not None else None,
        "status_phase_to": statuses[after],
        "actor_resolution": "unresolved_waset_co",
        "actor_monday_id": None,
        "actor_id": None,
        "mapping_version": version,
        "actor_mapping_version": None,
    }
    monday_id = raw.get("actor_monday_id", raw.get("user_id"))
    if monday_id is not None:
        event["actor_monday_id"] = _id(monday_id)
    if raw.get("actor_resolution") == "canonical_monday_id":
        event.update(actor_resolution="canonical_monday_id", actor_monday_id=_id(monday_id),
                     actor_id=_id(raw.get("actor_id")), actor_mapping_version=_id(raw.get("actor_mapping_version", raw.get("mapping_version"))))
    return event


def normalize_events(raw_events: Any, status_mapping: dict[str, Any]) -> NormalizationResult:
    """Return accepted/quarantined records and independent raw evidence.

    Raw evidence is position-aligned with input. Quarantine entries carry source_index,
    reason and raw_source. Exact duplicate occurrences are quarantined after the first;
    conflicting IDs quarantine *all* occurrences. Input order is preserved. Invalid
    mapping configuration raises ValueError/TypeError; malformed records are quarantined.
    """
    if not isinstance(status_mapping, dict):
        raise TypeError("INVALID_STATUS_MAPPING")
    version = status_mapping.get("version") or status_mapping.get("status_mapping_version")
    statuses = status_mapping.get("statuses") or status_mapping.get("status_mapping")
    if (not isinstance(version, str) or not version.strip() or not isinstance(statuses, dict)
            or not statuses or any(not isinstance(k, str) or not k or not isinstance(v, str)
                                   or (v not in STATUSES and v not in PHASES) for k, v in statuses.items())):
        raise ValueError("INVALID_STATUS_MAPPING")
    if isinstance(raw_events, str):
        raw_events = json.loads(raw_events)
    if not isinstance(raw_events, list):
        raise TypeError("EXPECTED_EVENT_LIST")
    sources = deepcopy(raw_events)
    groups: dict[str, list[int]] = {}
    for index, raw in enumerate(sources):
        if isinstance(raw, dict):
            try:
                key = _id(raw.get("event_id", raw.get("id")))
            except ValueError:
                continue
            groups.setdefault(key, []).append(index)
    reasons = {}
    for indexes in groups.values():
        if len(indexes) > 1:
            # JSON equality must distinguish booleans from numeric IDs/values.
            signatures = {json.dumps(sources[i], sort_keys=True, ensure_ascii=False) for i in indexes}
            conflict = len(signatures) > 1
            for i in indexes if conflict else indexes[1:]:
                reasons[i] = "CONFLICTING_EVENT_ID" if conflict else "DUPLICATE_EVENT_ID"
    result = NormalizationResult([], [], sources, version)
    for index, raw in enumerate(sources):
        try:
            if index in reasons:
                raise ValueError(reasons[index])
            if not isinstance(raw, dict):
                raise TypeError("INVALID_EVENT")
            result.accepted.append(_normalize(raw, statuses, version))
        except (ValueError, TypeError) as exc:
            result.quarantined.append({"source_index": index, "reason": str(exc), "raw_source": deepcopy(raw)})
    return result
