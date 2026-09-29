"""Explainable evidence strength (Task 6), kept separate from importance (Task 40).

Confidence answers *how well the data supports this finding*, not *how much it matters*. It is a level (``low``,
``moderate`` or ``strong`` evidence), never a fake-precise percentage. Every level lists the factors that produced it:

| Factor | Supports when | Limits when |
|---|---|---|
| sample size | every compared group has at least ``confidence.sample_multiple`` x its minimum | a group only just meets its minimum |
| replication | the effect repeats in independent slices (other window, other Video Types, other Editors) | it appears in one slice only |
| contradicting evidence | none was found | the finding carries contradicting evidence |
| data completeness | at least ``confidence.minimum_completeness`` of eligible projects have every field the finding needs | fields are missing |
| independent examples | several Editors and projects contribute | one Editor or few projects carry the result |

Level rule (deterministic, shown in every result):

- **strong**: sample well supported, and replicated in at least two independent slices, and no contradicting evidence, and data
  complete;
- **moderate**: the sample is well supported or the effect replicates at least once, unless contradicting evidence exists with
  no replication;
- **low**: everything else that passed the detector's minimum-evidence gate.

A factor whose parameter is not approved in the current mode is ``not_assessed`` and can never support ``strong``. Findings
below a detector's gate never reach this function: they are ``not_evaluated`` with their reason.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

from atlas_commander.investigation.policy import IntelligencePolicy

LOW, MODERATE, STRONG = "low", "moderate", "strong"
LEVELS = (LOW, MODERATE, STRONG)
LABELS = {LOW: "low evidence", MODERATE: "moderate evidence", STRONG: "strong evidence"}
SUPPORTS, LIMITS, NOT_ASSESSED, INFO = "supports", "limits", "not_assessed", "information"

RULE = ("strong = sample well supported AND replicated in >= 2 independent slices AND no contradicting evidence AND data complete; "
        "moderate = sample well supported OR replicated >= 1, unless contradicted without replication; low = passed the detector's "
        "minimum-evidence gate only")


def assess(policy: IntelligencePolicy, *, groups: Mapping[str, tuple[int, int | None]], replication: Sequence[Mapping[str, Any]] = (),
           contradictions: int = 0, completeness: tuple[int, int] | None = None, editors: int | None = None, projects: int | None = None) -> dict[str, Any]:
    """``groups`` maps each compared group to (sample, its minimum). ``replication`` lists independent slices tested, each
    ``{"slice": ..., "holds": bool}``. ``completeness`` is (projects with every needed field, eligible projects)."""
    factors: list[dict[str, Any]] = []
    multiple = policy.value("confidence.sample_multiple")
    if multiple is None:
        well_supported = None
        factors.append({"factor": "sample_size", "assessment": NOT_ASSESSED, "value": {name: sample for name, (sample, _) in sorted(groups.items())},
                        "detail": "confidence.sample_multiple is not approved"})
    else:
        weak = sorted(name for name, (sample, minimum) in groups.items() if minimum is not None and sample < multiple * minimum)
        well_supported = not weak and all(minimum is not None for _, minimum in groups.values())
        factors.append({"factor": "sample_size", "assessment": SUPPORTS if well_supported else LIMITS,
                        "value": {name: {"sample": sample, "minimum": minimum} for name, (sample, minimum) in sorted(groups.items())},
                        "detail": f"every group has at least {multiple} x its minimum" if well_supported else f"groups near their minimum: {weak}"})
    holds = [row for row in replication if row.get("holds")]
    factors.append({"factor": "replication", "assessment": SUPPORTS if holds else (LIMITS if replication else NOT_ASSESSED),
                    "value": {"tested": len(replication), "holds": len(holds)}, "slices": [dict(row) for row in replication]})
    factors.append({"factor": "contradicting_evidence", "assessment": LIMITS if contradictions else SUPPORTS, "value": contradictions})
    threshold = policy.value("confidence.minimum_completeness")
    complete: bool | None = None
    if completeness is not None:
        have, eligible = completeness
        if threshold is None:
            factors.append({"factor": "data_completeness", "assessment": NOT_ASSESSED, "value": {"complete": have, "eligible": eligible},
                            "detail": "confidence.minimum_completeness is not approved"})
        else:
            complete = eligible > 0 and Fraction(have, eligible) >= Fraction(str(threshold))
            factors.append({"factor": "data_completeness", "assessment": SUPPORTS if complete else LIMITS, "value": {"complete": have, "eligible": eligible},
                            "detail": f"{have} of {eligible} eligible projects carry every needed field"})
    if editors is not None or projects is not None:
        factors.append({"factor": "independent_examples", "assessment": INFO, "value": {"editors": editors, "projects": projects}})

    if well_supported and len(holds) >= 2 and not contradictions and complete is not False and completeness is not None and complete:
        level = STRONG
    elif (well_supported or holds) and not (contradictions and not holds):
        level = MODERATE
    else:
        level = LOW
    return {"level": level, "label": LABELS[level], "factors": factors, "rule": RULE,
            "method_status": "approved" if multiple is not None and threshold is not None and policy.parameters["confidence.sample_multiple"].approved else "proposed_not_approved",
            "why": _why(level, factors)}


def _why(level: str, factors: Sequence[Mapping[str, Any]]) -> list[str]:
    """One short code per factor that decided the level, for the confidence explanation (Task 58)."""
    return [f"{factor['factor']}:{factor['assessment']}" for factor in factors if factor["assessment"] in (SUPPORTS, LIMITS, NOT_ASSESSED)]
