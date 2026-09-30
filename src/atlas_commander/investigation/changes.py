"""Change against a baseline: an Editor against their own history, the team, and each Video Type (Tasks 19-21, 52).

Periods are the contract's Cairo windows (D24): ``current`` (last 30 completed days) against ``comparison`` (the 30 days
before) and against ``history`` (every completed project before the current window). Execution time is compared only inside
one exact Video Type. A change is material only at the (unapproved) ``evidence.material_rate_difference`` /
``evidence.material_duration_pct``. These are the same management question as the still-OPEN Trend materiality (D52), so in
``approved_only`` mode no change is classified. Otherwise the result is ``improving`` or ``deteriorating``, and a
non-material difference is recorded as examined without a finding (ordinary noise is never a finding).

An Editor's change is always set beside the rest of the team's change over the same periods. When the others moved the same way
by a material amount, that is published as contradicting evidence: the change is then less likely to be specific to the Editor.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from fractions import Fraction
from typing import Any

from atlas_commander.investigation import common as cm
from atlas_commander.investigation.baselines import COMPARISON, CURRENT, HISTORY, in_period
from atlas_commander.investigation.confidence import assess
from atlas_commander.investigation.context import Detector, DetectorResult, RunContext, uses
from atlas_commander.investigation.facts import ProjectFact
from atlas_commander.investigation.models import (
    ADVERSE,
    FAVOURABLE,
    HIDDEN_CONTEXT,
    HYPOTHESIS,
    IMPORTANT_IMPROVEMENT,
    INTERPRETATION,
    METRIC,
    NEEDS_ATTENTION,
    PATTERN,
    Evidence,
    Finding,
    Scope,
    Statement,
)
from atlas_commander.investigation.policy import INSUFFICIENT_RECENT_WINDOW, INSUFFICIENT_SAMPLE, NO_EFFECT, ParameterUse
from atlas_commander.investigation.stats import exact, median, pct_change, shown

VERSION = "changes-v1.0"
IMPROVING, DETERIORATING = "improving", "deteriorating"


def _late_rate(projects: Sequence[ProjectFact]) -> tuple[Fraction | None, int]:
    rows = [project for project in projects if project.deadline_classifiable]
    return (Fraction(sum(bool(p.late) for p in rows), len(rows)) if rows else None), len(rows)


def _negative_rate(projects: Sequence[ProjectFact]) -> tuple[Fraction | None, int]:
    return (Fraction(sum(len(p.negative_scored) for p in projects), len(projects)) if projects else None), len(projects)


RATE_MEASURES: dict[str, tuple[Callable[[Sequence[ProjectFact]], tuple[Fraction | None, int]], str, tuple[str, ...]]] = {
    "late_rate": (_late_rate, "recent_change.minimum_sample", ("status", "requested_eta", "editor")),
    "negative_label_rate": (_negative_rate, "quality.minimum_projects", ("status", "labels", "editor")),
}


def _classify(difference: Fraction, material: Fraction, lower_is_better: bool = True) -> str | None:
    if abs(difference) < material:
        return None
    return IMPROVING if (difference < 0) == lower_is_better else DETERIORATING


def _change_finding(ctx: RunContext, detector: str, scope: Scope, measure: str, params: dict[str, Any], supporting: list[Evidence],
                    used: list[ParameterUse], status: str, groups: dict[str, tuple[int, int | None]], limitations: list[str],
                    contradicting: list[Evidence], replication: list[dict[str, Any]], context: list[Evidence], magnitude: float) -> Finding:
    favourable = status == IMPROVING
    statements = [Statement(METRIC, f"{measure}_changed", params), Statement(PATTERN, f"change_{status}", params)]
    mirrors_team = bool(contradicting) and scope.kind == "editor"
    no_team = scope.kind == "editor" and params.get("team_comparison_available") is False
    if mirrors_team:
        statements.append(Statement(INTERPRETATION, "team_moved_the_same_way", params))
    elif no_team:
        statements.append(Statement(INTERPRETATION, "team_comparison_unavailable", params))
    elif scope.kind == "editor":
        statements.append(Statement(INTERPRETATION, "change_differs_from_team", params))
    elif params.get("shared_across_editors"):
        statements.append(Statement(INTERPRETATION, "change_is_group_wide", params))
    else:
        statements.append(Statement(INTERPRETATION, "change_breadth_not_established", params))
    statements.append(Statement(HYPOTHESIS, "change_needs_context_before_conclusion", params))
    category = HIDDEN_CONTEXT if mirrors_team or no_team else IMPORTANT_IMPROVEMENT if favourable else NEEDS_ATTENTION
    finding = Finding(detector, VERSION, category, FAVOURABLE if favourable else ADVERSE, scope,
                      statements, supporting, used, ctx.window("current"), limitations,
                      Statement(INTERPRETATION, "significance_change", params), [Statement(HYPOTHESIS, "investigate_change", params)],
                      key={"measure": measure, "against": params["against"], "cohort": params.get("cohort_key")},
                      contradicting_evidence=contradicting, context_evidence=context, magnitude=magnitude, worsening=not favourable)
    finding.confidence = assess(ctx.policy, groups=groups, replication=replication, contradictions=len(contradicting),
                                editors=len(finding.affected_editors), projects=finding.sample_size)
    return finding


BREADTH = ("evidence.minimum_projects_per_editor_for_breadth", "evidence.minimum_editors_for_breadth", "evidence.breadth_share")


def _breadth(rows: Sequence[dict[str, Any]], values: dict[str, Any]) -> dict[str, Any]:
    same = sum(bool(row["holds"]) for row in rows)
    return {"editors_same_direction": same, "editors_with_both_periods": len(rows),
            "minimum_projects_per_editor": values["evidence.minimum_projects_per_editor_for_breadth"],
            "shared_across_editors": cm.shared_across_editors(same, len(rows), values["evidence.minimum_editors_for_breadth"], values["evidence.breadth_share"])}


def _periods(projects: Sequence[ProjectFact]) -> dict[str, list[ProjectFact]]:
    return {name: [p for p in projects if in_period(p, name)] for name in (CURRENT, COMPARISON, HISTORY)}


def run_editor(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, "evidence.material_rate_difference", "evidence.material_duration_pct", "recent_change.minimum_sample",
                        "quality.minimum_projects", "speed.minimum_editor_projects", "speed.minimum_comparator_projects", "speed.minimum_comparator_editors")
    result = DetectorResult()
    material_rate, material_pct = exact(values["evidence.material_rate_difference"]), exact(values["evidence.material_duration_pct"]) / 100
    for editor in ctx.facts.editors():
        mine = [p for p in ctx.facts.attributed if p.editor_id == editor]
        others = [p for p in ctx.facts.attributed if p.editor_id != editor]
        periods, other_periods = _periods(mine), _periods(others)
        workload = {name: median(p.concurrency_at_start for p in rows if p.concurrency_at_start is not None) for name, rows in periods.items()}
        for measure, (fn, floor_name, columns) in RATE_MEASURES.items():
            floor = values[floor_name]
            for against in (COMPARISON, HISTORY):
                now, now_n = fn(periods[CURRENT])
                then, then_n = fn(periods[against])
                facts = {"measure": measure, "against": against, "current": shown(now), "current_sample": now_n, "baseline": shown(then), "baseline_sample": then_n}
                scope = Scope("editor", editor_id=editor)
                if now_n < floor:
                    result.skip("change.editor", scope, [INSUFFICIENT_RECENT_WINDOW], facts, (floor_name,))
                    continue
                if then_n < floor or now is None or then is None:
                    result.skip("change.editor", scope, [INSUFFICIENT_SAMPLE], facts, (floor_name,))
                    continue
                status = _classify(now - then, material_rate)
                if status is None:
                    result.skip("change.editor", scope, [NO_EFFECT], facts, ("evidence.material_rate_difference",))
                    continue
                other_now, other_now_n = fn(other_periods[CURRENT])
                other_then, other_then_n = fn(other_periods[against])
                # Difference-in-differences: the change is specific to the Editor only when it differs from the other Editors' change over the
                # same periods by at least the material difference; otherwise it mirrors the team and is published as context. The team's change
                # counts only when both of its periods meet the same sample floor as the Editor's (D52/D53); otherwise it is unavailable.
                team_valid = other_now is not None and other_then is not None and min(other_now_n, other_then_n) >= floor
                team_change = other_now - other_then if team_valid and other_now is not None and other_then is not None else None
                team_same = team_change is not None and abs((now - then) - team_change) < material_rate
                params = {**facts, "editor_id": editor, "editor_name": ctx.name(editor), "difference": shown(now - then), "status": status,
                          "team_current": shown(other_now), "team_baseline": shown(other_then), "team_moved_same_way": team_same,
                          "team_difference": shown(team_change), "editor_minus_team_change": shown((now - then) - team_change) if team_change is not None else None,
                          "team_comparison_available": team_change is not None, "team_current_sample": other_now_n, "team_baseline_sample": other_then_n,
                          "material_difference": shown(material_rate),
                          "workload_median_current": workload[CURRENT], "workload_median_baseline": workload[against]}
                label_events = measure == "negative_label_rate"
                supporting = [ctx.evidence("supporting", f"{measure}_{window}", f"{measure} of the Editor's projects in the {window} period "
                                           "(late rate = late / deadline-classifiable; label rate = scored Negative occurrences / completed projects)",
                                           {"projects": len(periods[window])},
                                           [p.record("deadline_result", "negative_scored", label_events=label_events) for p in periods[window]],
                                           columns=columns, time_window=ctx.window(window) if window != HISTORY else ctx.history_window)
                              for window in (CURRENT, against)]
                contradicting = [ctx.evidence("contradicting", f"team_{measure}_moved_same_way",
                                              "the other Editors' same measure over the same periods changed by an amount within the material difference of the Editor's change",
                                              {"current_projects": len(other_periods[CURRENT]), "baseline_projects": len(other_periods[against])},
                                              [p.record("deadline_result", "negative_scored") for p in other_periods[CURRENT]], columns=columns,
                                              comparison={"current": shown(other_now), "baseline": shown(other_then)}, time_window=ctx.window("current"))] if team_same else []
                context = [ctx.evidence("context", "workload_by_period", "median of the Editor's other open projects at each project's start (lower bound)",
                                        {"current": len(periods[CURRENT]), "baseline": len(periods[against])},
                                        [p.record("concurrency_at_start") for p in periods[CURRENT]], columns=("status", "editor"),
                                        comparison={"current_median": workload[CURRENT], "baseline_median": workload[against]}, time_window=ctx.window("current"))]
                limitations = [cm.ATTRIBUTED_ONLY, cm.NO_CAUSE_EVIDENCE] + ([cm.LABELS_LOWER_BOUND] if label_events else [cm.ETA_AFTER_START])
                replication = [{"slice": "other_baseline", "holds": _other_holds(fn, periods, against, status, material_rate)}]
                result.add(_change_finding(ctx, "change.editor", scope, measure, params, supporting, used, status,
                                           {"current": (now_n, floor), "baseline": (then_n, floor)}, limitations, contradicting, replication, context,
                                           float(abs(now - then))))
        _editor_speed(ctx, result, editor, periods, other_periods, used, values["speed.minimum_editor_projects"], material_pct,
                      (values["speed.minimum_comparator_projects"], values["speed.minimum_comparator_editors"]))
    return result


def _other_holds(fn: Callable[[Sequence[ProjectFact]], tuple[Fraction | None, int]], periods: dict[str, list[ProjectFact]], against: str,
                 status: str, material: Fraction) -> bool:
    other = HISTORY if against == COMPARISON else COMPARISON
    now, _ = fn(periods[CURRENT])
    then, n = fn(periods[other])
    return bool(n and now is not None and then is not None and _classify(now - then, material) == status)


def _editor_speed(ctx: RunContext, result: DetectorResult, editor: str, periods: dict[str, list[ProjectFact]], other_periods: dict[str, list[ProjectFact]],
                  used: list[ParameterUse], floor: int, material: Fraction, comparator: tuple[int, int]) -> None:
    for key in sorted({p.cohort_key for p in periods[CURRENT] if p.speed_measurable and p.cohort_key}):
        now = [p for p in periods[CURRENT] if p.cohort_key == key and p.speed_measurable]
        then = [p for p in periods[HISTORY] if p.cohort_key == key and p.speed_measurable]
        now_median, then_median = median(p.duration_seconds for p in now), median(p.duration_seconds for p in then)
        scope = Scope("editor", editor_id=editor, cohort_key=key)
        facts = {"measure": "median_execution", "against": HISTORY, "cohort_key": key, "current_sample": len(now), "baseline_sample": len(then),
                 "current_hours": cm.hours(now_median), "baseline_hours": cm.hours(then_median)}
        if len(now) < floor or len(then) < floor:
            result.skip("change.editor", scope, [INSUFFICIENT_RECENT_WINDOW if len(now) < floor else INSUFFICIENT_SAMPLE], facts, ("speed.minimum_editor_projects",))
            continue
        change = pct_change(now_median, then_median)
        if change is None or abs(change) < material:
            result.skip("change.editor", scope, [NO_EFFECT], facts, ("evidence.material_duration_pct",))
            continue
        status = IMPROVING if change < 0 else DETERIORATING
        peers_now = [p for p in other_periods[CURRENT] if p.cohort_key == key and p.speed_measurable]
        peers_then = [p for p in other_periods[HISTORY] if p.cohort_key == key and p.speed_measurable]
        # The peers' change is a valid comparison only at the approved D52 comparator minimums in both periods.
        peers_valid = all(len(rows) >= comparator[0] and len({p.editor_id for p in rows}) >= comparator[1] for rows in (peers_now, peers_then))
        peer_change = pct_change(median(p.duration_seconds for p in peers_now), median(p.duration_seconds for p in peers_then)) if peers_valid else None
        team_same = peer_change is not None and abs(change - peer_change) < material
        workload_now = median(p.concurrency_at_start for p in now if p.concurrency_at_start is not None)
        workload_then = median(p.concurrency_at_start for p in then if p.concurrency_at_start is not None)
        params = {**facts, "editor_id": editor, "editor_name": ctx.name(editor), "cohort_label": cm.cohort_name(now, key), "pct_change": shown(change * 100, 1),
                  "status": status, "team_pct_change": shown(peer_change * 100, 1) if peer_change is not None else None, "team_moved_same_way": team_same,
                  "team_comparison_available": peer_change is not None, "team_current_sample": len(peers_now), "team_baseline_sample": len(peers_then),
                  "material_pct": shown(material * 100, 1),
                  "workload_median_current": workload_now, "workload_median_baseline": workload_then,
                  "workload_higher_now": workload_now is not None and workload_then is not None and workload_now > workload_then}
        supporting = [ctx.evidence("supporting", f"execution_{window}", "median first-pass execution time (first In Progress -> first Ready For Approval) of the "
                                   "Editor's projects in this exact Video Type", {"projects": len(rows)},
                                   [p.record("duration_seconds", "concurrency_at_start") for p in rows], columns=("status", "video_type", "editor"),
                                   comparison={"median_hours": cm.hours(median(p.duration_seconds for p in rows))},
                                   time_window=ctx.window("current") if window == CURRENT else ctx.history_window)
                      for window, rows in ((CURRENT, now), (HISTORY, then))]
        contradicting = [ctx.evidence("contradicting", "team_execution_moved_same_way", "other Editors' median execution in the same Video Type changed by an amount "
                                      "within the material difference of the Editor's change",
                                      {"current": len(peers_now), "baseline": len(peers_then)}, [p.record("duration_seconds") for p in peers_now],
                                      columns=("status", "video_type", "editor"), comparison={"pct_change": params["team_pct_change"]},
                                      time_window=ctx.window("current"))] if team_same else []
        statements_extra = []
        if params["workload_higher_now"]:
            statements_extra.append(Statement(PATTERN, "workload_higher_in_same_period", params))
        finding = _change_finding(ctx, "change.editor", scope, "median_execution", params, supporting, used, status,
                                  {"current": (len(now), floor), "baseline": (len(then), floor)}, [cm.ELAPSED_TIME, cm.VIDEO_TYPE_ONLY, cm.NO_CAUSE_EVIDENCE,
                                                                                                    cm.WORKLOAD_LOWER_BOUND], contradicting, [], [], float(abs(change)))
        finding.statements[2:2] = statements_extra
        result.add(finding)


def run_team(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, "evidence.material_rate_difference", "recent_change.minimum_sample", "quality.minimum_projects", *BREADTH)
    result = DetectorResult()
    material = exact(values["evidence.material_rate_difference"])
    periods = _periods(ctx.facts.attributed)
    for measure, (fn, floor_name, columns) in RATE_MEASURES.items():
        floor = values[floor_name]
        for against in (COMPARISON, HISTORY):
            now, now_n = fn(periods[CURRENT])
            then, then_n = fn(periods[against])
            facts = {"measure": measure, "against": against, "current": shown(now), "current_sample": now_n, "baseline": shown(then), "baseline_sample": then_n}
            if min(now_n, then_n) < floor or now is None or then is None:
                result.skip("change.team", Scope("team"), [INSUFFICIENT_SAMPLE], facts, (floor_name,))
                continue
            status = _classify(now - then, material)
            if status is None:
                result.skip("change.team", Scope("team"), [NO_EFFECT], facts, ("evidence.material_rate_difference",))
                continue
            # Breadth (D53.4): Editors with enough comparable projects in both periods, and how many moved the same way (a replication
            # check). The change is called shared across Editors only under the D53 shared-pattern rule.
            per_editor = values["evidence.minimum_projects_per_editor_for_breadth"]
            editors = []
            for editor in ctx.facts.editors():
                e_now, n1 = fn([p for p in periods[CURRENT] if p.editor_id == editor])
                e_then, n2 = fn([p for p in periods[against] if p.editor_id == editor])
                if n1 >= per_editor and n2 >= per_editor and e_now is not None and e_then is not None:
                    editors.append({"slice": f"editor:{editor}", "holds": (e_now < e_then) == (status == IMPROVING) and e_now != e_then})
            params = {**facts, "difference": shown(now - then), "status": status, "material_difference": shown(material),
                      **_breadth(editors, values)}
            supporting = [ctx.evidence("supporting", f"team_{measure}_{window}", f"team {measure} in the {window} period", {"projects": len(periods[window])},
                                       [p.record("deadline_result", "negative_scored") for p in periods[window]], columns=columns,
                                       time_window=ctx.window(window) if window != HISTORY else ctx.history_window) for window in (CURRENT, against)]
            result.add(_change_finding(ctx, "change.team", Scope("team"), measure, params, supporting, used, status,
                                       {"current": (now_n, floor), "baseline": (then_n, floor)}, [cm.ATTRIBUTED_ONLY, cm.NO_CAUSE_EVIDENCE],
                                       [], editors, [], float(abs(now - then))))
    return result


def run_video_type(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, "evidence.material_duration_pct", "evidence.minimum_group_projects", *BREADTH)
    result = DetectorResult()
    material, floor = exact(values["evidence.material_duration_pct"]) / 100, values["evidence.minimum_group_projects"]
    periods = _periods([p for p in ctx.facts.attributed if p.speed_measurable])
    for key in sorted({p.cohort_key for p in periods[CURRENT] if p.cohort_key}):
        now = [p for p in periods[CURRENT] if p.cohort_key == key]
        then = [p for p in periods[HISTORY] if p.cohort_key == key]
        now_median, then_median = median(p.duration_seconds for p in now), median(p.duration_seconds for p in then)
        scope = Scope("video_type", cohort_key=key)
        facts = {"measure": "median_execution", "cohort_key": key, "current_sample": len(now), "baseline_sample": len(then),
                 "current_hours": cm.hours(now_median), "baseline_hours": cm.hours(then_median), "against": HISTORY}
        if min(len(now), len(then)) < floor:
            result.skip("change.video_type", scope, [INSUFFICIENT_SAMPLE], facts, ("evidence.minimum_group_projects",))
            continue
        change = pct_change(now_median, then_median)
        if change is None or abs(change) < material:
            result.skip("change.video_type", scope, [NO_EFFECT], facts, ("evidence.material_duration_pct",))
            continue
        status = IMPROVING if change < 0 else DETERIORATING
        per_editor = values["evidence.minimum_projects_per_editor_for_breadth"]
        breadth = []
        for editor in sorted({p.editor_id for p in now if p.editor_id}):
            mine_now = [p.duration_seconds for p in now if p.editor_id == editor]
            mine_then = [p.duration_seconds for p in then if p.editor_id == editor]
            e_now, e_then = median(mine_now), median(mine_then)
            if len(mine_now) >= per_editor and len(mine_then) >= per_editor and e_now is not None and e_then is not None:
                breadth.append({"slice": f"editor:{editor}", "holds": (e_now < e_then) == (status == IMPROVING) and e_now != e_then})
        params = {**facts, "cohort_label": cm.cohort_name(now, key), "pct_change": shown(change * 100, 1), "status": status, "material_pct": shown(material * 100, 1),
                  **_breadth(breadth, values)}
        supporting = [ctx.evidence("supporting", f"video_type_execution_{window}", "median first-pass execution time of every Editor's projects in this exact Video Type",
                                   {"projects": len(rows)}, [p.record("duration_seconds") for p in rows], columns=("status", "video_type", "editor"),
                                   comparison={"median_hours": cm.hours(median(p.duration_seconds for p in rows))},
                                   time_window=ctx.window("current") if window == CURRENT else ctx.history_window)
                      for window, rows in ((CURRENT, now), (HISTORY, then))]
        result.add(_change_finding(ctx, "change.video_type", scope, "median_execution", params, supporting, used, status,
                                   {"current": (len(now), floor), "baseline": (len(then), floor)}, [cm.ELAPSED_TIME, cm.VIDEO_TYPE_ONLY, cm.NO_CAUSE_EVIDENCE],
                                   [], breadth, [], float(abs(change))))
    return result


DETECTORS = [
    Detector("change.editor", VERSION, "19, 52", "An Editor against their own history: late rate and scored Negative label rate (current vs comparison window and vs "
             "history), median execution per exact Video Type (current vs history); the rest of the team's change over the same periods is shown beside it",
             ("editor_identity", "deadline_result", "performance_labels", "editor_execution_interval", "video_type", "concurrent_workload_history"),
             ("evidence.material_rate_difference", "evidence.material_duration_pct", "recent_change.minimum_sample", "quality.minimum_projects", "speed.minimum_editor_projects",
              "speed.minimum_comparator_projects", "speed.minimum_comparator_editors"),
             "both periods >= recent_change.minimum_sample (rates, D52) / quality.minimum_projects (labels, D52) / speed.minimum_editor_projects per Video Type (D52); "
             "the team's change counts only at the same floors (rates) or the D52 comparator minimums (execution), otherwise it is unavailable",
             "one finding per material change (improving / deteriorating) with both periods' projects, the team's change and the Editor's workload",
             "periods vs minimums; contradicting evidence when the team moved the same way; replication against the other baseline",
             (cm.NO_CAUSE_EVIDENCE, cm.ELAPSED_TIME, cm.WORKLOAD_LOWER_BOUND), run_editor),
    Detector("change.team", VERSION, "20", "Team late rate and scored Negative label rate, current vs comparison window and vs history",
             ("deadline_result", "performance_labels", "editor_identity"), ("evidence.material_rate_difference", "recent_change.minimum_sample", "quality.minimum_projects",
                                                                           *BREADTH),
             "both periods >= recent_change.minimum_sample / quality.minimum_projects; 'shared across Editors' only under the D53.4 breadth rule",
             "one finding per material team change, with how many Editors moved the same way",
             "periods vs minimums; replication = Editors moving the same way", (cm.NO_CAUSE_EVIDENCE,), run_team),
    Detector("change.video_type", VERSION, "21", "A Video Type's median execution time, current vs history, across Editors",
             ("editor_execution_interval", "video_type"), ("evidence.material_duration_pct", "evidence.minimum_group_projects", *BREADTH),
             "both periods >= evidence.minimum_group_projects in the exact Video Type; 'across Editors' only under the D53.4 breadth rule",
             "one finding per material change with how many Editors moved the same way",
             "periods vs minimums; replication = Editors moving the same way", (cm.ELAPSED_TIME, cm.VIDEO_TYPE_ONLY), run_video_type),
]
