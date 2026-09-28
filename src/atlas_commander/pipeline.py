"""Raw Monday payload -> normalized events -> transition attribution -> work cycles.

Every stage keeps what it could not use: status logs that fail normalization,
activity logs that cannot be parsed, and cycles excluded from aggregates are all
returned with reason codes instead of being dropped.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from atlas_commander.attribution import TransitionRoleMapping, attribute_transitions
from atlas_commander.cycles import CyclePolicy, CycleRecord, build_item_cycle
from atlas_commander.monday_source import ColumnChange, parse_column_changes, status_log_records
from atlas_commander.normalization import normalize_events


@dataclass
class CycleReconstruction:
    contract_version: str
    status_events: list[dict[str, Any]]
    quarantined_status_logs: list[dict[str, Any]]
    rejected_logs: list[dict[str, Any]]
    column_changes: list[ColumnChange]
    transitions: list[dict[str, Any]]
    cycles: list[CycleRecord] = field(default_factory=list)


def reconstruct_cycles(activity_payload: Mapping[str, Any], contract: Mapping[str, Any]) -> CycleReconstruction:
    board = contract["source_board"]
    status_column = board["status_column_id"]
    records = status_log_records(dict(activity_payload), status_column)
    undo_ids = {str(record["id"]) for record in records if record.get("is_undo_action")}
    normalized = normalize_events(records, {"version": contract["status_mapping_version"], "statuses": contract["status_mapping"]})
    tracked = frozenset({board["editor_column_id"], board["video_type_column_id"], board["requested_eta_column_id"], board["performance_issues_column_id"]})
    changes, rejected = parse_column_changes(dict(activity_payload), tracked)
    transitions = attribute_transitions(normalized.accepted, TransitionRoleMapping.from_contract(contract))
    result = CycleReconstruction(contract["contract_version"], normalized.accepted, normalized.quarantined, rejected, changes, transitions)

    quarantined_by_item: dict[str, list[str]] = {}
    for entry in normalized.quarantined:
        raw: dict[str, Any] = entry["raw_source"] if isinstance(entry.get("raw_source"), dict) else {}
        data: dict[str, Any] = raw["data"] if isinstance(raw.get("data"), dict) else {}
        quarantined_by_item.setdefault(str(data.get("pulse_id")), []).append(str(raw.get("id")))
    items: dict[tuple[str, str], None] = {}
    for event in normalized.accepted:
        items.setdefault((event["monday_board_id"], event["monday_item_id"]), None)
    policy = CyclePolicy.from_contract(contract)
    for board_id, item_id in sorted(items):
        cycle = build_item_cycle(board_id, item_id, normalized.accepted, changes, policy, undo_ids, quarantined_by_item.get(item_id, ()))
        if cycle is not None:
            result.cycles.append(cycle)
    return result
