"""Decisions (redesign T2.11, T2.14; `02-VERDICT-ENGINE-SPEC.md` §7): what the CEO should decide, as language-neutral records.

A decision's ID is stable across rebuilds of the same facts: a hash of its type and its subject (the Editors or the rule it is
about). Its priority is the position of its type in spec §7, so no number is chosen here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from atlas_commander.verdict.inputs import EditorInputs, msg
from atlas_commander.verdict.reasoning import SilentMeasurement

# Spec §7, in priority order (the first is priority 1).
OVERDUE_OPEN_WORK, WEAKEST_EDITOR, SCHEDULING_RUNWAY, LOW_ACTIVITY, APPROVE_RULE = (
    "overdue_open_work", "weakest_editor", "scheduling_runway", "low_activity", "approve_rule")
TYPES = (OVERDUE_OPEN_WORK, WEAKEST_EDITOR, SCHEDULING_RUNWAY, LOW_ACTIVITY, APPROVE_RULE)
HORIZONS = {OVERDUE_OPEN_WORK: "today", WEAKEST_EDITOR: "this_week", SCHEDULING_RUNWAY: "this_week", LOW_ACTIVITY: "ask",
            APPROVE_RULE: "management"}
ID_HEX_DIGITS = 12   # the schema's decision ID pattern: dec- and 12 hex digits


def decision_id(decision_type: str, subject: str) -> str:
    return "dec-" + hashlib.sha256(f"{decision_type}:{subject}".encode()).hexdigest()[:ID_HEX_DIGITS]


def decision(decision_type: str, subject: str, title: dict[str, Any], *, owner_editor_ids: Sequence[str] = (), owner_role: str | None = None,
             confidence: str = "high", evidence: Sequence[dict[str, Any]] = (), target: str | None = None) -> dict[str, Any]:
    return {"id": decision_id(decision_type, subject), "type": decision_type, "horizon": HORIZONS[decision_type], "title": title,
            "owner_editor_ids": list(owner_editor_ids), "owner_role": owner_role, "confidence": confidence, "evidence": list(evidence),
            "priority": TYPES.index(decision_type) + 1, "target": target}


def silent_measurement_decisions(silent: Sequence[SilentMeasurement]) -> list[dict[str, Any]]:
    """§6 row 5 / §7 row 5: the CEO approves (or reviews) the rule of a dimension Atlas cannot see. The facts are certain."""
    out = []
    for s in silent:
        evidence = [msg("verdict.evidence." + cause, dimension=s.dimension, editors=s.measured_editors) for cause in s.causes]
        title = msg("verdict.decision.review_rule" if s.rule_approved else "verdict.decision.approve_rule", dimension=s.dimension)
        out.append(decision(APPROVE_RULE, s.dimension, title, owner_role="ceo", evidence=evidence, target=f"rule:{s.dimension}"))
    return out


def zero_activity_decision(editors: Sequence[EditorInputs]) -> dict[str, Any] | None:
    """§6 row 6: Editors with no project this window and nothing in progress. The question to ask them: leave or assignment gap?
    T2.14 widens this `ask` decision to every Low-activity Editor (§7 row 4)."""
    if not editors:
        return None
    ordered = sorted(editors, key=lambda e: e.editor_id)
    return decision(LOW_ACTIVITY, ",".join(e.editor_id for e in ordered),
                    msg("verdict.decision.zero_activity", names=[e.display_name for e in ordered]),
                    owner_editor_ids=[e.editor_id for e in ordered],
                    evidence=[msg("verdict.evidence.zero_activity", name=e.display_name, lifetime_completed=e.lifetime_completed) for e in ordered])


def ordered(decisions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Priority first, then ID, so the order is total and the same on every rebuild."""
    return sorted(decisions, key=lambda d: (d["priority"], d["id"]))
