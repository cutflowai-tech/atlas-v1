"""Resolve Monday transition actors using an explicit, versioned ID mapping.

Person and team IDs occupy separate namespaces. A shared account or team does
not identify an Editor by itself: only a unique configured rule can do so.
Callers must obtain IDs and actor kinds from Monday, never from display names.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

ActorKind = Literal["person", "team"]


def _require_id(value: str, field: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a nonempty, unmodified ID string")


@dataclass(frozen=True)
class ActorMappingRule:
    """An explicit canonical Monday person/team ID to Editor ID assignment."""

    actor_kind: ActorKind
    actor_monday_id: str
    actor_id: str

    def __post_init__(self) -> None:
        if self.actor_kind not in ("person", "team"):
            raise ValueError("actor_kind must be person or team")
        _require_id(self.actor_monday_id, "actor_monday_id")
        _require_id(self.actor_id, "actor_id")


@dataclass(frozen=True)
class ActorMapping:
    """A mapping snapshot; versions must change when assignments change.

    Conflicting rules are retained so that their source actor stays unresolved.
    Repeated identical rules do not introduce ambiguity.
    """

    version: str
    rules: tuple[ActorMappingRule, ...]

    def __post_init__(self) -> None:
        _require_id(self.version, "version")
        rules = tuple(self.rules)
        if any(not isinstance(rule, ActorMappingRule) for rule in rules):
            raise ValueError("rules must contain ActorMappingRule values")
        object.__setattr__(self, "rules", rules)


def resolve_transition_actor(
    event: Mapping[str, Any],
    *,
    actor_kind: ActorKind | None = None,
    mapping: ActorMapping | None = None,
) -> dict[str, Any]:
    """Return an event copy with attribution recomputed, without guessing.

    Input is a normalized status event, with its original actor_monday_id.
    The kind is supplied separately because the frozen event contract has no
    actor-kind field. No rule crosses namespaces or uses team membership,
    display names, event ownership, prior attribution, or AI inference.

    All unresolved causes use the contract's existing unresolved_waset_co enum.
    The attempted mapping version is retained even when no unique match exists.
    Malformed source IDs are preserved rather than repaired; callers must still
    validate the normalized event against its schema.
    """
    resolved = dict(event)
    source_id = event.get("actor_monday_id")
    resolved.update(
        actor_monday_id=source_id,
        actor_id=None,
        actor_resolution="unresolved_waset_co",
        mapping_version=mapping.version if mapping is not None else None,
    )
    if mapping is None or actor_kind not in ("person", "team") or not isinstance(source_id, str) or not source_id:
        return resolved

    targets = {
        rule.actor_id
        for rule in mapping.rules
        if rule.actor_kind == actor_kind and rule.actor_monday_id == source_id
    }
    if len(targets) == 1:
        resolved.update(actor_id=next(iter(targets)), actor_resolution="canonical_monday_id")
    return resolved
