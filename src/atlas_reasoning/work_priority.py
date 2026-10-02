"""Deterministic reasoning-work priority (``REV/18`` #2). Python decides; the LLM never does.

Importance comes only from canonical data the work item already carries: its ``ReasoningCase`` document (the gate's copy for the run
that created the item), whose supporting findings hold Intelligence V2's own classification — ``category`` and ``direction`` — and
V2's deterministic importance ``rank`` (``atlas_commander.investigation.prioritization``: a lexicographic order, 1 = most important).

- **High importance**: the case's orientation is adverse and at least one supporting finding is an adverse ``needs_attention`` or
  ``emerging_risk`` finding (V2's time-sensitive tier).
- **Tiers**: 1 = updated high-importance cases (``gate_action = updated``: an active card whose evidence changed); 2 = new
  high-importance cases; 3 = all other work.
- **Within a tier** (tie-breaks, in order): best V2 rank of the case's supporting findings (lower first; a case without a rank last),
  ``updated`` before ``new``, ``case_id``, ``created_at``, ``work_item_id``. The order is total, so equal input always gives the same
  order whatever order the database returned the items in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from atlas_reasoning.enums import GateAction
from atlas_reasoning.store.repository import WorkItemRow

PRIORITY_VERSION = "work-priority-v1"
HIGH_IMPORTANCE_CATEGORIES = frozenset({"needs_attention", "emerging_risk"})
_NO_RANK = 10**9


@dataclass(frozen=True)
class Priority:
    tier: int
    best_rank: int
    high_importance: bool

    def to_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "best_rank": None if self.best_rank == _NO_RANK else self.best_rank, "high_importance": self.high_importance}


def high_importance(case_document: Mapping[str, Any] | None) -> bool:
    if not case_document or case_document.get("orientation") != "adverse":
        return False
    return any(finding.get("category") in HIGH_IMPORTANCE_CATEGORIES and finding.get("direction") == "adverse"
               for finding in case_document.get("supporting_findings") or ())


def best_rank(case_document: Mapping[str, Any] | None) -> int:
    ranks = [finding.get("rank") for finding in (case_document or {}).get("supporting_findings") or ()]
    valid = [rank for rank in ranks if isinstance(rank, int) and not isinstance(rank, bool) and rank >= 1]
    return min(valid) if valid else _NO_RANK


def priority(item: WorkItemRow) -> Priority:
    important = high_importance(item.case_document)
    if important and item.gate_action == GateAction.UPDATED:
        tier = 1
    elif important and item.gate_action == GateAction.NEW:
        tier = 2
    else:
        tier = 3
    return Priority(tier, best_rank(item.case_document), important)


def sort_key(item: WorkItemRow, created_at: Mapping[str, Any] | None = None) -> tuple[Any, ...]:
    p = priority(item)
    created = str((created_at or {}).get(item.work_item_id, ""))
    return (p.tier, p.best_rank, 0 if item.gate_action == GateAction.UPDATED else 1, item.case_id, created, item.work_item_id)


def prioritize(items: Iterable[WorkItemRow], created_at: Mapping[str, Any] | None = None) -> list[WorkItemRow]:
    """``items`` in deterministic priority order."""
    return sorted(items, key=lambda item: sort_key(item, created_at))
