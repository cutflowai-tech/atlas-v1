"""Deterministic role attribution for normalized status transitions (ATTR-001).

The role that performed a transition is decided only by the versioned transition
rule table. The Monday actor account, including the shared Waset Co account, is
kept as audit metadata and never decides the role or the evaluated Editor.
Transitions not listed in the table stay unresolved.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class TransitionRoleMapping:
    mapping_version: str
    exact: Mapping[tuple[str, str], str]
    into: Mapping[str, str]
    shared_account_ids: frozenset[str]

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> TransitionRoleMapping:
        section = contract["transition_roles"]
        version = section.get("mapping_version")
        if not isinstance(version, str) or not version:
            raise ValueError("transition role mapping requires mapping_version")
        exact: dict[tuple[str, str], str] = {}
        into: dict[str, str] = {}
        for rule in section.get("rules") or []:
            source, target, role = rule.get("from"), rule.get("to"), rule.get("role")
            if not all(isinstance(value, str) and value for value in (source, target, role)):
                raise ValueError(f"malformed transition role rule: {rule!r}")
            table: dict[Any, str] = into if source == "*" else exact
            key: Any = target if source == "*" else (source, target)
            if key in table and table[key] != role:
                raise ValueError(f"conflicting transition role rules for {key!r}")
            table[key] = role
        return cls(version, exact, into, frozenset(str(value) for value in section.get("shared_account_ids") or []))

    def role(self, from_status: str | None, to_status: str) -> str:
        if from_status is not None and (from_status, to_status) in self.exact:
            return self.exact[(from_status, to_status)]
        return self.into.get(to_status, UNRESOLVED)


def attribute_transition(event: Mapping[str, Any], mapping: TransitionRoleMapping) -> dict[str, Any]:
    """Return the attribution record for one normalized status event."""
    from_status = event.get("raw_from_status")
    to_status = event["raw_to_status"]
    actor = event.get("actor_monday_id")
    return {
        "event_id": event["event_id"],
        "monday_board_id": event["monday_board_id"],
        "monday_item_id": event["monday_item_id"],
        "occurred_at": event["occurred_at"],
        "from_status": from_status,
        "to_status": to_status,
        "role": mapping.role(from_status, to_status),
        "actor_monday_id": actor,
        "actor_is_shared_account": actor in mapping.shared_account_ids if actor is not None else False,
        "mapping_version": mapping.mapping_version,
    }


def attribute_transitions(events: Iterable[Mapping[str, Any]], mapping: TransitionRoleMapping) -> list[dict[str, Any]]:
    return [attribute_transition(event, mapping) for event in events]
