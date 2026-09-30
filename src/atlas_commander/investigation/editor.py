"""Editor intelligence: evidence-based strength and weakness patterns and fairness context (Tasks 52-55).

- ``editor.speed_pattern``: the approved per-Video-Type Speed verdicts (D38, D52; current window, leave-one-out) grouped into
  one strength (Faster) and one weakness (Slower) finding per Editor, with the comparator behind each. This runs in
  ``approved_only`` mode.
- ``editor.label_pattern``: where the Editor's labels sit. For example, "20 of 26 Negative signals are Late Delivery", so the
  negative evidence is concentrated in deadline performance rather than broad quality. Positive labels are treated the same
  way. Counts only (``evidence.minimum_outcome_events``); no personality or psychological wording, ever.

Self-baseline change (Task 52) is ``change.editor``. The fairness context (Task 55) is not a finding. It is a per-Editor block,
built by ``fairness_context``, that sits beside every Editor finding: project mix against the team, sample, workload, runway,
comparator strength and coverage.
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from typing import Any

from atlas_commander.investigation import common as cm
from atlas_commander.investigation.baselines import CURRENT, in_period
from atlas_commander.investigation.confidence import assess
from atlas_commander.investigation.context import Detector, DetectorResult, RunContext, uses
from atlas_commander.investigation.models import (
    ADVERSE,
    EDITOR_SPECIFIC_PATTERN,
    FAVOURABLE,
    HYPOTHESIS,
    INTERPRETATION,
    METRIC,
    PATTERN,
    Finding,
    Scope,
    Statement,
)
from atlas_commander.investigation.policy import INSUFFICIENT_OUTCOMES
from atlas_commander.investigation.stats import median, shown
from atlas_commander.investigation.workload import editor_medians

VERSION = "editor-v1.0"


def run_speed(ctx: RunContext) -> DetectorResult:
    _, used = uses(ctx, "speed.minimum_editor_projects", "speed.minimum_comparator_projects", "speed.minimum_comparator_editors",
                   "speed.faster_band_pct", "speed.slower_band_pct")
    result = DetectorResult()
    for editor, profile in sorted(ctx.profiles.items()):
        rows = profile["speed"]["cohorts"]
        for verdict, direction in (("faster", FAVOURABLE), ("slower", ADVERSE)):
            selected = [row for row in rows if row.get("verdict") == verdict]
            if not selected:
                continue
            params = {"editor_id": editor, "editor_name": ctx.name(editor), "verdict": verdict, "window": profile["speed"]["window"],
                      "video_types": [{"cohort_key": row["cohort_key"], "labels": row["cohort_labels"], "editor_projects": row["editor_sample_size"],
                                       "editor_median_hours": cm.hours(row["editor_median_seconds"]), "comparator_projects": row["team_sample_size"],
                                       "comparator_editors": row["team_editor_count"], "comparator_median_hours": cm.hours(row["team_median_seconds"]),
                                       "pct": row["editor_vs_team_median_pct"]} for row in selected],
                      "projects": sum(row["editor_sample_size"] for row in selected), "component_state": profile["speed"]["component"]["state"]}
            evidence = [ctx.evidence("supporting", f"speed_{row['cohort_key']}", "approved Speed comparison (D36 leave-one-out median, D52 minimums and bands) "
                                     "for one exact Video Type in the current window", {"editor": row["editor_sample_size"], "comparator": row["team_sample_size"]},
                                     cm.records_from_block(row["evidence"]), columns=("status", "video_type", "editor"),
                                     comparison={"editor_median_seconds": row["editor_median_seconds"], "comparator_median_seconds": row["team_median_seconds"],
                                                 "pct": row["editor_vs_team_median_pct"], "verdict": verdict}, time_window=profile["speed"]["window"])
                        for row in selected]
            statements = [Statement(METRIC, f"speed_{verdict}_than_comparable_team", params),
                          Statement(INTERPRETATION, "speed_pattern_within_video_type", params)]
            if direction == ADVERSE:
                statements.append(Statement(HYPOTHESIS, "check_context_before_speed_conclusion", params))
            finding = Finding("editor.speed_pattern", VERSION, EDITOR_SPECIFIC_PATTERN, direction, Scope("editor", editor_id=editor), statements, evidence, used,
                              profile["speed"]["window"], [cm.ELAPSED_TIME, cm.VIDEO_TYPE_ONLY, cm.WORKLOAD_LOWER_BOUND],
                              Statement(INTERPRETATION, f"significance_speed_{verdict}", params),
                              [Statement(HYPOTHESIS, "review_speed_context" if direction == ADVERSE else "recognise_evidence", params)],
                              key={"verdict": verdict}, magnitude=float(params["projects"]))
            finding.confidence = assess(ctx.policy, groups={row["cohort_key"]: (row["editor_sample_size"], ctx.policy.value("speed.minimum_editor_projects"))
                                                            for row in selected},
                                        replication=[{"slice": f"video_type:{row['cohort_key']}", "holds": True} for row in selected[1:]],
                                        projects=params["projects"], editors=1)
            result.add(finding)
    return result


def run_labels(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, "evidence.minimum_outcome_events")
    minimum = values["evidence.minimum_outcome_events"]
    result = DetectorResult()
    for editor in ctx.facts.editors():
        mine = [p for p in ctx.facts.attributed if p.editor_id == editor]
        for label_class, direction in (("Negative", ADVERSE), ("Positive", FAVOURABLE)):
            occurrences = [(p, label) for p in mine for label in p.labels if label.label_class == label_class]
            scope = Scope("editor", editor_id=editor)
            counts = Counter(label.label for _, label in occurrences)
            facts = {"label_class": label_class, "occurrences": len(occurrences), "labels": dict(sorted(counts.items()))}
            if len(occurrences) < minimum:
                result.skip("editor.label_pattern", scope, [INSUFFICIENT_OUTCOMES], facts, ("evidence.minimum_outcome_events",))
                continue
            top, top_count = min(counts.items(), key=lambda pair: (-pair[1], pair[0]))
            projects = sorted({p.monday_item_id for p, _ in occurrences})
            params = {**facts, "editor_id": editor, "editor_name": ctx.name(editor), "top_label": top, "top_count": top_count,
                      "top_share": shown(Fraction(top_count, len(occurrences))), "projects": len(projects), "completed_projects": len(mine),
                      "deadline_label": top in ("Late Delivery", "On Time Delivery")}
            records = [p.record("labels", "deadline_result", label_events=True) for p in mine if p.monday_item_id in projects]
            evidence = ctx.evidence("supporting", f"{label_class.lower()}_labels", f"every {label_class} label occurrence on the Editor's projects (visible taxonomy, D26-D30)",
                                    {"occurrences": len(occurrences), "projects": len(projects)}, records, columns=("status", "labels", "bonus", "editor"),
                                    comparison={"by_label": facts["labels"]}, time_window=ctx.history_window)
            code = "negative_signals_concentrated_in_deadline" if label_class == "Negative" and params["deadline_label"] else f"{label_class.lower()}_label_distribution"
            statements = [Statement(PATTERN, code, params), Statement(INTERPRETATION, f"{label_class.lower()}_label_pattern_meaning", params)]
            if label_class == "Negative":
                statements.append(Statement(HYPOTHESIS, "check_label_pattern_by_type_and_workload", params))
            finding = Finding("editor.label_pattern", VERSION, EDITOR_SPECIFIC_PATTERN, direction, scope, statements, [evidence], used, ctx.history_window,
                              [cm.LABELS_LOWER_BOUND, cm.NO_CAUSE_EVIDENCE], Statement(INTERPRETATION, f"significance_{label_class.lower()}_labels", params),
                              [Statement(HYPOTHESIS, "review_label_pattern" if direction == ADVERSE else "recognise_evidence", params)],
                              key={"label_class": label_class}, magnitude=float(top_count))
            finding.confidence = assess(ctx.policy, groups={"occurrences": (len(occurrences), minimum)}, projects=len(projects), editors=1)
            result.add(finding)
    return result


def fairness_context(ctx: RunContext, editor: str) -> dict[str, Any]:
    """Context that changes how any finding about this Editor should be read (Task 55). Facts only, never a judgement."""
    mine = [p for p in ctx.facts.attributed if p.editor_id == editor]
    team = ctx.facts.attributed
    mix = Counter(p.cohort_key for p in mine if p.cohort_key)
    team_mix = Counter(p.cohort_key for p in team if p.cohort_key)
    medians = editor_medians(team)
    team_median = median(p.concurrency_at_start for p in team if p.concurrency_at_start is not None)
    profile = ctx.profiles.get(editor) or {}
    weak = [row["cohort_key"] for row in (profile.get("speed") or {}).get("cohorts", []) if row.get("comparison_status") not in ("comparable", None)]
    runway: dict[str, Any] | None = None
    if ctx.policy.use("runway.short_rule") is not None:
        late = [p for p in mine if p.late]
        short = [p for p in late if cm.short_runway(p, ctx.baselines)]
        runway = {"late": len(late), "late_with_short_runway": len(short)}
    return {
        "editor_id": editor,
        "sample": {"completed_projects": len(mine), "current_window_projects": sum(in_period(p, CURRENT) for p in mine),
                   "deadline_classifiable": sum(p.deadline_classifiable for p in mine), "speed_measurable": sum(p.speed_measurable for p in mine)},
        "project_mix": [{"cohort_key": key, "labels": cm.cohort_name(mine, key), "projects": count, "share": shown(Fraction(count, len(mine))),
                         "team_share": shown(Fraction(team_mix[key], len(team))) if team else None}
                        for key, count in sorted(mix.items(), key=lambda pair: (-pair[1], pair[0]))],
        "workload": {"median_concurrency": medians.get(editor), "team_median_concurrency": team_median},
        "runway": runway,
        "weak_comparison_video_types": sorted(weak),
        "eta_observed_after_start": sum(p.eta_observed_after_start for p in mine),
        "note": "Context only. None of these facts is a judgement of the Editor; each can change how a finding should be read.",
    }


DETECTORS = [
    Detector("editor.speed_pattern", VERSION, "53, 54", "The approved per-Video-Type Speed verdicts (Faster / Slower, current window) as one strength and one "
             "weakness finding per Editor, with each comparator", ("editor_execution_interval", "video_type", "editor_identity"),
             ("speed.minimum_editor_projects", "speed.minimum_comparator_projects", "speed.minimum_comparator_editors", "speed.faster_band_pct", "speed.slower_band_pct"),
             "the approved D52 Speed minimums (5 Editor / 10 comparator projects / 2 comparator Editors)",
             "editor-specific pattern (favourable or adverse) listing each Video Type's comparison", "per Video Type sample vs approved minimum; replication = several Video Types",
             (cm.ELAPSED_TIME, cm.VIDEO_TYPE_ONLY), run_speed),
    Detector("editor.label_pattern", VERSION, "54, 53", "Where an Editor's Negative and Positive labels sit (top label and its share), e.g. negative evidence concentrated "
             "in Late Delivery rather than broad quality", ("performance_labels", "editor_identity"), ("evidence.minimum_outcome_events",),
             "label occurrences >= evidence.minimum_outcome_events", "editor-specific pattern with the label distribution", "occurrences vs minimum",
             (cm.LABELS_LOWER_BOUND,), run_labels),
]
