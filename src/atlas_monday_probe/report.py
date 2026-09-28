from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander.contracts import CONTRACTS, ROOT

from .adapter import StatusChange, dropdown_ids
from .raw_store import RawRecord

MANIFEST_VERSION = "data-001-manifest-v1"
DRIFT_VERSION = "data-001-drift-v1"
CONTRACT_CONFIG = ROOT / "config" / "monday-contract-v1.0.json"
# Only these StatusChange fields leave the raw store; item names, people names, links and update bodies never do.
MANIFEST_FIELDS = (
    "log_id", "board_id", "item_id", "column_id", "column_type", "user_id", "account_id", "created_at_raw", "occurred_at",
    "from_label_index", "from_label_text", "to_label_index", "to_label_text", "is_undo_action",
)


def contract_statuses() -> list[str]:
    schema = json.loads((CONTRACTS / "normalized-status-event.schema.json").read_text())
    statuses: list[str] = schema["properties"]["to_status"]["enum"]
    return statuses


def approved_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_CONFIG.read_text())


def column_settings(users_columns: dict[str, Any], column_id: str) -> dict[str, Any]:
    for board in users_columns.get("boards") or []:
        for column in board.get("columns") or []:
            if column["id"] == column_id:
                settings: dict[str, Any] = json.loads(column["settings_str"])
                return {"type": column["type"], "title": column["title"], "settings": settings}
    raise KeyError(column_id)


def snapshot_column_settings(snapshot_markdown: str, column_id: str) -> dict[str, Any]:
    """Read one column's settings_str from an immutable raw board snapshot table row."""
    match = re.search(rf"^\| `{re.escape(column_id)}` \| [^|]* \| `(\w+)` \| \w+ \| `(.*)` \|$", snapshot_markdown, re.MULTILINE)
    if not match:
        raise KeyError(column_id)
    settings: dict[str, Any] = json.loads(match.group(2))
    return {"type": match.group(1), "settings": settings}


def _status_labels(settings: dict[str, Any]) -> dict[str, str]:
    return {str(index): text for index, text in settings.get("labels", {}).items() if text}


def _dropdown_labels(settings: dict[str, Any]) -> dict[str, str]:
    return {str(label["id"]): label["name"] for label in settings.get("labels", [])}


def _diff(baseline: dict[str, str], live: dict[str, str]) -> dict[str, Any]:
    return {
        "added": {key: live[key] for key in sorted(live.keys() - baseline.keys(), key=int)},
        "removed": {key: baseline[key] for key in sorted(baseline.keys() - live.keys(), key=int)},
        "renamed": {key: {"from": baseline[key], "to": live[key]} for key in sorted(baseline.keys() & live.keys(), key=int) if baseline[key] != live[key]},
    }


def _column_value(item: dict[str, Any], column_id: str) -> dict[str, Any]:
    return next((column for column in item.get("column_values") or [] if column["id"] == column_id), {})


def _millis(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def build_manifest(changes: list[StatusChange], records: list[RawRecord], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_version": MANIFEST_VERSION,
        "source": "monday",
        "access": context["access"],
        "mutation_performed": False,
        "scope": context["scope"],
        "raw_payloads": [{"name": record.name, "sha256": record.sha256, "size_bytes": record.size_bytes} for record in records],
        "raw_store": context["raw_store"],
        "redaction": {
            "retained": list(MANIFEST_FIELDS),
            "removed": ["pulse_name", "item names", "people names", "emails", "links", "update bodies", "label colours"],
        },
        "status_change_count": len(changes),
        "status_changes": [{field: change.as_dict()[field] for field in MANIFEST_FIELDS} for change in changes],
    }


def build_drift_report(
    changes: list[StatusChange],
    items: dict[str, Any],
    users_columns: dict[str, Any],
    baseline_snapshot: str | None,
    columns: dict[str, str],
) -> dict[str, Any]:
    enum = contract_statuses()
    config = approved_contract()
    status_live = column_settings(users_columns, columns["status"])
    status_labels = _status_labels(status_live["settings"])
    findings: list[dict[str, Any]] = []

    status_mapping = config["status_mapping"]
    unmatched = {index: text for index, text in status_labels.items() if text not in status_mapping}
    findings.append({
        "code": "STATUS_LABEL_VOCABULARY_DRIFT", "field": "from_status/to_status", "blocking": bool(unmatched),
        "detail": "Monday labels are checked against the approved v1.0 status registry; unmapped labels are not inferred.",
        "mapping_version": config["status_mapping_version"],
        "exact_text_matches": {index: text for index, text in status_labels.items() if text in status_mapping},
        "monday_labels_without_contract_value": unmatched,
        "contract_values_without_monday_label": sorted(set(enum) - set(status_labels.values())),
    })
    transitions = Counter(f"{change.from_label_text} -> {change.to_label_text}" for change in changes)
    findings.append({
        "code": "OBSERVED_TRANSITIONS", "field": "from_status/to_status", "blocking": False,
        "detail": "Raw label transitions observed in the probed activity logs.",
        "counts": dict(sorted(transitions.items())),
        "outside_contract_enum": sorted({text for change in changes for text in (change.from_label_text, change.to_label_text) if text and text not in enum}),
    })
    findings.append({
        "code": "TIMESTAMP_ENCODING", "field": "occurred_at", "blocking": False,
        "detail": "activity_logs.created_at is a 17-digit string of 100ns ticks since epoch, not RFC 3339; the adapter converts it and retains the raw value.",
        "raw_examples": [change.created_at_raw for change in changes[:3]],
        "converted_examples": [change.occurred_at for change in changes[:3]],
    })
    cross_checks = []
    for item in items.get("items") or []:
        latest = [change for change in changes if change.item_id == str(item["id"])]
        status_value = _column_value(item, columns["status"]).get("value")
        if latest and status_value:
            changed_at = json.loads(status_value).get("changed_at")
            cross_checks.append({
                "item_id": str(item["id"]), "latest_log_id": latest[-1].log_id, "log_occurred_at": latest[-1].occurred_at,
                "column_changed_at": changed_at, "delta_ms": _millis(latest[-1].occurred_at) - _millis(changed_at),
                "labels_agree": latest[-1].to_label_index == json.loads(status_value).get("index"),
            })
    findings.append({
        "code": "TIMESTAMP_CROSS_CHECK", "field": "occurred_at", "blocking": False,
        "detail": "Latest converted log timestamp per item vs the status column changed_at returned by the items API.",
        "items": cross_checks,
    })
    findings.append({
        "code": "COLUMN_TYPE_ALIAS", "field": "status_column_id", "blocking": False,
        "detail": "Activity logs report the status column type as 'color'; the columns API reports 'status'.",
        "log_column_types": sorted({change.column_type for change in changes}), "columns_api_type": status_live["type"],
    })
    actor_counts = Counter(change.user_id for change in changes)
    editor_column = column_settings(users_columns, columns["editor"])
    editor_mapping = {str(entry["monday_person_id"]): entry for entry in config["editor_attribution"]["entries"]}
    editor_ids = {
        str(label_id)
        for item in items.get("items") or []
        for label_id in dropdown_ids(item, columns["editor"])
    }
    unresolved_editor_ids = sorted(editor_ids - set(editor_mapping), key=int)
    findings.append({
        "code": "ACTOR_IS_NOT_EDITOR", "field": "actor_resolution/actor_id", "blocking": bool(unresolved_editor_ids),
        "detail": ("Log user_id is audit metadata; the evaluated Editor is the Editor Name field. "
                   "Editor attribution uses the approved versioned label mapping and never infers identity from the actor."),
        "mapping_version": config["editor_attribution"]["mapping_version"],
        "authoritative_field": config["editor_attribution"]["authoritative_field"],
        "actor_user_ids": dict(actor_counts.most_common()),
        "editor_column": {"id": columns["editor"], "type": editor_column["type"]},
        "resolved_editor_label_ids": sorted(editor_ids - set(unresolved_editor_ids), key=int),
        "unresolved_editor_label_ids": unresolved_editor_ids,
    })
    video_type_items = {str(item["id"]): dropdown_ids(item, columns["video_type"]) for item in items.get("items") or []}
    video_mapping = {str(value) for value in config["video_type_cohorts"]["label_to_id"].values()}
    unresolved_video_ids = sorted({str(label_id) for ids in video_type_items.values() for label_id in ids} - video_mapping, key=int)
    findings.append({
        "code": "VIDEO_TYPE_MULTI_VALUE", "field": "video_type", "blocking": bool(unresolved_video_ids),
        "detail": "Video Type multi-select values use the approved exact normalized full-set cohort policy; no primary type is inferred.",
        "mapping_version": config["video_type_cohorts"]["mapping_version"],
        "policy": config["video_type_cohorts"]["multi_select_policy"],
        "items": {item_id: ids for item_id, ids in video_type_items.items() if len(ids) > 1},
        "single_value_items": sum(1 for ids in video_type_items.values() if len(ids) == 1),
        "unresolved_video_type_ids": unresolved_video_ids,
    })
    etas = []
    for item in items.get("items") or []:
        column = _column_value(item, columns["eta"])
        if column.get("value"):
            value = json.loads(column["value"])
            utc = datetime.fromisoformat(f"{value['date']}T{value.get('time') or '00:00:00'}+00:00")
            shown = datetime.strptime(column["text"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            etas.append({"item_id": str(item["id"]), "value_utc": utc.isoformat().replace("+00:00", "Z"), "text": column["text"],
                         "text_minus_value_hours": round((shown - utc.replace(second=0)).total_seconds() / 3600, 2)})
    findings.append({
        "code": "REQUESTED_ETA_TIMEZONE", "field": "requested_eta", "blocking": False,
        "detail": "Requested ETA value holds UTC date+time; text is rendered in the account timezone. Deadline logic must use value.",
        "items": etas,
    })
    if baseline_snapshot is not None:
        baseline_status = snapshot_column_settings(baseline_snapshot, columns["status"])
        baseline_editor = snapshot_column_settings(baseline_snapshot, columns["editor"])
        findings.append({
            "code": "LABEL_DRIFT_SINCE_BASELINE", "field": "status/editor labels", "blocking": False,
            "detail": "Live column settings compared with the immutable raw snapshot baseline.",
            "status_labels": _diff(_status_labels(baseline_status["settings"]), status_labels),
            "editor_labels": _diff(_dropdown_labels(baseline_editor["settings"]), _dropdown_labels(editor_column["settings"])),
            "editor_deactivated": {
                "baseline": sorted(baseline_editor["settings"].get("deactivated_labels", [])),
                "live": sorted(editor_column["settings"].get("deactivated_labels", [])),
            },
        })
    return {
        "report_version": DRIFT_VERSION,
        "contract": "contracts/normalized-status-event.schema.json",
        "contract_version": "1.0.0",
        "contract_change_required": any(finding["blocking"] for finding in findings),
        "findings": findings,
    }


def load_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data
