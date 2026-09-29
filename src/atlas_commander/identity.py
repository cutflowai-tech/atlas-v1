"""Canonical Editor identity resolution.

Contract 1.5 resolves a historical Editor only from the exact Monday
``(source_label_id, logged_name)`` tuple through an explicit, versioned mapping.
Earlier contracts keep their ID mapping plus label-name guard for reproducibility.
A current assignee is never treated as historical evidence. Anything that cannot
be resolved to exactly one canonical Editor is quarantined instead of being guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
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
EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE = "EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE"
INVALID_IDENTITY_VALUE = "invalid_identity_value"
UNRESOLVED_HISTORICAL_IDENTITY = "unresolved_historical_identity"

# Sources that describe the Editor at the time of the work. A current assignee
# snapshot is only acceptable when it is pinned to a source event.
HISTORICAL_SOURCES = frozenset({"editor_column_event"})
CURRENT_ASSIGNEE = "current_assignee"


class MappingError(ValueError):
    """The identity mapping itself is malformed and cannot be used."""


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MappingError(f"identity timestamp is invalid: {value!r}") from error
    if parsed.tzinfo is None:
        raise MappingError(f"identity timestamp must include an offset: {value!r}")
    return parsed


@dataclass(frozen=True)
class MappingEntry:
    monday_person_id: str
    editor_id: str
    display_name: str
    label_names: tuple[str, ...] = ()
    logged_name: str | None = None
    role: str | None = None
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    attestation_source: str | None = None
    decision_id: str | None = None


@dataclass(frozen=True)
class QuarantineReason:
    source_label_id: str
    logged_name: str
    code: str


@dataclass(frozen=True)
class IdentityMapping:
    mapping_version: str
    entries: tuple[MappingEntry, ...]
    strict_name_key: bool = False
    quarantine_reasons: tuple[QuarantineReason, ...] = ()

    @classmethod
    def from_dict(cls, data: Any) -> IdentityMapping:
        if not isinstance(data, dict):
            raise MappingError("mapping must be an object")
        version = data.get("mapping_version")
        if not isinstance(version, str) or not version:
            raise MappingError("mapping_version is required")
        raw_key = data.get("identity_key")
        strict_name_key = raw_key is not None
        if strict_name_key and raw_key != ["source_label_id", "logged_name"]:
            raise MappingError("identity_key must be ['source_label_id', 'logged_name']")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise MappingError("entries must be a list")
        entries = []
        for index, raw in enumerate(raw_entries):
            if not isinstance(raw, dict):
                raise MappingError(f"entry {index} must be an object")
            source_key = "source_label_id" if strict_name_key else "monday_person_id"
            display_key = "canonical_editor_name" if strict_name_key else "display_name"
            values = {}
            for key in (source_key, "editor_id", display_key):
                value = raw.get(key)
                if not isinstance(value, str) or not value:
                    raise MappingError(f"entry {index} missing {key}")
                values[key] = value
            logged_name = raw.get("logged_name") if strict_name_key else None
            if strict_name_key and (not isinstance(logged_name, str) or not logged_name):
                raise MappingError(f"entry {index} missing logged_name")
            names = [logged_name] if strict_name_key else raw.get("label_names", [])
            if not isinstance(names, list) or any(not isinstance(name, str) or not name for name in names):
                raise MappingError(f"entry {index} label_names must be a list of names")
            metadata = {}
            if strict_name_key:
                for key in ("role", "attestation_source", "decision_id"):
                    value = raw.get(key)
                    if not isinstance(value, str) or not value:
                        raise MappingError(f"entry {index} missing {key}")
                    metadata[key] = value
                if metadata["role"] != "editor":
                    raise MappingError(f"entry {index} role must be editor")
                for key in ("first_observed_at", "last_observed_at"):
                    if key not in raw or (raw[key] is not None and not isinstance(raw[key], str)):
                        raise MappingError(f"entry {index} {key} must be a timestamp or null")
                    metadata[key] = raw[key]
                    if isinstance(raw[key], str):
                        _timestamp(raw[key])
                if metadata["first_observed_at"] and metadata["last_observed_at"] and \
                        _timestamp(metadata["first_observed_at"]) > _timestamp(metadata["last_observed_at"]):
                    raise MappingError(f"entry {index} first_observed_at is after last_observed_at")
            entries.append(MappingEntry(values[source_key], values["editor_id"], values[display_key], tuple(names), logged_name,
                                        metadata.get("role"), metadata.get("first_observed_at"), metadata.get("last_observed_at"),
                                        metadata.get("attestation_source"), metadata.get("decision_id")))
        quarantine_reasons = []
        for index, raw in enumerate(data.get("quarantine_reasons", [])):
            if not isinstance(raw, dict):
                raise MappingError(f"quarantine reason {index} must be an object")
            reason_values = tuple(raw.get(key) for key in ("source_label_id", "logged_name", "code"))
            if any(not isinstance(value, str) or not value for value in reason_values):
                raise MappingError(f"quarantine reason {index} requires source_label_id, logged_name and code")
            source_label_id, logged_name_value, code = reason_values
            assert isinstance(source_label_id, str) and isinstance(logged_name_value, str) and isinstance(code, str)
            quarantine_reasons.append(QuarantineReason(source_label_id, logged_name_value, code))
        return cls(version, tuple(entries), strict_name_key, tuple(quarantine_reasons))

    @classmethod
    def load(cls, path: Path) -> IdentityMapping:
        return cls.from_dict(json.loads(path.read_text()))

    @classmethod
    def from_contract(cls, contract: Any) -> IdentityMapping:
        attribution = contract["editor_attribution"]
        return cls.from_dict({
            "mapping_version": attribution["mapping_version"],
            "entries": attribution["entries"],
            **({"identity_key": attribution["identity_key"]} if attribution.get("identity_key") else {}),
            "quarantine_reasons": attribution.get("quarantine_reasons", []),
        })

    def candidates(self, person_id: str, logged_name: str | None = None) -> tuple[MappingEntry, ...]:
        """Distinct records for a source label, optionally restricted to its exact logged name."""
        seen: dict[tuple[str, str, str | None], MappingEntry] = {}
        for entry in self.entries:
            if entry.monday_person_id == person_id and (not self.strict_name_key or logged_name is None or entry.logged_name == logged_name):
                seen.setdefault((entry.editor_id, entry.display_name, entry.logged_name), entry)
        return tuple(seen[key] for key in sorted(seen))

    def quarantine_code(self, source_label_id: str, logged_name: str) -> str | None:
        matches = [reason.code for reason in self.quarantine_reasons
                   if reason.source_label_id == source_label_id and reason.logged_name == logged_name]
        if len(set(matches)) > 1:
            raise MappingError(f"conflicting quarantine reasons for {(source_label_id, logged_name)!r}")
        return matches[0] if matches else None


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
    logged_names: tuple[str, ...] = field(default=())
    event_id: str | None = None
    observed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "reason": self.reason,
            "monday_board_id": self.monday_board_id,
            "monday_item_id": self.monday_item_id,
            "column_id": self.column_id,
            "person_ids": list(self.person_ids),
            "source_label_ids": list(self.person_ids),
            "mapping_version": self.mapping_version,
            "candidate_editor_ids": list(self.candidate_editor_ids),
            "logged_names": list(self.logged_names),
            "event_id": self.event_id,
            "observed_at": self.observed_at,
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


def _normalize_logged_names(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return ()
    names = []
    for value in values:
        if isinstance(value, str) and value and value not in names:
            names.append(value)
    return tuple(names)


def resolve_editor(observation: EditorObservation, mapping: IdentityMapping) -> Resolution:
    person_ids = _normalize_person_ids(observation.person_ids)
    logged_names = _normalize_logged_names(observation.label_names)

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
                logged_names=logged_names,
                event_id=observation.event_id,
                observed_at=observation.observed_at,
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
    if mapping.strict_name_key:
        if not logged_names:
            return reject(EDITOR_LABEL_NAME_UNVERIFIED, "observation carries no recorded logged name for the historical identity key")
        if len(logged_names) > 1:
            return reject(AMBIGUOUS_EDITOR, "Editor observation carries more than one logged name")
        special_code = mapping.quarantine_code(person_ids[0], logged_names[0])
        if special_code:
            return reject(special_code, f"identity tuple {(person_ids[0], logged_names[0])!r} is quarantined by {mapping.mapping_version}")
        candidates = mapping.candidates(person_ids[0], logged_names[0])
    else:
        candidates = mapping.candidates(person_ids[0])
    if not candidates:
        key = (person_ids[0], logged_names[0]) if mapping.strict_name_key and logged_names else person_ids[0]
        return reject(UNMAPPED_EDITOR, f"historical identity key {key!r} not present in mapping {mapping.mapping_version}")
    if len(candidates) > 1:
        return reject(
            AMBIGUOUS_EDITOR,
            "Monday person ID maps to more than one canonical record",
            tuple(sorted({entry.editor_id for entry in candidates})),
        )
    entry = candidates[0]
    if mapping.strict_name_key:
        try:
            observed = _timestamp(observation.observed_at)
        except MappingError:
            return reject(MISSING_EVIDENCE, "Editor observation timestamp is not a timezone-aware ISO timestamp", (entry.editor_id,))
        if entry.first_observed_at and observed < _timestamp(entry.first_observed_at):
            return reject(EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE, "identity observation predates the mapping's first observed bound",
                          (entry.editor_id,))
        if entry.last_observed_at and observed > _timestamp(entry.last_observed_at):
            return reject(EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE, "identity observation is after the mapping's last observed bound",
                          (entry.editor_id,))
    if entry.label_names and not mapping.strict_name_key:
        observed_names = logged_names
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
