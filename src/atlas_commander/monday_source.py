"""Read-only parsing of raw Monday activity logs into typed, evidence-preserving records.

Nothing here infers a business fact. Every record keeps the Monday log ID, board,
item, column, raw timestamp and raw values so derived results can point back to it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from atlas_monday_probe.adapter import AdapterError, activity_logs, monday_log_timestamp

REQUESTED_ETA_DATE_ONLY = "REQUESTED_ETA_DATE_ONLY"
REQUESTED_ETA_INVALID = "REQUESTED_ETA_INVALID"


@dataclass(frozen=True)
class ColumnChange:
    """One tracked column observation from an activity log, exactly as reported.

    ``source`` is ``update_column_value`` for an edit, or ``create_pulse`` for the value the
    item was created with (Monday's ``column_values_json``); a creation value has no previous value.
    """

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
    source: str = "update_column_value"

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

    ``create_pulse`` logs contribute one creation observation per tracked column present in
    the item's initial values. Logs for other columns or other events are skipped without
    being counted as errors.
    """
    changes: list[ColumnChange] = []
    rejected: list[dict[str, Any]] = []
    for log in activity_logs(payload):
        if log.get("event") == "create_pulse":
            try:
                changes.extend(_creation_observations(log, column_ids))
            except (KeyError, TypeError, ValueError, AdapterError):
                rejected.append({"log_id": log.get("id"), "reason": "INVALID_CREATE_PULSE_LOG"})
            continue
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


def _creation_observations(log: dict[str, Any], column_ids: set[str] | frozenset[str]) -> list[ColumnChange]:
    data = _data(log)
    initial = data.get("initial_values")
    if initial is None:
        initial = data.get("column_values_json")
        if isinstance(initial, str):
            initial = json.loads(initial)
    if not isinstance(initial, dict):
        return []
    occurred_at = monday_log_timestamp(str(log["created_at"]))
    return [ColumnChange(log_id=str(log["id"]), board_id=str(data["board_id"]), item_id=str(data["pulse_id"]), column_id=column_id,
                         column_type="create_pulse", user_id=str(log.get("user_id")), created_at_raw=str(log["created_at"]), occurred_at=occurred_at,
                         previous_value=None, value=value, is_undo_action=False, source="create_pulse")
            for column_id, value in sorted(initial.items()) if column_id in column_ids and value is not None]


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


def _items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("items"), list):
        return list(payload["items"])
    items: list[dict[str, Any]] = []
    for board in payload.get("boards") or []:
        page = board.get("items_page") if isinstance(board, dict) else None
        items.extend((page or {}).get("items") or [])
        items.extend(board.get("items") or [] if isinstance(board, dict) else [])
    return items


def item_column_snapshots(items_payload: Mapping[str, Any], column_id: str, retrieved_at: str | None = None) -> dict[str, dict[str, Any]]:
    """Current item values for one column from a Monday items query, keyed by item ID.

    Only items whose response actually contains the column are returned; an absent column
    is "not fetched", while a present column with a null value is the current empty value.
    Each snapshot carries a stable evidence ID and the ingestion time, never a guessed
    change time.
    """
    snapshots: dict[str, dict[str, Any]] = {}
    for item in _items(items_payload):
        column = next((value for value in item.get("column_values") or [] if value.get("id") == column_id), None)
        if column is None:
            continue
        board: dict[str, Any] = item["board"] if isinstance(item.get("board"), dict) else {}
        item_id = str(item["id"])
        snapshots[item_id] = {
            "monday_board_id": str(board.get("id")) if board.get("id") is not None else None,
            "monday_item_id": item_id,
            "column_id": column_id,
            "value": column.get("value"),
            "text": column.get("text"),
            "retrieved_at": retrieved_at,
            "evidence_id": f"item-snapshot:{item_id}:{column_id}" + (f"@{retrieved_at}" if retrieved_at else ""),
        }
    return snapshots
