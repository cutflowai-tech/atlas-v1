"""Contract 1.5 deterministic Editor-intelligence building blocks (D23--D47).

It accepts the factual records the contract 1.0--1.4 builders already produce (cycles, deadline results, Quality label
occurrences) and adds the 1.5 interpretation layer. Every rule comes from the contract through ``InterpretationPolicy``
in one vocabulary; a result is classified only when its rule is approved (D25), and otherwise keeps its facts with the
reason ``rule_not_approved``. Thresholds are compared unrounded; rounding is for display only.

Every conclusion carries an evidence block from which it can be recomputed without Atlas: the Monday source, board and
columns, the date range, the sample, the calculation, one record per contributing project (item, cycle, Monday event IDs,
source timestamps and the values used), the excluded projects with their reasons, the rule version and the calculation
time (CONTRACTS.md).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from atlas_commander.cycles import COMPLETED, CycleRecord, parse_time
from atlas_commander.interpretation_policy import (
    CLASSIFIED_STATES,
    HIGHER_IS_BETTER,
    NEGATIVE,
    NEUTRAL,
    NOT_CLASSIFIABLE,
    NOT_ENOUGH_APPROVED_LOGIC,
    NOT_ENOUGH_EVIDENCE,
    POSITIVE,
    RULE_NOT_APPROVED,
    SCORED_COMPONENTS,
    InterpretationPolicy,
    Rule,
)
from atlas_commander.metrics import cohort_benchmark_eligibility, median_seconds, speed_eligible
from atlas_commander.video_type import VideoTypeMapping

CAIRO = ZoneInfo("Africa/Cairo")

FASTER, SIMILAR, SLOWER = "faster", "similar", "slower"
SPEED_VERDICTS = frozenset({FASTER, SIMILAR, SLOWER, NOT_CLASSIFIABLE})

INSUFFICIENT_SAMPLE = "insufficient_sample"
NO_OTHER_EDITORS = "no_other_editors_in_cohort"
INSUFFICIENT_COMPARATOR_EDITORS = "insufficient_comparator_editors"
NOT_ENOUGH_COMPONENTS = "not_enough_classifiable_components"
NO_VALUE_IN_A_WINDOW = "no_value_in_one_window"

CLASSIFIED = "classified"

# Cycle exclusions that only remove a project from one metric (it stays in the window cohort for the others).
METRIC_ONLY_EXCLUSIONS = {"VIDEO_TYPE": "speed", "REQUESTED_ETA": "deadline", "MISSING_ETA": "deadline"}


# --------------------------------------------------------------------------------------------------- windows

@dataclass(frozen=True)
class CompletedDayWindows:
    """Two adjacent completed-calendar-day windows in Cairo.

    ``end`` values are exclusive local dates. The current Cairo day is excluded even when ``as_of`` is just after
    midnight. This intentionally does not use UTC dates.
    """

    timezone: str
    as_of: str
    current_start: date
    current_end: date
    comparison_start: date
    comparison_end: date

    def range(self, name: str) -> dict[str, Any]:
        start, end = (self.current_start, self.current_end) if name == "current" else (self.comparison_start, self.comparison_end)
        return {"window": name, "timezone": self.timezone, "start_date": start.isoformat(), "end_date_exclusive": end.isoformat(),
                "completed_days": (end - start).days}

    def to_dict(self) -> dict[str, Any]:
        return {"timezone": self.timezone, "as_of": self.as_of, "current": self.range("current"), "comparison": self.range("comparison")}


def completed_day_windows(as_of: str | datetime, days: int, comparison_days: int | None = None) -> CompletedDayWindows:
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError("days must be a positive integer")
    previous = days if comparison_days is None else comparison_days
    moment = parse_time(as_of) if isinstance(as_of, str) else as_of
    if moment.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    today = moment.astimezone(CAIRO).date()
    start = today - timedelta(days=days)
    return CompletedDayWindows("Africa/Cairo", moment.isoformat(), start, today, start - timedelta(days=previous), start)


def cairo_date(timestamp: str) -> date:
    return parse_time(timestamp).astimezone(CAIRO).date()


def window_assignment(ready_for_approval_at: str | None, windows: CompletedDayWindows) -> str:
    """Assign by first Ready For Approval in Cairo (D24, D42); never by a later label timestamp."""
    if ready_for_approval_at is None:
        return "excluded"
    local_day = cairo_date(ready_for_approval_at)
    if windows.current_start <= local_day < windows.current_end:
        return "current"
    if windows.comparison_start <= local_day < windows.comparison_end:
        return "comparison"
    return "outside"


def _metric_only(reason: str) -> str | None:
    return next((metric for marker, metric in METRIC_ONLY_EXCLUSIONS.items() if marker in reason), None)


def evaluation_cohort(cycles: Iterable[CycleRecord], windows: CompletedDayWindows, rule_version: str) -> dict[str, Any]:
    """Partition completed, attributed projects into the two windows while retaining every exclusion (team scope)."""
    included: dict[str, list[CycleRecord]] = {"current": [], "comparison": []}
    excluded: list[dict[str, Any]] = []
    metric_specific: list[dict[str, Any]] = []
    outside: list[str] = []
    for cycle in sorted(cycles, key=lambda value: (value.ready_for_approval_at or "", value.monday_item_id)):
        window = window_assignment(cycle.ready_for_approval_at, windows)
        reasons: list[str] = []
        if cycle.state != COMPLETED:
            reasons.append("cycle_not_completed")
        if cycle.editor_id is None:
            reasons.append("editor_unresolved")
        reasons.extend(reason for reason in cycle.exclusions if _metric_only(reason) is None)
        by_metric: dict[str, list[str]] = {}
        for reason in cycle.exclusions:
            metric = _metric_only(reason)
            if metric is not None:
                by_metric.setdefault(metric, []).append(reason)
        if reasons:
            excluded.append({"cycle_id": cycle.cycle_id, "monday_item_id": cycle.monday_item_id, "editor_id": cycle.editor_id,
                             "window": window, "reasons": sorted(set(reasons))})
            continue
        for metric, metric_reasons in sorted(by_metric.items()):
            metric_specific.append({"cycle_id": cycle.cycle_id, "monday_item_id": cycle.monday_item_id, "editor_id": cycle.editor_id,
                                    "window": window, "metric": metric, "reasons": sorted(metric_reasons)})
        if window in included:
            included[window].append(cycle)
        else:
            outside.append(cycle.cycle_id)
    return {
        "windows": windows.to_dict(),
        "current": included["current"],
        "comparison": included["comparison"],
        "coverage": {
            "scope": "team",
            "current_projects": len(included["current"]),
            "comparison_projects": len(included["comparison"]),
            "excluded_projects": len(excluded),
            "outside_window_projects": len(outside),
            "exclusions": excluded,
            "metric_specific_exclusions": metric_specific,
            "rule_version": rule_version,
        },
    }


def editor_window_coverage(cohort: Mapping[str, Any], editor_id: str) -> dict[str, Any]:
    """The Editor's own share of the window partition (the team partition stays in ``coverage.window`` with scope team)."""
    coverage = cohort["coverage"]
    exclusions = [row for row in coverage["exclusions"] if row["editor_id"] == editor_id and row["window"] in {"current", "comparison"}]
    specific = [row for row in coverage["metric_specific_exclusions"] if row["editor_id"] == editor_id and row["window"] in {"current", "comparison"}]
    return {
        "scope": "editor",
        "current_projects": sum(cycle.editor_id == editor_id for cycle in cohort["current"]),
        "comparison_projects": sum(cycle.editor_id == editor_id for cycle in cohort["comparison"]),
        "excluded_projects": len(exclusions),
        "exclusion_reasons": dict(sorted(Counter(reason for row in exclusions for reason in row["reasons"]).items())),
        "exclusions": exclusions,
        "metric_specific_exclusions": specific,
        "rule_version": coverage["rule_version"],
    }


# --------------------------------------------------------------------------------------------------- evidence

@dataclass(frozen=True)
class EvidenceScope:
    """What every evidence block names: the Monday board, the columns by role and the calculation time."""

    board_id: str
    columns: Mapping[str, str]
    calculated_at: str

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any], calculated_at: str) -> EvidenceScope:
        board = contract["source_board"]
        columns = {"status": board["status_column_id"], "editor": board["editor_column_id"], "video_type": board["video_type_column_id"],
                   "requested_eta": board["requested_eta_column_id"], "performance_issues": board["performance_issues_column_id"],
                   "for_bonus": board["for_bonus_column_id"]}
        return cls(str(board["board_id"]), columns, calculated_at)

    def block(self, *, roles: Sequence[str], rule_version: str | None, date_range: Mapping[str, Any] | None, calculation: str,
              sample: Mapping[str, Any], records: Sequence[Mapping[str, Any]], exclusions: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
        return {"source": "monday", "monday_board_id": self.board_id, "column_ids": sorted({self.columns[role] for role in roles}),
                "rule_version": rule_version, "calculated_at": self.calculated_at, "date_range": dict(date_range) if date_range else None,
                "calculation": calculation, "sample": dict(sample), "records": [dict(record) for record in records],
                "exclusions": [dict(row) for row in exclusions]}


def _ids(*values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        for item in (value if isinstance(value, (list, tuple)) else [value]):
            if item and str(item) not in out:
                out.append(str(item))
    return out


def speed_record(cycle: CycleRecord) -> dict[str, Any]:
    """One first-pass project as Speed evidence: its two status events, Editor and Video Type observations."""
    return {"monday_item_id": cycle.monday_item_id, "cycle_id": cycle.cycle_id,
            "event_ids": _ids((cycle.in_progress_event or {}).get("event_id"), (cycle.ready_for_approval_event or {}).get("event_id"),
                              cycle.editor_event_id, cycle.video_type_event_id),
            "source_timestamps": _ids(cycle.in_progress_at, cycle.ready_for_approval_at),
            "source_values": {"editor_id": cycle.editor_id, "cohort_key": cycle.cohort_key, "in_progress_at": cycle.in_progress_at,
                              "ready_for_approval_at": cycle.ready_for_approval_at, "duration_seconds": cycle.duration_seconds}}


def deadline_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """One deadline-classifiable project, from its contract-valid deadline metric."""
    metric = row["metric"]
    evidence = metric["evidence"]
    return {"monday_item_id": evidence["monday_item_id"], "cycle_id": row["cycle_id"], "event_ids": list(evidence["event_ids"]),
            "source_timestamps": [value for value in evidence["source_timestamps"] if value],
            "source_values": {"editor_id": metric["editor_id"], "ready_for_approval_at": metric["ready_for_approval_at"],
                              "requested_eta": metric["requested_eta"], "delta_seconds": metric["delta_seconds"], "result": metric["result"]}}


def quality_record(cycle: CycleRecord, occurrences: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One eligible completed project in the Quality denominator, with every label on it (scored or not)."""
    labels = [{"label": metric["performance_label"], "label_class": metric["evidence"]["source_values"]["label_class"],
               "scored_quality": metric["evidence"]["source_values"]["scoring_eligible"], "column_id": metric["label_column_id"],
               "event_ids": list(metric["evidence"]["event_ids"]), "source_timestamps": list(metric["evidence"]["source_timestamps"])}
              for metric in occurrences]
    return {"monday_item_id": cycle.monday_item_id, "cycle_id": cycle.cycle_id,
            "event_ids": _ids((cycle.ready_for_approval_event or {}).get("event_id"), cycle.editor_event_id, *[label["event_ids"] for label in labels]),
            "source_timestamps": _ids(cycle.ready_for_approval_at, *[label["source_timestamps"] for label in labels]),
            "source_values": {"editor_id": cycle.editor_id, "ready_for_approval_at": cycle.ready_for_approval_at, "labels": labels}}


def _rate(count: int, total: int) -> float | None:
    return count / total if total else None


def _shown(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


# --------------------------------------------------------------------------------------------------- components

def _component(state: str, reason: str | None, facts: Mapping[str, Any], rule: Rule, evidence: Mapping[str, Any]) -> dict[str, Any]:
    if state not in (*CLASSIFIED_STATES, NOT_CLASSIFIABLE):
        raise ValueError(f"invalid component state {state!r}")
    if (state == NOT_CLASSIFIABLE) != (reason is not None):
        raise ValueError("a component is not classifiable exactly when it has a reason")
    return {"state": state, "reason": reason, "facts": dict(facts), "rule": rule.state(), "evidence": dict(evidence)}


def quality_rates(editor_id: str, occurrences: Iterable[Mapping[str, Any]], cycles: Iterable[CycleRecord], scope: EvidenceScope,
                  date_range: Mapping[str, Any] | None, rule_version: str | None) -> dict[str, Any]:
    """Visible label taxonomy plus the two D39 rates over the Editor's eligible completed projects in one window.

    Whether a label counts comes only from the contract registry (``scored_quality``, D30); Context labels never count."""
    projects = sorted((cycle for cycle in cycles if cycle.state == COMPLETED and cycle.editor_id == editor_id), key=lambda c: c.monday_item_id)
    by_item: dict[str, list[Mapping[str, Any]]] = {cycle.monday_item_id: [] for cycle in projects}
    for metric in occurrences:
        item = metric["evidence"]["monday_item_id"]
        if metric["editor_id"] == editor_id and item in by_item:
            by_item[item].append(metric)
    visible: dict[str, Counter[str]] = {name: Counter() for name in ("positive", "negative", "context")}
    scored = {"Positive": 0, "Negative": 0}
    excluded: list[dict[str, Any]] = []
    for item, metrics in sorted(by_item.items()):
        for metric in metrics:
            values = metric["evidence"]["source_values"]
            label, label_class = metric["performance_label"], values["label_class"]
            visible[label_class.lower()][label] += 1
            if label_class == "Context" or not values["scoring_eligible"]:
                excluded.append({"monday_item_id": item, "label": label, "label_class": label_class, "column_id": metric["label_column_id"],
                                 "event_ids": list(metric["evidence"]["event_ids"]),
                                 "reason": "context_label" if label_class == "Context" else "not_scored_quality"})
            else:
                scored[label_class] += 1
    total = len(projects)
    evidence = scope.block(
        roles=("status", "editor", "performance_issues", "for_bonus"), rule_version=rule_version, date_range=date_range,
        calculation=("positive_rate = scored Positive label occurrences / eligible completed projects; negative_rate = scored Negative "
                     "label occurrences / eligible completed projects (D39). A label is scored only when its registry entry has "
                     "scored_quality=true; Context labels never are."),
        sample={"eligible_completed_projects": total, "scored_positive_occurrences": scored["Positive"], "scored_negative_occurrences": scored["Negative"]},
        records=[quality_record(cycle, by_item[cycle.monday_item_id]) for cycle in projects])
    return {
        "eligible_completed_projects": total,
        "positive_count": scored["Positive"],
        "positive_rate": _shown(_rate(scored["Positive"], total)),
        "negative_count": scored["Negative"],
        "negative_rate": _shown(_rate(scored["Negative"], total)),
        "visible": {name: [{"label": label, "occurrences": count} for label, count in sorted(counts.items())] for name, counts in visible.items()},
        "scoring_exclusions": excluded,
        "evidence": evidence,
    }


def quality_component(facts: Mapping[str, Any], rule: Rule) -> dict[str, Any]:
    summary = {key: facts[key] for key in ("eligible_completed_projects", "positive_count", "positive_rate", "negative_count", "negative_rate")}
    if not rule.approved:
        return _component(NOT_CLASSIFIABLE, RULE_NOT_APPROVED, summary, rule, facts["evidence"])
    total = facts["eligible_completed_projects"]
    if total < rule.values["minimum_project_sample_size"]:
        return _component(NOT_CLASSIFIABLE, INSUFFICIENT_SAMPLE, summary, rule, facts["evidence"])
    negative = facts["negative_count"] / total
    positive = facts["positive_count"] / total
    state = NEGATIVE if negative >= rule.values["negative_rate_threshold"] else POSITIVE if positive >= rule.values["positive_rate_threshold"] else NEUTRAL
    return _component(state, None, summary, rule, facts["evidence"])


def _benchmark_eligible(cycle: CycleRecord, mapping: VideoTypeMapping | None) -> bool:
    return bool(speed_eligible(cycle) and cycle.video_type is not None and cohort_benchmark_eligibility(cycle.video_type.canonical_ids, mapping)[0])


def speed_benchmarks(editor_id: str, cycles: Sequence[CycleRecord], mapping: VideoTypeMapping | None, rule: Rule, scope: EvidenceScope,
                     date_range: Mapping[str, Any] | None) -> dict[str, Any]:
    """Per Video Type: the Editor's first-pass median against the leave-one-out median of the other Editors (D32, D36).

    The subject's projects never enter the comparator. With no other Editor the verdict is never faster/slower/similar
    (D35). Bands are compared on the unrounded percentage."""
    eligible = [cycle for cycle in cycles if _benchmark_eligible(cycle, mapping)]
    by_type: dict[str, list[CycleRecord]] = {}
    for cycle in eligible:
        assert cycle.cohort_key is not None
        by_type.setdefault(cycle.cohort_key, []).append(cycle)
    mine_excluded: list[dict[str, Any]] = [{"monday_item_id": cycle.monday_item_id, "cycle_id": cycle.cycle_id,
                      "reasons": sorted(set(cycle.exclusions) | ({"cohort_not_benchmark_eligible"} if speed_eligible(cycle) else {"not_speed_eligible"}))}
                     for cycle in cycles if cycle.editor_id == editor_id and cycle.state == COMPLETED and not _benchmark_eligible(cycle, mapping)]
    minimum_editor = rule.value("minimum_editor_sample_size")
    minimum_comparator = rule.value("minimum_comparator_sample_size")
    minimum_editors = rule.value("minimum_comparator_editor_count")
    rows: list[dict[str, Any]] = []
    for cohort_key, cohort in sorted(by_type.items()):
        mine = sorted((cycle for cycle in cohort if cycle.editor_id == editor_id), key=lambda c: c.monday_item_id)
        if not mine:
            continue
        peers = sorted((cycle for cycle in cohort if cycle.editor_id != editor_id), key=lambda c: (str(c.editor_id), c.monday_item_id))
        mine_median = median_seconds(int(cycle.duration_seconds) for cycle in mine if cycle.duration_seconds is not None)
        peer_median = median_seconds(int(cycle.duration_seconds) for cycle in peers if cycle.duration_seconds is not None)
        comparator_editors = len({cycle.editor_id for cycle in peers})
        pct = 100 * (mine_median - peer_median) / peer_median if mine_median is not None and peer_median else None
        verdict, reason = NOT_CLASSIFIABLE, None
        if not peers:
            reason = NO_OTHER_EDITORS
        elif not rule.approved:
            reason = RULE_NOT_APPROVED
        elif len(mine) < minimum_editor or len(peers) < minimum_comparator:
            reason = INSUFFICIENT_SAMPLE
        elif comparator_editors < minimum_editors:
            reason = INSUFFICIENT_COMPARATOR_EDITORS
        else:
            assert pct is not None
            verdict = FASTER if pct < rule.values["faster_band"] else SLOWER if pct > rule.values["slower_band"] else SIMILAR
        sample = {"editor_projects": len(mine), "comparator_projects": len(peers), "comparator_editor_count": comparator_editors,
                  "minimum_editor_projects": minimum_editor, "minimum_comparator_projects": minimum_comparator,
                  "minimum_comparator_editors": minimum_editors}
        rows.append({
            "cohort_key": cohort_key,
            "editor_sample_size": len(mine),
            "editor_median_seconds": mine_median,
            "comparator_sample_size": len(peers),
            "comparator_editor_count": comparator_editors,
            "comparator_median_seconds": peer_median,
            "editor_minus_comparator_seconds": mine_median - peer_median if mine_median is not None and peer_median is not None else None,
            "editor_vs_comparator_pct": round(pct, 1) if pct is not None else None,
            "benchmark_excludes_subject_editor": True,
            "verdict": verdict,
            "reason": reason,
            "evidence": scope.block(
                roles=("status", "editor", "video_type"), rule_version=rule.rule_version, date_range=date_range,
                calculation=("editor median = median of the Editor's first-pass In Progress -> Ready For Approval durations in this exact "
                             "Video Type; comparator median = the same over every other eligible Editor's projects (the Editor excluded); "
                             "pct = (editor - comparator) / comparator x 100, compared unrounded with the approved bands"),
                sample=sample, records=[speed_record(cycle) for cycle in (*mine, *peers)],
                exclusions=[row for row in mine_excluded if row["reasons"] and _cohort_of(cycles, row["cycle_id"]) == cohort_key]),
        })
    return {"cohorts": rows, "excluded_editor_projects": mine_excluded, "rule": rule.state()}


def _cohort_of(cycles: Sequence[CycleRecord], cycle_id: str) -> str | None:
    return next((cycle.cohort_key for cycle in cycles if cycle.cycle_id == cycle_id), None)


def speed_component(editor_id: str, benchmarks: Mapping[str, Any], rule: Rule, scope: EvidenceScope, date_range: Mapping[str, Any] | None) -> dict[str, Any]:
    """D38: project-weighted majority over classified Video Types; percentages are never averaged."""
    rows = benchmarks["cohorts"]
    weighted: Counter[str] = Counter()
    for row in rows:
        if row["verdict"] in {FASTER, SIMILAR, SLOWER}:
            weighted[row["verdict"]] += row["editor_sample_size"]
    total = sum(weighted.values())
    records = [record for row in rows for record in row["evidence"]["records"] if record["source_values"]["editor_id"] == editor_id]
    facts = {"project_weights": {key: weighted[key] for key in (FASTER, SIMILAR, SLOWER)}, "classifiable_projects": total,
             "video_types": len(rows), "verdicts": {row["cohort_key"]: {"verdict": row["verdict"], "reason": row["reason"],
                                                                         "editor_sample_size": row["editor_sample_size"]} for row in rows}}
    evidence = scope.block(roles=("status", "editor", "video_type"), rule_version=rule.rule_version, date_range=date_range,
                           calculation=("each classified Video Type verdict is weighted by the Editor's project count in it; "
                                        "faster > 50% -> positive, slower > 50% -> negative, otherwise neutral (D38); each Video Type's "
                                        "own comparison is in speed.cohorts[].evidence"),
                           sample={"editor_projects": len(records), "classifiable_projects": total}, records=records,
                           exclusions=benchmarks["excluded_editor_projects"])
    if not rule.approved:
        return _component(NOT_CLASSIFIABLE, RULE_NOT_APPROVED, facts, rule, evidence)
    if not total:
        reasons = {row["reason"] for row in rows}
        return _component(NOT_CLASSIFIABLE, reasons.pop() if len(reasons) == 1 else INSUFFICIENT_SAMPLE, facts, rule, evidence)
    state = POSITIVE if weighted[FASTER] > total / 2 else NEGATIVE if weighted[SLOWER] > total / 2 else NEUTRAL
    return _component(state, None, facts, rule, evidence)


def late_rate_facts(editor_id: str, rows: Sequence[Mapping[str, Any]], scope: EvidenceScope, date_range: Mapping[str, Any] | None,
                    rule_version: str | None) -> dict[str, Any]:
    """The Editor's absolute deadline facts in one window (D45: facts stay absolute)."""
    mine = sorted((row for row in rows if row["metric"]["editor_id"] == editor_id), key=lambda row: row["monday_item_id"])
    late = sum(row["metric"]["result"] == "late" for row in mine)
    return {"deadline_classifiable_projects": len(mine), "late": late, "absolute_late_rate": _shown(_rate(late, len(mine))),
            "evidence": scope.block(roles=("status", "editor", "requested_eta"), rule_version=rule_version, date_range=date_range,
                                    calculation="late rate = projects with Ready For Approval after the Requested ETA / deadline-classifiable projects",
                                    sample={"deadline_classifiable_projects": len(mine), "late": late},
                                    records=[deadline_record(row) for row in mine])}


def deadline_component(editor_id: str, rows: Sequence[Mapping[str, Any]], rule: Rule, scope: EvidenceScope, date_range: Mapping[str, Any] | None,
                       exclusions: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """D45: the Editor's late rate against the other Editors' late rate in the same window; never an absolute fallback."""
    mine = sorted((row for row in rows if row["metric"]["editor_id"] == editor_id), key=lambda row: row["monday_item_id"])
    peers = sorted((row for row in rows if row["metric"]["editor_id"] != editor_id), key=lambda row: (row["metric"]["editor_id"], row["monday_item_id"]))
    late = lambda values: sum(row["metric"]["result"] == "late" for row in values)
    my_rate, peer_rate = _rate(late(mine), len(mine)), _rate(late(peers), len(peers))
    difference = my_rate - peer_rate if my_rate is not None and peer_rate is not None else None
    facts = {"deadline_classifiable_projects": len(mine), "late": late(mine), "absolute_late_rate": _shown(my_rate),
             "comparator_projects": len(peers), "comparator_editor_count": len({row["metric"]["editor_id"] for row in peers}),
             "comparator_late": late(peers), "comparator_late_rate": _shown(peer_rate), "late_rate_difference": _shown(difference)}
    evidence = scope.block(roles=("status", "editor", "requested_eta"), rule_version=rule.rule_version, date_range=date_range,
                           calculation=("difference = Editor late rate - late rate of every other Editor's deadline-classifiable projects "
                                        "(the Editor excluded); compared unrounded: below better_band positive, above worse_band negative"),
                           sample={"editor_projects": len(mine), "comparator_projects": len(peers),
                                   "minimum_editor_projects": rule.value("minimum_editor_sample_size"),
                                   "minimum_comparator_projects": rule.value("minimum_comparator_sample_size")},
                           records=[deadline_record(row) for row in (*mine, *peers)], exclusions=exclusions)
    if not peers or not mine:
        return _component(NOT_CLASSIFIABLE, NO_OTHER_EDITORS if not peers else INSUFFICIENT_SAMPLE, facts, rule, evidence)
    if not rule.approved:
        return _component(NOT_CLASSIFIABLE, RULE_NOT_APPROVED, facts, rule, evidence)
    if len(mine) < rule.values["minimum_editor_sample_size"] or len(peers) < rule.values["minimum_comparator_sample_size"]:
        return _component(NOT_CLASSIFIABLE, INSUFFICIENT_SAMPLE, facts, rule, evidence)
    assert difference is not None
    state = POSITIVE if difference < rule.values["better_band"] else NEGATIVE if difference > rule.values["worse_band"] else NEUTRAL
    return _component(state, None, facts, rule, evidence)


def overall_status(components: Mapping[str, Mapping[str, Any]], policy: InterpretationPolicy, date_range: Mapping[str, Any] | None,
                   calculated_at: str) -> dict[str, Any]:
    """D37 lookup of the three component states; no arithmetic, weight or fallback status.

    Fewer than the minimum classifiable components (D41) is a data state, ``Not enough evidence to classify`` (D47) -- unless
    the missing classifications are themselves caused by unapproved rules, which is ``Not enough approved logic to
    classify`` (D25). "Why this status" lists every component's state and reason, and the lookup's own approval state."""
    states = {name: components[name]["state"] for name in SCORED_COMPONENTS}
    classifiable = [name for name in SCORED_COMPONENTS if states[name] in CLASSIFIED_STATES]
    why = [{"component": name, "state": states[name], "reason": components[name]["reason"]} for name in SCORED_COMPONENTS]
    why.append({"component": "overall_lookup", "state": "approved" if policy.overall.approved else RULE_NOT_APPROVED,
                "reason": None if policy.overall.approved else RULE_NOT_APPROVED})
    key = "|".join(states[name] for name in SCORED_COMPONENTS)
    base = {"component_states": states, "classifiable_components": len(classifiable),
            "minimum_classifiable_components": policy.minimum_classifiable_components, "why": why, "rule": policy.overall.state(),
            "evidence": {"source": "monday", "rule_version": policy.overall.rule_version, "calculated_at": calculated_at,
                         "date_range": dict(date_range) if date_range else None,
                         "calculation": "Overall Status = lookup_table[quality|speed|deadline component states] (D37); no weights or arithmetic",
                         "components": {name: f"{name}.component" for name in SCORED_COMPONENTS},
                         "lookup_key": key}}
    unapproved_components = [name for name in SCORED_COMPONENTS if components[name]["reason"] == RULE_NOT_APPROVED]
    enough = len(classifiable) >= policy.minimum_classifiable_components and bool({"quality", "deadline"} & set(classifiable))
    if not enough:
        # A component held back by an unapproved rule makes this a logic gap (D25); otherwise it is a data state (D47).
        logic_missing = bool(unapproved_components)
        return {**base, "status": None, "status_label": NOT_ENOUGH_APPROVED_LOGIC if logic_missing else NOT_ENOUGH_EVIDENCE,
                "status_state": RULE_NOT_APPROVED if logic_missing else "not_enough_evidence_to_classify", "reason": NOT_ENOUGH_COMPONENTS}
    if not policy.overall.approved:
        return {**base, "status": None, "status_label": NOT_ENOUGH_APPROVED_LOGIC, "status_state": RULE_NOT_APPROVED, "reason": RULE_NOT_APPROVED}
    status = policy.overall.values["lookup_table"][key]
    if status == NOT_ENOUGH_EVIDENCE:
        return {**base, "status": None, "status_label": NOT_ENOUGH_EVIDENCE, "status_state": "not_enough_evidence_to_classify", "reason": "lookup"}
    return {**base, "status": status, "status_label": status, "status_state": CLASSIFIED, "reason": None}


# --------------------------------------------------------------------------------------------------- recent change / trend

def recent_change(measurement: str, current: Mapping[str, Any], comparison: Mapping[str, Any], policy: InterpretationPolicy) -> dict[str, Any]:
    """D23: the factual current-minus-comparison difference, and a Trend label only under an approved rule.

    ``current`` and ``comparison`` are ``{"value", "sample", "evidence"}`` for the same measurement in each window. Whether a
    rise is better comes from the measurement's direction (a lower late rate or negative rate is an improvement)."""
    direction = policy.trend_directions[measurement]
    value, previous = current["value"], comparison["value"]
    difference = value - previous if value is not None and previous is not None else None
    shown = lambda number: round(number, 4) if isinstance(number, float) else number
    result: dict[str, Any] = {
        "measurement": measurement, "direction": direction, "current": shown(value), "comparison": shown(previous),
        "difference": shown(difference),
        "current_sample": current["sample"], "comparison_sample": comparison["sample"],
        "trend": None, "trend_reason": None, "rule": policy.trend.state(),
        "evidence": {"current": current["evidence"], "comparison": comparison["evidence"],
                     "calculation": "difference = current window value - comparison window value; each value is recomputable from its window's records"},
    }
    if difference is None:
        result["trend_reason"] = NO_VALUE_IN_A_WINDOW
    elif not policy.trend.approved:
        result["trend_reason"] = RULE_NOT_APPROVED
    elif min(current["sample"], comparison["sample"]) < policy.trend.values["minimum_sample_size"]:
        result["trend_reason"] = INSUFFICIENT_SAMPLE
    elif abs(difference) < policy.trend.values["material_change_thresholds"][measurement]:
        result["trend"] = "Stable"
    else:
        improving = difference > 0 if direction == HIGHER_IS_BETTER else difference < 0
        result["trend"] = "Improving" if improving else "Declining"
    return result
