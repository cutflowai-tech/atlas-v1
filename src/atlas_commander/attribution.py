"""Deterministic transition actor attribution.

A Monday status transition actor is resolved to an Atlas actor only through its
canonical Monday person/team ID and an explicit, versioned mapping. Display
names are preserved for evidence but never consulted. Shared Waset Co actors,
unknown IDs, missing actors and ambiguous mappings stay unresolved.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

ActorKind = Literal["person", "team"]
ACTOR_KINDS: frozenset[str] = frozenset({"person", "team"})

RESOLVED = "resolved"
UNRESOLVED = "unresolved"

REASON_MISSING_ACTOR = "missing_actor"
REASON_UNKNOWN_ACTOR = "unknown_actor"
REASON_AMBIGUOUS_MAPPING = "ambiguous_mapping"
REASON_WASET_CO_SHARED_ACTOR = "waset_co_shared_actor"

# Values of NormalizedStatusEvent.actor_resolution (contracts/normalized-status-event.schema.json).
CONTRACT_RESOLVED = "canonical_monday_id"
CONTRACT_UNRESOLVED = "unresolved_waset_co"


def _require_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _require_kind(value: Any, field: str) -> ActorKind:
    if value not in ACTOR_KINDS:
        raise ValueError(f"{field} must be one of {sorted(ACTOR_KINDS)}")
    return cast(ActorKind, value)


def _require_objects(value: Any, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{field} must be a list of objects")
    return value


@dataclass(frozen=True)
class TransitionActor:
    """The actor Monday recorded on a status transition, as received."""

    monday_id: str | None
    kind: ActorKind | None
    display_name: str | None = None

    @classmethod
    def from_source(cls, source: Mapping[str, Any] | None) -> TransitionActor:
        if not source:
            return cls(monday_id=None, kind=None)
        monday_id = source.get("monday_id")
        kind = source.get("kind")
        display_name = source.get("display_name")
        return cls(
            monday_id=monday_id if isinstance(monday_id, str) and monday_id else None,
            kind=cast(ActorKind, kind) if kind in ACTOR_KINDS else None,
            display_name=display_name if isinstance(display_name, str) else None,
        )


@dataclass(frozen=True)
class ActorMapping:
    """Explicit versioned mapping from canonical Monday IDs to Atlas actor IDs."""

    mapping_version: str
    entries: tuple[tuple[ActorKind, str, str], ...]
    shared_actors: frozenset[tuple[ActorKind, str]]

    def __post_init__(self) -> None:
        _require_id(self.mapping_version, "mapping_version")

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> ActorMapping:
        version = _require_id(config.get("mapping_version"), "mapping_version")
        entries = []
        for index, entry in enumerate(_require_objects(config.get("entries", []), "entries")):
            entries.append(
                (
                    _require_kind(entry.get("monday_kind"), f"entries[{index}].monday_kind"),
                    _require_id(entry.get("monday_id"), f"entries[{index}].monday_id"),
                    _require_id(entry.get("actor_id"), f"entries[{index}].actor_id"),
                )
            )
        shared = set()
        for index, entry in enumerate(_require_objects(config.get("waset_co_shared_actors", []), "waset_co_shared_actors")):
            shared.add(
                (
                    _require_kind(entry.get("monday_kind"), f"waset_co_shared_actors[{index}].monday_kind"),
                    _require_id(entry.get("monday_id"), f"waset_co_shared_actors[{index}].monday_id"),
                )
            )
        return cls(mapping_version=version, entries=tuple(sorted(set(entries))), shared_actors=frozenset(shared))

    def candidates(self, kind: ActorKind, monday_id: str) -> tuple[str, ...]:
        return tuple(sorted({actor_id for entry_kind, entry_id, actor_id in self.entries if entry_kind == kind and entry_id == monday_id}))


@dataclass(frozen=True)
class ActorResolution:
    """Outcome of resolving one transition actor, with preserved source evidence."""

    status: str
    reason: str | None
    source_monday_id: str | None
    source_kind: ActorKind | None
    source_display_name: str | None
    actor_id: str | None
    mapping_version: str
    candidate_actor_ids: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status == RESOLVED

    def event_fields(self) -> dict[str, str | None]:
        """Actor fields for a NormalizedStatusEvent (contract 1.0.0)."""
        if self.resolved:
            return {
                "actor_resolution": CONTRACT_RESOLVED,
                "actor_monday_id": self.source_monday_id,
                "actor_id": self.actor_id,
                "mapping_version": self.mapping_version,
            }
        return {
            "actor_resolution": CONTRACT_UNRESOLVED,
            "actor_monday_id": self.source_monday_id,
            "actor_id": None,
            "mapping_version": self.mapping_version,
        }

    def evidence(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "source_monday_id": self.source_monday_id,
            "source_kind": self.source_kind,
            "source_display_name": self.source_display_name,
            "actor_id": self.actor_id,
            "mapping_version": self.mapping_version,
            "candidate_actor_ids": list(self.candidate_actor_ids),
        }


def resolve_actor(actor: TransitionActor, mapping: ActorMapping) -> ActorResolution:
    """Resolve a transition actor by canonical Monday ID only; never by name."""

    def unresolved(reason: str, candidates: tuple[str, ...] = ()) -> ActorResolution:
        return ActorResolution(
            status=UNRESOLVED,
            reason=reason,
            source_monday_id=actor.monday_id,
            source_kind=actor.kind,
            source_display_name=actor.display_name,
            actor_id=None,
            mapping_version=mapping.mapping_version,
            candidate_actor_ids=candidates,
        )

    if actor.monday_id is None or actor.kind is None:
        return unresolved(REASON_MISSING_ACTOR)
    candidates = mapping.candidates(actor.kind, actor.monday_id)
    if (actor.kind, actor.monday_id) in mapping.shared_actors:
        return unresolved(REASON_WASET_CO_SHARED_ACTOR, candidates)
    if not candidates:
        return unresolved(REASON_UNKNOWN_ACTOR)
    if len(candidates) > 1:
        return unresolved(REASON_AMBIGUOUS_MAPPING, candidates)
    return ActorResolution(
        status=RESOLVED,
        reason=None,
        source_monday_id=actor.monday_id,
        source_kind=actor.kind,
        source_display_name=actor.display_name,
        actor_id=candidates[0],
        mapping_version=mapping.mapping_version,
        candidate_actor_ids=candidates,
    )
