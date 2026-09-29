"""Concurrent workload and its association with outcomes (Tasks 22-26).

**Workload model (Task 22).** A project's concurrent workload is the number of the same Editor's *other* attributed completed
first cycles whose ``[first In Progress, first Ready For Approval)`` interval contains this project's first In Progress
moment. It is a lower bound: open, unattributed and rework work is invisible. No capacity rule is approved (D33, HANDOFF §21),
so there is no universal overload threshold. Under ``workload.band_rule`` a project is in the *higher* band when its
concurrency is above **the same Editor's own median** concurrency, and in the *lower* band otherwise.

**Associations (Tasks 23-25).** Comparisons are stratified so unlike work is never pooled:

- execution time: within each Editor x exact Video Type stratum with projects in both bands; the stratum's median percentage
  difference, then the median of those differences, and how many strata point the same way;
- late rate and scored Negative label rate: higher-band vs lower-band rates, with how many exact Video Types agree.

Wording is always *associated with*. Workload is never said to cause anything.

**Overload pattern (Task 26).** The same comparison inside one Editor's own work: repeated combinations of higher concurrency
and a worse outcome, relative to that Editor's own distribution.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from fractions import Fraction
from typing import Any

from atlas_commander.investigation import common as cm
from atlas_commander.investigation.confidence import assess
from atlas_commander.investigation.context import Detector, DetectorResult, RunContext, uses
from atlas_commander.investigation.facts import ProjectFact
from atlas_commander.investigation.models import (
    ADVERSE,
    ASSOCIATION,
    FAVOURABLE,
    HIDDEN_CONTEXT,
    HYPOTHESIS,
    INTERPRETATION,
    METRIC,
    SYSTEM_PATTERN,
    Finding,
    Scope,
    Statement,
)
from atlas_commander.investigation.policy import INSUFFICIENT_OUTCOMES, INSUFFICIENT_SAMPLE, NO_EFFECT
from atlas_commander.investigation.stats import distribution, exact, median, shown

VERSION = "workload-v1.0"
HIGH, LOW = "higher", "lower"


def editor_medians(projects: Sequence[ProjectFact]) -> dict[str, int]:
    by_editor: dict[str, list[int]] = defaultdict(list)
    for project in projects:
        if project.editor_id and project.concurrency_at_start is not None:
            by_editor[project.editor_id].append(project.concurrency_at_start)
    return {editor: int(median(values) or 0) for editor, values in by_editor.items()}


def band(project: ProjectFact, medians: dict[str, int]) -> str | None:
    if project.editor_id is None or project.concurrency_at_start is None or project.editor_id not in medians:
        return None
    return HIGH if project.concurrency_at_start > medians[project.editor_id] else LOW


def _speed_association(projects: Sequence[ProjectFact], medians: dict[str, int]) -> dict[str, Any]:
    strata: dict[tuple[str, str], dict[str, list[ProjectFact]]] = defaultdict(lambda: {HIGH: [], LOW: []})
    for project in projects:
        side = band(project, medians)
        if side and project.speed_measurable and project.cohort_key and project.editor_id:
            strata[(project.editor_id, project.cohort_key)][side].append(project)
    rows = []
    for (editor, key), sides in sorted(strata.items()):
        if sides[HIGH] and sides[LOW]:
            high, low = median(p.duration_seconds for p in sides[HIGH]), median(p.duration_seconds for p in sides[LOW])
            if high is not None and low:
                rows.append({"editor_id": editor, "cohort_key": key, "higher": len(sides[HIGH]), "lower": len(sides[LOW]),
                             "higher_median_hours": cm.hours(high), "lower_median_hours": cm.hours(low), "pct": Fraction(high - low, low),
                             "projects": [*sides[HIGH], *sides[LOW]]})
    return {"strata": rows, "higher": sum(row["higher"] for row in rows), "lower": sum(row["lower"] for row in rows)}


def _rate(projects: Sequence[ProjectFact], outcome: Callable[[ProjectFact], bool | None]) -> tuple[int, int]:
    rows = [outcome(p) for p in projects]
    valid = [value for value in rows if value is not None]
    return sum(bool(value) for value in valid), len(valid)


OUTCOMES: dict[str, tuple[Callable[[ProjectFact], bool | None], str, tuple[str, ...]]] = {
    "late_rate": (lambda p: p.late, "evidence.material_rate_difference", ("status", "requested_eta", "editor")),
    "negative_label_rate": (lambda p: bool(p.negative_scored), "evidence.material_rate_difference", ("status", "labels", "editor")),
}


def _finding(ctx: RunContext, detector: str, scope: Scope, code: str, params: dict[str, Any], records: list[Any], sample: dict[str, int],
             comparison: dict[str, Any], used: list[Any], groups: dict[str, tuple[int, int | None]], replication: list[dict[str, Any]], magnitude: float,
             adverse: bool, columns: tuple[str, ...], category: str) -> Finding:
    statements = [Statement(METRIC, "workload_bands", params), Statement(ASSOCIATION, code, params),
                  Statement(INTERPRETATION, "association_not_cause_workload", params), Statement(HYPOTHESIS, "workload_may_contribute", params)]
    evidence = ctx.evidence("supporting", code, ("band = higher when the project's concurrent workload at its start is above the same Editor's own median, "
                                                 "else lower; compared within Editor x exact Video Type (execution) or by band with Video Type agreement (rates)"),
                            sample, records, columns=columns, comparison=comparison, time_window=ctx.history_window)
    finding = Finding(detector, VERSION, category, ADVERSE if adverse else FAVOURABLE, scope, statements, [evidence], used, ctx.history_window,
                      [cm.ASSOCIATION_NOT_CAUSE, cm.WORKLOAD_LOWER_BOUND, cm.ELAPSED_TIME, cm.VIDEO_TYPE_ONLY, cm.ATTRIBUTED_ONLY],
                      Statement(INTERPRETATION, "significance_workload", params), [Statement(HYPOTHESIS, "compare_assignment_volume", params)],
                      key={"code": code, "scope": scope.to_dict()}, magnitude=magnitude)
    finding.confidence = assess(ctx.policy, groups=groups, replication=replication, editors=len(finding.affected_editors), projects=finding.sample_size)
    return finding


def _speed(ctx: RunContext, result: DetectorResult, detector: str, projects: Sequence[ProjectFact], scope: Scope, medians: dict[str, int],
           values: dict[str, Any], used: list[Any], category: str) -> None:
    floor, material = values["evidence.minimum_group_projects"], exact(values["evidence.material_duration_pct"]) / 100
    association = _speed_association(projects, medians)
    strata = association["strata"]
    facts = {"higher_band_projects": association["higher"], "lower_band_projects": association["lower"], "strata": len(strata)}
    if min(association["higher"], association["lower"]) < floor or not strata:
        result.skip(detector, scope, [INSUFFICIENT_SAMPLE], facts, ("evidence.minimum_group_projects",))
        return
    typical = sorted(row["pct"] for row in strata)
    middle = typical[len(typical) // 2] if len(typical) % 2 else (typical[len(typical) // 2 - 1] + typical[len(typical) // 2]) / 2
    longer = sum(row["pct"] > 0 for row in strata)
    if abs(middle) < material:
        result.skip(detector, scope, [NO_EFFECT], {**facts, "median_stratum_pct": shown(middle * 100, 1)}, ("evidence.material_duration_pct",))
        return
    params = {**facts, "median_stratum_pct": shown(middle * 100, 1), "strata_longer_when_higher": longer, "editor_id": scope.editor_id,
              "editor_name": ctx.name(scope.editor_id), "direction": "longer" if middle > 0 else "shorter"}
    records = [p.record("duration_seconds", "concurrency_at_start", extra={"band": band(p, medians), "editor_median_concurrency": medians.get(p.editor_id or "")})
               for row in strata for p in row["projects"]]
    comparison = {"strata": [{key: (shown(value * 100, 1) if key == "pct" else value) for key, value in row.items() if key != "projects"} for row in strata]}
    replication = [{"slice": f"{row['editor_id']}:{row['cohort_key']}", "holds": (row["pct"] > 0) == (middle > 0)} for row in strata]
    result.add(_finding(ctx, detector, scope, "higher_workload_associated_with_execution_time", params, records,
                        {"higher_band": association["higher"], "lower_band": association["lower"], "strata": len(strata)}, comparison, used,
                        {"higher_band": (association["higher"], floor), "lower_band": (association["lower"], floor)}, replication, float(abs(middle)),
                        middle > 0, ("status", "video_type", "editor"), category))


def _rates(ctx: RunContext, result: DetectorResult, detector: str, projects: Sequence[ProjectFact], scope: Scope, medians: dict[str, int],
           values: dict[str, Any], used: list[Any], category: str) -> None:
    floor, minimum_outcomes = values["evidence.minimum_group_projects"], values["evidence.minimum_outcome_events"]
    material = exact(values["evidence.material_rate_difference"])
    for name, (outcome, _, columns) in OUTCOMES.items():
        sides = {HIGH: [p for p in projects if band(p, medians) == HIGH], LOW: [p for p in projects if band(p, medians) == LOW]}
        (high_k, high_n), (low_k, low_n) = _rate(sides[HIGH], outcome), _rate(sides[LOW], outcome)
        facts = {"measure": name, "higher_band": high_n, "higher_band_outcomes": high_k, "lower_band": low_n, "lower_band_outcomes": low_k}
        reasons = []
        if min(high_n, low_n) < floor:
            reasons.append(INSUFFICIENT_SAMPLE)
        if high_k + low_k < minimum_outcomes:
            reasons.append(INSUFFICIENT_OUTCOMES)
        if reasons:
            result.skip(detector, scope, reasons, facts, ("evidence.minimum_group_projects", "evidence.minimum_outcome_events"))
            continue
        difference = Fraction(high_k, high_n) - Fraction(low_k, low_n)
        if abs(difference) < material:
            result.skip(detector, scope, [NO_EFFECT], {**facts, "difference": shown(difference)}, ("evidence.material_rate_difference",))
            continue
        replication = []
        for key in sorted({p.cohort_key for p in sides[HIGH] if p.cohort_key}):
            hk, hn = _rate([p for p in sides[HIGH] if p.cohort_key == key], outcome)
            lk, ln = _rate([p for p in sides[LOW] if p.cohort_key == key], outcome)
            if hn and ln:
                replication.append({"slice": f"video_type:{key}", "holds": (Fraction(hk, hn) > Fraction(lk, ln)) == (difference > 0)})
        params = {**facts, "higher_rate": shown(Fraction(high_k, high_n)), "lower_rate": shown(Fraction(low_k, low_n)), "difference": shown(difference),
                  "editor_id": scope.editor_id, "editor_name": ctx.name(scope.editor_id)}
        records = [p.record("deadline_result", "concurrency_at_start", "negative_scored", extra={"band": band(p, medians)},
                            label_events=name == "negative_label_rate") for p in (*sides[HIGH], *sides[LOW]) if outcome(p) is not None]
        result.add(_finding(ctx, detector, scope, f"higher_workload_associated_with_{name}", params, records, {"higher_band": high_n, "lower_band": low_n},
                            {"higher": params["higher_rate"], "lower": params["lower_rate"]}, used,
                            {"higher_band": (high_n, floor), "lower_band": (low_n, floor), "outcomes": (high_k + low_k, minimum_outcomes)},
                            replication, float(abs(difference)), difference > 0, columns, category))


PARAMS = ("workload.band_rule", "evidence.minimum_group_projects", "evidence.minimum_outcome_events", "evidence.material_duration_pct",
          "evidence.material_rate_difference")


def run_team(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, *PARAMS)
    result = DetectorResult()
    projects = ctx.facts.attributed
    medians = editor_medians(projects)
    _speed(ctx, result, "workload.association", projects, Scope("team"), medians, values, used, SYSTEM_PATTERN)
    _rates(ctx, result, "workload.association", projects, Scope("team"), medians, values, used, SYSTEM_PATTERN)
    return result


def run_editor(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, *PARAMS)
    result = DetectorResult()
    medians = editor_medians(ctx.facts.attributed)
    for editor in ctx.facts.editors():
        mine = [p for p in ctx.facts.attributed if p.editor_id == editor]
        _speed(ctx, result, "workload.overload_pattern", mine, Scope("editor", editor_id=editor), medians, values, used, HIDDEN_CONTEXT)
        _rates(ctx, result, "workload.overload_pattern", mine, Scope("editor", editor_id=editor), medians, values, used, HIDDEN_CONTEXT)
    return result


def workload_model(ctx: RunContext) -> dict[str, Any]:
    """The documented workload model and each Editor's distribution (Task 22), published in the document."""
    medians = editor_medians(ctx.facts.attributed)
    return {"definition": ("concurrent workload at start = the same Editor's other attributed completed first cycles whose [first In Progress, first Ready "
                           "For Approval) interval contains this project's first In Progress (lower bound)"),
            "band_rule": ctx.policy.parameters["workload.band_rule"].to_dict(),
            "editors": [{"editor_id": editor, "display_name": ctx.name(editor), "median": medians.get(editor),
                         "distribution": distribution(p.concurrency_at_start for p in ctx.facts.attributed if p.editor_id == editor and p.concurrency_at_start is not None)}
                        for editor in ctx.facts.editors()],
            "capacity_classification": {"value": None, "availability": "rule_not_approved", "reason": "No capacity threshold is approved (D33, HANDOFF §21)."}}


DETECTORS = [
    Detector("workload.association", VERSION, "22, 23, 24, 25", "Team-wide association between concurrent workload (relative to each Editor's own median) and "
             "execution time (within Editor x exact Video Type), late rate and scored Negative label rate", ("concurrent_workload_history", "editor_execution_interval",
             "video_type", "deadline_result", "performance_labels"), PARAMS,
             "both bands >= evidence.minimum_group_projects; rate outcomes >= evidence.minimum_outcome_events",
             "one association finding per measurement with both bands, strata and agreement", "bands vs minimums; replication = strata / Video Types agreeing",
             (cm.ASSOCIATION_NOT_CAUSE, cm.WORKLOAD_LOWER_BOUND), run_team),
    Detector("workload.overload_pattern", VERSION, "26", "Inside one Editor's work: repeated combination of higher concurrency (above their own median) and "
             "longer execution, a higher late rate or more Negative labels", ("concurrent_workload_history", "editor_execution_interval", "video_type",
             "deadline_result", "performance_labels"), PARAMS, "both bands >= evidence.minimum_group_projects inside the Editor's work",
             "one association finding per Editor and measurement", "bands vs minimums; replication = strata / Video Types agreeing",
             (cm.ASSOCIATION_NOT_CAUSE, cm.WORKLOAD_LOWER_BOUND), run_editor),
]
