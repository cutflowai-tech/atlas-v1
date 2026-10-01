"""Combination rules (redesign T2.8–T2.11, `02-VERDICT-ENGINE-SPEC.md` §6): connect findings instead of listing them.

Each rule reads the normalized inputs and returns what it concluded; the engine applies the effect (a reason, a tier limit, a
finding hidden from the overview, a decision candidate). No rule adds a new metric.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from atlas_commander.verdict.config import VerdictConfig
from atlas_commander.verdict.inputs import EditorInputs, OwnChange, TeamInputs, msg
from atlas_commander.verdict.tiers import WATCH, WEAKEST

RUNWAY_EXPLAINS, RUNWAY_NOT_EXPLAINING = "runway_explains", "runway_not_explaining"


@dataclass(frozen=True)
class RunwayResult:
    code: str
    reason: dict[str, Any]


def _pct(value: float, config: VerdictConfig) -> float:
    return round(value * 100, int(config["precision.pct_digits"]))


def runway(editor: EditorInputs, team: TeamInputs, config: VerdictConfig) -> RunwayResult | None:
    """Rows 1 and 2: does short runway (scheduling) explain this Editor's lateness?

    - Explains: the Editor's late rate is at or below the team's late rate for short-runway projects, and at least the team's share
      of the Editor's late projects started with short runway. Most of the lateness comes from scheduling.
    - Does not explain: the Editor's late rate is above the team's short-runway late rate, i.e. later than even the worst
      scheduling conditions produce across the team.
    None when the Editor has no late rate or Intelligence V2 published no runway split."""
    split = team.runway
    if editor.late_rate is None or not split:
        return None
    short_rate = split["short_runway_late_rate"]
    team_share = split["share_of_late_with_short_runway"]
    late, short = editor.runway_late, editor.runway_late_short
    share = short / late if late and short is not None else None
    params = {"late_pct": _pct(editor.late_rate, config), "short_runway_late_pct": _pct(short_rate, config)}
    if editor.late_rate > short_rate:
        return RunwayResult(RUNWAY_NOT_EXPLAINING, msg("verdict.reason.runway_not_explaining", **params))
    if share is not None and share >= team_share:
        return RunwayResult(RUNWAY_EXPLAINS, msg("verdict.reason.runway_explains", short_share_pct=_pct(share, config),
                                                 team_short_share_pct=_pct(team_share, config), late=late, short=short))
    return None


def limit_tier(tier: str, result: RunwayResult | None) -> str:
    """When scheduling explains the lateness the tier is not worse than Watch; "not explaining" allows Weakest."""
    if result is not None and result.code == RUNWAY_EXPLAINS and tier == WEAKEST:
        return WATCH
    return tier



MIRRORS_TEAM = "mirrors_team"


def mirrors_team(change: OwnChange, config: VerdictConfig) -> bool:
    """Row 3: the Editor's change against their own baseline is within the material difference (D53.6) of the other Editors'
    change over the same periods, so it is the team's change, not this Editor's."""
    if change.team_difference is None:
        return False
    gap = abs(change.difference - change.team_difference)
    limit = config["reasoning.material_rate_difference"] if change.measure == "late_rate" else config["reasoning.material_duration_pct"]
    return gap < limit


def mirrored_changes(editor: EditorInputs, config: VerdictConfig) -> list[OwnChange]:
    return [change for change in editor.changes if mirrors_team(change, config)]


def mirror_reason(changes: list[OwnChange], config: VerdictConfig) -> dict[str, Any] | None:
    """"Same as the whole team", stated with the largest mirrored change (neither credit nor blame)."""
    if not changes:
        return None
    change = max(changes, key=lambda c: c.sample)
    if change.measure == "late_rate":
        return msg("verdict.reason.mirrors_team_late_rate", before_pct=_pct(change.before or 0, config), now_pct=_pct(change.now or 0, config),
                   team_before_pct=_pct(change.team_before or 0, config), team_now_pct=_pct(change.team_now or 0, config))
    return msg("verdict.reason.mirrors_team_speed", change_pct=round(change.difference, int(config["precision.pct_digits"])),
               team_change_pct=round(change.team_difference or 0, int(config["precision.pct_digits"])))


DUPLICATE = "duplicate"


def _measure_key(finding: Mapping[str, Any]) -> tuple[str, str, str, str] | None:
    """(editor, finding type, measure, Video Type) for a single-Editor finding that names its measure; otherwise None."""
    if len(finding.get("affected_editors") or []) != 1:
        return None
    params = (finding.get("statements") or [{}])[0].get("params") or {}
    if not params.get("measure"):
        return None
    cohort = str(params.get("cohort_key") or params.get("cohort_label") or "")
    return finding["affected_editors"][0], finding["finding_type"], str(params["measure"]), cohort


def _overlap(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Whether two findings' windows overlap. A finding without a dated window covers the whole snapshot, so it overlaps."""
    wa, wb = a.get("time_window") or {}, b.get("time_window") or {}
    if not (wa.get("start_date") and wa.get("end_date_exclusive") and wb.get("start_date") and wb.get("end_date_exclusive")):
        return True
    return bool(wa["start_date"] < wb["end_date_exclusive"] and wb["start_date"] < wa["end_date_exclusive"])


def duplicates(findings: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Row 4: findings about the same Editor and the same measure over overlapping windows are one finding. The one with the
    larger sample is kept on the overview; the others stay under More details."""
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for finding in findings:
        key = _measure_key(finding)
        if key is not None:
            groups.setdefault(key, []).append(finding)
    out = []
    for (editor_id, _type, measure, _cohort), members in sorted(groups.items()):
        members = sorted(members, key=lambda f: (-f["sample_size"], f["finding_id"]))
        kept, rest = members[0], [f for f in members[1:] if _overlap(members[0], f)]
        if rest:
            out.append({"kept": kept["finding_id"], "hidden": [f["finding_id"] for f in rest], "editor_id": editor_id, "measure": measure})
    return out


QUALITY = "quality"
RULE_NOT_APPROVED, ZERO_FOR_EVERYONE = "rule_not_approved", "zero_for_everyone"


@dataclass(frozen=True)
class SilentMeasurement:
    """A dimension Atlas cannot see this window, and why (one or both causes)."""

    dimension: str
    causes: tuple[str, ...]
    measured_editors: int      # Editors with a value for the dimension's measure
    rule_approved: bool


def silent_measurement(editors: Sequence[EditorInputs]) -> list[SilentMeasurement]:
    """Row 5: a measure that reads 0% for every Editor with a value is "not measured", never "good"; so is a dimension whose rule is
    approved for nobody (spec §7, "a rule not approved that silences a dimension"). Quality is the only dimension with such a rule:
    Deadlines and Speed are approved (D52), Volume is a count. Its measure is the share of projects with a quality issue."""
    if not editors:
        return []
    measured = [e.quality_negative_rate for e in editors if e.quality_negative_rate is not None]
    approved = any(e.quality_approved for e in editors)
    causes = []
    if not approved:
        causes.append(RULE_NOT_APPROVED)
    if len(measured) > 1 and not any(measured):
        causes.append(ZERO_FOR_EVERYONE)
    return [SilentMeasurement(QUALITY, tuple(causes), len(measured), approved)] if causes else []


def not_measured(editors: Sequence[EditorInputs], silent: Sequence[SilentMeasurement]) -> list[EditorInputs]:
    """A silenced Quality measure is read as "not measured yet": no Quality state, no Quality weight in the score."""
    if not any(s.dimension == QUALITY for s in silent):
        return list(editors)
    return [replace(e, quality_approved=False, quality_state=None) for e in editors]


def zero_activity(editor: EditorInputs) -> bool:
    """Row 6: no completed project in the window and nothing in progress (Low activity by §3; the question is leave or assignment)."""
    return editor.completed == 0 and editor.active == 0
