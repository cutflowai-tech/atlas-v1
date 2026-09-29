"""Contradictory evidence and counter-intuitive findings (Tasks 34-37).

- ``contradiction.metric_conflict`` (Task 37). It reads only approved, already-published component states (D38, D45, D52),
  so it runs in ``approved_only`` mode. Findings:
  - Speed and Deadline point in opposite directions ("fast but late", "slow but on time");
  - the Deadline comparison is favourable while most of the Editor's own projects are still late (D45: facts stay absolute).

  Conflicts stay visible instead of being collapsed into one status.
- ``contradiction.bad_headline`` (Tasks 34, 35). The Editor's late rate is above the other Editors' (whole ingested history),
  but deeper evidence weakens "the Editor executes slowly":
  - execution speed is competitive under the approved Speed rule;
  - late projects cluster in short runway;
  - many late projects were executed within the typical time;
  - the other Editors are about as late on the same mix of Video Types;
  - some ETAs had already passed when work started.

  This never proves innocence. It tells management not to stop at the headline.
- ``contradiction.hidden_risk`` (Task 36). A favourable headline (Speed or Deadline Positive, or a late rate below the others')
  hides another signal:
  - Negative labels are rising or present in the current window;
  - workload is above the Editor's own history;
  - the late rate is rising behind good speed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from fractions import Fraction
from typing import Any

from atlas_commander.investigation import common as cm
from atlas_commander.investigation.baselines import COMPARISON, CURRENT, HISTORY, in_period
from atlas_commander.investigation.confidence import assess
from atlas_commander.investigation.context import Detector, DetectorResult, RunContext, uses
from atlas_commander.investigation.facts import ProjectFact
from atlas_commander.investigation.models import (
    ADVERSE,
    FACT,
    HIDDEN_CONTEXT,
    HYPOTHESIS,
    INTERPRETATION,
    METRIC,
    MIXED,
    PATTERN,
    Evidence,
    Finding,
    Scope,
    Statement,
)
from atlas_commander.investigation.person_system import expected_late
from atlas_commander.investigation.policy import INSUFFICIENT_SAMPLE, NO_EFFECT, ParameterUse
from atlas_commander.investigation.stats import exact, median, shown

VERSION = "contradictions-v1.0"
HOLDS, DOES_NOT_HOLD, NOT_ASSESSED = "holds", "does_not_hold", "not_assessed"


# --------------------------------------------------------------------------------------------------- metric conflict

def run_metric_conflict(ctx: RunContext) -> DetectorResult:
    result = DetectorResult()
    for editor, profile in sorted(ctx.profiles.items()):
        speed, deadline = profile["speed"]["component"], profile["deadline"]["component"]
        states = {"speed": speed["state"], "deadline": deadline["state"], "quality": profile["quality"]["component"]["state"]}
        facts = dict(deadline["facts"])
        conflicts = []
        if states["speed"] == "positive" and states["deadline"] == "negative":
            conflicts.append("fast_but_late")
        if states["speed"] == "negative" and states["deadline"] == "positive":
            conflicts.append("slow_but_on_time")
        late, total = facts.get("late") or 0, facts.get("deadline_classifiable_projects") or 0
        if states["deadline"] == "positive" and total and Fraction(late, total) > Fraction(1, 2):
            conflicts.append("better_than_team_but_mostly_late")
        scope = Scope("editor", editor_id=editor)
        if not conflicts:
            result.skip("contradiction.metric_conflict", scope, [NO_EFFECT], {"component_states": states})
            continue
        params = {"editor_id": editor, "editor_name": ctx.name(editor), "conflicts": conflicts, "component_states": states,
                  "overall_status": profile["overall"].get("status_label"), "absolute_late_rate": facts.get("absolute_late_rate"),
                  "comparator_late_rate": facts.get("comparator_late_rate"), "late": late, "deadline_classifiable_projects": total,
                  "speed_weights": speed["facts"].get("project_weights"), "window": profile["deadline"]["window"]}
        supporting = [ctx.evidence("supporting", f"{name}_component", f"the published {name} component (contract 1.5, {'D38' if name == 'speed' else 'D45'}); "
                                   "records are the Editor's own projects", dict(block["evidence"]["sample"]),
                                   cm.records_from_block(block["evidence"], editor), columns=("status", "editor", "video_type" if name == "speed" else "requested_eta"),
                                   comparison={"state": block["state"], "facts": block["facts"]}, time_window=profile["deadline"]["window"])
                      for name, block in (("speed", speed), ("deadline", deadline))]
        supporting = [block for block in supporting if block.records]
        if not supporting:
            result.skip("contradiction.metric_conflict", scope, ["missing_data"], params)
            continue
        statements = [Statement(METRIC, f"conflict_{name}", params) for name in conflicts]
        statements += [Statement(INTERPRETATION, "components_disagree_do_not_collapse", params), Statement(HYPOTHESIS, "conflict_points_outside_execution", params)]
        finding = Finding("contradiction.metric_conflict", VERSION, HIDDEN_CONTEXT, MIXED, scope, statements, supporting, [], profile["deadline"]["window"],
                          [cm.VIDEO_TYPE_ONLY, cm.NO_CAUSE_EVIDENCE, cm.ELAPSED_TIME], Statement(INTERPRETATION, "significance_metric_conflict", params),
                          [Statement(HYPOTHESIS, "investigate_conflict", params)], key={"conflicts": conflicts}, magnitude=float(len(conflicts)),
                          headline_contradiction=True)
        speed_n = speed["facts"].get("classifiable_projects") or 0
        finding.confidence = assess(ctx.policy, groups={"deadline_projects": (total, ctx.policy.value("deadline.minimum_editor_projects")),
                                                        "speed_projects": (speed_n, ctx.policy.value("speed.minimum_editor_projects"))},
                                    projects=finding.sample_size, editors=1)
        result.add(finding)
    return result


# --------------------------------------------------------------------------------------------------- bad headline

def speed_all_history(ctx: RunContext, editor: str) -> dict[str, Any] | None:
    """The approved D38 Speed reading applied to the Editor's whole ingested history (D52 minimums and bands, leave-one-out)."""
    names = ("speed.minimum_editor_projects", "speed.faster_band_pct", "speed.slower_band_pct")
    uses_ = {name: ctx.policy.use(name) for name in names}
    if any(use is None for use in uses_.values()):
        return None
    minimum = int(uses_["speed.minimum_editor_projects"].value)  # type: ignore[union-attr]
    faster, slower = exact(uses_["speed.faster_band_pct"].value), exact(uses_["speed.slower_band_pct"].value)  # type: ignore[union-attr]
    weights = {"faster": 0, "similar": 0, "slower": 0}
    rows = []
    mine = [p for p in ctx.baselines.speed_projects if p.editor_id == editor]
    for key in sorted({p.cohort_key for p in mine if p.cohort_key}):
        typed = [p for p in mine if p.cohort_key == key]
        typical = ctx.baselines.typical(key, editor)
        own = median(p.duration_seconds for p in typed)
        if len(typed) < minimum or not typical.valid or not typical.median_seconds or own is None:
            continue
        pct = Fraction(own - typical.median_seconds, typical.median_seconds) * 100
        verdict = "faster" if pct < faster else "slower" if pct > slower else "similar"
        weights[verdict] += len(typed)
        rows.append({"cohort_key": key, "projects": len(typed), "editor_median_hours": cm.hours(own), "typical_hours": cm.hours(typical.median_seconds),
                     "pct": shown(pct, 1), "verdict": verdict, "records": typed})
    total = sum(weights.values())
    if not total:
        return None
    state = "positive" if weights["faster"] * 2 > total else "negative" if weights["slower"] * 2 > total else "neutral"
    return {"state": state, "weights": weights, "rows": rows}


def run_bad_headline(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, "evidence.minimum_outcome_events", "deadline.minimum_editor_projects")
    result = DetectorResult()
    minimum_outcomes, minimum_editor = values["evidence.minimum_outcome_events"], values["deadline.minimum_editor_projects"]
    runway_use, material_use, peers_use = ctx.policy.use("runway.short_rule"), ctx.policy.use("evidence.material_rate_difference"), ctx.policy.use("evidence.minimum_group_projects")
    classifiable = [p for p in ctx.facts.attributed if p.deadline_classifiable]
    for editor in ctx.facts.editors():
        mine = [p for p in classifiable if p.editor_id == editor]
        peers = [p for p in classifiable if p.editor_id != editor]
        scope = Scope("editor", editor_id=editor)
        if len(mine) < minimum_editor or not peers:
            result.skip("contradiction.bad_headline", scope, [INSUFFICIENT_SAMPLE], {"deadline_classifiable_projects": len(mine)}, ("deadline.minimum_editor_projects",))
            continue
        late = [p for p in mine if p.late]
        rate, peer_rate = Fraction(len(late), len(mine)), Fraction(sum(bool(p.late) for p in peers), len(peers))
        if rate <= peer_rate:
            continue                                               # no adverse headline to question
        checks: list[dict[str, Any]] = []
        extra_uses: list[ParameterUse] = []
        contradicting: list[Evidence] = []
        speed = speed_all_history(ctx, editor)
        if speed is None:
            checks.append({"check": "speed_competitive", "result": NOT_ASSESSED})
        else:
            holds = speed["state"] in ("positive", "neutral")
            checks.append({"check": "speed_competitive", "result": HOLDS if holds else DOES_NOT_HOLD, "state": speed["state"], "weights": speed["weights"]})
            if holds:
                contradicting.append(ctx.evidence("contradicting", "execution_speed_competitive", "approved Speed rule (D38, D52 bands, leave-one-out) applied to the "
                                                  "Editor's whole history per exact Video Type", {"projects": sum(speed["weights"].values())},
                                                  [p.record("duration_seconds") for row in speed["rows"] for p in row["records"]], columns=("status", "video_type", "editor"),
                                                  comparison={"rows": [{k: v for k, v in row.items() if k != "records"} for row in speed["rows"]]},
                                                  time_window=ctx.history_window))
        if runway_use is None:
            checks.append({"check": "late_cluster_in_short_runway", "result": NOT_ASSESSED})
        else:
            extra_uses.append(runway_use)
            short_late = [p for p in late if cm.short_runway(p, ctx.baselines)]
            on_time = [p for p in mine if not p.late]
            short_on_time = [p for p in on_time if cm.short_runway(p, ctx.baselines)]
            holds = len(short_late) >= minimum_outcomes and (not on_time or Fraction(len(short_late), len(late)) > Fraction(len(short_on_time), len(on_time)))
            checks.append({"check": "late_cluster_in_short_runway", "result": HOLDS if holds else DOES_NOT_HOLD, "short_runway_late": len(short_late), "late": len(late),
                           "short_runway_not_late": len(short_on_time), "not_late": len(on_time)})
            if holds:
                contradicting.append(ctx.evidence("contradicting", "late_with_short_runway", "the Editor's late projects whose runway was below the other Editors' typical "
                                                  "execution time in the same Video Type", {"projects": len(short_late)},
                                                  [p.record("runway_seconds", "requested_eta", "deadline_result", extra={"typical_execution_seconds": cm.typical_seconds(p, ctx.baselines)})
                                                   for p in short_late], columns=("status", "requested_eta", "video_type", "editor"), time_window=ctx.history_window))
        within_typical = [p for p in late if (typical := cm.typical_seconds(p, ctx.baselines)) is not None and p.duration_seconds <= typical]
        holds = len(within_typical) >= minimum_outcomes
        checks.append({"check": "late_despite_typical_execution", "result": HOLDS if holds else DOES_NOT_HOLD, "projects": len(within_typical), "late": len(late)})
        if holds:
            contradicting.append(ctx.evidence("contradicting", "late_despite_typical_execution", "late projects whose own execution time was at or below the other Editors' "
                                              "typical execution time in the same Video Type", {"projects": len(within_typical)},
                                              [p.record("duration_seconds", "deadline_result", "runway_seconds", extra={"typical_execution_seconds": cm.typical_seconds(p, ctx.baselines)})
                                               for p in within_typical], columns=("status", "requested_eta", "video_type", "editor"), time_window=ctx.history_window))
        if material_use is None or peers_use is None:
            checks.append({"check": "peers_as_late_on_same_mix", "result": NOT_ASSESSED})
        else:
            extra_uses += [material_use, peers_use]
            adjusted = expected_late(ctx, editor, lambda p: p.cohort_key, int(peers_use.value))
            n = len(adjusted["covered"])
            holds = n >= minimum_editor and Fraction(adjusted["observed"], n) - adjusted["expected"] / n < exact(material_use.value) if n else False
            checks.append({"check": "peers_as_late_on_same_mix", "result": HOLDS if holds else DOES_NOT_HOLD, "covered": n,
                           "observed_rate": shown(Fraction(adjusted["observed"], n)) if n else None, "expected_rate": shown(adjusted["expected"] / n) if n else None})
        passed = [p for p in late if p.runway_seconds is not None and p.runway_seconds <= 0]
        checks.append({"check": "eta_passed_before_start", "result": HOLDS if passed else DOES_NOT_HOLD, "projects": len(passed)})
        deep = [row for row in checks if row["result"] == HOLDS and row["check"] in ("late_cluster_in_short_runway", "late_despite_typical_execution", "peers_as_late_on_same_mix")]
        params = {"editor_id": editor, "editor_name": ctx.name(editor), "late": len(late), "deadline_classifiable_projects": len(mine), "late_rate": shown(rate),
                  "peer_late_rate": shown(peer_rate), "checks": checks, "holding_checks": [row["check"] for row in checks if row["result"] == HOLDS]}
        if not deep:
            result.skip("contradiction.bad_headline", scope, [NO_EFFECT], params)
            continue
        headline = ctx.evidence("supporting", "headline_late_rate", "the Editor's late projects / deadline-classifiable projects over the whole ingested history, beside the "
                                "other Editors' rate", {"editor_projects": len(mine), "peer_projects": len(peers)},
                                [p.record("deadline_result", "requested_eta") for p in mine], columns=("status", "requested_eta", "editor"),
                                comparison={"editor": shown(rate), "others": shown(peer_rate)}, time_window=ctx.history_window)
        statements = [Statement(FACT, "headline_late_rate_above_peers", params)]
        statements += [Statement(PATTERN, f"check_{row['check']}", {**params, **row}) for row in checks if row["result"] == HOLDS]
        statements += [Statement(INTERPRETATION, "headline_may_overstate_execution_cause", params), Statement(HYPOTHESIS, "lateness_may_arise_outside_execution", params)]
        finding = Finding("contradiction.bad_headline", VERSION, HIDDEN_CONTEXT, MIXED, scope, statements, [headline], [*used, *extra_uses], ctx.history_window,
                          [cm.NO_CAUSE_EVIDENCE, cm.TYPICAL_WHOLE_HISTORY, cm.VIDEO_TYPE_ONLY, cm.ELAPSED_TIME, cm.ASSOCIATION_NOT_CAUSE],
                          Statement(INTERPRETATION, "significance_bad_headline", params), [Statement(HYPOTHESIS, "investigate_before_concluding_speed", params)],
                          key={"headline": "late_rate_above_peers"}, contradicting_evidence=contradicting, magnitude=float(len(deep)), headline_contradiction=True)
        finding.confidence = assess(ctx.policy, groups={"editor_projects": (len(mine), minimum_editor), "late": (len(late), minimum_outcomes)},
                                    replication=[{"slice": row["check"], "holds": row["result"] == HOLDS} for row in checks if row["result"] != NOT_ASSESSED],
                                    projects=len(mine), editors=1)
        result.add(finding)
    return result


# --------------------------------------------------------------------------------------------------- hidden risk

def _favourable_headline(profile: Mapping[str, Any], mine: list[ProjectFact], peers: list[ProjectFact]) -> list[str]:
    reasons = [f"{name}_component_positive" for name in ("speed", "deadline") if profile[name]["component"]["state"] == "positive"]
    if profile["overall"].get("status") in ("Strong", "Good"):
        reasons.append(f"overall_{profile['overall']['status'].lower()}")
    m = [p for p in mine if p.deadline_classifiable]
    o = [p for p in peers if p.deadline_classifiable]
    if m and o and Fraction(sum(bool(p.late) for p in m), len(m)) < Fraction(sum(bool(p.late) for p in o), len(o)):
        reasons.append("late_rate_below_peers")
    return reasons


def run_hidden_risk(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, "evidence.material_rate_difference", "evidence.minimum_outcome_events", "recent_change.minimum_sample", "quality.minimum_projects")
    result = DetectorResult()
    material, minimum_outcomes = exact(values["evidence.material_rate_difference"]), values["evidence.minimum_outcome_events"]
    floor, quality_floor = values["recent_change.minimum_sample"], values["quality.minimum_projects"]
    for editor, profile in sorted(ctx.profiles.items()):
        mine = [p for p in ctx.facts.attributed if p.editor_id == editor]
        peers = [p for p in ctx.facts.attributed if p.editor_id != editor]
        headline = _favourable_headline(profile, mine, peers)
        scope = Scope("editor", editor_id=editor)
        if not headline:
            continue
        current = [p for p in mine if in_period(p, CURRENT)]
        comparison = [p for p in mine if in_period(p, COMPARISON)]
        history = [p for p in mine if in_period(p, HISTORY)]
        checks: list[dict[str, Any]] = []

        def rate(rows: list[ProjectFact], fn: Callable[[ProjectFact], bool | None]) -> tuple[Fraction | None, int]:
            valid = [fn(p) for p in rows if fn(p) is not None]
            return (Fraction(sum(bool(v) for v in valid), len(valid)) if valid else None), len(valid)

        now, now_n = rate(current, lambda p: bool(p.negative_scored))
        then, then_n = rate(comparison, lambda p: bool(p.negative_scored))
        if min(now_n, then_n) >= quality_floor and now is not None and then is not None and now - then >= material:
            checks.append({"check": "negative_labels_rising", "current": shown(now), "comparison": shown(then), "current_sample": now_n, "comparison_sample": then_n})
        negatives = sum(len(p.negative_scored) for p in current)
        if profile["speed"]["component"]["state"] == "positive" and negatives >= minimum_outcomes:
            checks.append({"check": "negative_labels_behind_good_speed", "occurrences": negatives, "projects": len(current)})
        work_now = median(p.concurrency_at_start for p in current if p.concurrency_at_start is not None)
        work_then = median(p.concurrency_at_start for p in history if p.concurrency_at_start is not None)
        if len(current) >= floor and work_now is not None and work_then is not None and work_now > work_then:
            checks.append({"check": "workload_above_own_history", "current_median": work_now, "history_median": work_then, "current_projects": len(current)})
        late_now, late_now_n = rate(current, lambda p: p.late)
        late_then, late_then_n = rate(comparison, lambda p: p.late)
        if (profile["speed"]["component"]["state"] == "positive" and min(late_now_n, late_then_n) >= floor and late_now is not None and late_then is not None
                and late_now - late_then >= material):
            checks.append({"check": "late_rate_rising_behind_good_speed", "current": shown(late_now), "comparison": shown(late_then)})
        if not checks:
            result.skip("contradiction.hidden_risk", scope, [NO_EFFECT], {"favourable_headline": headline})
            continue
        params = {"editor_id": editor, "editor_name": ctx.name(editor), "favourable_headline": headline, "checks": checks,
                  "holding_checks": [row["check"] for row in checks]}
        supporting = ctx.evidence("supporting", "current_window_projects", "the Editor's projects in the current window with their labels, deadline result and concurrency",
                                  {"current": len(current), "comparison": len(comparison)},
                                  [p.record("deadline_result", "negative_scored", "concurrency_at_start", label_events=True) for p in current],
                                  columns=("status", "labels", "requested_eta", "editor"), comparison={"checks": checks}, time_window=ctx.window("current"))
        statements = [Statement(FACT, "favourable_headline", params)] + [Statement(PATTERN, f"check_{row['check']}", {**params, **row}) for row in checks]
        statements += [Statement(INTERPRETATION, "good_headline_hides_signal", params), Statement(HYPOTHESIS, "early_signal_worth_review", params)]
        finding = Finding("contradiction.hidden_risk", VERSION, HIDDEN_CONTEXT, ADVERSE, scope, statements, [supporting] if supporting.records else [], used,
                          ctx.window("current"), [cm.LABELS_LOWER_BOUND, cm.WORKLOAD_LOWER_BOUND, cm.NO_CAUSE_EVIDENCE],
                          Statement(INTERPRETATION, "significance_hidden_risk", params), [Statement(HYPOTHESIS, "review_hidden_signal", params)],
                          key={"checks": [row["check"] for row in checks]}, magnitude=float(len(checks)), headline_contradiction=True, worsening=True)
        if not finding.supporting_evidence:
            continue
        finding.confidence = assess(ctx.policy, groups={"current": (len(current), floor)}, projects=len(current), editors=1)
        result.add(finding)
    return result


DETECTORS = [
    Detector("contradiction.metric_conflict", VERSION, "37", "Approved component states that point in opposite directions (fast but late, slow but on time, "
             "better than team but mostly late)", ("editor_identity", "deadline_result", "editor_execution_interval"), (),
             "the published components' own approved minimums (D52)", "one hidden-context finding per Editor with the conflicting components' evidence",
             "component samples vs their approved minimums", (cm.NO_CAUSE_EVIDENCE,), run_metric_conflict),
    Detector("contradiction.bad_headline", VERSION, "34, 35", "A late rate above the other Editors' that deeper evidence qualifies: competitive execution speed, "
             "late projects clustered in short runway, late despite typical execution, peers as late on the same mix, ETA passed before work started",
             ("deadline_result", "execution_runway", "editor_execution_interval", "video_type", "editor_identity"),
             ("evidence.minimum_outcome_events", "deadline.minimum_editor_projects"),
             "Editor deadline-classifiable projects >= deadline.minimum_editor_projects (D52); each check's own minimum",
             "one hidden-context finding per Editor with every check (holds / does not hold / not assessed) and contradicting evidence blocks",
             "Editor sample vs minimum; replication = checks that hold", (cm.NO_CAUSE_EVIDENCE, cm.TYPICAL_WHOLE_HISTORY), run_bad_headline),
    Detector("contradiction.hidden_risk", VERSION, "36", "A favourable headline hiding another signal: Negative labels rising or present behind good speed, workload "
             "above the Editor's own history, late rate rising behind good speed", ("performance_labels", "concurrent_workload_history", "deadline_result"),
             ("evidence.material_rate_difference", "evidence.minimum_outcome_events", "recent_change.minimum_sample", "quality.minimum_projects"),
             "each check's window samples >= recent_change.minimum_sample / quality.minimum_projects (D52)", "one hidden-context finding per Editor listing the checks that hold",
             "current window vs minimum", (cm.LABELS_LOWER_BOUND, cm.WORKLOAD_LOWER_BOUND), run_hidden_risk),
]
