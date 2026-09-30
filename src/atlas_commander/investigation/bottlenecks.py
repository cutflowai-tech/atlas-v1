"""Where project time is spent, and whether lateness begins before or after the Editor's interval (Tasks 14-17).

The Editor's interval stays exactly ``first In Progress -> first Ready For Approval`` (Task 15, D2). Everything before it
(creation, assignment, waiting) and after it (review, delivery) is measured separately and is never attributed to the
Editor. Stage owners are named as *stages*, never as people: most card moves come from the shared Waset Co account.

- ``workflow.time_map``: median elapsed time of each phase (pre-editor, editor execution, review wait, submission to
  delivery), from valid timelines only; open visits and visits containing an unknown status are excluded and counted.
- ``bottleneck.pre_editor_runway``: late projects that entered In Progress with less runway (Requested ETA - first In
  Progress) than the other Editors' typical execution time for the same exact Video Type; the association between short
  runway and lateness is reported with both groups.
- ``bottleneck.post_editor``: projects submitted for approval on or before the Requested ETA that reached delivery after it.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from typing import Any

from atlas_commander.cycles import parse_time
from atlas_commander.investigation import common as cm
from atlas_commander.investigation.baselines import COMPARISON, CURRENT, in_period
from atlas_commander.investigation.confidence import assess
from atlas_commander.investigation.context import Detector, DetectorResult, RunContext, uses
from atlas_commander.investigation.facts import ProjectFact
from atlas_commander.investigation.models import (
    ADVERSE,
    ASSOCIATION,
    FACT,
    HIDDEN_CONTEXT,
    HYPOTHESIS,
    INTERPRETATION,
    METRIC,
    NEUTRAL,
    PATTERN,
    SYSTEM_PATTERN,
    Finding,
    Scope,
    Statement,
)
from atlas_commander.investigation.policy import INSUFFICIENT_OUTCOMES, INSUFFICIENT_SAMPLE, NO_EFFECT
from atlas_commander.investigation.stats import distribution, exact, shown

VERSION = "bottlenecks-v1.0"
TIMING_INVALID = frozenset({"UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW", "NON_POSITIVE_DURATION"})


def _timing_valid(project: ProjectFact) -> bool:
    return not TIMING_INVALID & set(project.exclusions)


def run_time_map(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, "evidence.minimum_group_projects")
    minimum = values["evidence.minimum_group_projects"]
    result = DetectorResult()
    projects = [project for project in ctx.facts.projects if _timing_valid(project)]
    phases: dict[str, list[tuple[ProjectFact, int]]] = {"pre_editor": [], "editor_execution": [], "review_wait": [], "submission_to_delivery": []}
    for project in projects:
        if project.created_at and project.created_at <= project.in_progress_at:
            phases["pre_editor"].append((project, cm_seconds(project.created_at, project.in_progress_at)))
        phases["editor_execution"].append((project, project.duration_seconds))
        if project.review_wait_seconds is not None:
            phases["review_wait"].append((project, project.review_wait_seconds))
        if project.delivered_at:
            phases["submission_to_delivery"].append((project, cm_seconds(project.ready_for_approval_at, project.delivered_at)))
    summary = {name: distribution(value for _, value in rows) for name, rows in phases.items()}
    small = sorted(name for name, rows in phases.items() if len(rows) < minimum)
    if small:
        result.skip("workflow.time_map", Scope("team"), [INSUFFICIENT_SAMPLE], {"phases": summary, "below_minimum": small}, ("evidence.minimum_group_projects",))
        return result
    timelines = ctx.facts.timelines.values()
    excluded = {"projects_with_unknown_status_in_cycle": sum(not _timing_valid(project) for project in ctx.facts.projects),
                "stage_visits_with_unknown_status": sum(visit.invalid_reason == "unknown_or_cleared_status_within_visit" for t in timelines for visit in t.visits),
                "open_visits_right_censored": sum(visit.invalid_reason == "open_visit_right_censored" for t in timelines for visit in t.visits)}
    largest = max(summary, key=lambda name: (summary[name]["median"] or 0, name))
    params: dict[str, Any] = {"phases": {name: {"n": value["n"], "median_hours": cm.hours(value["median"]), "p75_hours": cm.hours(value["p75"])} for name, value in summary.items()},
              "largest_median_phase": largest, "excluded": excluded}
    records = [project.record("duration_seconds", "review_wait_seconds", "delivered_at", extra={"created_at": project.created_at})
               for project in projects]
    evidence = ctx.evidence("supporting", "phase_durations",
                            ("pre_editor = first In Progress - item creation (create_pulse); editor_execution = first Ready For Approval - first In Progress "
                             "(D2); review_wait = time in the first Ready For Approval before the next status; submission_to_delivery = first Sent/Done "
                             "after first Ready For Approval - first Ready For Approval. Medians of elapsed clock time; invalid timelines excluded"),
                            {name: len(rows) for name, rows in phases.items()}, records, columns=("status",), comparison=dict(params["phases"]),
                            time_window=ctx.history_window, exclusions=[excluded])
    finding = Finding("workflow.time_map", VERSION, SYSTEM_PATTERN, NEUTRAL, Scope("stage", stage="end_to_end"),
                      [Statement(METRIC, "phase_time_medians", params), Statement(PATTERN, "largest_median_phase", params)],
                      [evidence], used, ctx.history_window,
                      [cm.ELAPSED_TIME, cm.NO_PERSON_FOR_STAGE, cm.INGEST_WINDOW],
                      Statement(INTERPRETATION, "significance_time_map", params), [Statement(HYPOTHESIS, "investigate_largest_phase", params)],
                      key={"phases": sorted(phases)}, magnitude=float(summary[largest]["median"] or 0))
    finding.confidence = assess(ctx.policy, groups={name: (len(rows), minimum) for name, rows in phases.items()},
                                completeness=(len(phases["pre_editor"]), len(projects)), projects=len(projects))
    result.add(finding)
    return result


def cm_seconds(start: str, end: str) -> int:
    return int((parse_time(end) - parse_time(start)).total_seconds())


def _runway_groups(ctx: RunContext, projects: Sequence[ProjectFact]) -> tuple[list[ProjectFact], list[ProjectFact], list[ProjectFact]]:
    """(short-runway, adequate-runway, not-assessable) among deadline-classifiable projects."""
    short: list[ProjectFact] = []
    adequate: list[ProjectFact] = []
    unknown: list[ProjectFact] = []
    for project in projects:
        flag = cm.short_runway(project, ctx.baselines)
        (short if flag else adequate if flag is False else unknown).append(project)
    return short, adequate, unknown


def run_pre_editor(ctx: RunContext) -> DetectorResult:
    names = ("runway.short_rule", "evidence.minimum_group_projects", "evidence.minimum_outcome_events", "evidence.material_rate_difference")
    values, used = uses(ctx, *names)
    result = DetectorResult()
    minimum, minimum_outcomes = values["evidence.minimum_group_projects"], values["evidence.minimum_outcome_events"]
    material = exact(values["evidence.material_rate_difference"])
    classifiable = [project for project in ctx.facts.attributed if project.deadline_classifiable]
    short, adequate, unknown = _runway_groups(ctx, classifiable)
    late = [project for project in classifiable if project.late]
    short_late = [project for project in short if project.late]
    adequate_late = [project for project in adequate if project.late]
    passed = [project for project in late if project.runway_seconds is not None and project.runway_seconds <= 0]
    facts = {"deadline_classifiable": len(classifiable), "late": len(late), "short_runway": len(short), "short_runway_late": len(short_late),
             "adequate_runway": len(adequate), "adequate_runway_late": len(adequate_late), "runway_not_assessable": len(unknown),
             "late_with_eta_passed_at_start": len(passed)}
    reasons = []
    if min(len(short), len(adequate)) < minimum:
        reasons.append(INSUFFICIENT_SAMPLE)
    if len(short_late) < minimum_outcomes:
        reasons.append(INSUFFICIENT_OUTCOMES)
    short_rate = Fraction(len(short_late), len(short)) if short else None
    adequate_rate = Fraction(len(adequate_late), len(adequate)) if adequate else None
    if not reasons and (short_rate is None or adequate_rate is None or short_rate - adequate_rate < material):
        reasons.append(NO_EFFECT)
    if reasons:
        result.skip("bottleneck.pre_editor_runway", Scope("stage", stage="pre_editor"), reasons, facts, names)
        return result
    assert short_rate is not None and adequate_rate is not None
    replication = []
    for key in sorted({project.cohort_key for project in short if project.cohort_key}):
        s = [p for p in short if p.cohort_key == key]
        a = [p for p in adequate if p.cohort_key == key]
        if s and a and len(s) + len(a) >= minimum:
            replication.append({"slice": f"video_type:{key}", "holds": Fraction(sum(bool(p.late) for p in s), len(s)) > Fraction(sum(bool(p.late) for p in a), len(a)),
                                "short": len(s), "adequate": len(a)})
    for name in (CURRENT, COMPARISON):
        s = [p for p in short if in_period(p, name)]
        a = [p for p in adequate if in_period(p, name)]
        if s and a:
            replication.append({"slice": f"{name}_window", "holds": Fraction(sum(bool(p.late) for p in s), len(s)) > Fraction(sum(bool(p.late) for p in a), len(a)),
                                "short": len(s), "adequate": len(a)})
    editors_short = sorted({p.editor_id for p in short_late if p.editor_id})
    params = {**facts, "short_runway_late_rate": shown(short_rate), "adequate_runway_late_rate": shown(adequate_rate),
              "rate_difference": shown(short_rate - adequate_rate), "share_of_late_with_short_runway": shown(Fraction(len(short_late), len(late))),
              "editors_affected": len(editors_short), "video_types_affected": len({p.cohort_key for p in short_late})}
    records = [p.record("runway_seconds", "requested_eta", "deadline_result", "duration_seconds",
                        extra={"typical_execution_seconds": cm.typical_seconds(p, ctx.baselines), "eta_observed_after_start": p.eta_observed_after_start})
               for p in short_late]
    supporting = ctx.evidence("supporting", "late_projects_with_short_runway",
                              ("runway = Requested ETA in effect at first Ready For Approval (D19) - first In Progress; short when runway < the median first-pass "
                               "execution time of the other Editors in the same exact Video Type (leave-one-out, D36, valid at the D52 comparator minimums)"),
                              {"short_runway_late": len(short_late), "short_runway": len(short), "adequate_runway": len(adequate), "late": len(late)},
                              records, columns=("status", "requested_eta", "video_type", "editor"),
                              comparison={"short_runway": {"late": len(short_late), "projects": len(short), "late_rate": shown(short_rate)},
                                          "adequate_runway": {"late": len(adequate_late), "projects": len(adequate), "late_rate": shown(adequate_rate)}},
                              time_window=ctx.history_window)
    contradicting = ctx.evidence("contradicting", "late_projects_with_adequate_runway",
                                 "late projects whose runway was at or above the typical execution time: lateness these projects show is not explained by runway",
                                 {"adequate_runway_late": len(adequate_late)},
                                 [p.record("runway_seconds", "requested_eta", "deadline_result", "duration_seconds",
                                           extra={"typical_execution_seconds": cm.typical_seconds(p, ctx.baselines)}) for p in adequate_late],
                                 columns=("status", "requested_eta", "video_type", "editor"), time_window=ctx.history_window)
    statements = [Statement(FACT, "late_projects_with_short_runway", params), Statement(ASSOCIATION, "short_runway_associated_with_lateness", params)]
    if passed:
        statements.append(Statement(FACT, "eta_passed_before_work_started", params))
    statements += [Statement(INTERPRETATION, "lateness_may_begin_before_editor_execution", params),
                   Statement(HYPOTHESIS, "upstream_scheduling_or_eta_setting", params)]
    limitations = [cm.ASSOCIATION_NOT_CAUSE, cm.TYPICAL_WHOLE_HISTORY, cm.VIDEO_TYPE_ONLY, cm.ELAPSED_TIME, cm.NO_PERSON_FOR_STAGE, cm.ATTRIBUTED_ONLY]
    if any(p.eta_observed_after_start for p in short_late):
        limitations.append(cm.ETA_AFTER_START)
    finding = Finding("bottleneck.pre_editor_runway", VERSION, SYSTEM_PATTERN, ADVERSE, Scope("stage", stage="pre_editor"), statements, [supporting], used,
                      ctx.history_window, limitations, Statement(INTERPRETATION, "significance_pre_editor", params),
                      [Statement(HYPOTHESIS, "inspect_upstream_scheduling", params)], key={"population": "attributed_deadline_classifiable"},
                      contradicting_evidence=[contradicting] if adequate_late else [], magnitude=float(short_rate - adequate_rate),
                      headline_contradiction=True, persistent=all(bool(row["holds"]) for row in replication if str(row["slice"]).endswith("_window")) or None)
    finding.confidence = assess(ctx.policy, groups={"short_runway": (len(short), minimum), "adequate_runway": (len(adequate), minimum),
                                                    "short_runway_late": (len(short_late), minimum_outcomes)},
                                replication=replication, contradictions=0, completeness=(len(short) + len(adequate), len(classifiable)),
                                editors=len(editors_short), projects=len(short_late))
    result.add(finding)
    return result


def run_post_editor(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, "evidence.minimum_outcome_events", "evidence.minimum_group_projects")
    result = DetectorResult()
    minimum_outcomes, minimum = values["evidence.minimum_outcome_events"], values["evidence.minimum_group_projects"]
    submitted_in_time = [p for p in ctx.facts.attributed if p.late is False and p.delivered_at]
    delivered_late = [p for p in submitted_in_time if p.delivered_after_eta]
    labelled_late = [p for p in ctx.facts.attributed if p.late is False and any(label.label == "Late Delivery" for label in p.labels)]
    facts = {"submitted_on_or_before_eta_and_delivered": len(submitted_in_time), "delivered_after_eta": len(delivered_late),
             "late_delivery_label_on_on_time_submission": len(labelled_late)}
    reasons = []
    if len(submitted_in_time) < minimum:
        reasons.append(INSUFFICIENT_SAMPLE)
    if len(delivered_late) < minimum_outcomes:
        reasons.append(INSUFFICIENT_OUTCOMES)
    if reasons:
        result.skip("bottleneck.post_editor", Scope("stage", stage="post_editor"), reasons, facts,
                    ("evidence.minimum_outcome_events", "evidence.minimum_group_projects"))
        return result
    waits = distribution(p.review_wait_seconds for p in delivered_late if p.review_wait_seconds is not None)
    after = distribution(cm_seconds(p.ready_for_approval_at, p.delivered_at) for p in delivered_late if p.delivered_at)
    params: dict[str, Any] = {**facts, "share": shown(Fraction(len(delivered_late), len(submitted_in_time))), "median_review_wait_hours": cm.hours(waits["median"]),
              "median_submission_to_delivery_hours": cm.hours(after["median"]), "editors_affected": len({p.editor_id for p in delivered_late})}
    records = [p.record("deadline_result", "requested_eta", "delivered_at", "review_wait_seconds", label_events=True) for p in delivered_late]
    evidence = ctx.evidence("supporting", "on_time_submissions_delivered_after_eta",
                            ("projects whose first Ready For Approval was on or before the Requested ETA (deadline result early or on_time, D5/D19) and "
                             "whose first Sent/Done after it is later than that ETA"),
                            {"delivered_after_eta": len(delivered_late), "submitted_on_or_before_eta_and_delivered": len(submitted_in_time)},
                            records, columns=("status", "requested_eta", "editor"), time_window=ctx.history_window)
    context = [ctx.evidence("context", "late_delivery_label_on_on_time_submission",
                            "projects carrying the Late Delivery label although their first Ready For Approval was on or before the Requested ETA",
                            {"projects": len(labelled_late)}, [p.record("deadline_result", "labels", label_events=True) for p in labelled_late],
                            columns=("status", "labels", "requested_eta"), time_window=ctx.history_window)] if labelled_late else []
    statements = [Statement(FACT, "on_time_submissions_delivered_after_eta", params)]
    if labelled_late:
        statements.append(Statement(FACT, "late_label_on_on_time_submission", params))
    statements += [Statement(INTERPRETATION, "delay_after_editor_interval_not_editor_execution", params),
                   Statement(HYPOTHESIS, "review_or_delivery_stage_may_add_delay", params)]
    finding = Finding("bottleneck.post_editor", VERSION, HIDDEN_CONTEXT, ADVERSE, Scope("stage", stage="post_editor"), statements, [evidence], used,
                      ctx.history_window, [cm.ELAPSED_TIME, cm.NO_PERSON_FOR_STAGE, cm.LABELS_LOWER_BOUND, cm.NO_CAUSE_EVIDENCE],
                      Statement(INTERPRETATION, "significance_post_editor", params), [Statement(HYPOTHESIS, "inspect_review_and_delivery", params)],
                      key={"population": "on_time_submissions"}, context_evidence=context, magnitude=float(len(delivered_late)), headline_contradiction=bool(labelled_late))
    finding.confidence = assess(ctx.policy, groups={"on_time_submissions": (len(submitted_in_time), minimum), "delivered_after_eta": (len(delivered_late), minimum_outcomes)},
                                editors=len({p.editor_id for p in delivered_late}), projects=len(delivered_late))
    result.add(finding)
    return result


DETECTORS = [
    Detector("workflow.time_map", VERSION, "14, 15", "Where elapsed project time is spent: pre-editor, editor execution (first In Progress -> first Ready For "
             "Approval), review wait, submission to delivery", ("status_history", "editor_execution_interval", "item_creation_time", "post_editor_delivery"),
             ("evidence.minimum_group_projects",), "every phase >= evidence.minimum_group_projects valid projects",
             "one team finding with each phase's median and 75th percentile, invalid and censored visits counted",
             "each phase vs its minimum; completeness = projects with a creation time", (cm.ELAPSED_TIME, cm.NO_PERSON_FOR_STAGE), run_time_map),
    Detector("bottleneck.pre_editor_runway", VERSION, "16", "Late projects that entered editor execution with less runway than typical same-Video-Type "
             "execution, and the association between short runway and lateness", ("requested_eta", "execution_runway", "video_type", "deadline_result", "editor_identity"),
             ("runway.short_rule", "evidence.minimum_group_projects", "evidence.minimum_outcome_events", "evidence.material_rate_difference"),
             "short and adequate runway groups >= evidence.minimum_group_projects; short-runway late >= evidence.minimum_outcome_events",
             "one team finding: late projects with short runway, both groups' late rates, ETA already passed at start, contradicting late-with-adequate-runway projects",
             "groups vs minimums; replication per exact Video Type and per window", (cm.ASSOCIATION_NOT_CAUSE, cm.TYPICAL_WHOLE_HISTORY, cm.ETA_AFTER_START),
             run_pre_editor),
    Detector("bottleneck.post_editor", VERSION, "17", "Projects submitted for approval on or before the Requested ETA that were delivered after it (delay after the Editor's interval)",
             ("deadline_result", "post_editor_delivery", "performance_labels"), ("evidence.minimum_outcome_events", "evidence.minimum_group_projects"),
             "on-time submissions >= evidence.minimum_group_projects; delivered after ETA >= evidence.minimum_outcome_events",
             "one team finding with the projects, review wait and submission-to-delivery medians, and Late Delivery labels on on-time submissions",
             "groups vs minimums", (cm.NO_PERSON_FOR_STAGE, cm.LABELS_LOWER_BOUND), run_post_editor),
]
