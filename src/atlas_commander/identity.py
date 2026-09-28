"""Resolve observed Monday Editors through an explicitly selected mapping version.

Mappings are indexed as version -> Monday person ID -> candidate identity records.
Candidate lists preserve conflicts instead of silently overwriting duplicate keys.
The caller must extract observations from the Monday Editor column, not assignees.
Quarantine envelopes are internal results, not a new persisted contract.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EditorObservation:
    """Evidence for the Editor field at a particular Monday observation.

    Historical observations require the event that established that Editor value.
    A current snapshot cannot establish an Editor for an earlier work cycle.
    """

    monday_person_ids: tuple[str, ...]
    monday_board_id: str
    monday_item_id: str
    editor_column_id: str
    source_timestamp: str
    event_id: str | None = None
    context: str = "current"
    source: str = "monday"


IdentityMappings = Mapping[str, Mapping[str, Sequence[Mapping[str, str]]]]


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def resolve_editor(
    observation: EditorObservation,
    mappings: IdentityMappings,
    *,
    mapping_version: str,
    historical: bool = True,
) -> dict[str, Any]:
    """Return exactly one canonical identity or a quarantine exception, with evidence.

    No latest-version fallback, ID coercion, name matching, or assignee lookup is
    performed. ``historical=False`` explicitly opts into current snapshot use.
    Identical duplicate candidates are harmless; any differing candidates fail
    closed, including conflicting display labels within one mapping version.
    """
    evidence = asdict(observation)
    evidence["monday_person_ids"] = list(observation.monday_person_ids)
    evidence["mapping_version"] = mapping_version
    evidence["historical_requested"] = historical

    def quarantine(code: str) -> dict[str, Any]:
        return {"identity": None, "exception": {"code": code}, "evidence": evidence}

    if (
        observation.source != "monday"
        or observation.context not in ("current", "historical")
        or not all(_nonempty(value) for value in (
            observation.monday_board_id, observation.monday_item_id,
            observation.editor_column_id, observation.source_timestamp,
        ))
    ):
        return quarantine("INVALID_EDITOR_EVIDENCE")
    if (historical or observation.context == "historical") and (
        observation.context != "historical" or not _nonempty(observation.event_id)
    ):
        return quarantine("MISSING_HISTORICAL_EDITOR_EVIDENCE")

    person_ids = observation.monday_person_ids
    if not person_ids:
        return quarantine("MISSING_EDITOR")
    if not isinstance(person_ids, (tuple, list)) or not all(_nonempty(value) for value in person_ids):
        return quarantine("INVALID_EDITOR_ID")
    unique_person_ids = sorted(set(person_ids))
    if len(unique_person_ids) != 1:
        return quarantine("AMBIGUOUS_EDITOR")
    person_id = unique_person_ids[0]

    if not _nonempty(mapping_version) or mapping_version not in mappings:
        return quarantine("MISSING_MAPPING_VERSION")
    candidates = mappings[mapping_version].get(person_id, ())
    # Capture every candidate, including rejected records, for deterministic audit.
    if not isinstance(candidates, (tuple, list)) or not all(isinstance(row, Mapping) for row in candidates):
        return quarantine("INVALID_IDENTITY_MAPPING")
    rows = [dict(row) for row in candidates]
    evidence["mapping_candidates"] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
    if not rows:
        return quarantine("UNMAPPED_EDITOR")
    required = {"contract_version", "editor_id", "monday_person_id", "display_name", "mapping_version", "resolution"}
    for row in rows:
        if (
            set(row) != required
            or not all(_nonempty(value) for value in row.values())
            or row["contract_version"] != "1.0.0"
            or row["resolution"] != "canonical_monday_id"
            or row["monday_person_id"] != person_id
            or row["mapping_version"] != mapping_version
        ):
            return quarantine("INVALID_IDENTITY_MAPPING")
    if any(row != rows[0] for row in rows[1:]):
        return quarantine("AMBIGUOUS_EDITOR")
    return {"identity": dict(rows[0]), "exception": None, "evidence": evidence}
