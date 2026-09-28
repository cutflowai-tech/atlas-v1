from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from atlas_commander.contracts import schema_errors

CONTRACT = "normalized-status-event.schema.json"
CONTRACT_VERSION = "1.0.0"
# Monday activity_logs.created_at is a 17-digit count of 100 ns ticks since the Unix epoch.
_TICKS_PER_SECOND = 10_000_000

_STATUS_PHASES = {
    "Create File": "pre-cycle", "Waiting": "pre-cycle", "Captions Revisions": "pre-cycle",
    "Captions In Progress": "pre-cycle", "Waiting For Captions": "pre-cycle", "Captions Done": "pre-cycle",
    "In Progress": "active-production", "Internal Revisions": "internal-rework",
    "Revisions": "external-client-rework", "TOPAZ": "delivery-preparation",
    "Ready To Send": "delivery-preparation", "Sent": "delivered", "Done": "delivered",
    "Ready For Approval": "approval-terminal",
}


class AdapterError(ValueError):
    pass


def monday_log_timestamp(raw: str) -> str:
    """Convert a raw activity-log created_at to RFC 3339 UTC without losing sub-second precision."""
    if not isinstance(raw, str) or not raw.isdigit() or len(raw) != 17:
        raise AdapterError(f"unrecognised Monday activity-log timestamp: {raw!r}")
    ticks = int(raw)
    seconds, remainder = divmod(ticks, _TICKS_PER_SECOND)
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=remainder // 10)
    return moment.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class StatusChange:
    """One status-column change exactly as Monday reported it; every raw identifier and timestamp is kept."""

    log_id: str
    event: str
    board_id: str
    item_id: str
    column_id: str
    column_type: str
    user_id: str
    account_id: str
    created_at_raw: str
    occurred_at: str
    from_label_index: int | None
    from_label_text: str | None
    to_label_index: int | None
    to_label_text: str | None
    is_undo_action: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _label(value: Any) -> tuple[int | None, str | None]:
    if not isinstance(value, dict) or not isinstance(value.get("label"), dict):
        return None, None
    label = value["label"]
    return label.get("index"), label.get("text")


def activity_logs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    boards = payload.get("boards") or []
    return [log for board in boards for log in (board.get("activity_logs") or [])]


def parse_status_changes(payload: dict[str, Any], column_id: str) -> list[StatusChange]:
    changes = []
    for log in activity_logs(payload):
        if log.get("event") != "update_column_value":
            continue
        data = json.loads(log["data"]) if isinstance(log.get("data"), str) else log.get("data") or {}
        if data.get("column_id") != column_id:
            continue
        from_index, from_text = _label(data.get("previous_value"))
        to_index, to_text = _label(data.get("value"))
        changes.append(StatusChange(
            log_id=str(log["id"]), event=log["event"], board_id=str(data["board_id"]), item_id=str(data["pulse_id"]),
            column_id=data["column_id"], column_type=str(data.get("column_type")), user_id=str(log["user_id"]),
            account_id=str(log["account_id"]), created_at_raw=str(log["created_at"]),
            occurred_at=monday_log_timestamp(str(log["created_at"])), from_label_index=from_index, from_label_text=from_text,
            to_label_index=to_index, to_label_text=to_text, is_undo_action=bool(data.get("is_undo_action")),
        ))
    return sorted(changes, key=lambda change: (change.item_id, change.created_at_raw, change.log_id))


@dataclass(frozen=True)
class StatusMapping:
    """Versioned, owner-approved mapping from Monday status label index to contract status. Never inferred."""

    version: str
    board_id: str
    column_id: str
    labels: dict[int, str]


@dataclass(frozen=True)
class ActorMapping:
    """Versioned mapping from canonical Monday user ID to Atlas actor ID, plus declared shared Waset Co accounts."""

    version: str
    actors: dict[str, str]
    waset_co_accounts: frozenset[str]


def normalize(change: StatusChange, status_mapping: StatusMapping | None, actor_mapping: ActorMapping | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Build a NormalizedStatusEvent only from explicit versioned mappings; otherwise return the blocking reasons."""
    reasons = []
    if change.is_undo_action:
        reasons.append("UNDO_ACTION")
    if status_mapping is None:
        reasons.append("STATUS_MAPPING_MISSING")
    elif (status_mapping.board_id, status_mapping.column_id) != (change.board_id, change.column_id):
        reasons.append("STATUS_MAPPING_SCOPE_MISMATCH")
    else:
        if change.to_label_index not in status_mapping.labels:
            reasons.append("UNMAPPED_TO_STATUS")
        if change.from_label_index is not None and change.from_label_index not in status_mapping.labels:
            reasons.append("UNMAPPED_FROM_STATUS")
    if actor_mapping is None:
        reasons.append("ACTOR_MAPPING_MISSING")
    elif change.user_id not in actor_mapping.actors and change.user_id not in actor_mapping.waset_co_accounts:
        reasons.append("ACTOR_NOT_IN_MAPPING")
    if reasons or status_mapping is None or actor_mapping is None:
        return None, reasons
    waset_co = change.user_id in actor_mapping.waset_co_accounts
    from_status = None if change.from_label_index is None else status_mapping.labels[change.from_label_index]
    to_status = status_mapping.labels[change.to_label_index]  # type: ignore[index]
    event: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "event_id": change.log_id,
        "monday_board_id": change.board_id,
        "monday_item_id": change.item_id,
        "status_column_id": change.column_id,
        "occurred_at": change.occurred_at,
        "from_status": from_status,
        "to_status": to_status,
        "raw_from_status": change.from_label_text,
        "raw_to_status": change.to_label_text or to_status,
        "status_phase_from": None if from_status is None else _STATUS_PHASES.get(from_status, from_status),
        "status_phase_to": _STATUS_PHASES.get(to_status, to_status),
        "actor_resolution": "unresolved_waset_co" if waset_co else "canonical_monday_id",
        "actor_monday_id": change.user_id,
        "actor_id": None if waset_co else actor_mapping.actors[change.user_id],
        "mapping_version": f"{status_mapping.version}+{actor_mapping.version}",
        "actor_mapping_version": actor_mapping.version,
    }
    errors = schema_errors(event, CONTRACT)
    if errors:
        return None, ["SCHEMA_INVALID", *errors]
    return event, []


def dropdown_ids(item: dict[str, Any], column_id: str) -> list[int]:
    """Raw dropdown label IDs for an item column (e.g. Editor Name). No identity is derived from them here."""
    for column in item.get("column_values") or []:
        if column.get("id") == column_id and column.get("value"):
            ids: list[int] = json.loads(column["value"]).get("ids") or []
            return ids
    return []
