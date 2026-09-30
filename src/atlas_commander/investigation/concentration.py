"""Where outcomes are disproportionately concentrated (Tasks 12, 13).

For an outcome (late delivery, a scored Negative label, a not-late delivery, a scored Positive label) and a dimension
(Video Type, Cairo month; or, inside one Editor's own work, Video Type), a group is *concentrated* when:

- the group has at least ``evidence.minimum_group_projects`` projects;
- it holds at least ``evidence.minimum_outcome_events`` outcomes, and so does the whole population;
- its share of the outcome is at least ``concentration.minimum_share_ratio`` x its share of the population; and
- its share of the outcome exceeds its population share by at least ``concentration.minimum_share_difference``.

Every finding publishes the numerator, the denominator, the expected (population) share, the sample, the affected projects
and the limitations. A concentration inside one Editor's work compares that Editor only with their *own* project mix, so it
says where their outcomes sit, not that they are worse than anyone.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from fractions import Fraction
from typing import Any

from atlas_commander.investigation import common as cm
from atlas_commander.investigation.baselines import COMPARISON, CURRENT, in_period, monthly_series
from atlas_commander.investigation.confidence import assess
from atlas_commander.investigation.context import Detector, DetectorResult, RunContext, uses
from atlas_commander.investigation.facts import ProjectFact
from atlas_commander.investigation.models import (
    ADVERSE,
    EDITOR_SPECIFIC_PATTERN,
    FAVOURABLE,
    HYPOTHESIS,
    INTERPRETATION,
    PATTERN,
    SYSTEM_PATTERN,
    Finding,
    Scope,
    Statement,
)
from atlas_commander.investigation.policy import INSUFFICIENT_OUTCOMES, INSUFFICIENT_SAMPLE, NO_EFFECT
from atlas_commander.investigation.stats import exact, shown

VERSION = "concentration-v1.0"
PARAMS = ("evidence.minimum_group_projects", "evidence.minimum_outcome_events", "concentration.minimum_share_ratio",
          "concentration.minimum_share_difference")


def _late(project: ProjectFact) -> bool:
    return bool(project.late)


def _not_late(project: ProjectFact) -> bool:
    return project.late is False


def _negative_label(project: ProjectFact) -> bool:
    return bool(project.negative_scored)


def _positive_label(project: ProjectFact) -> bool:
    return bool(project.positive_scored)


# outcome -> (population filter, outcome test, direction, columns, label evidence)
OUTCOMES: dict[str, tuple[Callable[[ProjectFact], bool], Callable[[ProjectFact], bool], str, tuple[str, ...], bool]] = {
    "late_delivery": (lambda p: p.deadline_classifiable, _late, ADVERSE, ("status", "requested_eta", "video_type", "editor"), False),
    "negative_quality_label": (lambda p: True, _negative_label, ADVERSE, ("status", "labels", "video_type", "editor"), True),
    "not_late_delivery": (lambda p: p.deadline_classifiable, _not_late, FAVOURABLE, ("status", "requested_eta", "video_type", "editor"), False),
    "positive_quality_label": (lambda p: True, _positive_label, FAVOURABLE, ("status", "labels", "bonus", "video_type", "editor"), True),
}


def _test(ctx: RunContext, result: DetectorResult, detector: str, *, outcome: str, dimension: str, population: Sequence[ProjectFact],
          group_of: Callable[[ProjectFact], Any], scope_for: Callable[[Any], Scope], editor: str | None, window: dict[str, Any]) -> None:
    values, used = uses(ctx, *PARAMS)
    minimum_group, minimum_outcomes = values["evidence.minimum_group_projects"], values["evidence.minimum_outcome_events"]
    ratio_floor, difference_floor = exact(values["concentration.minimum_share_ratio"]), exact(values["concentration.minimum_share_difference"])
    eligible_of, is_outcome, direction, columns, label_events = OUTCOMES[outcome]
    base = [project for project in population if eligible_of(project)]
    hits = [project for project in base if is_outcome(project)]
    groups: dict[Any, list[ProjectFact]] = {}
    for project in base:
        key = group_of(project)
        if key is not None:
            groups.setdefault(key, []).append(project)
    for key, members in sorted(groups.items(), key=lambda pair: str(pair[0])):
        k = sum(is_outcome(project) for project in members)
        if not hits or not base:
            continue
        outcome_share, base_share = Fraction(k, len(hits)), Fraction(len(members), len(base))
        facts = {"outcome": outcome, "dimension": dimension, "group": key, "group_projects": len(members), "group_outcomes": k,
                 "population_projects": len(base), "population_outcomes": len(hits), "outcome_share": shown(outcome_share),
                 "population_share": shown(base_share)}
        if outcome_share <= base_share:
            continue                                        # not a candidate: nothing to report either way
        reasons = []
        if len(members) < minimum_group:
            reasons.append(INSUFFICIENT_SAMPLE)
        if k < minimum_outcomes or len(hits) < minimum_outcomes:
            reasons.append(INSUFFICIENT_OUTCOMES)
        ratio = outcome_share / base_share
        if not reasons and (ratio < ratio_floor or outcome_share - base_share < difference_floor):
            reasons.append(NO_EFFECT)
        if reasons:
            result.skip(detector, scope_for(key), reasons, facts, PARAMS)
            continue
        replication = []
        for name in (CURRENT, COMPARISON):
            window_base = [project for project in base if in_period(project, name)]
            window_hits = [project for project in window_base if is_outcome(project)]
            window_group = [project for project in window_base if group_of(project) == key]
            if len(window_group) >= minimum_group and window_hits:
                share = Fraction(sum(is_outcome(project) for project in window_group), len(window_hits))
                replication.append({"slice": f"{name}_window", "holds": share > Fraction(len(window_group), len(window_base)),
                                    "group_projects": len(window_group)})
        group_label = cm.cohort_name(members, key) if dimension == "video_type" else str(key)
        partial = dimension == "month" and any(row["month"] == key and row["partial"] for row in _months(ctx))
        params = {**facts, "group_label": group_label, "share_ratio": shown(ratio), "group_rate": shown(Fraction(k, len(members))),
                  "population_rate": shown(Fraction(len(hits), len(base))), "editor_id": editor, "editor_name": ctx.name(editor),
                  "partial_period": partial}
        statements = [Statement(PATTERN, f"{'editor_' if editor else ''}outcome_concentrated", params)]
        if direction == ADVERSE:
            statements.append(Statement(INTERPRETATION, "concentration_suggests_group_level_factor" if not editor else "editor_outcomes_sit_in_group", params))
            statements.append(Statement(HYPOTHESIS, "group_may_differ_in_difficulty_or_scheduling", params))
        else:
            statements.append(Statement(INTERPRETATION, "favourable_outcomes_sit_in_group", params))
        records = [project.record("deadline_result", "cohort_key", "cairo_month", extra={"outcome": is_outcome(project)}, label_events=label_events)
                   for project in members]
        evidence = ctx.evidence("supporting", f"{outcome}_by_{dimension}",
                                (f"outcome share = {outcome} in the group / {outcome} in the population; population share = group projects / population "
                                 "projects; concentrated when outcome share / population share >= minimum_share_ratio AND outcome share - population "
                                 "share >= minimum_share_difference (exact fractions)"),
                                {"group_projects": len(members), "group_outcomes": k, "population_projects": len(base), "population_outcomes": len(hits)},
                                records, columns=columns, comparison={"group": {"outcome_share": shown(outcome_share), "rate": params["group_rate"]},
                                                                      "population": {"share": shown(base_share), "rate": params["population_rate"]}},
                                time_window=window)
        limitations = [cm.VIDEO_TYPE_ONLY, cm.ATTRIBUTED_ONLY, cm.INGEST_WINDOW, cm.NO_CAUSE_EVIDENCE]
        if label_events:
            limitations.append(cm.LABELS_LOWER_BOUND)
        if partial:
            limitations.append(cm.PARTIAL_PERIOD)
        finding = Finding(
            detector, VERSION, (EDITOR_SPECIFIC_PATTERN if editor else SYSTEM_PATTERN), direction, scope_for(key), statements, [evidence], used,
            window, limitations, Statement(INTERPRETATION, "significance_concentration", params),
            [Statement(HYPOTHESIS, "investigate_concentrated_group", params)],
            key={"outcome": outcome, "dimension": dimension, "group": key, "editor": editor}, magnitude=float(ratio),
            persistent=bool(replication) and all(row["holds"] for row in replication) if replication else None)
        finding.confidence = assess(ctx.policy, groups={"group": (len(members), minimum_group), "outcomes": (k, minimum_outcomes)},
                                    replication=replication, editors=len({p.editor_id for p in members if p.editor_id}), projects=len(members))
        result.add(finding)


def _months(ctx: RunContext) -> list[dict[str, Any]]:
    return monthly_series(ctx.facts)


def _editor_scope(editor: str) -> Callable[[Any], Scope]:
    return lambda key: Scope("editor", editor_id=editor, cohort_key=key)


def run_negative(ctx: RunContext) -> DetectorResult:
    return _run(ctx, "concentration.negative", ("late_delivery", "negative_quality_label"))


def run_positive(ctx: RunContext) -> DetectorResult:
    return _run(ctx, "concentration.positive", ("not_late_delivery", "positive_quality_label"))


def _run(ctx: RunContext, detector: str, outcomes: Sequence[str]) -> DetectorResult:
    result = DetectorResult()
    history = ctx.history_window
    population = ctx.facts.attributed
    for outcome in outcomes:
        _test(ctx, result, detector, outcome=outcome, dimension="video_type", population=population, group_of=lambda p: p.cohort_key,
              scope_for=lambda key: Scope("video_type", cohort_key=key), editor=None, window=history)
        if outcome == "late_delivery":
            _test(ctx, result, detector, outcome=outcome, dimension="month", population=population, group_of=lambda p: p.cairo_month,
                  scope_for=lambda key: Scope("team"), editor=None, window=history)
        for editor in ctx.facts.editors():
            mine = [project for project in population if project.editor_id == editor]
            _test(ctx, result, detector, outcome=outcome, dimension="video_type", population=mine, group_of=lambda p: p.cohort_key,
                  scope_for=_editor_scope(editor), editor=editor, window=history)
    return result


def _detector(detector_id: str, task: str, purpose: str, limitations: tuple[str, ...], run: Callable[[RunContext], DetectorResult]) -> Detector:
    return Detector(detector_id, VERSION, task, purpose, ("editor_identity", "video_type", "deadline_result", "performance_labels"), PARAMS,
                    "group >= evidence.minimum_group_projects; outcomes in group and population >= evidence.minimum_outcome_events",
                    "one finding per concentrated group with numerator, denominator, population share, ratio and the group's projects",
                    "groups vs minimums; replication = the outcome share also exceeds the population share in the current and comparison windows",
                    limitations, run)


DETECTORS = [
    _detector("concentration.negative", "12", "Where late deliveries and scored Negative labels are disproportionately concentrated "
              "(by Video Type, Cairo month, and inside each Editor's own work by Video Type)",
              (cm.VIDEO_TYPE_ONLY, cm.LABELS_LOWER_BOUND, cm.NO_CAUSE_EVIDENCE), run_negative),
    _detector("concentration.positive", "13", "Where not-late deliveries and scored Positive labels are disproportionately concentrated",
              (cm.VIDEO_TYPE_ONLY, cm.LABELS_LOWER_BOUND), run_positive),
]
