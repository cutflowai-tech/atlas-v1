"""Deterministic, fixture-driven normalization of Monday status activity."""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "contracts/normalized-status-event.schema.json").read_text())
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_STATUSES = set(_SCHEMA["properties"]["to_status"]["enum"])


@dataclass
class NormalizationResult:
    """Unpack as accepted, quarantined; raw_sources retains every input by index."""

    accepted: list[dict[str, Any]]
    quarantined: list[dict[str, Any]]
    raw_sources: list[Any]
    status_mapping_version: str

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        yield self.accepted
        yield self.quarantined


def _id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError("INVALID_ID")
    return str(value)


def _status(value: Any, mapping: dict[str, str], *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if isinstance(value, dict):
        value = value.get("label", value)
        if isinstance(value, dict):
            value = value.get("text", value.get("index"))
    if isinstance(value, bool) or not isinstance(value, (str, int)) or str(value) not in mapping:
        raise ValueError("UNKNOWN_STATUS")
    return mapping[str(value)]


def _timestamp(value: Any) -> str:
    # Monday activity created_at uses Unix timestamps in 100-nanosecond units.
    # Never pass these through a float (which would discard source precision).
    if isinstance(value, str) and not value.isdigit():
        return value  # Schema checks RFC3339; preserve source offset and precision.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise TypeError("INVALID_TIMESTAMP")
    try:
        ticks = int(value)
        seconds, fraction = divmod(ticks, 10_000_000)
        instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
        return instant.strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction:07d}Z"
    except (ValueError, OverflowError):
        raise ValueError("INVALID_TIMESTAMP") from None


def _normalize(raw: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    activity = "data" in raw
    data = raw.get("data", raw)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            raise ValueError("INVALID_ACTIVITY_DATA") from None
    if not isinstance(data, dict):
        raise TypeError("INVALID_ACTIVITY_DATA")
    if activity and raw.get("event", "update_column_value") != "update_column_value":
        raise ValueError("UNSUPPORTED_EVENT")
    try:
        event = {
            "contract_version": "1.0.0",
            "event_id": _id(raw["id"] if activity else raw["event_id"]),
            "monday_board_id": _id(data["board_id"] if activity else raw["monday_board_id"]),
            "monday_item_id": _id(data["pulse_id"] if activity else raw["monday_item_id"]),
            "status_column_id": _id(data["column_id"] if activity else raw["status_column_id"]),
            "occurred_at": _timestamp(raw["created_at"] if activity else raw["occurred_at"]),
            "from_status": _status(data.get("previous_value") if activity else raw.get("from_status"), mapping, nullable=True),
            "to_status": _status(data["value"] if activity else raw["to_status"], mapping),
        }
    except KeyError:
        raise ValueError("MISSING_FIELD") from None
    source_actor = raw.get("user_id") if activity else raw.get("actor_monday_id")
    monday_id = _id(source_actor) if source_actor is not None else None
    actor_id = raw.get("actor_id")
    version = raw.get("mapping_version")
    resolved = (
        monday_id is not None
        and isinstance(actor_id, str) and bool(actor_id.strip())
        and isinstance(version, str) and bool(version.strip())
        and raw.get("actor_resolution") == "canonical_monday_id"
    )
    event.update({
        "actor_resolution": "canonical_monday_id" if resolved else "unresolved_waset_co",
        "actor_monday_id": monday_id,
        "actor_id": actor_id if resolved else None,
        "mapping_version": version if resolved else None,
    })
    if not _VALIDATOR.is_valid(event):
        raise ValueError("SCHEMA_INVALID")
    return event


def normalize_events(raw_events: Any, status_mapping: dict[str, Any]) -> NormalizationResult:
    """Normalize an iterable (or JSON array string) without modifying its input.

    status_mapping is {"version": "status-v1", "statuses": {source: canonical}}.
    Only explicitly mapped labels/index strings are accepted, including canonical
    labels. Activity records use id, created_at, user_id and data (object or JSON
    string) containing board_id, pulse_id, column_id, previous_value and value.
    Contract-shaped records are also supported. Absent previous_value is null.

    Source snapshots are indexed in input order. Quarantine records contain
    source_index, event_id, reason and raw_source. Exact JSON-identical repeats
    keep the first accepted event and quarantine subsequent copies. Conflicting
    IDs quarantine the entire group, even when the conflict is otherwise invalid.
    JSON object key order is insignificant; all other source differences conflict.
    Accepted events retain first-source order. No metrics or actor guesses occur.
    """
    version = status_mapping.get("version")
    mapping = status_mapping.get("statuses")
    if not isinstance(version, str) or not version.strip() or not isinstance(mapping, dict) or not mapping:
        raise ValueError("A nonempty version and statuses mapping are required")
    if any(not isinstance(key, str) or not isinstance(value, str) or value not in _STATUSES for key, value in mapping.items()):
        raise ValueError("Status mappings must map string source values to canonical statuses")
    if isinstance(raw_events, str):
        raw_events = json.loads(raw_events)
    if isinstance(raw_events, (dict, str, bytes)):
        raise TypeError("raw_events must be an iterable of records")
    sources = deepcopy(list(raw_events))
    result = NormalizationResult([], [], sources, version)
    groups: dict[str, list[int]] = defaultdict(list)
    identities: dict[int, str] = {}
    fingerprints: dict[int, str] = {}
    for index, raw in enumerate(sources):
        if isinstance(raw, dict):
            try:
                event_id = _id(raw.get("id") if "data" in raw else raw.get("event_id"))
            except ValueError:
                continue
            groups[event_id].append(index)
            identities[index] = event_id
            fingerprints[index] = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    conflicts = {event_id for event_id, indices in groups.items() if len({fingerprints[index] for index in indices}) > 1}
    for index, raw in enumerate(sources):
        source_event_id = identities.get(index)
        try:
            if source_event_id in conflicts:
                raise ValueError("CONFLICTING_DUPLICATE_ID")
            if source_event_id is not None and groups[source_event_id][0] != index:
                raise ValueError("DUPLICATE_EVENT")
            if not isinstance(raw, dict):
                raise TypeError("INVALID_RECORD")
            result.accepted.append(_normalize(raw, mapping))
        except (ValueError, TypeError) as error:
            result.quarantined.append({
                "source_index": index, "event_id": source_event_id,
                "reason": str(error), "raw_source": deepcopy(raw),
            })
    return result
