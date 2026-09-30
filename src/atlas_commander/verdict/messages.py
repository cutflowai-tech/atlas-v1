"""Every message key the verdict engine can write, with the parameters it may carry (redesign T4.1).

The engine writes sentences as ``Msg`` (a key and its parameters, never language). The pages render each key from the i18n
catalogue (``locales/catalog.json``, same key, English and Arabic). This registry is the contract between the two:
``tests/test_redesign_verdict_messages.py`` fails when the engine can emit a key that is not listed here, when a listed key has no
English or Arabic template, or when a template uses a parameter the key does not carry.

Parameter names carry their unit (schema ``Msg``): ``*_pct`` a percentage, ``*_hours`` and ``hours_past_eta`` hours, ``name``/``names`` Monday names,
``labels`` Video Type labels, ``dimension`` a dimension code, ``count`` the number a plural template agrees with; the rest are counts
or Monday values.
"""

from __future__ import annotations

TIERS = ("best", "steady", "watch", "weakest", "low_activity")
TEAM_STATES = ("critical", "needs_intervention", "on_track")
TEAM_TRENDS = ("improving", "flat", "declining")
QUALITY_STATES = ("positive", "neutral", "negative", "not_classifiable")

_LATE = ("late", "n", "late_pct", "team_pct")
_SPEED = ("speed_pct", "labels", "editor_hours", "peer_hours")

HEADLINES: dict[str, tuple[str, ...]] = {
    "weakest.not_scheduling_slower_self": ("late_pct", "speed_pct", "own_pct"),
    "weakest.not_scheduling_slower": ("late_pct", "speed_pct"),
    "weakest.not_scheduling": ("late_pct",),
    "weakest.late": ("late_pct", "team_pct"),
    "weakest.slow_and_late": ("speed_pct", "late_pct", "team_pct"),
    "watch.overdue": ("count",),
    "watch.late": ("late_pct", "team_pct"),
    "watch.slow": ("speed_pct",),
    "watch.scheduling": ("late_pct",),
    "best.highest_volume_faster": (),
    "best.faster": ("speed_pct", "late_pct", "team_pct"),
    "best.default": ("late_pct", "team_pct"),
    "steady.mirrors_team": (),
    "steady.scheduling": ("late_pct",),
    "steady.few_data": ("completed",),
    "steady.default": ("late_pct", "team_pct"),
    "low_activity.zero_activity": ("lifetime_completed",),
    "low_activity.nothing_completed": ("active",),
    "low_activity.few": ("completed",),
}

REASONS: dict[str, tuple[str, ...]] = {
    "late_above_team": _LATE, "late_below_team": _LATE, "late_at_team": _LATE,
    "slower_than_peers": _SPEED, "faster_than_peers": _SPEED, "speed_as_peers": _SPEED,
    "slower_than_own_history": ("change_pct",), "faster_than_own_history": ("change_pct",),
    "volume_highest": ("completed",), "volume_above_median": ("completed", "median"), "volume_below_median": ("completed", "median"),
    "overdue_open": ("count",),
    "no_projects": ("lifetime_completed",), "nothing_in_progress": (), "nothing_completed": ("active",),
    "few_completed_none_overdue": ("completed",), "not_ranked": ("completed", "minimum"), "in_progress": ("active",),
    "completed_in_window": ("completed", "lifetime_completed"),
    "runway_not_explaining": ("late_pct", "short_runway_late_pct"),
    "runway_explains": ("short_share_pct", "team_short_share_pct", "late", "short"),
    "mirrors_team_late_rate": ("before_pct", "now_pct", "team_before_pct", "team_now_pct"),
    "mirrors_team_speed": ("change_pct", "team_change_pct"),
}

_TEAM_HEADLINE = ("late_pct", "previous_pct", "overdue")
TEAM: dict[str, tuple[str, ...]] = {
    **{f"headline.{state}.{trend}": _TEAM_HEADLINE for state in TEAM_STATES for trend in TEAM_TRENDS},
    "supporting.scheduling": ("short_share_pct", "overdue"), "supporting.editing": ("short_share_pct", "overdue"), "supporting.unknown": ("overdue",),
    "fact.late_rate_change": ("late_pct", "late", "n", "previous_pct"), "fact.late_rate": ("late_pct", "late", "n"), "fact.no_late_rate": (),
    "pattern.short_runway": ("short_runway_late_pct", "short_runway", "adequate_runway_late_pct", "adequate_runway"), "pattern.no_runway_split": (),
    "conclusion.scheduling": ("short_share_pct", "short_runway_late", "late"), "conclusion.editing": ("short_share_pct", "short_runway_late", "late"),
    "conclusion.unknown": (),
    "kpi.late_rate": ("previous_pct",), "kpi.late_rate_now": (), "kpi.overdue": ("count",), "kpi.short_runway_share": ("short_runway_late", "late"),
}

DECISIONS: dict[str, tuple[str, ...]] = {
    "overdue_open_work": ("count", "names"), "weakest_editor": ("name",), "scheduling_runway": ("short_share_pct",),
    "low_activity": ("names",), "zero_activity": ("names",), "approve_rule": ("dimension",), "review_rule": ("dimension",),
}

EVIDENCE: dict[str, tuple[str, ...]] = {
    "overdue_project": ("name", "item_id", "status", "hours_past_eta", "video_type"),
    "short_runway_split": ("short_runway_late_pct", "short_runway", "adequate_runway_late_pct", "adequate_runway", "short_runway_late", "late"),
    "low_activity": ("name", "completed", "active", "overdue"), "zero_activity": ("name", "lifetime_completed"),
    "rule_not_approved": ("dimension", "editors"), "zero_for_everyone": ("dimension", "editors"),
}

OTHER: dict[str, tuple[str, ...]] = {
    "project.reference": ("video_type", "item_id"), "project.item": ("item_id",),
    "speed.label": ("labels", "editor_hours", "peer_hours", "n"),
    "quality.positive_notes": ("positive_pct",), **{f"quality.state.{state}": () for state in QUALITY_STATES},
}

KEYS: dict[str, tuple[str, ...]] = {
    **{f"verdict.headline.{k}": v for k, v in HEADLINES.items()},
    **{f"verdict.reason.{k}": v for k, v in REASONS.items()},
    **{f"verdict.team.{k}": v for k, v in TEAM.items()},
    **{f"verdict.decision.{k}": v for k, v in DECISIONS.items()},
    **{f"verdict.evidence.{k}": v for k, v in EVIDENCE.items()},
    **{f"verdict.{k}": v for k, v in OTHER.items()},
}
PLURAL = frozenset(key for key, params in KEYS.items() if "count" in params)   # templates that agree with the count
