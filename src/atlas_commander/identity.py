"""Canonical Editor identity resolution.

Editors are resolved only from Monday person IDs through an explicit, versioned
mapping. Display names are never matched, and a current assignee is never
treated as the historical Editor unless the observation carries source evidence.
Anything that cannot be resolved to exactly one canonical Editor is quarantined
as an ``IdentityException`` instead of being guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas_commander.contracts import validate

CONTRACT_VERSION = "1.0.0"
SCHEMA = "editor-identity.schema.json"
RESOLUTION = "canonical_monday_id"

MISSING_EDITOR = "MISSING_EDITOR"
AMBIGUOUS_EDITOR = "AMBIGUOUS_EDITOR"
UNMAPPED_EDITOR = "UNMAPPED_EDITOR"
MISSING_EVIDENCE = "MISSING_EVIDENCE"
# Monday reuses Editor Name dropdown labels for different people over time (e.g. label 5 was
# "Ahmed", later "Anas"). A mapping entry that lists label_names only resolves observations
# whose recorded label name is one of them.
EDITOR_LABEL_NAME_MISMATCH = "EDITOR_LABEL_NAME_MISMATCH"
EDITOR_LABEL_NAME_UNVERIFIED = "EDITOR_LABEL_NAME_UNVERIFIED"

# Sources that describe the Editor at the time of the work. A current assignee
# snapshot is only acceptable when it is pinned to a source event.
HISTORICAL_SOURCES = frozenset({"editor_column_event"})
CURRENT_ASSIGNEE = "current_assignee"


class MappingError(ValueError):
    """The identity mapping itself is malformed and cannot be used."""


@dataclass(frozen=True)
class MappingEntry:
    monday_person_id: str
    editor_id: str
    display_name: str
    label_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentityMapping:
    mapping_version: str
    entries: tuple[MappingEntry, ...]

    @classmethod
    def from_dict(cls, data: Any) -> IdentityMapping:
        if not isinstance(data, dict):
            raise MappingError("mapping must be an object")
        version = data.get("mapping_version")
        if not isinstance(version, str) or not version:
            raise MappingError("mapping_version is required")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise MappingError("entries must be a list")
        entries = []
        for index, raw in enumerate(raw_entries):
            if not isinstance(raw, dict):
                raise MappingError(f"entry {index} must be an object")
            values = {}
            for key in ("monday_person_id", "editor_id", "display_name"):
                value = raw.get(key)
                if not isinstance(value, str) or not value:
                    raise MappingError(f"entry {index} missing {key}")
                values[key] = value
            names = raw.get("label_names", [])
            if not isinstance(names, list) or any(not isinstance(name, str) or not name for name in names):
                raise MappingError(f"entry {index} label_names must be a list of names")
            entries.append(MappingEntry(values["monday_person_id"], values["editor_id"], values["display_name"], tuple(names)))
        return cls(version, tuple(entries))

    @classmethod
    def load(cls, path: Path) -> IdentityMapping:
        return cls.from_dict(json.loads(path.read_text()))

    def candidates(self, person_id: str) -> tuple[MappingEntry, ...]:
        """Distinct canonical records for a person ID; more than one is ambiguous."""
        seen: dict[tuple[str, str], MappingEntry] = {}
        for entry in self.entries:
            if entry.monday_person_id == person_id:
                seen.setdefault((entry.editor_id, entry.display_name), entry)
        return tuple(seen[key] for key in sorted(seen))


@dataclass(frozen=True)
class EditorObservation:
    """The Editor people-column value for one Monday item, as observed."""

    monday_board_id: str
    monday_item_id: str
    column_id: str
    person_ids: tuple[str, ...]
    source: str
    event_id: str | None = None
    observed_at: str | None = None
    # Label names exactly as the source recorded them at observation time (activity-log chosenValues).
    label_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentityException:
    code: str
    reason: str
    monday_board_id: str
    monday_item_id: str
    column_id: str
    person_ids: tuple[str, ...]
    mapping_version: str
    candidate_editor_ids: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "reason": self.reason,
            "monday_board_id": self.monday_board_id,
            "monday_item_id": self.monday_item_id,
            "column_id": self.column_id,
            "person_ids": list(self.person_ids),
            "mapping_version": self.mapping_version,
            "candidate_editor_ids": list(self.candidate_editor_ids),
        }


@dataclass(frozen=True)
class Resolution:
    identity: dict[str, Any] | None
    exception: IdentityException | None

    @property
    def resolved(self) -> bool:
        return self.identity is not None


def _normalize_person_ids(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, int)) and not isinstance(values, bool):
        values = [values]
    ids = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        text = str(value)
        if text and text not in ids:
            ids.append(text)
    return tuple(ids)


def resolve_editor(observation: EditorObservation, mapping: IdentityMapping) -> Resolution:
    person_ids = _normalize_person_ids(observation.person_ids)

    def reject(code: str, reason: str, candidates: tuple[str, ...] = ()) -> Resolution:
        return Resolution(
            None,
            IdentityException(
                code=code,
                reason=reason,
                monday_board_id=observation.monday_board_id,
                monday_item_id=observation.monday_item_id,
                column_id=observation.column_id,
                person_ids=person_ids,
                mapping_version=mapping.mapping_version,
                candidate_editor_ids=candidates,
            ),
        )

    if observation.source not in HISTORICAL_SOURCES or not observation.event_id or not observation.observed_at:
        if observation.source == CURRENT_ASSIGNEE:
            return reject(MISSING_EVIDENCE, "current assignee is not evidence of the historical Editor")
        return reject(MISSING_EVIDENCE, "Editor observation requires a historical source event and timestamp")
    if not person_ids:
        return reject(MISSING_EDITOR, "Editor column has no Monday person ID")
    if len(person_ids) > 1:
        return reject(AMBIGUOUS_EDITOR, "Editor column holds more than one Monday person ID")
    candidates = mapping.candidates(person_ids[0])
    if not candidates:
        return reject(UNMAPPED_EDITOR, f"Monday person ID not present in mapping {mapping.mapping_version}")
    if len(candidates) > 1:
        return reject(
            AMBIGUOUS_EDITOR,
            "Monday person ID maps to more than one canonical record",
            tuple(sorted({entry.editor_id for entry in candidates})),
        )
    entry = candidates[0]
    if entry.label_names:
        observed_names = tuple(name for name in observation.label_names if name)
        if not observed_names:
            return reject(EDITOR_LABEL_NAME_UNVERIFIED, "observation carries no recorded label name to verify against the mapping")
        if any(name not in entry.label_names for name in observed_names):
            return reject(EDITOR_LABEL_NAME_MISMATCH, f"label recorded as {list(observed_names)}, mapping {mapping.mapping_version} expects {list(entry.label_names)}",
                          (entry.editor_id,))
    identity = {
        "contract_version": CONTRACT_VERSION,
        "editor_id": entry.editor_id,
        "monday_person_id": entry.monday_person_id,
        "display_name": entry.display_name,
        "mapping_version": mapping.mapping_version,
        "resolution": RESOLUTION,
    }
    errors = validate(identity, SCHEMA)
    if errors:
        raise MappingError(f"resolved identity violates {SCHEMA}: {errors}")
    return Resolution(identity, None)


def resolve_all(observations: list[EditorObservation], mapping: IdentityMapping) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split observations into contract-valid identities and quarantined exceptions."""
    identities: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    for observation in observations:
        result = resolve_editor(observation, mapping)
        if result.identity is not None:
            identities.append(result.identity)
        elif result.exception is not None:
            exceptions.append(result.exception.to_dict())
    return identities, exceptions
