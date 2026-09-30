"""Decisions (redesign T2.11, T2.14; `02-VERDICT-ENGINE-SPEC.md` §7): what the CEO should decide, as language-neutral records.

A decision's ID is stable across rebuilds of the same facts: a hash of its type and its subject (the Editors, projects or rule it is
about). Its priority is the position of its type in spec §7, so no number is chosen here. Within one priority, decisions keep the
order they were generated in (Weakest Editors: the lowest-ranked first).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from atlas_commander.verdict.config import VerdictConfig
from atlas_commander.verdict.inputs import EditorInputs, TeamInputs, msg
from atlas_commander.verdict.reasoning import SilentMeasurement, zero_activity
from atlas_commander.verdict.tiers import LOW_ACTIVITY as LOW_ACTIVITY_TIER
from atlas_commander.verdict.tiers import WEAKEST

# Spec §7, in priority order (the first is priority 1).
OVERDUE_OPEN_WORK, WEAKEST_EDITOR, SCHEDULING_RUNWAY, LOW_ACTIVITY, APPROVE_RULE = (
    "overdue_open_work", "weakest_editor", "scheduling_runway", "low_activity", "approve_rule")
TYPES = (OVERDUE_OPEN_WORK, WEAKEST_EDITOR, SCHEDULING_RUNWAY, LOW_ACTIVITY, APPROVE_RULE)
HORIZONS = {OVERDUE_OPEN_WORK: "today", WEAKEST_EDITOR: "this_week", SCHEDULING_RUNWAY: "this_week", LOW_ACTIVITY: "ask",
            APPROVE_RULE: "management"}
ID_HEX_DIGITS = 12   # the schema's decision ID pattern: dec- and 12 hex digits
INTELLIGENCE_CONFIDENCE = {"strong": "high", "moderate": "medium", "weak": "low"}   # Intelligence V2 levels in the verdict's words


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


def low_activity_decision(editors: Sequence[EditorInputs]) -> dict[str, Any] | None:
    """§7 row 4 with §6 row 6: one `ask` decision listing every Low-activity Editor. An Editor with no project this window and
    nothing in progress is asked "leave or assignment gap?"; the others are listed with what they did complete or hold."""
    if not editors:
        return None
    ordered_editors = sorted(editors, key=lambda e: (e.display_name, e.editor_id))
    idle = all(zero_activity(e) for e in ordered_editors)
    evidence = [msg("verdict.evidence.zero_activity", name=e.display_name, lifetime_completed=e.lifetime_completed) if zero_activity(e)
                else msg("verdict.evidence.low_activity", name=e.display_name, completed=e.completed, active=e.active, overdue=len(e.overdue))
                for e in ordered_editors]
    return decision(LOW_ACTIVITY, ",".join(sorted(e.editor_id for e in ordered_editors)),
                    msg("verdict.decision.zero_activity" if idle else "verdict.decision.low_activity", names=[e.display_name for e in ordered_editors]),
                    owner_editor_ids=[e.editor_id for e in ordered_editors], evidence=evidence)


def overdue_decision(editors: Sequence[EditorInputs]) -> dict[str, Any] | None:
    """§7 row 1: every open project past Requested ETA, in one decision for today, owned by the Editors holding them. Projects are
    listed most overdue first, and the Editors in the order of their first project."""
    projects = sorted(((e, o) for e in editors for o in e.overdue), key=lambda pair: (-(pair[1].hours_past_eta or 0), pair[1].project_id))
    if not projects:
        return None
    holders = list({e.editor_id: e for e, _ in projects}.values())   # first appearance order
    evidence = [msg("verdict.evidence.overdue_project", name=e.display_name, item_id=o.project_id, status=o.status,
                    **{k: v for k, v in (("hours_past_eta", o.hours_past_eta), ("video_type", o.video_type)) if v is not None})
                for e, o in projects]
    return decision(OVERDUE_OPEN_WORK, ",".join(sorted(o.project_id for _, o in projects)),
                    msg("verdict.decision.overdue_open_work", count=len(projects), names=[e.display_name for e in holders]),
                    owner_editor_ids=[e.editor_id for e in holders], evidence=evidence, target="overdue")


def weakest_decisions(verdicts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """§7 row 2: a plan this week for each Weakest Editor, with the Editors manager; the lowest-ranked first. The evidence is the
    verdict's own reasons, and the decision is as confident as the verdict."""
    weakest = sorted((v for v in verdicts if v["tier"] == WEAKEST), key=lambda v: (-(v["rank"] or 0), v["editor_id"]))
    return [decision(WEAKEST_EDITOR, v["editor_id"], msg("verdict.decision.weakest_editor", name=v["display_name"]),
                     owner_editor_ids=[v["editor_id"]], owner_role="editors_manager", confidence=v["confidence"], evidence=v["reasons"],
                     target=f"editor:{v['editor_id']}")
            for v in weakest]


def scheduling_decision(team: TeamInputs, config: VerdictConfig) -> dict[str, Any] | None:
    """§7 row 3: the scheduling owner reviews runway when at least ``decisions.scheduling_runway_share`` of late projects started
    with short runway (Intelligence V2 split); as confident as that finding."""
    split = team.runway
    if not split or split.get("share_of_late_with_short_runway") is None or split["share_of_late_with_short_runway"] < config["decisions.scheduling_runway_share"]:
        return None
    digits = int(config["precision.pct_digits"])
    finding = team.findings.get(team.runway_finding_id or "") or {}
    level = INTELLIGENCE_CONFIDENCE.get(((finding.get("confidence") or {}).get("level")) or "", "medium")
    evidence = [msg("verdict.evidence.short_runway_split", short_runway_late_pct=round(split["short_runway_late_rate"] * 100, digits),
                    short_runway=split["short_runway"], adequate_runway_late_pct=round(split["adequate_runway_late_rate"] * 100, digits),
                    adequate_runway=split["adequate_runway"], short_runway_late=split["short_runway_late"], late=split["late"])]
    return decision(SCHEDULING_RUNWAY, "team", msg("verdict.decision.scheduling_runway",
                                                   short_share_pct=round(split["share_of_late_with_short_runway"] * 100, digits)),
                    owner_role="scheduling_owner", confidence=level, evidence=evidence,
                    target=f"finding:{team.runway_finding_id}" if team.runway_finding_id else None)


def generate(editors: Sequence[EditorInputs], verdicts: Sequence[Mapping[str, Any]], team: TeamInputs, silent: Sequence[SilentMeasurement],
             config: VerdictConfig) -> list[dict[str, Any]]:
    """Every decision of spec §7 for this snapshot, in priority order."""
    tiers = {v["editor_id"]: v["tier"] for v in verdicts}
    candidates = [overdue_decision(editors), *weakest_decisions(verdicts), scheduling_decision(team, config),
                  low_activity_decision([e for e in editors if tiers[e.editor_id] == LOW_ACTIVITY_TIER]), *silent_measurement_decisions(silent)]
    return ordered([d for d in candidates if d is not None])


def ordered(decisions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Priority first; within a priority the generation order is kept (it is deterministic), so every rebuild orders the same."""
    return sorted(decisions, key=lambda d: d["priority"])
