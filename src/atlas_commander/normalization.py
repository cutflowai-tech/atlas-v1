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


def _label_index(value: Any) -> int | None:
    if isinstance(value, dict) and isinstance(value.get("label"), dict):
        index = value["label"].get("index")
        return index if isinstance(index, int) and not isinstance(index, bool) else None
    return None


def _is_cleared(value: Any) -> bool:
    """A Monday status value with no label (``None`` excluded): an empty dict or blank text."""
    if isinstance(value, dict):
        if "label" not in value:
            return True
        label = value["label"]
        return isinstance(label, dict) and label.get("text") == ""
    return value == ""


def _canonical(text: Any, index: int | None, statuses: dict[str, str], aliases: dict[str, dict[str, Any]]) -> str | None:
    """Mapped label for a raw label text; aliases apply only when the Monday label index matches."""
    if not isinstance(text, str):
        return None
    if text in statuses:
        return text
    alias = aliases.get(text)
    if alias and index is not None and index == alias.get("label_index") and alias.get("canonical") in statuses:
        return str(alias["canonical"])
    return None


def _normalize(raw: dict[str, Any], statuses: dict[str, str], version: str, aliases: dict[str, dict[str, Any]] | None = None,
               accept_unresolved_previous: bool = False) -> dict[str, Any]:
    aliases = aliases or {}
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
    raw_before = raw.get("from_status", data.get("previous_value"))
    raw_after = raw.get("to_status", data.get("value"))
    if accept_unresolved_previous and _is_cleared(raw_after):
        raise ValueError("STATUS_CLEARED")
    after = _label(raw_after)
    after_label = _canonical(after, _label_index(raw_after), statuses, aliases)
    if after_label is None:
        raise ValueError("UNKNOWN_STATUS")
    before_label: str | None = None
    if accept_unresolved_previous and _is_cleared(raw_before):
        before = ""
    else:
        try:
            before = _label(raw_before)
        except ValueError:
            if not accept_unresolved_previous:
                raise
            before = json.dumps(raw_before, sort_keys=True)
        before_label = _canonical(before, _label_index(raw_before), statuses, aliases) if before is not None else None
        if before is not None and before_label is None and not accept_unresolved_previous:
            raise ValueError("UNKNOWN_STATUS")
    event = {
        "contract_version": "1.0.0",
        "event_id": _id(raw.get("event_id", raw.get("id"))),
        "monday_board_id": _id(raw.get("monday_board_id", raw.get("board_id"))),
        "monday_item_id": _id(raw.get("monday_item_id", data.get("pulse_id"))),
        "status_column_id": _id(raw.get("status_column_id", data.get("column_id"))),
        "occurred_at": timestamp,
        # An unmapped or cleared previous label is kept verbatim in raw_from_status and left unresolved.
        "from_status": (statuses[before_label] if statuses[before_label] in STATUSES else before_label) if before_label is not None else None,
        "to_status": statuses[after_label] if statuses[after_label] in STATUSES else after_label,
        "raw_from_status": before,
        "raw_to_status": after,
        "status_phase_from": statuses[before_label] if before_label is not None else None,
        "status_phase_to": statuses[after_label],
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

    Optional mapping keys (versioned in the executable contract):
    ``aliases`` maps a historical label text to ``{"canonical", "label_index"}``; it applies
    only when the Monday label index matches, i.e. the same Monday label was renamed.
    ``unmapped_previous_status = "accept-with-unresolved-previous"`` keeps an entry into a
    mapped status whose previous label is unmapped or cleared: the raw previous text is
    retained and ``from_status``/``status_phase_from`` stay null. Without it (the v1.0
    behavior), such events are quarantined. A transition into a cleared (label-less) status
    is quarantined as ``STATUS_CLEARED`` under that policy; unmapped next labels are always
    quarantined as ``UNKNOWN_STATUS``.
    """
    if not isinstance(status_mapping, dict):
        raise TypeError("INVALID_STATUS_MAPPING")
    version = status_mapping.get("version") or status_mapping.get("status_mapping_version")
    statuses = status_mapping.get("statuses") or status_mapping.get("status_mapping")
    aliases = status_mapping.get("aliases") or {}
    accept_unresolved_previous = status_mapping.get("unmapped_previous_status") == "accept-with-unresolved-previous"
    if not isinstance(aliases, dict) or any(not isinstance(value, dict) or not isinstance(value.get("label_index"), int) for value in aliases.values()):
        raise ValueError("INVALID_STATUS_MAPPING")
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
            result.accepted.append(_normalize(raw, statuses, version, aliases, accept_unresolved_previous))
        except (ValueError, TypeError) as exc:
            result.quarantined.append({"source_index": index, "reason": str(exc), "raw_source": deepcopy(raw)})
    return result


def status_mapping_config(contract: dict[str, Any] | Any) -> dict[str, Any]:
    """The normalize_events mapping argument for an executable Monday contract (any version)."""
    mapping: dict[str, Any] = {"version": contract["status_mapping_version"], "statuses": contract["status_mapping"]}
    if contract.get("status_label_aliases"):
        mapping["aliases"] = contract["status_label_aliases"]
    if contract.get("unmapped_previous_status"):
        mapping["unmapped_previous_status"] = contract["unmapped_previous_status"]
    return mapping
