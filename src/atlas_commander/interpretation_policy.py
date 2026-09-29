"""Contract 1.5 interpretation rules, read in one canonical vocabulary.

Each classification rule lives in the versioned contract next to an explicit approval state (D25): a rule is approved only
when its status is ``approved`` *and* it names the decision-log entry that authorises it. Unapproved values are ``null``
and keep their state ``rule_not_approved``; nothing here supplies a default threshold. A rule marked approved but missing
any value, or naming the wrong decision, makes the contract invalid when it is loaded (``policy_errors``), so a
half-configured rule can never silently classify or silently stay unclassified.

Direction is part of each Recent Change measurement's meaning, not a threshold: a lower late rate is better whatever
materiality is later approved. It is therefore carried by the contract for every measurement and checked here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import product
from typing import Any

APPROVED = "approved"
RULE_NOT_APPROVED = "rule_not_approved"
RULE_STATUSES = frozenset({APPROVED, RULE_NOT_APPROVED})

# Component states and Overall Status labels exactly as the contract names them (interpretation.component_states / labels).
POSITIVE, NEUTRAL, NEGATIVE, NOT_CLASSIFIABLE = "positive", "neutral", "negative", "not_classifiable"
COMPONENT_STATES = (POSITIVE, NEUTRAL, NEGATIVE, NOT_CLASSIFIABLE)
CLASSIFIED_STATES = frozenset({POSITIVE, NEUTRAL, NEGATIVE})
SCORED_COMPONENTS = ("quality", "speed", "deadline")
OVERALL_LABELS = ("Strong", "Good", "Mixed", "Below Expectations")
NOT_ENOUGH_EVIDENCE = "Not enough evidence to classify"              # D37 / D41 / D47: a data state, never a performance state
NOT_ENOUGH_APPROVED_LOGIC = "Not enough approved logic to classify"  # D25: the governing rule is not approved yet
TREND_LABELS = ("Improving", "Stable", "Declining")

# Recent Change measurements and the direction that means "better" (a fact about the measurement, not a threshold).
HIGHER_IS_BETTER, LOWER_IS_BETTER = "higher_is_better", "lower_is_better"
TREND_DIRECTIONS = {
    "positive_quality_rate": HIGHER_IS_BETTER,
    "negative_quality_rate": LOWER_IS_BETTER,
    "late_rate": LOWER_IS_BETTER,
    "median_speed_seconds": LOWER_IS_BETTER,
}

DECISIONS = {"quality": "D39", "speed": "D38", "deadline": "D45", "overall": "D37", "trend": "D23"}


@dataclass(frozen=True)
class Rule:
    """One classification rule: its values, its approval state and the decision that approves it."""

    name: str
    rule_version: str | None
    status: str
    decision_id: str | None
    values: Mapping[str, Any] = field(default_factory=dict)
    # Per-value approval, where a contract approves parts of a rule separately (Speed minimums and bands).
    value_status: Mapping[str, str] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.status == APPROVED and self.decision_id == DECISIONS[self.name]

    def value(self, key: str) -> Any:
        """The configured value, or None when that value is not approved."""
        if self.value_status.get(key, self.status) != APPROVED:
            return None
        return self.values.get(key)

    def state(self) -> dict[str, Any]:
        """The rule's approval state as published beside every result it governs (D25, D47)."""
        return {"rule": self.name, "rule_version": self.rule_version, "status": APPROVED if self.approved else RULE_NOT_APPROVED,
                "decision_id": self.decision_id if self.approved else None,
                "values": {key: self.value(key) for key in self.values}}


@dataclass(frozen=True)
class InterpretationPolicy:
    window_days: int
    comparison_days: int
    timezone: str
    window_rule_version: str
    minimum_classifiable_components: int
    quality: Rule
    speed: Rule
    deadline: Rule
    overall: Rule
    trend: Rule
    trend_directions: Mapping[str, str]
    rule_versions: Mapping[str, str]

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> InterpretationPolicy:
        errors = policy_errors(contract)
        if errors:
            raise ValueError("invalid contract interpretation rules: " + "; ".join(errors))
        return _policy(contract)


def _section(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _policy(contract: Mapping[str, Any]) -> InterpretationPolicy:
    versions = _section(contract.get("rule_versions"))
    windows = _section(contract.get("time_windows"))
    interpretation = _section(contract.get("interpretation"))
    quality = _section(interpretation.get("quality_component"))
    speed_root = _section(contract.get("speed_benchmark"))
    speed_component = _section(speed_root.get("component"))
    deadline_component = _section(_section(contract.get("deadline")).get("component"))
    overall = _section(interpretation.get("overall_status"))
    trend = _section(interpretation.get("trend"))

    speed_values = {key: speed_root.get(key) for key in SPEED_MINIMUMS} | {key: speed_component.get(key) for key in SPEED_BANDS}
    speed_status = {key: str(speed_root.get(f"{key}_status")) for key in SPEED_MINIMUMS} | {key: str(speed_component.get("band_status")) for key in SPEED_BANDS}
    speed_all_approved = all(value == APPROVED for value in speed_status.values())
    return InterpretationPolicy(
        window_days=int(_section(windows.get("current_window"))["completed_days"]),
        comparison_days=int(_section(windows.get("comparison_window"))["completed_days"]),
        timezone=str(windows["timezone"]),
        window_rule_version=str(windows.get("rule_version") or versions["windowing"]),
        minimum_classifiable_components=int(overall["minimum_classifiable_components"]),
        quality=Rule("quality", versions.get("quality_component"), str(quality.get("threshold_status")), quality.get("decision_id"),
                     {key: quality.get(key) for key in QUALITY_VALUES}),
        speed=Rule("speed", versions.get("speed_component"), APPROVED if speed_all_approved else RULE_NOT_APPROVED,
                   speed_component.get("decision_id"), speed_values, speed_status),
        deadline=Rule("deadline", versions.get("deadline_component"), str(deadline_component.get("threshold_status")),
                      deadline_component.get("decision_id"), {key: deadline_component.get(key) for key in DEADLINE_VALUES}),
        overall=Rule("overall", versions.get("overall_status"), str(overall.get("threshold_status")), overall.get("decision_id"),
                     {"lookup_table": overall.get("lookup_table")}),
        trend=Rule("trend", versions.get("trend"), str(trend.get("threshold_status")), trend.get("decision_id"),
                   {"minimum_sample_size": trend.get("minimum_sample_size"),
                    "material_change_thresholds": trend.get("material_change_thresholds")}),
        trend_directions=dict(_section(trend.get("directions"))),
        rule_versions=dict(versions),
    )


QUALITY_VALUES = ("minimum_project_sample_size", "negative_rate_threshold", "positive_rate_threshold")
SPEED_MINIMUMS = ("minimum_editor_sample_size", "minimum_comparator_sample_size", "minimum_comparator_editor_count")
SPEED_BANDS = ("faster_band", "slower_band")
DEADLINE_VALUES = ("minimum_editor_sample_size", "minimum_comparator_sample_size", "better_band", "worse_band")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def lookup_keys() -> list[str]:
    """Every Overall Status lookup key, in the contract's component-state vocabulary: ``quality|speed|deadline``."""
    return ["|".join(states) for states in product(COMPONENT_STATES, repeat=len(SCORED_COMPONENTS))]


def policy_errors(contract: Mapping[str, Any]) -> list[str]:
    """Everything that makes the contract's interpretation rules unusable. Empty for an unapproved, well-formed contract."""
    errors: list[str] = []
    interpretation = _section(contract.get("interpretation"))
    states = interpretation.get("component_states")
    if states != list(COMPONENT_STATES):
        errors.append(f"interpretation.component_states must be {list(COMPONENT_STATES)}")
    overall_section = _section(interpretation.get("overall_status"))
    if overall_section.get("labels") != list(OVERALL_LABELS):
        errors.append(f"interpretation.overall_status.labels must be {list(OVERALL_LABELS)}")
    if overall_section.get("scored_components") != list(SCORED_COMPONENTS):
        errors.append(f"interpretation.overall_status.scored_components must be {list(SCORED_COMPONENTS)}")
    if overall_section.get("weighted_composite") is not False:
        errors.append("interpretation.overall_status.weighted_composite must be false (D37: no weighted score)")
    if not _positive_int(overall_section.get("minimum_classifiable_components")):
        errors.append("interpretation.overall_status.minimum_classifiable_components must be a positive integer")
    trend_section = _section(interpretation.get("trend"))
    if trend_section.get("labels") != list(TREND_LABELS):
        errors.append(f"interpretation.trend.labels must be {list(TREND_LABELS)}")
    if dict(_section(trend_section.get("directions"))) != TREND_DIRECTIONS:
        errors.append(f"interpretation.trend.directions must be {TREND_DIRECTIONS}")
    thresholds = trend_section.get("material_change_thresholds")
    if not isinstance(thresholds, Mapping) or set(thresholds) != set(TREND_DIRECTIONS):
        errors.append(f"interpretation.trend.material_change_thresholds must name every measurement {sorted(TREND_DIRECTIONS)}")
    windows = _section(contract.get("time_windows"))
    if windows.get("timezone") != "Africa/Cairo":
        errors.append("time_windows.timezone must be Africa/Cairo")
    for name in ("current_window", "comparison_window"):
        if not _positive_int(_section(windows.get(name)).get("completed_days")):
            errors.append(f"time_windows.{name}.completed_days must be a positive integer")
    if errors:
        return errors

    policy = _policy(contract)
    statuses = {
        "quality": _section(interpretation.get("quality_component")).get("threshold_status"),
        "deadline": _section(_section(contract.get("deadline")).get("component")).get("threshold_status"),
        "overall": overall_section.get("threshold_status"),
        "trend": trend_section.get("threshold_status"),
    }
    statuses.update({f"speed.{key}": value for key, value in policy.speed.value_status.items()})
    errors += [f"{name} status {value!r} is not one of {sorted(RULE_STATUSES)}" for name, value in statuses.items() if value not in RULE_STATUSES]
    for rule in (policy.quality, policy.speed, policy.deadline, policy.overall, policy.trend):
        approved_parts = [key for key in rule.values if rule.value_status.get(key, rule.status) == APPROVED]
        if approved_parts and rule.decision_id != DECISIONS[rule.name]:
            errors.append(f"{rule.name} rule approves {approved_parts} without its decision {DECISIONS[rule.name]}")
        for key in rule.values:
            value = rule.values[key]
            approved = rule.value_status.get(key, rule.status) == APPROVED
            if not approved and value is not None and not (rule.name == "trend" and key == "material_change_thresholds"):
                errors.append(f"{rule.name}.{key} has a value but is not approved (D25)")
    errors += _approved_value_errors(policy)
    return errors


def _approved_value_errors(policy: InterpretationPolicy) -> list[str]:
    errors: list[str] = []
    if policy.quality.status == APPROVED:
        values = policy.quality.values
        if not _positive_int(values["minimum_project_sample_size"]):
            errors.append("approved quality.minimum_project_sample_size must be a positive integer")
        for key in ("negative_rate_threshold", "positive_rate_threshold"):
            if not (_number(values[key]) and 0 <= values[key] <= 1):
                errors.append(f"approved quality.{key} must be a rate between 0 and 1")
    for key in SPEED_MINIMUMS:
        if policy.speed.value_status[key] == APPROVED and not _positive_int(policy.speed.values[key]):
            errors.append(f"approved speed.{key} must be a positive integer")
    if policy.speed.value_status["faster_band"] == APPROVED:
        faster, slower = policy.speed.values["faster_band"], policy.speed.values["slower_band"]
        if not (_number(faster) and _number(slower) and faster <= 0 <= slower):
            errors.append("approved speed bands must be percentages with faster_band <= 0 <= slower_band")
    if policy.deadline.status == APPROVED:
        values = policy.deadline.values
        for key in ("minimum_editor_sample_size", "minimum_comparator_sample_size"):
            if not _positive_int(values[key]):
                errors.append(f"approved deadline.{key} must be a positive integer")
        if not (_number(values["better_band"]) and _number(values["worse_band"]) and -1 <= values["better_band"] <= 0 <= values["worse_band"] <= 1):
            errors.append("approved deadline bands must be late-rate differences with -1 <= better_band <= 0 <= worse_band <= 1")
    if policy.overall.status == APPROVED:
        table = policy.overall.values["lookup_table"]
        if not isinstance(table, Mapping) or set(table) != set(lookup_keys()):
            errors.append("approved overall_status.lookup_table must map every quality|speed|deadline state combination exactly once")
        elif any(value not in (*OVERALL_LABELS, NOT_ENOUGH_EVIDENCE) for value in table.values()):
            errors.append(f"approved overall_status.lookup_table values must be one of {[*OVERALL_LABELS, NOT_ENOUGH_EVIDENCE]} (D37)")
    if policy.trend.status == APPROVED:
        values = policy.trend.values
        if not _positive_int(values["minimum_sample_size"]):
            errors.append("approved trend.minimum_sample_size must be a positive integer")
        thresholds = values["material_change_thresholds"]
        if not all(_number(thresholds.get(name)) and thresholds[name] >= 0 for name in TREND_DIRECTIONS):
            errors.append("approved trend.material_change_thresholds must give a non-negative threshold for every measurement")
    elif any(value is not None for value in _section(policy.trend.values["material_change_thresholds"]).values()):
        errors.append("trend.material_change_thresholds has values but the trend rule is not approved (D25)")
    return errors
