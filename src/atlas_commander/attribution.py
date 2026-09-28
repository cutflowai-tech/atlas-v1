"""Deterministic transition attribution using explicitly curated Monday IDs.

The caller supplies the actor kind from Monday, never from a display name.
Shared accounts (including Waset Co) must be registered as shared in the
mapping. They cannot identify an Editor even if an editor_id is also supplied.
"""

from dataclasses import dataclass
from typing import Literal, TypedDict

ActorKind = Literal["person", "team"]


@dataclass(frozen=True)
class ActorMappingEntry:
    actor_kind: ActorKind
    monday_id: str
    editor_id: str | None = None
    shared: bool = False

    def __post_init__(self) -> None:
        if self.actor_kind not in ("person", "team"):
            raise ValueError("actor_kind must be person or team")
        if not isinstance(self.monday_id, str) or not self.monday_id.strip():
            raise ValueError("monday_id must be a nonempty canonical ID")
        if self.editor_id is not None and (not isinstance(self.editor_id, str) or not self.editor_id.strip()):
            raise ValueError("editor_id must be a nonempty ID or None")
        if not isinstance(self.shared, bool):
            raise TypeError("shared must be boolean")


@dataclass(frozen=True)
class ActorMapping:
    version: str
    entries: tuple[ActorMappingEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("an explicit mapping version is required")
        # Snapshot mutable input so subsequent caller edits cannot change results.
        object.__setattr__(self, "entries", tuple(self.entries))
        if any(not isinstance(entry, ActorMappingEntry) for entry in self.entries):
            raise ValueError("entries must contain ActorMappingEntry values")


class ActorResolution(TypedDict):
    actor_resolution: Literal["canonical_monday_id", "unresolved_waset_co"]
    actor_monday_id: str | None
    actor_id: str | None
    mapping_version: str | None


def resolve_transition_actor(
    actor_kind: ActorKind | None,
    actor_monday_id: str | None,
    mapping: ActorMapping | None = None,
) -> ActorResolution:
    """Return contract fields; preserve source ID exactly, without name fallback.

    Unknown kinds, absent mappings, absent IDs, shared accounts, unassigned
    entries and conflicting targets remain unresolved. Duplicate identical
    targets are harmless. Person/team namespaces never match one another.
    The frozen v1 contract uses unresolved_waset_co for every unresolved case.
    Invalid source ID types/empty strings raise rather than being coerced into
    potentially different canonical IDs or emitted in violation of the schema.
    """
    if actor_monday_id is not None and (not isinstance(actor_monday_id, str) or not actor_monday_id):
        raise ValueError("actor_monday_id must be a nonempty string or None")
    result: ActorResolution = {
        "actor_resolution": "unresolved_waset_co",
        "actor_monday_id": actor_monday_id,
        "actor_id": None,
        "mapping_version": mapping.version if mapping is not None else None,
    }
    if mapping is None or actor_kind not in ("person", "team") or actor_monday_id is None:
        return result
    matches = tuple(
        entry for entry in mapping.entries
        if entry.actor_kind == actor_kind and entry.monday_id == actor_monday_id
    )
    if not matches or any(entry.shared or entry.editor_id is None for entry in matches):
        return result
    targets = {entry.editor_id for entry in matches}
    if len(targets) == 1:
        result["actor_id"] = matches[0].editor_id
        result["actor_resolution"] = "canonical_monday_id"
    return result
