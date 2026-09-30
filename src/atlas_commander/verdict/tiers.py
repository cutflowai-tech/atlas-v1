"""Tier assignment and score (redesign T2.5, T2.6; `02-VERDICT-ENGINE-SPEC.md` §3 and §4). Pure functions over the normalized
metrics; every threshold and weight comes from ``config/verdict-v1.json``.

Rates are fractions with ``precision.rate_digits`` decimals; they are compared in percentage points rounded to the same precision,
so a value exactly on a threshold is decided by the threshold's own comparison (``≥`` or ``>``), never by representation error.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from atlas_commander.verdict.config import VerdictConfig

BEST, STEADY, WATCH, WEAKEST, LOW_ACTIVITY = "best", "steady", "watch", "weakest", "low_activity"
TIERS = (BEST, STEADY, WATCH, WEAKEST, LOW_ACTIVITY)   # display order: Best → Low activity
DIMENSIONS = ("deadlines", "speed", "volume", "quality")


def points_above(rate: float | None, team_rate: float | None, config: VerdictConfig) -> float | None:
    """Percentage points by which ``rate`` exceeds ``team_rate`` (negative when below); None when either is unknown."""
    if rate is None or team_rate is None:
        return None
    return round((rate - team_rate) * 100, int(config["precision.rate_digits"]) - 2)


def speed_for_verdict(metrics: Mapping[str, Any]) -> float | None:
    """The speed difference a verdict may use: only a comparison the approved Speed rule classifies (D52 samples)."""
    return metrics["speed_delta_pct"] if metrics["speed_classified"] else None


@dataclass(frozen=True)
class Standing:
    """Where the Editor stands among the ranked Editors (from the scores)."""

    in_top_share: bool
    worse_dimensions: tuple[str, ...]


def assign_tier(metrics: Mapping[str, Any], overdue: int, config: VerdictConfig, standing: Standing) -> str:
    """Spec §3: the first rule that matches wins."""
    completed = metrics["completed"]
    if completed == 0 or (completed < config["tier.low_activity_below_completed"] and overdue == 0):
        return LOW_ACTIVITY
    above = points_above(metrics["late_rate"], metrics["team_late_rate"], config)
    speed = speed_for_verdict(metrics)
    if above is not None and (above >= config["tier.weakest_late_above_team_pp"]
                              or (speed is not None and speed >= config["tier.weakest_speed_pct"] and above > 0)):
        return WEAKEST
    if (above is not None and above > config["tier.watch_late_above_team_pp"]) or (speed is not None and speed >= config["tier.watch_speed_pct"]) \
            or overdue > 0:
        return WATCH
    if standing.in_top_share and not standing.worse_dimensions:
        return BEST
    return STEADY


# --------------------------------------------------------------------------------------------------- score (spec §4)

def _clamp(value: float, config: VerdictConfig) -> float:
    return max(config["score.minimum"], min(config["score.maximum"], value))


def dimension_points(metrics: Mapping[str, Any], median_completed: float | None, config: VerdictConfig) -> dict[str, float | None]:
    """0–100 points per dimension; ``score.neutral`` is exactly the team level. None when the dimension has no usable value."""
    neutral = config["score.neutral"]
    above = points_above(metrics["late_rate"], metrics["team_late_rate"], config)
    speed = speed_for_verdict(metrics)
    return {
        "deadlines": None if above is None else _clamp(neutral - above * config["score.deadline_points_per_pp"], config),
        "speed": None if speed is None else _clamp(neutral - speed * config["score.speed_points_per_pct"], config),
        "volume": (None if not median_completed else
                   _clamp(neutral + (metrics["completed"] / median_completed - 1) * config["score.volume_points_per_median_multiple"], config)),
        "quality": None,   # no Quality rule is approved (open decision 0); it joins the score only once one is
    }


def weights(config: VerdictConfig, quality_approved: bool) -> dict[str, float]:
    """Spec §4 weights; once a Quality rule is approved, Quality takes its weight and the others share the rest proportionally."""
    base = {"deadlines": config["score.weight_deadlines"], "speed": config["score.weight_speed"], "volume": config["score.weight_volume"]}
    if not quality_approved:
        return base
    rest = 1 - config["score.weight_quality"]
    total = sum(base.values())
    return {**{name: weight / total * rest for name, weight in base.items()}, "quality": config["score.weight_quality"]}


@dataclass(frozen=True)
class Scored:
    editor_id: str
    score: float
    late_rate: float | None
    completed: int


def rank(entries: list[Scored]) -> dict[str, int]:
    """Spec §4: by score, highest first; ties go to the lower late rate, then to more completed projects (then the ID, so the
    order is total and deterministic)."""
    order = sorted(entries, key=lambda e: (-e.score, e.late_rate if e.late_rate is not None else float("inf"), -e.completed, e.editor_id))
    return {e.editor_id: position for position, e in enumerate(order, start=1)}


def score(points: Mapping[str, float | None], config: VerdictConfig, quality_approved: bool) -> tuple[float | None, list[str]]:
    """The weighted score and the dimensions that were missing (their weight is redistributed proportionally)."""
    used = {name: weight for name, weight in weights(config, quality_approved).items() if points.get(name) is not None}
    missing = [name for name in weights(config, quality_approved) if name not in used]
    total = sum(used.values())
    if not total:
        return None, missing
    value = sum(weight / total * float(points[name] or 0) for name, weight in used.items())
    return round(value, int(config["precision.pct_digits"])), missing
