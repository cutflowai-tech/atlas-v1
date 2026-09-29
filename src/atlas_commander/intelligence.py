"""Contract 1.5 deterministic Editor-intelligence building blocks.

This module deliberately does not alter the contract 1.0--1.4 profile builders.  It
accepts the factual records those builders already produce and adds the pending 1.5
interpretation framework.  A business classification is returned only when its rule
contains both an explicit approval marker and the decision-log ID that authorises it.
Absent or partially configured rules therefore remain facts with ``rule_not_approved``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from atlas_commander.cycles import COMPLETED, CycleRecord, parse_time
from atlas_commander.metrics import cohort_benchmark_eligibility, deadline_eligible, speed_eligible
from atlas_commander.video_type import VideoTypeMapping

CAIRO = ZoneInfo("Africa/Cairo")

POSITIVE = "Positive"
NEUTRAL = "Neutral"
NEGATIVE = "Negative"
NOT_CLASSIFIABLE = "Not classifiable"
COMPONENT_STATES = frozenset({POSITIVE, NEUTRAL, NEGATIVE, NOT_CLASSIFIABLE})

FASTER = "Faster"
SIMILAR = "Similar"
SLOWER = "Slower"
SPEED_VERDICTS = frozenset({FASTER, SIMILAR, SLOWER, NOT_CLASSIFIABLE})

RULE_NOT_APPROVED = "rule_not_approved"
INSUFFICIENT_SAMPLE = "insufficient_sample"
NO_OTHER_EDITORS = "no_other_editors_in_cohort"
NOT_ENOUGH_COMPONENTS = "not_enough_classifiable_components"
NOT_ENOUGH_EVIDENCE = "Not enough evidence to classify"

SCORED_POSITIVE_LABELS = frozenset({"1- Exceptional Quality", "Client Praise", "Saved Rush Project"})
SCORED_NEGATIVE_EXCLUSIONS = frozenset({"Late Delivery"})
SCORED_POSITIVE_EXCLUSIONS = frozenset({"On Time Delivery"})


@dataclass(frozen=True)
class CompletedDayWindows:
    """Two adjacent completed-calendar-day windows in Cairo.

    ``end`` values are exclusive local dates.  The current Cairo day is excluded even
    when ``as_of`` is just after midnight.  This intentionally does not use UTC dates.
    """

    timezone: str
    as_of: str
    current_start: date
    current_end: date
    comparison_start: date
    comparison_end: date

    def to_dict(self) -> dict[str, Any]:
        return {
            "timezone": self.timezone,
            "as_of": self.as_of,
            "current": {"start_date": self.current_start.isoformat(), "end_date_exclusive": self.current_end.isoformat(), "completed_days": (self.current_end - self.current_start).days},
            "comparison": {"start_date": self.comparison_start.isoformat(), "end_date_exclusive": self.comparison_end.isoformat(), "completed_days": (self.comparison_end - self.comparison_start).days},
        }


@dataclass(frozen=True)
class IntelligencePolicy:
    """Best-effort reader for versioned 1.5 sections without inventing defaults."""

    window_days: int
    window_rule_version: str
    quality: Mapping[str, Any] | None
    speed: Mapping[str, Any] | None
    deadline: Mapping[str, Any] | None
    overall: Mapping[str, Any] | None
    trend: Mapping[str, Any] | None

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> IntelligencePolicy:
        # Contract 1.5's canonical executable shape keeps factual rules beside their
        # source metric and interpretation thresholds under ``interpretation``.
        # Translate that shape explicitly; no missing value receives a default
        # classification threshold.
        if str(contract.get("contract_version")) == "1.5.0" and isinstance(contract.get("time_windows"), Mapping):
            windows_value = contract.get("time_windows")
            assert isinstance(windows_value, Mapping)
            windows: Mapping[str, Any] = windows_value
            current_window_value = windows.get("current_window")
            current_window: Mapping[str, Any] = current_window_value if isinstance(current_window_value, Mapping) else {}
            days = current_window.get("completed_days")
            if isinstance(days, bool) or not isinstance(days, int) or days < 1:
                raise ValueError("contract 1.5 current-window completed_days must be a positive integer")
            if windows.get("timezone") != "Africa/Cairo":
                raise ValueError("contract 1.5 evaluation windows must use Africa/Cairo")
            interpretation_value = contract.get("interpretation")
            interpretation: Mapping[str, Any] = interpretation_value if isinstance(interpretation_value, Mapping) else {}
            quality = interpretation.get("quality_component") if isinstance(interpretation.get("quality_component"), Mapping) else None
            speed_root_value = contract.get("speed_benchmark")
            speed_root: Mapping[str, Any] = speed_root_value if isinstance(speed_root_value, Mapping) else {}
            speed_component_value = speed_root.get("component")
            speed_component_rule: Mapping[str, Any] = speed_component_value if isinstance(speed_component_value, Mapping) else {}
            speed = {**speed_root, **speed_component_rule}
            deadline_root_value = contract.get("deadline")
            deadline_root: Mapping[str, Any] = deadline_root_value if isinstance(deadline_root_value, Mapping) else {}
            deadline = deadline_root.get("component") if isinstance(deadline_root.get("component"), Mapping) else None
            overall = interpretation.get("overall_status") if isinstance(interpretation.get("overall_status"), Mapping) else None
            trend = interpretation.get("trend") if isinstance(interpretation.get("trend"), Mapping) else None
            versions_value = contract.get("rule_versions")
            versions: Mapping[str, Any] = versions_value if isinstance(versions_value, Mapping) else {}

            def versioned(rule: Mapping[str, Any] | None, key: str) -> Mapping[str, Any] | None:
                if rule is None:
                    return None
                return {"rule_version": versions.get(key), **rule}

            return cls(
                days,
                str(windows.get("rule_version") or versions.get("windowing") or "cairo-completed-days-v1.0"),
                versioned(quality, "quality_component"),
                versioned(speed, "speed_component"),
                versioned(deadline, "deadline_component"),
                versioned(overall, "overall_status"),
                versioned(trend, "trend"),
            )
        intelligence = contract.get("editor_intelligence")
        root: Mapping[str, Any] = intelligence if isinstance(intelligence, Mapping) else contract
        components = root.get("components") or root.get("component_rules")
        components = components if isinstance(components, Mapping) else {}

        def section(name: str, *aliases: str) -> Mapping[str, Any] | None:
            for container in (components, root, contract):
                for key in (name, *aliases):
                    value = container.get(key)
                    if isinstance(value, Mapping):
                        nested = value.get("component_rule") or value.get("classification_rule")
                        return nested if isinstance(nested, Mapping) else value
            return None

        window = section("evaluation_window", "completed_day_window", "windows") or {}
        days = window.get("days") or window.get("current_window_days") or 30
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise ValueError("evaluation window days must be a positive integer")
        if window.get("timezone", "Africa/Cairo") != "Africa/Cairo":
            raise ValueError("contract 1.5 evaluation windows must use Africa/Cairo")
        return cls(days, str(window.get("rule_version") or "evaluation-window-v1.5"), section("quality", "quality_component", "quality_labels"),
                   section("speed", "speed_component", "speed_benchmark"), section("deadline", "deadline_component"),
                   section("overall", "overall_status"), section("trend", "trend_rule"))


def completed_day_windows(as_of: str | datetime, days: int = 30) -> CompletedDayWindows:
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError("days must be a positive integer")
    moment = parse_time(as_of) if isinstance(as_of, str) else as_of
    if moment.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    today = moment.astimezone(CAIRO).date()
    return CompletedDayWindows("Africa/Cairo", moment.isoformat(), today - timedelta(days=days), today, today - timedelta(days=days * 2), today - timedelta(days=days))


def window_assignment(ready_for_approval_at: str | None, windows: CompletedDayWindows) -> dict[str, Any]:
    """Assign by first Ready For Approval in Cairo; never by a later label timestamp."""
    if ready_for_approval_at is None:
        return {"window": "excluded", "reason": "missing_first_ready_for_approval", "anchor": None, "timezone": windows.timezone}
    local = parse_time(ready_for_approval_at).astimezone(CAIRO)
    local_day = local.date()
    if windows.current_start <= local_day < windows.current_end:
        name = "current"
    elif windows.comparison_start <= local_day < windows.comparison_end:
        name = "comparison"
    else:
        name = "outside"
    return {"window": name, "reason": None, "anchor": ready_for_approval_at, "anchor_cairo": local.isoformat(), "anchor_cairo_date": local_day.isoformat(), "timezone": windows.timezone}


def evaluation_cohort(cycles: Iterable[CycleRecord], as_of: str | datetime, days: int = 30, rule_version: str = "evaluation-window-v1.5") -> dict[str, Any]:
    """Partition completed, attributed projects while retaining every exclusion."""
    windows = completed_day_windows(as_of, days)
    included: dict[str, list[CycleRecord]] = {"current": [], "comparison": []}
    excluded: list[dict[str, Any]] = []
    data_quality_flags: list[dict[str, Any]] = []
    outside: list[str] = []
    for cycle in sorted(cycles, key=lambda value: (value.ready_for_approval_at or "", value.monday_item_id)):
        assignment = window_assignment(cycle.ready_for_approval_at, windows)
        reasons: list[str] = []
        if cycle.state != COMPLETED:
            reasons.append("cycle_not_completed")
        if cycle.editor_id is None:
            reasons.append("editor_unresolved")
        metric_only = {
            reason for reason in cycle.exclusions
            if "VIDEO_TYPE" in reason or "REQUESTED_ETA" in reason or reason.startswith("MISSING_ETA")
        }
        reasons.extend(reason for reason in cycle.exclusions if reason not in metric_only)
        if metric_only:
            data_quality_flags.append({"cycle_id": cycle.cycle_id, "monday_item_id": cycle.monday_item_id,
                                       "metric": "speed", "reasons": sorted(metric_only)})
        if reasons:
            excluded.append({"cycle_id": cycle.cycle_id, "monday_item_id": cycle.monday_item_id, "window": assignment["window"], "reasons": sorted(set(reasons))})
        elif assignment["window"] in included:
            included[assignment["window"]].append(cycle)
        else:
            outside.append(cycle.cycle_id)
    return {
        "windows": windows.to_dict(),
        "current": included["current"],
        "comparison": included["comparison"],
        "coverage": {
            "current_projects": len(included["current"]),
            "comparison_projects": len(included["comparison"]),
            "excluded_projects": len(excluded),
            "outside_window_projects": len(outside),
            "exclusions": excluded,
            "metric_specific_exclusions": data_quality_flags,
            "outside_window_cycle_ids": outside,
            "rule_version": rule_version,
        },
    }


def _decision_ids(rule: Mapping[str, Any] | None) -> set[str]:
    if not rule:
        return set()
    approval = rule.get("approval")
    values: list[Any] = []
    for source in (rule, approval if isinstance(approval, Mapping) else {}):
        values.extend(source.get(key) for key in ("decision", "decision_id", "decision_log_id") if source.get(key) is not None)
        listed = source.get("decisions") or source.get("decision_ids")
        if isinstance(listed, (list, tuple, set)):
            values.extend(listed)
    return {str(value) for value in values}


def rule_is_approved(rule: Mapping[str, Any] | None, decision_id: str) -> bool:
    """D25: a configured value and its matching decision-log entry are both required."""
    if not rule:
        return False
    approval = rule.get("approval")
    marker = rule.get("approved") is True or (isinstance(approval, Mapping) and approval.get("approved") is True)
    return marker and decision_id in _decision_ids(rule)


def _rule_version(rule: Mapping[str, Any] | None) -> str | None:
    if not rule:
        return None
    value = rule.get("rule_version") or rule.get("version")
    return str(value) if value is not None else None


def _component(state: str, reason: str | None, facts: Mapping[str, Any], rule: Mapping[str, Any] | None, evidence: Mapping[str, Any]) -> dict[str, Any]:
    if state not in COMPONENT_STATES:
        raise ValueError(f"invalid component state {state!r}")
    return {"state": state, "reason": reason, "facts": dict(facts), "rule_version": _rule_version(rule), "evidence": dict(evidence)}


def _metric_label_class(metric: Mapping[str, Any]) -> str:
    values = ((metric.get("evidence") or {}).get("source_values") or {})
    value = str(values.get("label_class") or "Negative").title()
    return value if value in {"Positive", "Negative", "Context"} else "Context"


def quality_rates(editor_id: str, occurrences: Iterable[Mapping[str, Any]], eligible_cycles: Iterable[CycleRecord], rule_version: str = "quality-rates-v1.5") -> dict[str, Any]:
    """Visible label taxonomy plus the two D39 scored rates.

    Legacy occurrences have no class marker and are Performance Issues, so they remain
    Negative.  Lateness labels and all Context labels stay visible but never score.
    """
    cycles = [cycle for cycle in eligible_cycles if cycle.state == COMPLETED and cycle.editor_id == editor_id]
    item_ids = {cycle.monday_item_id for cycle in cycles}
    mine = [
        metric
        for metric in occurrences
        if metric.get("editor_id") == editor_id and (metric.get("evidence") or {}).get("monday_item_id") in item_ids
    ]
    visible: dict[str, Counter[str]] = {name: Counter() for name in ("Positive", "Negative", "Context")}
    scored_positive: list[Mapping[str, Any]] = []
    scored_negative: list[Mapping[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for metric in mine:
        label = str(metric["performance_label"])
        label_class = _metric_label_class(metric)
        visible[label_class][label] += 1
        if label_class == "Context":
            excluded.append({"label": label, "label_class": label_class, "reason": "context_label"})
        elif (label_class == "Positive" and label in SCORED_POSITIVE_EXCLUSIONS) or (label_class == "Negative" and label in SCORED_NEGATIVE_EXCLUSIONS):
            excluded.append({"label": label, "label_class": label_class, "reason": "deadline_label_scored_once"})
        elif label_class == "Positive" and label not in SCORED_POSITIVE_LABELS:
            excluded.append({"label": label, "label_class": label_class, "reason": "positive_label_not_in_scored_registry"})
        elif label_class == "Positive":
            scored_positive.append(metric)
        elif label_class == "Negative":
            scored_negative.append(metric)
    denominator = len(cycles)
    rate = lambda count: round(count / denominator, 4) if denominator else None
    return {
        "eligible_completed_projects": denominator,
        "positive_count": len(scored_positive),
        "positive_rate": rate(len(scored_positive)),
        "negative_count": len(scored_negative),
        "negative_rate": rate(len(scored_negative)),
        "visible": {name.lower(): [{"label": label, "occurrences": count} for label, count in sorted(counts.items())] for name, counts in visible.items()},
        "scoring_exclusions": excluded,
        "evidence": {"cycle_ids": [cycle.cycle_id for cycle in cycles], "monday_item_ids": sorted(item_ids), "occurrence_event_ids": sorted({event_id for metric in mine for event_id in ((metric.get("evidence") or {}).get("event_ids") or [])}), "rule_version": rule_version},
    }


def quality_component(facts: Mapping[str, Any], rule: Mapping[str, Any] | None) -> dict[str, Any]:
    raw_evidence = facts.get("evidence")
    evidence: Mapping[str, Any] = raw_evidence if isinstance(raw_evidence, Mapping) else {}
    if not rule_is_approved(rule, "D39"):
        return _component(NOT_CLASSIFIABLE, RULE_NOT_APPROVED, facts, rule, evidence)
    configured = rule or {}
    required = ("minimum_project_sample", "negative_rate_at_least", "positive_rate_at_least")
    if any(configured.get(key) is None for key in required):
        return _component(NOT_CLASSIFIABLE, RULE_NOT_APPROVED, facts, rule, evidence)
    sample = int(facts.get("eligible_completed_projects") or 0)
    if sample < int(configured["minimum_project_sample"]):
        return _component(NOT_CLASSIFIABLE, INSUFFICIENT_SAMPLE, facts, rule, evidence)
    negative_rate = float(facts.get("negative_rate") or 0)
    positive_rate = float(facts.get("positive_rate") or 0)
    state = NEGATIVE if negative_rate >= float(configured["negative_rate_at_least"]) else POSITIVE if positive_rate >= float(configured["positive_rate_at_least"]) else NEUTRAL
    return _component(state, None, facts, rule, evidence)


def _benchmark_rule_values(rule: Mapping[str, Any]) -> tuple[int, int, float] | None:
    editor_min = rule.get("minimum_editor_sample") or rule.get("minimum_editor_sample_size")
    comparator_min = rule.get("minimum_comparator_sample") or rule.get("minimum_team_sample_size")
    band = rule.get("similar_band_pct")
    if editor_min is None or comparator_min is None or band is None:
        return None
    return int(editor_min), int(comparator_min), float(band)


def speed_benchmarks_v15(editor_id: str, cycles: Iterable[CycleRecord], mapping: VideoTypeMapping | None, rule: Mapping[str, Any] | None, calculated_at: str) -> dict[str, Any]:
    """Leave-one-out, same-Video-Type first-pass medians with explicit non-results."""
    records = list(cycles)
    eligible = [cycle for cycle in records if speed_eligible(cycle) and cycle.video_type is not None
                and cohort_benchmark_eligibility(cycle.video_type.canonical_ids, mapping)[0]]
    by_type: dict[str, list[CycleRecord]] = defaultdict(list)
    exclusions: list[dict[str, Any]] = []
    for cycle in records:
        reasons = set(cycle.exclusions)
        if not speed_eligible(cycle):
            reasons.add("not_speed_eligible")
        elif cycle.video_type is None or not cohort_benchmark_eligibility(cycle.video_type.canonical_ids, mapping)[0]:
            reasons.add("cohort_not_benchmark_eligible")
        if reasons:
            exclusions.append({"cycle_id": cycle.cycle_id, "monday_item_id": cycle.monday_item_id, "reasons": sorted(reasons)})
    for cycle in eligible:
        assert cycle.cohort_key is not None
        by_type[cycle.cohort_key].append(cycle)
    approved = rule_is_approved(rule, "D38")
    values = _benchmark_rule_values(rule or {}) if approved else None
    rows: list[dict[str, Any]] = []
    for cohort_key, cohort in sorted(by_type.items()):
        mine = [cycle for cycle in cohort if cycle.editor_id == editor_id]
        if not mine:
            continue
        peers = [cycle for cycle in cohort if cycle.editor_id != editor_id]
        mine_values = [int(cycle.duration_seconds) for cycle in mine if cycle.duration_seconds is not None]
        peer_values = [int(cycle.duration_seconds) for cycle in peers if cycle.duration_seconds is not None]
        mine_median = int(median(mine_values))
        peer_median = int(median(peer_values)) if peer_values else None
        difference = mine_median - peer_median if peer_median is not None else None
        pct = round(100 * (mine_median - peer_median) / peer_median, 1) if peer_median else None
        reason = None
        verdict = NOT_CLASSIFIABLE
        if not peers:
            reason = NO_OTHER_EDITORS
        elif values is None:
            reason = RULE_NOT_APPROVED
        else:
            editor_min, comparator_min, band = values
            if len(mine) < editor_min or len(peers) < comparator_min:
                reason = INSUFFICIENT_SAMPLE
            elif pct is not None:
                verdict = FASTER if pct < -band else SLOWER if pct > band else SIMILAR
        rows.append({
            "cohort_key": cohort_key,
            "editor_sample_size": len(mine),
            "editor_median_seconds": mine_median,
            "comparator_sample_size": len(peers),
            "comparator_editor_count": len({cycle.editor_id for cycle in peers}),
            "comparator_median_seconds": peer_median,
            "editor_minus_comparator_seconds": difference,
            "editor_vs_comparator_pct": pct,
            "benchmark_excludes_subject_editor": True,
            "verdict": verdict,
            "reason": reason,
            "rule_version": _rule_version(rule),
            "evidence": {"editor_cycle_ids": [cycle.cycle_id for cycle in mine], "comparator_cycle_ids": [cycle.cycle_id for cycle in peers], "calculated_at": calculated_at},
        })
    return {"cohorts": rows, "coverage": {"eligible_first_pass_projects": len(eligible), "excluded_projects": len(exclusions), "exclusions": exclusions}, "rule_version": _rule_version(rule)}


def speed_component(cohorts: Iterable[Mapping[str, Any]], rule: Mapping[str, Any] | None) -> dict[str, Any]:
    rows = list(cohorts)
    weighted: Counter[str] = Counter()
    cycle_ids: list[str] = []
    for row in rows:
        verdict = str(row.get("verdict"))
        if verdict in {FASTER, SIMILAR, SLOWER}:
            weighted[verdict] += int(row.get("editor_sample_size") or 0)
            cycle_ids.extend((row.get("evidence") or {}).get("editor_cycle_ids") or [])
    facts = {"project_weights": {key.lower(): weighted[key] for key in (FASTER, SIMILAR, SLOWER)}, "classifiable_projects": sum(weighted.values()), "cohorts": rows}
    evidence = {"editor_cycle_ids": cycle_ids}
    if not rule_is_approved(rule, "D38"):
        return _component(NOT_CLASSIFIABLE, RULE_NOT_APPROVED, facts, rule, evidence)
    total = sum(weighted.values())
    if not total:
        return _component(NOT_CLASSIFIABLE, INSUFFICIENT_SAMPLE, facts, rule, evidence)
    if weighted[FASTER] > total / 2:
        state = POSITIVE
    elif weighted[SLOWER] > total / 2:
        state = NEGATIVE
    else:
        state = NEUTRAL
    return _component(state, None, facts, rule, evidence)


def deadline_component(editor_id: str, results: Iterable[Mapping[str, Any]], rule: Mapping[str, Any] | None) -> dict[str, Any]:
    """Relative leave-one-out Deadline state; absolute deadline facts remain untouched."""
    rows: list[dict[str, Any]] = []
    for result in results:
        metric = result.get("metric")
        if isinstance(metric, Mapping):
            rows.append({**metric, "cycle_id": result.get("cycle_id"), "monday_item_id": result.get("monday_item_id")})
        else:
            rows.append(dict(result))
    mine = [row for row in rows if row.get("editor_id") == editor_id]
    peers = [row for row in rows if row.get("editor_id") != editor_id]
    late = lambda values: sum(1 for value in values if value.get("result") == "late")
    my_late, peer_late = late(mine), late(peers)
    my_rate = round(my_late / len(mine), 4) if mine else None
    peer_rate = round(peer_late / len(peers), 4) if peers else None
    difference = round(my_rate - peer_rate, 4) if my_rate is not None and peer_rate is not None else None
    facts = {"deadline_classifiable_projects": len(mine), "late": my_late, "absolute_late_rate": my_rate, "comparator_projects": len(peers), "comparator_editor_count": len({row.get("editor_id") for row in peers}), "comparator_late_rate": peer_rate, "late_rate_difference": difference}
    evidence = {"editor_cycle_ids": [row.get("cycle_id") for row in mine if row.get("cycle_id")], "comparator_cycle_ids": [row.get("cycle_id") for row in peers if row.get("cycle_id")], "rule_version": _rule_version(rule)}
    if not peers:
        return _component(NOT_CLASSIFIABLE, NO_OTHER_EDITORS, facts, rule, evidence)
    if not rule_is_approved(rule, "D45"):
        return _component(NOT_CLASSIFIABLE, RULE_NOT_APPROVED, facts, rule, evidence)
    configured = rule or {}
    editor_min = configured.get("minimum_editor_sample")
    comparator_min = configured.get("minimum_comparator_sample")
    band = configured.get("similar_band")
    if editor_min is None or comparator_min is None or band is None:
        return _component(NOT_CLASSIFIABLE, RULE_NOT_APPROVED, facts, rule, evidence)
    if len(mine) < int(editor_min) or len(peers) < int(comparator_min):
        return _component(NOT_CLASSIFIABLE, INSUFFICIENT_SAMPLE, facts, rule, evidence)
    assert difference is not None
    threshold = float(band)
    state = POSITIVE if difference < -threshold else NEGATIVE if difference > threshold else NEUTRAL
    return _component(state, None, facts, rule, evidence)


def overall_status(components: Mapping[str, Mapping[str, Any]], rule: Mapping[str, Any] | None) -> dict[str, Any]:
    """D37/D41 lookup only; no arithmetic or hidden fallback."""
    states = {name: str(component.get("state")) for name, component in components.items() if name in {"quality", "speed", "deadline"}}
    classifiable = {name: state for name, state in states.items() if state in {POSITIVE, NEUTRAL, NEGATIVE}}
    evidence = {name: component.get("evidence") for name, component in components.items() if name in states}
    base = {"component_states": states, "classifiable_components": len(classifiable), "rule_version": _rule_version(rule), "evidence": evidence}
    if len(classifiable) < 2:
        return {**base, "status": NOT_ENOUGH_EVIDENCE, "reason": NOT_ENOUGH_COMPONENTS}
    if not rule_is_approved(rule, "D37"):
        return {**base, "status": NOT_ENOUGH_EVIDENCE, "reason": RULE_NOT_APPROVED}
    lookup = (rule or {}).get("lookup")
    if not isinstance(lookup, Mapping):
        return {**base, "status": NOT_ENOUGH_EVIDENCE, "reason": RULE_NOT_APPROVED}
    key = "|".join(states.get(name, NOT_CLASSIFIABLE) for name in ("quality", "speed", "deadline"))
    status = lookup.get(key)
    if status not in {"Strong", "Good", "Mixed", "Below Expectations", NOT_ENOUGH_EVIDENCE}:
        return {**base, "status": NOT_ENOUGH_EVIDENCE, "reason": "lookup_combination_not_configured", "lookup_key": key}
    return {**base, "status": status, "reason": None, "lookup_key": key}


def recent_change(current: float | None, comparison: float | None, measurement: str, rule: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Factual current-minus-comparison change, separate from optional Trend."""
    difference = current - comparison if current is not None and comparison is not None else None
    result: dict[str, Any] = {"measurement": measurement, "current": current, "comparison": comparison, "difference": difference, "trend": None, "trend_reason": None, "rule_version": _rule_version(rule)}
    if difference is None:
        result["trend_reason"] = INSUFFICIENT_SAMPLE
        return result
    if not rule_is_approved(rule, "D23"):
        result["trend_reason"] = RULE_NOT_APPROVED
        return result
    configured = rule or {}
    minimum = configured.get("minimum_sample")
    material = configured.get("material_change")
    current_sample = configured.get("current_sample")
    comparison_sample = configured.get("comparison_sample")
    if None in (minimum, material, current_sample, comparison_sample):
        result["trend_reason"] = RULE_NOT_APPROVED
    else:
        assert minimum is not None and material is not None and current_sample is not None and comparison_sample is not None
        required_sample = int(minimum)
        current_size = int(current_sample)
        comparison_size = int(comparison_sample)
        material_change = float(material)
        if current_size < required_sample or comparison_size < required_sample:
            result["trend_reason"] = INSUFFICIENT_SAMPLE
            return result
        if abs(float(difference)) < material_change:
            result["trend"] = "Stable"
        else:
            lower_is_better = bool(configured.get("lower_is_better"))
            improving = difference < 0 if lower_is_better else difference > 0
            result["trend"] = "Improving" if improving else "Declining"
    return result


def data_coverage(cycles: Iterable[CycleRecord], occurrences: Iterable[Mapping[str, Any]] = (), quarantined: Iterable[Mapping[str, Any]] = (), rule_version: str = "data-coverage-v1.5") -> dict[str, Any]:
    records = list(cycles)
    completed = [cycle for cycle in records if cycle.state == COMPLETED]
    return {
        "projects_seen": len(records),
        "completed_projects": len(completed),
        "speed_eligible_projects": sum(speed_eligible(cycle) for cycle in completed),
        "deadline_classifiable_projects": sum(deadline_eligible(cycle) for cycle in completed),
        "quality_label_occurrences": len(list(occurrences)),
        "exclusions_by_reason": dict(Counter(reason for cycle in records for reason in cycle.exclusions)),
        "excluded_projects": [{"cycle_id": cycle.cycle_id, "monday_item_id": cycle.monday_item_id, "reasons": list(cycle.exclusions)} for cycle in records if cycle.exclusions],
        "quarantined_quality_labels": list(quarantined),
        "rule_version": rule_version,
    }


def revision_context(editor_id: str, cycles: Iterable[CycleRecord], rule_version: str = "revision-context-v1.5") -> dict[str, Any]:
    """Separate Client/Internal Revision facts; neither is a scored component."""
    mine = [cycle for cycle in cycles if cycle.state == COMPLETED and cycle.editor_id == editor_id]
    client = [cycle for cycle in mine if cycle.revision_context.get("client_revision_events", 0) > 0]
    internal = [cycle for cycle in mine if cycle.revision_context.get("internal_revision_events", 0) > 0]
    client_events = sum(cycle.revision_context.get("client_revision_events", 0) for cycle in mine)
    internal_events = sum(cycle.revision_context.get("internal_revision_events", 0) for cycle in mine)
    return {
        "context_only": True,
        "affects_scoring": False,
        "completed_projects": len(mine),
        "client_revision": {"projects": len(client), "events": client_events, "rate": round(len(client) / len(mine), 4) if mine else None,
                            "monday_item_ids": sorted(cycle.monday_item_id for cycle in client)},
        "internal_revision": {"projects": len(internal), "events": internal_events, "rate": round(len(internal) / len(mine), 4) if mine else None,
                              "monday_item_ids": sorted(cycle.monday_item_id for cycle in internal)},
        "total_revision_activity": {"events": client_events + internal_events},
        "rule_version": rule_version,
        "evidence": {"cycle_ids": [cycle.cycle_id for cycle in mine],
                     "revision_event_ids": sorted({event_id for cycle in mine for event_id in cycle.revision_context.get("event_ids", [])})},
    }
