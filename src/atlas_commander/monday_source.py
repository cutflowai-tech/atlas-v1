"""Read-only parsing of raw Monday activity logs into typed, evidence-preserving records.

Nothing here infers a business fact. Every record keeps the Monday log ID, board,
item, column, raw timestamp and raw values so derived results can point back to it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from atlas_monday_probe.adapter import AdapterError, activity_logs, monday_log_timestamp

REQUESTED_ETA_DATE_ONLY = "REQUESTED_ETA_DATE_ONLY"
REQUESTED_ETA_INVALID = "REQUESTED_ETA_INVALID"


@dataclass(frozen=True)
class ColumnChange:
    """One ``update_column_value`` activity log for a tracked column, exactly as reported."""

    log_id: str
    board_id: str
    item_id: str
    column_id: str
    column_type: str
    user_id: str
    created_at_raw: str
    occurred_at: str
    previous_value: Any
    value: Any
    is_undo_action: bool

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.created_at_raw.zfill(20), self.log_id)


def _data(log: dict[str, Any]) -> dict[str, Any]:
    data = log.get("data")
    if isinstance(data, str):
        data = json.loads(data)
    return data if isinstance(data, dict) else {}


def parse_column_changes(payload: dict[str, Any], column_ids: set[str] | frozenset[str]) -> tuple[list[ColumnChange], list[dict[str, Any]]]:
    """Return tracked column changes in (item, time, log ID) order, plus unparseable logs.

    Logs for other columns or other events are skipped without being counted as errors.
    """
    changes: list[ColumnChange] = []
    rejected: list[dict[str, Any]] = []
    for log in activity_logs(payload):
        if log.get("event") != "update_column_value":
            continue
        try:
            data = _data(log)
        except (TypeError, ValueError):
            rejected.append({"log_id": log.get("id"), "reason": "INVALID_ACTIVITY_DATA"})
            continue
        if data.get("column_id") not in column_ids:
            continue
        try:
            changes.append(ColumnChange(
                log_id=str(log["id"]), board_id=str(data["board_id"]), item_id=str(data["pulse_id"]), column_id=str(data["column_id"]),
                column_type=str(data.get("column_type")), user_id=str(log.get("user_id")), created_at_raw=str(log["created_at"]),
                occurred_at=monday_log_timestamp(str(log["created_at"])), previous_value=data.get("previous_value"), value=data.get("value"),
                is_undo_action=bool(data.get("is_undo_action")),
            ))
        except (KeyError, AdapterError):
            rejected.append({"log_id": log.get("id"), "reason": "INVALID_ACTIVITY_LOG"})
    changes.sort(key=lambda change: (change.item_id, *change.sort_key))
    return changes, rejected


def status_log_records(payload: dict[str, Any], column_id: str) -> list[dict[str, Any]]:
    """Status-column logs shaped for ``normalize_events``, with the tick timestamp converted.

    The raw tick value is retained as ``created_at_raw``; undo actions are marked so the
    cycle builder can flag them.
    """
    records = []
    for log in activity_logs(payload):
        if log.get("event") != "update_column_value":
            continue
        try:
            data = _data(log)
        except (TypeError, ValueError):
            continue
        if data.get("column_id") != column_id:
            continue
        record = {
            "id": log.get("id"),
            "event": log.get("event"),
            "board_id": data.get("board_id"),
            "user_id": log.get("user_id"),
            "created_at_raw": log.get("created_at"),
            "is_undo_action": bool(data.get("is_undo_action")),
            "data": {key: data.get(key) for key in ("pulse_id", "column_id", "previous_value", "value")},
        }
        try:
            record["occurred_at"] = monday_log_timestamp(str(log.get("created_at")))
        except AdapterError:
            record["occurred_at"] = None
        records.append(record)
    return records


def dropdown_value_ids(value: Any) -> tuple[str, ...]:
    """Label IDs from an activity-log dropdown value (``{"chosenValues": [...]}``) or item value (``{"ids": [...]}``)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return ()
    if not isinstance(value, dict):
        return ()
    if isinstance(value.get("chosenValues"), list):
        return tuple(str(choice["id"]) for choice in value["chosenValues"] if isinstance(choice, dict) and "id" in choice)
    if isinstance(value.get("ids"), list):
        return tuple(str(choice) for choice in value["ids"])
    return ()


def dropdown_value_labels(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict) and isinstance(value.get("chosenValues"), list):
        return tuple(str(choice.get("name")) for choice in value["chosenValues"] if isinstance(choice, dict))
    return ()


def requested_eta(value: Any) -> tuple[str | None, str | None]:
    """Return (UTC RFC 3339 ETA, None) or (None, reason). Date-only values are never given a guessed time."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None, REQUESTED_ETA_INVALID
    if value is None:
        return None, None
    if not isinstance(value, dict) or not isinstance(value.get("date"), str):
        return None, REQUESTED_ETA_INVALID
    if not value.get("time"):
        return None, REQUESTED_ETA_DATE_ONLY
    text = f"{value['date']}T{value['time']}Z"
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, REQUESTED_ETA_INVALID
    return text, None
