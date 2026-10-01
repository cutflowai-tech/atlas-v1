"""Verdict confidence (redesign T2.7, `02-VERDICT-ENGINE-SPEC.md` §5): start High and step down one level per reason, never below
Low. Low data lowers confidence; it never removes the verdict.

- ``few_projects``: fewer completed projects in the window than ``confidence.few_projects_below``.
- ``missing_dimension``: a key dimension (deadlines or speed) has no usable value; the specific ``missing_<dimension>`` codes from
  the score stay alongside it as detail and do not lower the level twice.
- ``mixed_evidence``: a published Intelligence V2 finding qualifies this Editor's late-rate headline with contradicting evidence
  while the verdict uses the deadline dimension.
- ``timeline_only`` would set Low directly for a verdict resting only on the event timeline. Every Atlas verdict rests on computed
  counts from the Editor Profile (completed, late, overdue, active), so it does not occur; the code is kept so the rule stays
  explicit (see docs/redesign/DECISIONS.md R7).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from atlas_commander.verdict.config import VerdictConfig

LEVELS = ("high", "medium", "low")
KEY_DIMENSIONS = ("deadlines", "speed")


def confidence(metrics: Mapping[str, Any], missing: Sequence[str], based_on: Sequence[str], headline_contradictions: Sequence[str],
               config: VerdictConfig, *, timeline_only: bool = False) -> tuple[str, list[str]]:
    """The confidence level and its reasons, in the order they lowered it (detail codes last)."""
    reasons = []
    if metrics["completed"] < config["confidence.few_projects_below"]:
        reasons.append("few_projects")
    key_missing = [name for name in KEY_DIMENSIONS if name in missing]
    if key_missing:
        reasons.append("missing_dimension")
    if headline_contradictions and "deadlines" in based_on:
        reasons.append("mixed_evidence")
    if timeline_only:
        return "low", [*reasons, "timeline_only"]
    level = LEVELS[min(len(reasons), len(LEVELS) - 1)]
    return level, reasons + [f"missing_{name}" for name in missing]
