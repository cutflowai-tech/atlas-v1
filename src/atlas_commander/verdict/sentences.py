"""Headlines and reasons (redesign T2.12, `02-VERDICT-ENGINE-SPEC.md` §6): the one-line verdict and the 2–4 "why this verdict"
bullets, as message keys with parameters. No language here: the pages own the English and Arabic templates.

The headline is chosen by the tier and the strongest fact behind it (the rule of §3 that placed the Editor, or the §6 combination
that qualifies it). The reasons are that tier's facts in order of strength, capped by the schema; every one restates a value the
verdict already carries (metrics, runway split, own changes, overdue work), so nothing new is computed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from atlas_commander.verdict.config import VerdictConfig
from atlas_commander.verdict.inputs import EditorInputs, msg
from atlas_commander.verdict.reasoning import RUNWAY_EXPLAINS, RUNWAY_NOT_EXPLAINING, RunwayResult
from atlas_commander.verdict.tiers import BEST, LOW_ACTIVITY, STEADY, WATCH, WEAKEST, points_above, speed_for_verdict


@dataclass(frozen=True)
class Context:
    """What the sentences may cite about one Editor (all already in the verdict)."""

    editor: EditorInputs
    metrics: Mapping[str, Any]
    tier: str
    ranked: bool
    median_completed: float | None
    highest_completed: int | None
    runway: RunwayResult | None
    mirror: dict[str, Any] | None      # the "same as the whole team" reason, when a kept change mirrors the team
    own_change_mirrored: bool          # the own-history speed change is the team's, so it is not cited as the Editor's


def _pct(rate: float | None, config: VerdictConfig) -> float | None:
    return None if rate is None else round(rate * 100, int(config["precision.pct_digits"]))


def _round(value: float, config: VerdictConfig) -> float:
    return round(value, int(config["precision.pct_digits"]))


# --------------------------------------------------------------------------------------------------- facts as reasons

def _late(c: Context, config: VerdictConfig) -> dict[str, Any] | None:
    m = c.metrics
    above = points_above(m["late_rate"], m["team_late_rate"], config)
    if above is None:
        return None
    key = "late_above_team" if above > 0 else "late_below_team" if above < 0 else "late_at_team"
    return msg("verdict.reason." + key, late=m["late_count"], n=m["deadline_classifiable"], late_pct=_pct(m["late_rate"], config),
               team_pct=_pct(m["team_late_rate"], config))


def _speed(c: Context, config: VerdictConfig) -> dict[str, Any] | None:
    speed = speed_for_verdict(c.metrics)
    if speed is None:
        return None
    label = c.metrics["speed_label"]["params"] if c.metrics["speed_label"] else {}
    params = {"speed_pct": _round(abs(speed), config), **{k: label[k] for k in ("labels", "editor_hours", "peer_hours") if k in label}}
    if abs(speed) < config["display.speed_same_band_pct"]:
        return msg("verdict.reason.speed_as_peers", **params)
    return msg("verdict.reason.slower_than_peers" if speed > 0 else "verdict.reason.faster_than_peers", **params)


def _own_speed(c: Context, config: VerdictConfig) -> dict[str, Any] | None:
    own = c.metrics["own_speed_delta_pct"]
    if own is None or c.own_change_mirrored or abs(own) < config["display.speed_same_band_pct"]:
        return None
    return msg("verdict.reason.slower_than_own_history" if own > 0 else "verdict.reason.faster_than_own_history", change_pct=_round(abs(own), config))


def _volume(c: Context, config: VerdictConfig) -> dict[str, Any] | None:
    completed = c.metrics["completed"]
    if not c.ranked or not c.median_completed:
        return None
    if c.highest_completed is not None and completed == c.highest_completed:
        return msg("verdict.reason.volume_highest", completed=completed)
    if completed == c.median_completed:
        return None
    return msg("verdict.reason.volume_above_median" if completed > c.median_completed else "verdict.reason.volume_below_median",
               completed=completed, median=_round(c.median_completed, config))


def _overdue(c: Context, config: VerdictConfig) -> dict[str, Any] | None:
    count = len(c.editor.overdue)
    return msg("verdict.reason.overdue_open", count=count) if count else None


def _activity(c: Context, config: VerdictConfig) -> list[dict[str, Any]]:
    """Why an Editor has little to judge: nothing, or few, completed projects this window."""
    m = c.metrics
    if m["completed"] == 0 and m["active"] == 0:
        return [msg("verdict.reason.no_projects", lifetime_completed=m["lifetime_completed"]), msg("verdict.reason.nothing_in_progress")]
    if m["completed"] == 0:
        return [msg("verdict.reason.nothing_completed", active=m["active"])]
    if m["completed"] < config["tier.low_activity_below_completed"] and not c.editor.overdue:
        return [msg("verdict.reason.few_completed_none_overdue", completed=m["completed"])]
    return []


def _not_ranked(c: Context, config: VerdictConfig) -> dict[str, Any] | None:
    if c.ranked or c.tier == LOW_ACTIVITY:
        return None
    return msg("verdict.reason.not_ranked", completed=c.metrics["completed"], minimum=int(config["score.minimum_completed"]))


def _in_progress(c: Context, config: VerdictConfig) -> dict[str, Any] | None:
    active = c.metrics["active"]
    return msg("verdict.reason.in_progress", active=active) if active and c.metrics["completed"] else None   # else "nothing completed" cites it


def reasons(c: Context, config: VerdictConfig) -> list[dict[str, Any]]:
    """The tier's facts in order of strength: first the one that decided the tier, then the §6 context, then the other dimensions."""
    runway = c.runway.reason if c.runway else None
    late, speed, own, volume, overdue = (_late(c, config), _speed(c, config), _own_speed(c, config), _volume(c, config), _overdue(c, config))
    ordered: list[dict[str, Any] | None]
    if c.tier == WEAKEST:
        ordered = [runway, late, speed, own, overdue, volume]
    elif c.tier == WATCH:
        ordered = [overdue, late, speed, own, runway, c.mirror, volume]
    elif c.tier == BEST:
        ordered = [volume, speed, late, own, c.mirror, runway]
    elif c.tier == STEADY:
        ordered = [c.mirror, runway, late, speed, volume, own]
    else:
        ordered = [*_activity(c, config), overdue, late, runway]
    ordered += [_not_ranked(c, config), _in_progress(c, config)]   # general facts, after the tier's own
    out: list[dict[str, Any]] = []
    for reason in ordered:
        if reason is not None and reason not in out:
            out.append(reason)
    return _fill(out, c, config)


def _fill(out: list[dict[str, Any]], c: Context, config: VerdictConfig) -> list[dict[str, Any]]:
    if len(out) < config["display.reasons_min"]:   # an Editor with one fact still gets two bullets: the size of the evidence is the second
        out.append(msg("verdict.reason.completed_in_window", completed=c.metrics["completed"], lifetime_completed=c.metrics["lifetime_completed"]))
    return out[:int(config["display.reasons_max"])]


# --------------------------------------------------------------------------------------------------- headline

def headline(c: Context, config: VerdictConfig) -> dict[str, Any]:
    """``verdict.headline.<tier>.<variant>``: the tier and the strongest fact behind it."""
    m = c.metrics
    late_pct, team_pct = _pct(m["late_rate"], config), _pct(m["team_late_rate"], config)
    above = points_above(m["late_rate"], m["team_late_rate"], config)
    speed = speed_for_verdict(m)
    own = None if c.own_change_mirrored else m["own_speed_delta_pct"]
    slower = speed is not None and speed >= config["display.speed_same_band_pct"]
    faster = speed is not None and speed <= -config["display.speed_same_band_pct"]
    speed_pct = _round(abs(speed), config) if speed is not None else None

    def key(variant: str, **params: Any) -> dict[str, Any]:
        return msg(f"verdict.headline.{c.tier}.{variant}", **params)

    if c.tier == WEAKEST:
        if c.runway and c.runway.code == RUNWAY_NOT_EXPLAINING:
            if slower and own is not None and own >= config["display.speed_same_band_pct"]:
                return key("not_scheduling_slower_self", late_pct=late_pct, speed_pct=speed_pct, own_pct=_round(own, config))
            if slower:
                return key("not_scheduling_slower", late_pct=late_pct, speed_pct=speed_pct)
            return key("not_scheduling", late_pct=late_pct)
        if above is not None and above >= config["tier.weakest_late_above_team_pp"]:
            return key("late", late_pct=late_pct, team_pct=team_pct)
        return key("slow_and_late", speed_pct=speed_pct, late_pct=late_pct, team_pct=team_pct)
    if c.tier == WATCH:
        if c.editor.overdue:
            return key("overdue", count=len(c.editor.overdue))
        if above is not None and above > config["tier.watch_late_above_team_pp"]:
            return key("late", late_pct=late_pct, team_pct=team_pct)
        if speed is not None and speed >= config["tier.watch_speed_pct"]:
            return key("slow", speed_pct=speed_pct)
        return key("scheduling", late_pct=late_pct)          # a Weakest verdict limited to Watch because scheduling explains it
    if c.tier == BEST:
        highest = c.highest_completed is not None and m["completed"] == c.highest_completed
        if highest and faster:
            return key("highest_volume_faster")
        if faster:
            return key("faster", speed_pct=speed_pct, late_pct=late_pct, team_pct=team_pct)
        return key("default", late_pct=late_pct, team_pct=team_pct)
    if c.tier == STEADY:
        if c.mirror is not None:
            return key("mirrors_team")
        if c.runway and c.runway.code == RUNWAY_EXPLAINS:
            return key("scheduling", late_pct=late_pct)
        if late_pct is None:
            return key("few_data", completed=m["completed"])
        return key("default", late_pct=late_pct, team_pct=team_pct)
    if m["completed"] == 0 and m["active"] == 0:
        return key("zero_activity", lifetime_completed=m["lifetime_completed"])
    if m["completed"] == 0:
        return key("nothing_completed", active=m["active"])
    return key("few", completed=m["completed"])
