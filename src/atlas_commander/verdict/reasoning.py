"""Combination rules (redesign T2.8–T2.11, `02-VERDICT-ENGINE-SPEC.md` §6): connect findings instead of listing them.

Each rule reads the normalized inputs and returns what it concluded; the engine applies the effect (a reason, a tier limit, a
finding hidden from the overview, a decision candidate). No rule adds a new metric.
"""

from __future__ import annotations

from dataclasses import dataclass
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
