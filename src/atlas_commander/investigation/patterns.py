"""Pattern discovery in a controlled search space (Tasks 18, 27-30, 32).

- ``pattern.shared_across_editors`` (Tasks 18, 29, 32): for each exact Video Type, the Editors with at least
  ``evidence.minimum_projects_per_editor_for_breadth`` projects both inside and outside it. The pattern is **shared** (process-wide)
  when at least ``evidence.minimum_editors_for_breadth`` of them are late more often inside the Video Type than outside it (the
  same direction) **and** those Editors are at least ``evidence.breadth_share`` (two thirds, exactly) of the qualifying Editors (D53.4). With the same qualifying Editors it is **confined** when exactly one does.
  Comparing each Editor with *themselves* controls for who they are. The measurements are late delivery and, under
  ``runway.short_rule``, short runway (a stage delay across Editors, Task 18).
- ``pattern.repeated_delay`` (Task 27): late rate in cells of Video Type x runway band and Video Type x workload band. At most
  ``patterns.maximum_combinations`` cells are tested, largest first, and the number tested is always published. A cell is
  reported only when its late rate exceeds the late rate of its own Video Type by the material difference **and** it is elevated in both halves
  of the history (split at the median first Ready For Approval), so a one-off burst is not a pattern.
- ``pattern.repeated_quality`` (Task 28): the same scored Negative label repeated in one Video Type across several Editors.
- ``pattern.time`` (Task 30): late rate by Cairo weekday of first In Progress and by period of the month (days 1-10, 11-20, 21+).
  A bucket is reported only when it is late more often than its own Video Type mix predicts (indirect standardisation) by the
  material difference, and is elevated in at least two different months.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from fractions import Fraction
from typing import Any

from atlas_commander.cycles import parse_time
from atlas_commander.intelligence import CAIRO
from atlas_commander.investigation import common as cm
from atlas_commander.investigation.confidence import assess
from atlas_commander.investigation.context import Detector, DetectorResult, RunContext, uses
from atlas_commander.investigation.facts import ProjectFact
from atlas_commander.investigation.models import (
    ADVERSE,
    EDITOR_SPECIFIC_PATTERN,
    HIDDEN_CONTEXT,
    HYPOTHESIS,
    INTERPRETATION,
    MIXED,
    PATTERN,
    SYSTEM_PATTERN,
    Finding,
    Scope,
    Statement,
)
from atlas_commander.investigation.person_system import shared_breadth
from atlas_commander.investigation.policy import INSUFFICIENT_EDITORS, INSUFFICIENT_OUTCOMES, INSUFFICIENT_SAMPLE, NO_EFFECT
from atlas_commander.investigation.stats import exact, shown
from atlas_commander.investigation.workload import band, editor_medians

VERSION = "patterns-v1.0"


def _late(project: ProjectFact) -> bool | None:
    return project.late


def run_shared(ctx: RunContext) -> DetectorResult:
    names = ("evidence.minimum_projects_per_editor_for_breadth", "evidence.minimum_editors_for_breadth", "evidence.breadth_share")
    values, used = uses(ctx, *names)
    result = DetectorResult()
    per_editor, min_editors, share = values[names[0]], values[names[1]], exact(values[names[2]])
    measures: list[tuple[str, Callable[[ProjectFact], bool | None]]] = [("late_delivery", _late)]
    runway_use = ctx.policy.use("runway.short_rule")
    if runway_use is not None:
        measures.append(("short_runway", lambda p: cm.short_runway(p, ctx.baselines) if p.deadline_classifiable else None))
    for measure, outcome in measures:
        for key in sorted({p.cohort_key for p in ctx.facts.attributed if p.cohort_key}):
            rows = shared_breadth(ctx, key, outcome, per_editor)
            elevated = [row for row in rows if row["elevated"]]
            scope = Scope("video_type", cohort_key=key)
            facts = {"measure": measure, "cohort_key": key, "qualifying_editors": len(rows), "elevated_editors": len(elevated)}
            if len(rows) < min_editors:
                result.skip("pattern.shared_across_editors", scope, [INSUFFICIENT_EDITORS], facts, names)
                continue
            shared = cm.shared_across_editors(len(elevated), len(rows), min_editors, share)
            confined = len(elevated) == 1
            if not shared and not confined:
                result.skip("pattern.shared_across_editors", scope, [NO_EFFECT], facts, names)
                continue
            projects = [p for row in rows for p in row["projects"]]
            label = cm.cohort_name(projects, key)
            params = {**facts, "cohort_label": label, "pattern": "shared" if shared else "confined",
                      "editors": [{"editor_id": row["editor_id"], "editor_name": ctx.name(row["editor_id"]), "inside": row["inside"], "outside": row["outside"],
                                   "rate_inside": shown(row["rate_inside"]), "rate_outside": shown(row["rate_outside"]), "elevated": row["elevated"]} for row in rows]}
            if confined:
                params["confined_editor_id"] = elevated[0]["editor_id"]
                params["confined_editor_name"] = ctx.name(elevated[0]["editor_id"])
            records = [p.record("deadline_result", "cohort_key", "runway_seconds", extra={"outcome": outcome(p)}) for p in projects]
            evidence = ctx.evidence("supporting", f"{measure}_inside_vs_outside_by_editor",
                                    (f"for each Editor with >= {per_editor} projects inside and outside the Video Type: {measure} rate inside vs outside it; shared "
                                     f"when >= {min_editors} Editors, and >= {share} of the qualifying Editors, are elevated inside; confined when exactly one is"),
                                    {"qualifying_editors": len(rows), "projects": len(projects)}, records,
                                    columns=("status", "requested_eta", "video_type", "editor"), comparison={"editors": params["editors"]}, time_window=ctx.history_window)
            if shared:
                statements = [Statement(PATTERN, f"{measure}_elevated_across_editors", params),
                              Statement(INTERPRETATION, "pattern_appears_process_wide", params),
                              Statement(HYPOTHESIS, "shared_workflow_or_type_factor", params)]
                category, finding_scope = SYSTEM_PATTERN, scope
            elif measure == "short_runway":
                # Runway is set upstream of the Editor: a runway pattern confined to one Editor is scheduling context about the work
                # that Editor received, never an Editor weakness.
                statements = [Statement(PATTERN, "short_runway_elevated_for_one_editor_only", params),
                              Statement(INTERPRETATION, "runway_pattern_is_upstream_context", params),
                              Statement(HYPOTHESIS, "assignment_or_scheduling_for_this_editor", params)]
                category, finding_scope = HIDDEN_CONTEXT, Scope("editor", editor_id=elevated[0]["editor_id"], cohort_key=key)
            else:
                statements = [Statement(PATTERN, f"{measure}_elevated_for_one_editor_only", params),
                              Statement(INTERPRETATION, "pattern_confined_to_one_editor", params),
                              Statement(HYPOTHESIS, "editor_specific_factor_possible", params)]
                category, finding_scope = EDITOR_SPECIFIC_PATTERN, Scope("editor", editor_id=elevated[0]["editor_id"], cohort_key=key)
            direction = ADVERSE if shared or measure != "short_runway" else MIXED
            finding = Finding("pattern.shared_across_editors", VERSION, category, direction, finding_scope, statements, [evidence], used, ctx.history_window,
                              [cm.VIDEO_TYPE_ONLY, cm.NO_CAUSE_EVIDENCE, cm.ATTRIBUTED_ONLY] + ([cm.TYPICAL_WHOLE_HISTORY] if measure == "short_runway" else []),
                              Statement(INTERPRETATION, "significance_shared" if shared else f"significance_confined_{measure}", params),
                              [Statement(HYPOTHESIS, "review_shared_workflow" if shared else f"review_confined_{measure}", params)],
                              key={"measure": measure, "cohort": key}, magnitude=float(Fraction(len(elevated), len(rows))),
                              headline_contradiction=shared)
            finding.confidence = assess(ctx.policy, groups={"qualifying_editors": (len(rows), min_editors)},
                                        replication=[{"slice": f"editor:{row['editor_id']}", "holds": row["elevated"] == shared} for row in rows],
                                        editors=len(rows), projects=len(projects))
            result.add(finding)
    return result


def _halves(projects: Sequence[ProjectFact]) -> tuple[list[ProjectFact], list[ProjectFact]]:
    ordered = sorted(projects, key=lambda p: (p.ready_for_approval_at, p.monday_item_id))
    middle = len(ordered) // 2
    return ordered[:middle], ordered[middle:]


def _late_rate(projects: Sequence[ProjectFact]) -> Fraction | None:
    return Fraction(sum(bool(p.late) for p in projects), len(projects)) if projects else None


def run_repeated_delay(ctx: RunContext) -> DetectorResult:
    names = ("runway.short_rule", "workload.band_rule", "evidence.minimum_group_projects", "evidence.minimum_outcome_events",
             "evidence.material_rate_difference", "patterns.maximum_combinations")
    values, used = uses(ctx, *names)
    result = DetectorResult()
    floor, minimum_outcomes = values["evidence.minimum_group_projects"], values["evidence.minimum_outcome_events"]
    material, cap = exact(values["evidence.material_rate_difference"]), int(values["patterns.maximum_combinations"])
    classifiable = [p for p in ctx.facts.attributed if p.deadline_classifiable]
    by_type: dict[str, list[ProjectFact]] = defaultdict(list)
    for project in classifiable:
        if project.cohort_key:
            by_type[project.cohort_key].append(project)
    medians = editor_medians(ctx.facts.attributed)
    runway = {p.monday_item_id: cm.short_runway(p, ctx.baselines) for p in classifiable}
    dimensions: dict[str, Callable[[ProjectFact], Any]] = {
        "runway": lambda p: None if runway[p.monday_item_id] is None else ("short" if runway[p.monday_item_id] else "adequate"),
        "workload": lambda p: band(p, medians),
    }
    cells: dict[tuple[str, str, Any], list[ProjectFact]] = defaultdict(list)
    for project in classifiable:
        for name, fn in dimensions.items():
            value = fn(project)
            if value is not None and project.cohort_key:
                cells[(name, project.cohort_key, value)].append(project)
    tested = sorted(cells.items(), key=lambda pair: (-len(pair[1]), str(pair[0])))[:cap]
    early, late_half = _halves(classifiable)
    for (dimension, key, value), members in tested:
        # The reference is the same exact Video Type (every project of that type), never the pooled rate of all types: a cell must be
        # late materially more often than its own Video Type, overall and in both halves of the history.
        overall = _late_rate(by_type[key])
        rate = _late_rate(members)
        late_count = sum(bool(p.late) for p in members)
        scope = Scope("video_type", cohort_key=key)
        facts = {"dimension": dimension, "cohort_key": key, "value": value, "projects": len(members), "late": late_count, "late_rate": shown(rate),
                 "overall_late_rate": shown(overall), "video_type_projects": len(by_type[key]), "cells_tested": len(tested)}
        if len(members) < floor or late_count < minimum_outcomes:
            result.skip("pattern.repeated_delay", scope, [INSUFFICIENT_SAMPLE if len(members) < floor else INSUFFICIENT_OUTCOMES], facts, names)
            continue
        assert rate is not None and overall is not None
        halves = []
        for half_name, half in (("earlier_half", early), ("later_half", late_half)):
            ids = {p.monday_item_id for p in half}
            in_cell = [p for p in members if p.monday_item_id in ids]
            half_rate, cell_rate = _late_rate([p for p in by_type[key] if p.monday_item_id in ids]), _late_rate(in_cell)
            halves.append({"slice": half_name, "holds": bool(in_cell and half_rate is not None and cell_rate is not None and cell_rate > half_rate),
                           "projects": len(in_cell)})
        if rate - overall < material or not all(row["holds"] for row in halves):
            result.skip("pattern.repeated_delay", scope, [NO_EFFECT], {**facts, "halves": halves}, names)
            continue
        params = {**facts, "cohort_label": cm.cohort_name(members, key), "difference": shown(rate - overall), "editors": len({p.editor_id for p in members})}
        records = [p.record("deadline_result", "runway_seconds", "concurrency_at_start", extra={dimension: value}) for p in members]
        evidence = ctx.evidence("supporting", f"late_rate_{dimension}_cell", f"late rate of projects in Video Type {key} with {dimension} = {value}, against the late rate of every project of "
                                "the same Video Type; elevated in both halves of the history", {"projects": len(members), "late": late_count}, records,
                                columns=("status", "requested_eta", "video_type", "editor"), comparison={"cell": shown(rate), "video_type": shown(overall), "halves": halves},
                                time_window=ctx.history_window)
        finding = Finding("pattern.repeated_delay", VERSION, SYSTEM_PATTERN, ADVERSE, scope,
                          [Statement(PATTERN, "repeated_delay_combination", params), Statement(INTERPRETATION, "combination_repeats_over_time", params),
                           Statement(HYPOTHESIS, "combination_may_mark_process_risk", params)], [evidence], used, ctx.history_window,
                          [cm.MULTIPLE_COMPARISONS, cm.ASSOCIATION_NOT_CAUSE, cm.VIDEO_TYPE_ONLY, cm.TYPICAL_WHOLE_HISTORY, cm.WORKLOAD_LOWER_BOUND],
                          Statement(INTERPRETATION, "significance_repeated_delay", params), [Statement(HYPOTHESIS, "review_combination", params)],
                          key={"dimension": dimension, "cohort": key, "value": value}, magnitude=float(rate - overall), persistent=True)
        finding.confidence = assess(ctx.policy, groups={"cell": (len(members), floor), "late": (late_count, minimum_outcomes)}, replication=halves,
                                    editors=params["editors"], projects=len(members))
        result.add(finding)
    return result


def run_repeated_quality(ctx: RunContext) -> DetectorResult:
    names = ("evidence.minimum_outcome_events", "evidence.minimum_editors_for_breadth")
    values, used = uses(ctx, *names)
    result = DetectorResult()
    minimum_outcomes, min_editors = values[names[0]], values[names[1]]
    cells: dict[tuple[str, str], list[ProjectFact]] = defaultdict(list)
    for project in ctx.facts.attributed:
        for occurrence in project.negative_scored:
            if project.cohort_key:
                cells[(occurrence.label, project.cohort_key)].append(project)
    for (label, key), members in sorted(cells.items()):
        editors = sorted({p.editor_id for p in members if p.editor_id})
        scope = Scope("video_type", cohort_key=key)
        facts = {"label": label, "cohort_key": key, "occurrences": len(members), "editors": len(editors)}
        if len(members) < minimum_outcomes:
            result.skip("pattern.repeated_quality", scope, [INSUFFICIENT_OUTCOMES], facts, names)
            continue
        if len(editors) < min_editors:
            result.skip("pattern.repeated_quality", scope, [INSUFFICIENT_EDITORS], facts, names)
            continue
        type_projects = [p for p in ctx.facts.attributed if p.cohort_key == key]
        params = {**facts, "cohort_label": cm.cohort_name(members, key), "type_projects": len(type_projects),
                  "editor_names": [ctx.name(editor) for editor in editors]}
        evidence = ctx.evidence("supporting", "repeated_label_in_video_type", "occurrences of one scored Negative label on projects of one exact Video Type, by Editor",
                                {"occurrences": len(members), "editors": len(editors)}, [p.record("negative_scored", label_events=True) for p in members],
                                columns=("status", "labels", "video_type", "editor"), time_window=ctx.history_window)
        finding = Finding("pattern.repeated_quality", VERSION, SYSTEM_PATTERN, ADVERSE, scope,
                          [Statement(PATTERN, "same_label_repeats_across_editors", params), Statement(INTERPRETATION, "label_pattern_not_one_editor", params),
                           Statement(HYPOTHESIS, "type_brief_or_process_may_drive_label", params)], [evidence], used, ctx.history_window,
                          [cm.LABELS_LOWER_BOUND, cm.VIDEO_TYPE_ONLY, cm.NO_CAUSE_EVIDENCE], Statement(INTERPRETATION, "significance_repeated_quality", params),
                          [Statement(HYPOTHESIS, "review_label_in_type", params)], key={"label": label, "cohort": key}, magnitude=float(len(members)))
        finding.confidence = assess(ctx.policy, groups={"occurrences": (len(members), minimum_outcomes), "editors": (len(editors), min_editors)},
                                    editors=len(editors), projects=len(members))
        result.add(finding)
    return result


def _period_of_month(project: ProjectFact) -> str:
    day = int(project.cairo_date[8:10])
    return "days_01_10" if day <= 10 else "days_11_20" if day <= 20 else "days_21_end"


def _start_weekday(project: ProjectFact) -> str:
    return parse_time(project.in_progress_at).astimezone(CAIRO).strftime("%A")


def run_time(ctx: RunContext) -> DetectorResult:
    names = ("evidence.minimum_group_projects", "evidence.minimum_outcome_events", "evidence.material_rate_difference")
    values, used = uses(ctx, *names)
    result = DetectorResult()
    floor, minimum_outcomes, material = values[names[0]], values[names[1]], exact(values[names[2]])
    classifiable = [p for p in ctx.facts.attributed if p.deadline_classifiable and p.cohort_key]
    # Mix-fair reference (indirect standardisation): a bucket's expected late rate is the mean of its projects' own Video Type late
    # rates, so a weekday that simply receives more of a slow Video Type is not reported as a timing pattern.
    type_rate: dict[str, Fraction] = {}
    for key in {p.cohort_key for p in classifiable if p.cohort_key}:
        rows = [p for p in classifiable if p.cohort_key == key]
        type_rate[key] = Fraction(sum(bool(p.late) for p in rows), len(rows))

    def expected(rows: Sequence[ProjectFact]) -> Fraction | None:
        return sum((type_rate[p.cohort_key or ""] for p in rows), Fraction(0)) / len(rows) if rows else None

    for dimension, fn in (("start_weekday", _start_weekday), ("period_of_month", _period_of_month)):
        buckets: dict[str, list[ProjectFact]] = defaultdict(list)
        for project in classifiable:
            buckets[fn(project)].append(project)
        for value, members in sorted(buckets.items()):
            rate = _late_rate(members)
            overall = expected(members)
            late = sum(bool(p.late) for p in members)
            facts = {"dimension": dimension, "value": value, "projects": len(members), "late": late, "late_rate": shown(rate), "overall_late_rate": shown(overall)}
            if len(members) < floor or late < minimum_outcomes:
                result.skip("pattern.time", Scope("team"), [INSUFFICIENT_SAMPLE if len(members) < floor else INSUFFICIENT_OUTCOMES], facts, names)
                continue
            assert rate is not None and overall is not None
            months = []
            for month in sorted({p.cairo_month for p in members}):
                bucket = [p for p in members if p.cairo_month == month]
                month_rate, bucket_rate = expected(bucket), _late_rate(bucket)
                if len(bucket) >= 2 and month_rate is not None and bucket_rate is not None:
                    months.append({"slice": f"month:{month}", "holds": bucket_rate > month_rate, "projects": len(bucket)})
            if rate - overall < material or sum(bool(row["holds"]) for row in months) < 2:
                result.skip("pattern.time", Scope("team"), [NO_EFFECT], {**facts, "months_elevated": sum(bool(row["holds"]) for row in months)}, names)
                continue
            params = {**facts, "difference": shown(rate - overall), "months_elevated": sum(bool(row["holds"]) for row in months), "months_tested": len(months)}
            evidence = ctx.evidence("supporting", f"late_rate_by_{dimension}", f"late rate of projects with {dimension} = {value} against the rate their own Video Types "
                                    "predict (mix-adjusted), overall and in each Cairo month", {"projects": len(members), "late": late},
                                    [p.record("deadline_result", extra={dimension: value}) for p in members], columns=("status", "requested_eta"),
                                    comparison={"bucket": shown(rate), "expected_from_video_type_mix": shown(overall), "months": months}, time_window=ctx.history_window)
            finding = Finding("pattern.time", VERSION, SYSTEM_PATTERN, ADVERSE, Scope("team"),
                              [Statement(PATTERN, "time_bucket_elevated", params), Statement(INTERPRETATION, "timing_pattern_repeats", params),
                               Statement(HYPOTHESIS, "timing_may_reflect_scheduling", params)], [evidence], used, ctx.history_window,
                              [cm.ASSOCIATION_NOT_CAUSE, cm.MULTIPLE_COMPARISONS, cm.NO_CAUSE_EVIDENCE], Statement(INTERPRETATION, "significance_time_pattern", params),
                              [Statement(HYPOTHESIS, "review_timing", params)], key={"dimension": dimension, "value": value}, magnitude=float(rate - overall),
                              persistent=True)
            finding.confidence = assess(ctx.policy, groups={"bucket": (len(members), floor)}, replication=months, projects=len(members),
                                        editors=len({p.editor_id for p in members}))
            result.add(finding)
    return result


DETECTORS = [
    Detector("pattern.shared_across_editors", VERSION, "18, 29, 32", "Whether elevated lateness (or short runway) in a Video Type appears across several Editors "
             "(process-wide) or in one Editor only, comparing each Editor with themselves inside vs outside the Video Type",
             ("editor_identity", "video_type", "deadline_result", "execution_runway"),
             ("evidence.minimum_projects_per_editor_for_breadth", "evidence.minimum_editors_for_breadth", "evidence.breadth_share"),
             "qualifying Editors (>= minimum projects inside and outside) >= evidence.minimum_editors_for_breadth",
             "system pattern (shared) or editor-specific pattern (confined), with every qualifying Editor's two rates",
             "qualifying Editors vs minimum; replication = each Editor agreeing with the conclusion", (cm.VIDEO_TYPE_ONLY, cm.NO_CAUSE_EVIDENCE), run_shared),
    Detector("pattern.repeated_delay", VERSION, "27", "Repeated combinations (Video Type x runway band, Video Type x workload band) with elevated lateness in both halves "
             "of the history", ("video_type", "execution_runway", "concurrent_workload_history", "deadline_result"),
             ("runway.short_rule", "workload.band_rule", "evidence.minimum_group_projects", "evidence.minimum_outcome_events", "evidence.material_rate_difference",
              "patterns.maximum_combinations"), "cell >= evidence.minimum_group_projects and late >= evidence.minimum_outcome_events",
             "one finding per repeated combination; cells tested published", "cell vs minimums; replication = both halves of history",
             (cm.MULTIPLE_COMPARISONS, cm.ASSOCIATION_NOT_CAUSE), run_repeated_delay),
    Detector("pattern.repeated_quality", VERSION, "28", "The same scored Negative label repeated in one Video Type across several Editors",
             ("performance_labels", "video_type", "editor_identity"), ("evidence.minimum_outcome_events", "evidence.minimum_editors_for_breadth"),
             "occurrences >= evidence.minimum_outcome_events across >= evidence.minimum_editors_for_breadth Editors", "one finding per repeated label and Video Type",
             "occurrences and Editors vs minimums", (cm.LABELS_LOWER_BOUND,), run_repeated_quality),
    Detector("pattern.time", VERSION, "30", "Late rate by Cairo weekday of first In Progress and by period of the month, reported only when it repeats in >= 2 months",
             ("deadline_result", "status_history"), ("evidence.minimum_group_projects", "evidence.minimum_outcome_events", "evidence.material_rate_difference"),
             "bucket >= evidence.minimum_group_projects with >= evidence.minimum_outcome_events late", "one finding per repeated timing bucket",
             "bucket vs minimum; replication = months where the bucket is elevated", (cm.MULTIPLE_COMPARISONS, cm.ASSOCIATION_NOT_CAUSE), run_time),
]
