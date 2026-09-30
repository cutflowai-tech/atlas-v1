"""Small, dependency-free descriptive statistics for Intelligence V2.

Robust statistics only: medians and interquartile ranges (never means of skewed durations), counts beside every rate, and
exact ``Fraction`` comparisons against thresholds so a boundary value is never decided by float rounding. The median and
quantile rules are the engine's own (``metrics.median_seconds`` / ``quantile_seconds``: even samples take the mean of the two
middle values floored to whole seconds; quantiles interpolate linearly), so V2 never reports a different median for the same
projects.
"""

from __future__ import annotations

from collections.abc import Iterable
from fractions import Fraction
from typing import Any

from atlas_commander.metrics import median_seconds, quantile_seconds


def median(values: Iterable[int]) -> int | None:
    return median_seconds(int(value) for value in values)


def quantile(values: Iterable[int], q: float) -> int | None:
    return quantile_seconds([int(value) for value in values], q)


def rate(count: int, total: int) -> Fraction | None:
    return Fraction(count, total) if total else None


def shown(value: Fraction | float | None, digits: int = 4) -> float | None:
    """Display value of an exact rate (rounding is for display only; comparisons use the exact value)."""
    return None if value is None else round(float(value), digits)


def pct_change(new: int | None, old: int | None) -> Fraction | None:
    """(new - old) / old as an exact fraction; None when either side is missing or old is zero."""
    if new is None or not old:
        return None
    return Fraction(new - old, old)


def exact(value: Any) -> Fraction:
    """A configured threshold as an exact fraction (so 0.15 is exactly 15/100, not a binary approximation)."""
    return Fraction(str(value))


def distribution(values: Iterable[int]) -> dict[str, int | None]:
    ordered = sorted(int(value) for value in values)
    return {"n": len(ordered), "median": median(ordered), "p25": quantile(ordered, 0.25), "p75": quantile(ordered, 0.75),
            "min": ordered[0] if ordered else None, "max": ordered[-1] if ordered else None}


def rate_summary(count: int, total: int) -> dict[str, Any]:
    return {"count": count, "total": total, "rate": shown(rate(count, total))}
