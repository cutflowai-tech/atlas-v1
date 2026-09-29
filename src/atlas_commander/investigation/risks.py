"""Deterministic risk signals on current open work, and historical similarity (Tasks 38, 39).

This is **not** prediction (HANDOFF §27). No model estimates a probability of lateness. Each signal is a fact about current
work, or a comparison with what was historically normal for the same exact Video Type. The wording is "risk signal",
"deserves attention" and "historically associated with", never "will be late".

Signals on Active Work (D33: In Progress, Revisions, Internal Revisions) and Awaiting Approval, from the Monday snapshot:

- ``past_eta`` (fact, runs in ``approved_only``): the current Requested ETA is already before the retrieval time;
- ``short_remaining_runway`` (``runway.short_rule``): an In Progress project has less time left before its ETA than the other
  Editors' typical execution time minus what has already elapsed;
- ``elapsed_beyond_typical`` (``risk.elapsed_percentile``): an In Progress project has been in execution longer than that
  percentile of historical same-Video-Type execution;
- ``editor_workload_above_own_median`` (``workload.band_rule``): the current Editor has more other active projects than their
  own historical median concurrency;
- ``review_wait_beyond_typical`` (``risk.elapsed_percentile``): an Awaiting Approval project has waited longer than that
  percentile of historical review waits. This is a production review stage signal, never an Editor signal.

Historical similarity (``risk.historical_similarity``): an In Progress project is compared with the historical projects of the
same exact Video Type that started with the same runway band (short / adequate). The late share among them is a base rate, not
a prediction.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from fractions import Fraction
from typing import Any

from atlas_commander.cycles import parse_time
from atlas_commander.investigation import common as cm
from atlas_commander.investigation.confidence import assess
from atlas_commander.investigation.context import Detector, DetectorResult, RunContext, uses
from atlas_commander.investigation.facts import OpenWork
from atlas_commander.investigation.models import (
    ADVERSE,
    EMERGING_RISK,
    FACT,
    HYPOTHESIS,
    INTERPRETATION,
    METRIC,
    PATTERN,
    EvidenceRecord,
    Finding,
    Scope,
    Statement,
)
from atlas_commander.investigation.policy import INSUFFICIENT_SAMPLE, ParameterUse
from atlas_commander.investigation.stats import quantile, shown
from atlas_commander.investigation.workload import editor_medians

VERSION = "risks-v1.0"
IN_PROGRESS = "In Progress"
AWAITING = "Ready For Approval"


def _seconds(start: str, end: str) -> int:
    return int((parse_time(end) - parse_time(start)).total_seconds())


def _signal_finding(ctx: RunContext, signal: str, items: Sequence[tuple[OpenWork, dict[str, Any]]], used: list[ParameterUse], stage: str | None = None) -> Finding:
    records: list[EvidenceRecord] = [item.record(extra) for item, extra in items]
    params = {"signal": signal, "projects": len(items), "statuses": sorted({item.current_status for item, _ in items}),
              "editors": sorted({ctx.name(item.current_editor_id) or "unresolved" for item, _ in items}), "retrieved_at": ctx.facts.retrieved_at,
              "items": [{"monday_item_id": item.monday_item_id, "status": item.current_status, "editor_name": ctx.name(item.current_editor_id), **extra}
                        for item, extra in items]}
    evidence = ctx.evidence("supporting", f"open_work_{signal}", f"current Monday snapshot ({ctx.facts.retrieved_at}): status, Editor Name, Requested ETA and "
                            "Video Type of each open project, with the status history event that opened its current status", {"projects": len(items)}, records,
                            columns=("status", "editor", "requested_eta", "video_type"), time_window={"window": "snapshot", "retrieved_at": ctx.facts.retrieved_at})
    level = FACT if signal == "past_eta" else METRIC
    statements = [Statement(level, f"risk_{signal}", params), Statement(INTERPRETATION, "risk_signal_deserves_attention", params),
                  Statement(HYPOTHESIS, "risk_signal_not_prediction", params)]
    finding = Finding("risk.open_work", VERSION, EMERGING_RISK, ADVERSE, Scope("stage", stage=stage) if stage else Scope("team"), statements, [evidence], used,
                      {"window": "snapshot", "retrieved_at": ctx.facts.retrieved_at}, [cm.CURRENT_SNAPSHOT, cm.NO_CAUSE_EVIDENCE] +
                      ([cm.TYPICAL_WHOLE_HISTORY] if signal != "past_eta" else []), Statement(INTERPRETATION, "significance_open_risk", params),
                      [Statement(HYPOTHESIS, f"check_open_{signal}", params)], key={"signal": signal}, magnitude=float(len(items)), worsening=True)
    finding.confidence = assess(ctx.policy, groups={"projects": (len(items), None)}, projects=len(items), editors=len(finding.affected_editors))
    return finding


def run_open_work(ctx: RunContext) -> DetectorResult:
    result = DetectorResult()
    now = ctx.facts.retrieved_at
    if not now:
        result.skip("risk.open_work", Scope("team"), ["missing_data"], {"reason": "no retrieval time"})
        return result
    active = [item for item in ctx.facts.open_work if item.active]
    awaiting = [item for item in ctx.facts.open_work if item.current_status == AWAITING]
    past = [(item, {"requested_eta": item.requested_eta, "hours_past_eta": cm.hours(_seconds(item.requested_eta, now))})
            for item in active if item.requested_eta and parse_time(item.requested_eta) < parse_time(now)]
    if past:
        result.add(_signal_finding(ctx, "past_eta", past, []))
    else:
        result.skip("risk.open_work", Scope("team"), ["no_effect_at_approved_threshold"], {"signal": "past_eta", "active_projects": len(active)})

    runway = ctx.policy.use("runway.short_rule")
    percentile = ctx.policy.use("risk.elapsed_percentile")
    band_rule = ctx.policy.use("workload.band_rule")
    in_progress = [item for item in active if item.current_status == IN_PROGRESS and item.first_in_progress_at and item.cohort_key and item.benchmark_eligible]
    if runway is None:
        result.skip("risk.open_work", Scope("team"), ["rule_not_approved"], {"signal": "short_remaining_runway"}, ("runway.short_rule",))
    else:
        rows = []
        for item in in_progress:
            typical = ctx.baselines.typical(item.cohort_key or "", item.current_editor_id)
            if not item.requested_eta or not typical.valid or typical.median_seconds is None or parse_time(item.requested_eta) < parse_time(now):
                continue
            elapsed = _seconds(item.first_in_progress_at or now, now)
            remaining = _seconds(now, item.requested_eta)
            if remaining < typical.median_seconds - elapsed:
                rows.append((item, {"remaining_hours": cm.hours(remaining), "elapsed_hours": cm.hours(elapsed), "typical_hours": cm.hours(typical.median_seconds)}))
        if rows:
            result.add(_signal_finding(ctx, "short_remaining_runway", rows, [runway]))
    if percentile is None:
        result.skip("risk.open_work", Scope("team"), ["rule_not_approved"], {"signal": "elapsed_beyond_typical"}, ("risk.elapsed_percentile",))
    else:
        rows = []
        for item in in_progress:
            history = [p.duration_seconds for p in ctx.baselines.speed_projects if p.cohort_key == item.cohort_key]
            typical = ctx.baselines.typical(item.cohort_key or "", None)
            if not typical.valid:
                continue
            threshold = quantile(history, float(percentile.value))
            elapsed = _seconds(item.first_in_progress_at or now, now)
            if threshold is not None and elapsed > threshold:
                rows.append((item, {"elapsed_hours": cm.hours(elapsed), "historical_percentile_hours": cm.hours(threshold), "percentile": percentile.value}))
        if rows:
            result.add(_signal_finding(ctx, "elapsed_beyond_typical", rows, [percentile]))
        waits = [p.review_wait_seconds for p in ctx.facts.projects if p.review_wait_seconds is not None]
        threshold = quantile(waits, float(percentile.value))
        rows = [(item, {"waiting_hours": cm.hours(_seconds(item.status_entered_at, now)), "historical_percentile_hours": cm.hours(threshold)})
                for item in awaiting if item.status_entered_at and threshold is not None and _seconds(item.status_entered_at, now) > threshold]
        if rows:
            result.add(_signal_finding(ctx, "review_wait_beyond_typical", rows, [percentile], stage="review"))
    if band_rule is None:
        result.skip("risk.open_work", Scope("team"), ["rule_not_approved"], {"signal": "editor_workload_above_own_median"}, ("workload.band_rule",))
    else:
        medians = editor_medians(ctx.facts.attributed)
        by_editor: dict[str, list[OpenWork]] = defaultdict(list)
        for item in active:
            if item.current_editor_id:
                by_editor[item.current_editor_id].append(item)
        rows = []
        for editor, items in sorted(by_editor.items()):
            if editor in medians and len(items) - 1 > medians[editor]:
                rows += [(item, {"editor_active_projects": len(items), "editor_median_concurrency": medians[editor]}) for item in items]
        if rows:
            result.add(_signal_finding(ctx, "editor_workload_above_own_median", rows, [band_rule]))
    return result


def run_similarity(ctx: RunContext) -> DetectorResult:
    values, used = uses(ctx, "runway.short_rule", "evidence.minimum_group_projects")
    result = DetectorResult()
    floor = values["evidence.minimum_group_projects"]
    now = ctx.facts.retrieved_at or ""
    for item in ctx.facts.open_work:
        if item.current_status != IN_PROGRESS or not item.first_in_progress_at or not item.requested_eta or not item.cohort_key or not item.benchmark_eligible:
            continue
        typical = ctx.baselines.typical(item.cohort_key, item.current_editor_id)
        scope = Scope("project", monday_item_id=item.monday_item_id, cohort_key=item.cohort_key, editor_id=None)
        if not typical.valid or typical.median_seconds is None:
            result.skip("risk.historical_similarity", scope, [INSUFFICIENT_SAMPLE], {"typical_projects": typical.projects}, ("speed.minimum_comparator_projects",))
            continue
        runway = _seconds(item.first_in_progress_at, item.requested_eta)
        short = runway < typical.median_seconds
        similar = [p for p in ctx.facts.attributed if p.cohort_key == item.cohort_key and p.deadline_classifiable and cm.short_runway(p, ctx.baselines) == short]
        late = sum(bool(p.late) for p in similar)
        same_type = [p for p in ctx.facts.attributed if p.cohort_key == item.cohort_key and p.deadline_classifiable]
        type_rate = Fraction(sum(bool(p.late) for p in same_type), len(same_type)) if same_type else None
        facts = {"runway_hours": cm.hours(runway), "typical_hours": cm.hours(typical.median_seconds), "runway_band": "short" if short else "adequate",
                 "similar_projects": len(similar), "similar_late": late, "video_type_projects": len(same_type), "video_type_late_rate": shown(type_rate)}
        if len(similar) < floor:
            result.skip("risk.historical_similarity", scope, [INSUFFICIENT_SAMPLE], facts, ("evidence.minimum_group_projects",))
            continue
        # A resemblance is a risk signal only when the similar projects were late more often than the Video Type as a whole.
        if type_rate is None or Fraction(late, len(similar)) <= type_rate:
            result.skip("risk.historical_similarity", scope, ["no_effect_at_approved_threshold"], facts, ("runway.short_rule",))
            continue
        params = {**facts, "monday_item_id": item.monday_item_id, "cohort_label": cm.cohort_name(similar, item.cohort_key),
                  "similar_late_rate": shown(Fraction(late, len(similar))), "editor_name": ctx.name(item.current_editor_id), "retrieved_at": now}
        evidence = [ctx.evidence("supporting", "open_project", "the open project from the current snapshot", {"projects": 1},
                                 [item.record({"runway_hours": facts["runway_hours"]})], columns=("status", "requested_eta", "video_type", "editor"),
                                 time_window={"window": "snapshot", "retrieved_at": now}),
                    ctx.evidence("context", "similar_historical_projects", "historical projects of the same exact Video Type whose runway fell in the same band",
                                 {"projects": len(similar), "late": late}, [p.record("deadline_result", "runway_seconds") for p in similar],
                                 columns=("status", "requested_eta", "video_type", "editor"), time_window=ctx.history_window)]
        finding = Finding("risk.historical_similarity", VERSION, EMERGING_RISK, ADVERSE, scope,
                          [Statement(METRIC, "open_project_runway", params), Statement(PATTERN, "resembles_historical_projects", params),
                           Statement(HYPOTHESIS, "base_rate_not_prediction", params)], evidence[:1], used, {"window": "snapshot", "retrieved_at": now},
                          [cm.CURRENT_SNAPSHOT, cm.TYPICAL_WHOLE_HISTORY, cm.ASSOCIATION_NOT_CAUSE, cm.VIDEO_TYPE_ONLY],
                          Statement(INTERPRETATION, "significance_similarity", params), [Statement(HYPOTHESIS, "check_open_project", params)],
                          key={"item": item.monday_item_id}, context_evidence=evidence[1:], magnitude=float(Fraction(late, len(similar))))
        finding.confidence = assess(ctx.policy, groups={"similar": (len(similar), floor)}, projects=len(similar))
        result.add(finding)
    return result


DETECTORS = [
    Detector("risk.open_work", VERSION, "38", "Deterministic risk signals on current open work: past ETA (fact), short remaining runway, execution beyond the typical "
             "percentile, Editor workload above their own median, review wait beyond the typical percentile",
             ("current_open_work", "current_editor_of_open_work", "requested_eta", "video_type", "status_history", "concurrent_workload_history"),
             ("runway.short_rule", "risk.elapsed_percentile", "workload.band_rule"), "no minimum for the past-ETA fact; typical times valid at the D52 comparator minimums",
             "one emerging-risk finding per signal listing the projects", "facts about the snapshot; not graded beyond the sample shown",
             (cm.CURRENT_SNAPSHOT, cm.TYPICAL_WHOLE_HISTORY), run_open_work),
    Detector("risk.historical_similarity", VERSION, "39", "An In Progress project compared with historical same-Video-Type projects in the same runway band: their late "
             "share is a base rate, not a prediction", ("current_open_work", "execution_runway", "video_type", "deadline_result"),
             ("runway.short_rule", "evidence.minimum_group_projects"), "similar historical projects >= evidence.minimum_group_projects",
             "one emerging-risk finding per open project", "similar group vs minimum", (cm.CURRENT_SNAPSHOT, cm.ASSOCIATION_NOT_CAUSE), run_similarity),
]
