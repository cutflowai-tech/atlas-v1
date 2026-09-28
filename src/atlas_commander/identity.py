"""Canonical Editor identity resolution (ID-001).

Editors are resolved only by exact Monday person ID through an explicit,
versioned mapping. Display names are never used to resolve identity, and a
current assignee is never treated as the historical editor unless the
observation carries Monday event evidence. Anything that cannot be resolved
deterministically is quarantined as an exception record instead of guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeGuard

from atlas_commander.contracts import schema_errors

CONTRACT_VERSION = "1.0.0"
IDENTITY_SCHEMA = "editor-identity.schema.json"
RESOLUTION = "canonical_monday_id"

MISSING_EDITOR = "MISSING_EDITOR"
AMBIGUOUS_EDITOR = "AMBIGUOUS_EDITOR"
UNMAPPED_EDITOR = "UNMAPPED_EDITOR"
AMBIGUOUS_MAPPING = "AMBIGUOUS_MAPPING"
UNEVIDENCED_EDITOR = "UNEVIDENCED_EDITOR"
INVALID_OBSERVATION = "INVALID_OBSERVATION"

HISTORICAL_SOURCES = frozenset({"historical_column_value", "activity_log"})
CURRENT_ASSIGNEE_SOURCE = "current_assignee"
KNOWN_SOURCES = HISTORICAL_SOURCES | {CURRENT_ASSIGNEE_SOURCE}


def _canonical_person_id(value: Any) -> str | None:
    """Monday person IDs arrive as ints (API) or strings (exports); nothing else is an ID."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip() and value == value.strip():
        return value
    return None


def _non_empty_str(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class MappingEntry:
    monday_person_id: str
    editor_id: str
    display_name: str


@dataclass(frozen=True)
class IdentityMapping:
    """A versioned Monday person ID -> canonical Editor mapping.

    A person ID listed with two different canonical editors is recorded as
    conflicting; resolving it yields ``AMBIGUOUS_MAPPING`` rather than a pick.
    """

    mapping_version: str
    entries: dict[str, MappingEntry]
    conflicts: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdentityMapping:
        version = data.get("mapping_version")
        if not _non_empty_str(version):
            raise ValueError("identity mapping requires a non-empty mapping_version")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise TypeError("identity mapping requires an entries list")
        candidates: dict[str, set[MappingEntry]] = {}
        for index, raw in enumerate(raw_entries):
            if not isinstance(raw, dict):
                raise TypeError(f"mapping entry {index} must be an object")
            person_id = _canonical_person_id(raw.get("monday_person_id"))
            editor_id = raw.get("editor_id")
            display_name = raw.get("display_name")
            if person_id is None or not _non_empty_str(editor_id) or not _non_empty_str(display_name):
                raise ValueError(f"mapping entry {index} requires monday_person_id, editor_id and display_name")
            candidates.setdefault(person_id, set()).add(MappingEntry(person_id, editor_id, display_name))
        entries: dict[str, MappingEntry] = {}
        conflicts: dict[str, tuple[str, ...]] = {}
        for person_id, found in candidates.items():
            editor_ids = sorted({entry.editor_id for entry in found})
            if len(editor_ids) > 1:
                conflicts[person_id] = tuple(editor_ids)
            elif len(found) > 1:
                # Same editor with differing display names is still ambiguous as to canonical record.
                conflicts[person_id] = tuple(sorted(f"{entry.editor_id}:{entry.display_name}" for entry in found))
            else:
                entries[person_id] = next(iter(found))
        return cls(mapping_version=version, entries=entries, conflicts=conflicts)


@dataclass(frozen=True)
class IdentityResolution:
    identity: dict[str, Any] | None
    exception: dict[str, Any] | None

    @property
    def resolved(self) -> bool:
        return self.identity is not None


def _exception(observation: dict[str, Any], mapping: IdentityMapping, code: str, reason: str, person_ids: list[str]) -> IdentityResolution:
    return IdentityResolution(
        identity=None,
        exception={
            "code": code,
            "reason": reason,
            "monday_board_id": observation.get("monday_board_id"),
            "monday_item_id": observation.get("monday_item_id"),
            "column_id": observation.get("column_id"),
            "event_ids": sorted(observation.get("event_ids") or []) if isinstance(observation.get("event_ids"), list) else [],
            "source": observation.get("source"),
            "monday_person_ids": person_ids,
            "mapping_version": mapping.mapping_version,
        },
    )


def resolve_editor(observation: dict[str, Any], mapping: IdentityMapping) -> IdentityResolution:
    """Resolve the Editor for one Monday work item observation.

    ``observation`` fields:
      monday_board_id, monday_item_id, column_id: Monday identifiers.
      editor_person_ids: Monday person IDs in the Editor column for the work interval.
      source: ``historical_column_value`` | ``activity_log`` | ``current_assignee``.
      event_ids: Monday event IDs evidencing the value (required for every source).
    Any ``display_name`` on the observation is ignored for resolution.
    """
    if not isinstance(observation, dict):
        raise TypeError("observation must be a dict")
    for key in ("monday_board_id", "monday_item_id", "column_id"):
        if not _non_empty_str(observation.get(key)):
            return _exception(observation, mapping, INVALID_OBSERVATION, f"missing {key}", [])
    source = observation.get("source")
    if source not in KNOWN_SOURCES:
        return _exception(observation, mapping, INVALID_OBSERVATION, f"unknown source {source!r}", [])

    raw_ids = observation.get("editor_person_ids")
    if raw_ids is None:
        raw_ids = []
    if not isinstance(raw_ids, list):
        return _exception(observation, mapping, INVALID_OBSERVATION, "editor_person_ids must be a list", [])
    person_ids: list[str] = []
    for raw in raw_ids:
        person_id = _canonical_person_id(raw)
        if person_id is None:
            return _exception(observation, mapping, INVALID_OBSERVATION, f"non-canonical Monday person ID {raw!r}", [])
        person_ids.append(person_id)
    person_ids = sorted(set(person_ids))

    event_ids = observation.get("event_ids")
    has_evidence = isinstance(event_ids, list) and bool(event_ids) and all(_non_empty_str(item) for item in event_ids)
    if not has_evidence:
        reason = "current assignee is not evidence of the historical editor" if source == CURRENT_ASSIGNEE_SOURCE else "no Monday event evidence"
        return _exception(observation, mapping, UNEVIDENCED_EDITOR, reason, person_ids)

    if not person_ids:
        return _exception(observation, mapping, MISSING_EDITOR, "no Monday person ID for the Editor", person_ids)
    if len(person_ids) > 1:
        return _exception(observation, mapping, AMBIGUOUS_EDITOR, "multiple Monday person IDs for the Editor", person_ids)

    person_id = person_ids[0]
    if person_id in mapping.conflicts:
        return _exception(observation, mapping, AMBIGUOUS_MAPPING, "mapping lists conflicting canonical editors", person_ids)
    entry = mapping.entries.get(person_id)
    if entry is None:
        return _exception(observation, mapping, UNMAPPED_EDITOR, "Monday person ID not in identity mapping", person_ids)

    identity = {
        "contract_version": CONTRACT_VERSION,
        "editor_id": entry.editor_id,
        "monday_person_id": entry.monday_person_id,
        "display_name": entry.display_name,
        "mapping_version": mapping.mapping_version,
        "resolution": RESOLUTION,
    }
    errors = schema_errors(identity, IDENTITY_SCHEMA)
    if errors:
        raise ValueError(f"resolved identity violates {IDENTITY_SCHEMA}: {errors}")
    return IdentityResolution(identity=identity, exception=None)


def resolve_editors(observations: list[dict[str, Any]], mapping: IdentityMapping) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve many observations; returns (resolved, exceptions) in deterministic Monday ID order.

    Resolved records pair the observation's board/item/evidence with the contract-valid identity.
    """
    resolved: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    for observation in observations:
        result = resolve_editor(observation, mapping)
        if result.identity is not None:
            resolved.append(
                {
                    "monday_board_id": observation["monday_board_id"],
                    "monday_item_id": observation["monday_item_id"],
                    "column_id": observation["column_id"],
                    "event_ids": sorted(observation["event_ids"]),
                    "identity": result.identity,
                }
            )
        elif result.exception is not None:
            exceptions.append(result.exception)

    def order(record: dict[str, Any]) -> tuple[str, str]:
        return (str(record.get("monday_board_id") or ""), str(record.get("monday_item_id") or ""))

    return sorted(resolved, key=order), sorted(exceptions, key=lambda record: (*order(record), record["code"]))
