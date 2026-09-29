"""Raw Monday payload -> normalized events -> transition attribution -> work cycles.

``reconstruct_cycles`` is the production entry point. It takes the activity-log payload,
optionally the current items payload (used as the latest available Requested ETA), and
optional ingestion metadata describing what the ingestion can prove about coverage::

    {"retrieved_at": "...", "activity_log_window": {"since": "...", "until": "..."},
     "complete_history_item_ids": [...], "complete_history_basis": "..."}

An item's Requested ETA history is labelled complete only when its ID is listed in
``complete_history_item_ids``; otherwise it is "observed in ingested evidence".

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
from atlas_commander.monday_source import ColumnChange, item_column_snapshots, parse_column_changes, status_log_records
from atlas_commander.normalization import normalize_events, status_mapping_config
from atlas_commander.quality import QualityPolicy, QualityResult, quality_occurrences


@dataclass
class CycleReconstruction:
    contract_version: str
    status_events: list[dict[str, Any]]
    quarantined_status_logs: list[dict[str, Any]]
    rejected_logs: list[dict[str, Any]]
    column_changes: list[ColumnChange]
    transitions: list[dict[str, Any]]
    eta_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Current item values from the items payload, per tracked column, keyed by item ID.
    item_snapshots: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    ingestion: dict[str, Any] = field(default_factory=dict)
    cycles: list[CycleRecord] = field(default_factory=list)


def reconstruct_quality(result: CycleReconstruction, contract: Mapping[str, Any], calculated_at: str) -> QualityResult:
    """Quality occurrences for a reconstruction, using the current item values when they were ingested."""
    policy = QualityPolicy.from_contract(contract)
    snapshots: Mapping[str, Any] = (result.item_snapshots if len(policy.label_sources) > 1 else result.item_snapshots.get(policy.column_id, {}))
    return quality_occurrences(result.cycles, result.column_changes, policy, calculated_at, snapshots)


def reconstruct_cycles(activity_payload: Mapping[str, Any], contract: Mapping[str, Any], items_payload: Mapping[str, Any] | None = None,
                       ingestion: Mapping[str, Any] | None = None) -> CycleReconstruction:
    board = contract["source_board"]
    status_column = board["status_column_id"]
    records = status_log_records(dict(activity_payload), status_column)
    undo_ids = {str(record["id"]) for record in records if record.get("is_undo_action")}
    normalized = normalize_events(records, status_mapping_config(contract))
    tracked = frozenset({status_column, board["editor_column_id"], board["video_type_column_id"], board["requested_eta_column_id"],
                         board["performance_issues_column_id"], *([board["for_bonus_column_id"]] if board.get("for_bonus_column_id") else [])})
    changes, rejected = parse_column_changes(dict(activity_payload), tracked)
    transitions = attribute_transitions(normalized.accepted, TransitionRoleMapping.from_contract(contract))
    meta = dict(ingestion or {})
    item_snapshots = {column: item_column_snapshots(items_payload, column, meta.get("retrieved_at")) for column in sorted(tracked)} if items_payload is not None else {}
    snapshots = item_snapshots.get(board["requested_eta_column_id"], {})
    complete_ids = {str(value) for value in meta.get("complete_history_item_ids") or []}
    result = CycleReconstruction(contract["contract_version"], normalized.accepted, normalized.quarantined, rejected, changes, transitions, snapshots,
                                 item_snapshots, meta)

    quarantined_by_item: dict[str, list[dict[str, Any]]] = {}
    for entry in normalized.quarantined:
        raw: dict[str, Any] = entry["raw_source"] if isinstance(entry.get("raw_source"), dict) else {}
        data: dict[str, Any] = raw["data"] if isinstance(raw.get("data"), dict) else {}
        quarantined_by_item.setdefault(str(data.get("pulse_id")), []).append(entry)
    items: dict[tuple[str, str], None] = {}
    for event in normalized.accepted:
        items.setdefault((event["monday_board_id"], event["monday_item_id"]), None)
    policy = CyclePolicy.from_contract(contract)
    for board_id, item_id in sorted(items):
        coverage = {"complete_history": item_id in complete_ids, "activity_log_window": meta.get("activity_log_window"),
                    "basis": meta.get("complete_history_basis")}
        cycle = build_item_cycle(board_id, item_id, normalized.accepted, changes, policy, undo_ids, quarantined_by_item.get(item_id, ()),
                                 eta_snapshot=snapshots.get(item_id), history_coverage=coverage)
        if cycle is not None:
            result.cycles.append(cycle)
    return result
