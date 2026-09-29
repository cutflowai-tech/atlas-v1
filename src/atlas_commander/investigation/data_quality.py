"""Data warnings (Tasks 59, 62, HANDOFF §26-27): what the data could not support, stated as facts, never as performance.

Each warning is a ``data_warning`` finding with the affected projects as evidence. None needs a threshold, so all of them run
in ``approved_only`` mode. The warnings cover:

- completed projects without a verified Editor;
- deadline-unclassifiable projects (date-only or missing ETA);
- ETAs first observed after work started;
- status spans containing an unknown or cleared status;
- performance labels that disagree with the computed deadline facts;
- Video Types that are not benchmark-eligible.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from atlas_commander.investigation import common as cm
from atlas_commander.investigation.confidence import assess
from atlas_commander.investigation.context import Detector, DetectorResult, RunContext
from atlas_commander.investigation.facts import UNKNOWN_STATUS_WITHIN_VISIT, ProjectFact
from atlas_commander.investigation.models import DATA_WARNING, FACT, HYPOTHESIS, INTERPRETATION, NEUTRAL, EvidenceRecord, Finding, Scope, Statement

VERSION = "data-quality-v1.0"
EDITOR_REASONS = ("MISSING_EDITOR_EVENT", "EDITOR_CHANGED_WITHIN_CYCLE", "UNMAPPED_EDITOR", "MISSING_EDITOR", "AMBIGUOUS_EDITOR",
                  "EDITOR_LABEL_NAME_MISMATCH", "EDITOR_LABEL_NAME_UNVERIFIED", "EDITOR_IDENTITY_OUTSIDE_OBSERVED_RANGE", "invalid_identity_value",
                  "unresolved_historical_identity")


def _warning(ctx: RunContext, code: str, projects: Sequence[ProjectFact] | None, params: dict[str, object], records: Sequence[EvidenceRecord] | None = None,
             keys: tuple[str, ...] = ("deadline_result",)) -> Finding:
    rows = list(records) if records is not None else [p.record(*keys, extra={"exclusions": list(p.exclusions)}) for p in projects or []]
    evidence = ctx.evidence("supporting", code, f"projects affected by {code}", {"projects": len(rows)}, rows,
                            columns=("status", "editor", "requested_eta", "video_type", "labels"), time_window=ctx.history_window)
    finding = Finding(f"data.{code}", VERSION, DATA_WARNING, NEUTRAL, Scope("data"),
                      [Statement(FACT, f"data_{code}", params), Statement(INTERPRETATION, "data_state_not_performance", params)], [evidence], [],
                      ctx.history_window, [cm.INGEST_WINDOW], Statement(INTERPRETATION, f"significance_data_{code}", params),
                      [Statement(HYPOTHESIS, f"fix_data_{code}", params)], key={"code": code}, magnitude=float(len(rows)))
    finding.confidence = assess(ctx.policy, groups={"projects": (len(rows), None)}, projects=len(rows))
    return finding


def run(ctx: RunContext) -> DetectorResult:
    result = DetectorResult()
    projects = ctx.facts.projects
    unattributed = [p for p in projects if not p.attributed]
    if unattributed:
        reasons = Counter(next((reason for reason in p.exclusions if reason in EDITOR_REASONS), "OTHER") for p in unattributed)
        result.add(_warning(ctx, "unattributed_projects", unattributed, {"projects": len(unattributed), "completed": len(projects),
                                                                          "reasons": dict(sorted(reasons.items()))}))
    attributed = ctx.facts.attributed
    unclassifiable = [p for p in attributed if not p.deadline_classifiable]
    if unclassifiable:
        reasons = Counter(p.requested_eta_issue or "OTHER_EXCLUSION" for p in unclassifiable)
        result.add(_warning(ctx, "deadline_not_classifiable", unclassifiable, {"projects": len(unclassifiable), "attributed": len(attributed),
                                                                                "reasons": dict(sorted(reasons.items()))}, keys=("requested_eta_issue",)))
    after_start = [p for p in attributed if p.eta_observed_after_start]
    if after_start:
        result.add(_warning(ctx, "eta_observed_after_work_started", after_start, {"projects": len(after_start), "attributed": len(attributed)},
                            keys=("requested_eta", "requested_eta_observed_at", "in_progress_at")))
    invalid = [(timeline.monday_item_id, visit) for timeline in ctx.facts.timelines.values() for visit in timeline.visits
               if visit.invalid_reason == UNKNOWN_STATUS_WITHIN_VISIT]
    if invalid:
        records = [EvidenceRecord(item, None, tuple(v for v in (visit.enter_event_id, visit.leave_event_id) if v),
                                  tuple(v for v in (visit.entered_at, visit.left_at) if v), {"status": visit.status, "phase": visit.phase})
                   for item, visit in invalid]
        cycles = sum("UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW" in p.exclusions for p in projects)
        result.add(_warning(ctx, "unknown_status_spans", None, {"visits": len(invalid), "items": len({item for item, _ in invalid}),
                                                                "cycles_excluded_from_metrics": cycles}, records))
    late_label = [p for p in attributed if p.late is False and any(label.label == "Late Delivery" for label in p.labels)]
    on_time_label = [p for p in attributed if p.late is True and any(label.label == "On Time Delivery" for label in p.labels)]
    unlabelled_late = sum(1 for p in attributed if p.late and not any(label.label == "Late Delivery" for label in p.labels))
    if late_label or on_time_label:
        records = [p.record("deadline_result", "labels", label_events=True) for p in (*late_label, *on_time_label)]
        result.add(_warning(ctx, "label_fact_disagreement", None, {"late_label_on_not_late": len(late_label), "on_time_label_on_late": len(on_time_label),
                                                                   "late_without_late_label": unlabelled_late}, records))
    ineligible = [p for p in attributed if p.cohort_key and not p.benchmark_eligible and not p.exclusions]
    if ineligible:
        types = Counter(" + ".join(p.cohort_labels) for p in ineligible)
        result.add(_warning(ctx, "video_type_not_benchmark_eligible", ineligible, {"projects": len(ineligible), "video_types": dict(sorted(types.items()))},
                            keys=("cohort_key",)))
    return result


DETECTORS = [
    Detector("data.quality", VERSION, "59, 62", "Data warnings: unattributed projects, deadline-unclassifiable projects, ETAs set after work started, unknown-status "
             "spans, label/fact disagreement, non-benchmark-eligible Video Types", ("editor_identity", "requested_eta", "status_history", "performance_labels", "video_type"),
             (), "none: each warning is a count of affected projects", "one data-warning finding per issue with the affected projects",
             "not graded beyond the count shown", (cm.INGEST_WINDOW,), run),
]
