"""Team verdict (redesign T2.15, `02-VERDICT-ENGINE-SPEC.md` §8): the state of the whole team, its trend against the previous window,
the fact → pattern → conclusion chain and up to three KPIs. Every value is a team input the Editor verdicts already use (sums of the
Editors' own counts, the overdue list, the Intelligence V2 short-runway split); every threshold is in the configuration.
"""

from __future__ import annotations

from typing import Any

from atlas_commander.verdict.confidence import LEVELS
from atlas_commander.verdict.config import VerdictConfig
from atlas_commander.verdict.inputs import TeamInputs, msg

CRITICAL, NEEDS_INTERVENTION, ON_TRACK = "critical", "needs_intervention", "on_track"
IMPROVING, FLAT, DECLINING = "improving", "flat", "declining"
SCHEDULING, EDITING = "scheduling", "editing"


def _msg(key: str, **params: Any) -> dict[str, Any]:
    """A message without the parameters that have no value (a Msg parameter is never null)."""
    return msg(key, **{name: value for name, value in params.items() if value is not None})


def _pct(rate: float | None, config: VerdictConfig) -> float | None:
    return None if rate is None else round(rate * 100, int(config["precision.pct_digits"]))


def state(late_rate: float | None, overdue: int, config: VerdictConfig) -> str:
    """Critical at or above the critical late rate or overdue count; needs intervention at or above the intervention late rate."""
    if (late_rate is not None and late_rate >= config["team.critical_late_rate"]) or overdue >= config["team.critical_overdue"]:
        return CRITICAL
    if late_rate is not None and late_rate >= config["team.intervention_late_rate"]:
        return NEEDS_INTERVENTION
    return ON_TRACK


def trend(late_rate: float | None, previous: float | None, config: VerdictConfig) -> str:
    """Against the previous window: a lower late rate is improving; a move of at most ``team.flat_band_pp`` points is flat. Without
    a previous window there is no movement to report (flat, with lower confidence)."""
    if late_rate is None or previous is None:
        return FLAT
    moved = round((late_rate - previous) * 100, int(config["precision.rate_digits"]) - 2)
    if abs(moved) <= config["team.flat_band_pp"]:
        return FLAT
    return IMPROVING if moved < 0 else DECLINING


def dominant_cause(team: TeamInputs, config: VerdictConfig) -> str | None:
    """Which share dominates the late projects: short runway (scheduling) when it reaches ``decisions.scheduling_runway_share``,
    otherwise adequate runway (the editing itself). None without the Intelligence V2 split."""
    share = (team.runway or {}).get("share_of_late_with_short_runway")
    if share is None:
        return None
    return SCHEDULING if share >= config["decisions.scheduling_runway_share"] else EDITING


def _tone_late(late_rate: float | None, config: VerdictConfig) -> str:
    if late_rate is None:
        return "neutral"
    if late_rate >= config["team.critical_late_rate"]:
        return "bad"
    return "warn" if late_rate >= config["team.intervention_late_rate"] else "good"


def _tone_overdue(overdue: int, config: VerdictConfig) -> str:
    if overdue >= config["team.critical_overdue"]:
        return "bad"
    return "warn" if overdue else "good"


def _number(value: float) -> str:
    """A KPI value as a language-neutral numeral; the page adds the unit and the locale's digits."""
    return str(value)


def team_verdict(team: TeamInputs, config: VerdictConfig) -> dict[str, Any]:
    late_rate, previous, overdue = team.late_rate, team.previous_late_rate, len(team.overdue)
    split = team.runway or {}
    late_pct, previous_pct = _pct(late_rate, config), _pct(previous, config)
    now_state, now_trend, cause = state(late_rate, overdue, config), trend(late_rate, previous, config), dominant_cause(team, config)
    short_share_pct = _pct(split.get("share_of_late_with_short_runway"), config)

    missing = [reason for reason, absent in (("no_previous_window", previous is None), ("no_intelligence", not team.intelligence_available),
                                             ("no_late_rate", late_rate is None)) if absent]
    level = LEVELS[min(len(missing), len(LEVELS) - 1)]

    if late_rate is None:
        fact = msg("verdict.team.fact.no_late_rate")
    elif previous is None:
        fact = msg("verdict.team.fact.late_rate", late_pct=late_pct, late=team.late, n=team.classifiable)
    else:
        fact = msg("verdict.team.fact.late_rate_change", late_pct=late_pct, late=team.late, n=team.classifiable, previous_pct=previous_pct)
    if cause is None:
        pattern = msg("verdict.team.pattern.no_runway_split")
    else:
        pattern = msg("verdict.team.pattern.short_runway", short_runway_late_pct=_pct(split["short_runway_late_rate"], config),
                      short_runway=split["short_runway"], adequate_runway_late_pct=_pct(split["adequate_runway_late_rate"], config),
                      adequate_runway=split["adequate_runway"])
    conclusion = _msg(f"verdict.team.conclusion.{cause or 'unknown'}", short_share_pct=short_share_pct, short_runway_late=split.get("short_runway_late"),
                      late=split.get("late"))

    kpis = [{"key": "late_rate", "value": _number(late_pct) if late_pct is not None else "", "tone": _tone_late(late_rate, config),
             "label": msg("verdict.team.kpi.late_rate", previous_pct=previous_pct) if previous_pct is not None else msg("verdict.team.kpi.late_rate_now")},
            {"key": "overdue", "value": _number(overdue), "tone": _tone_overdue(overdue, config), "label": msg("verdict.team.kpi.overdue", count=overdue)}]
    if short_share_pct is not None:
        kpis.append({"key": "short_runway_share", "value": _number(short_share_pct), "tone": "warn" if cause == SCHEDULING else "neutral",
                     "label": msg("verdict.team.kpi.short_runway_share", short_runway_late=split["short_runway_late"], late=split["late"])})
    return {
        "headline": _msg(f"verdict.team.headline.{now_state}.{now_trend}", late_pct=late_pct, previous_pct=previous_pct, overdue=overdue),
        "supporting": _msg(f"verdict.team.supporting.{cause or 'unknown'}", short_share_pct=short_share_pct, overdue=overdue),
        "state": now_state, "trend": now_trend, "confidence": level,
        "chain": {"fact": fact, "pattern": pattern, "conclusion": conclusion},
        "kpis": kpis,
        "facts": {"late": team.late, "classifiable": team.classifiable, "late_rate": None if late_rate is None else round(late_rate, int(config["precision.rate_digits"])),
                  "previous_late": team.previous_late, "previous_classifiable": team.previous_classifiable,
                  "previous_late_rate": None if previous is None else round(previous, int(config["precision.rate_digits"])),
                  "overdue": overdue, "short_runway": dict(split) or None, "short_runway_finding_id": team.runway_finding_id,
                  "confidence_reasons": missing},
    }
