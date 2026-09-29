"""Intelligence V2 parameters, their approval state (D25) and the two run modes.

A parameter is *approved* only when ``config/intelligence-v2.json`` marks it ``approved`` **and** names its decision.
Approved values that reuse an existing contract rule are read from that contract (``from_contract``) and must be approved
there too, so a V2 value can never drift from, or outlive, the rule it reuses.

Unapproved parameters have ``value: null``. In ``approved_only`` mode (the default and the only publishable mode) they are
unavailable, and every detector that needs one records ``rule_not_approved`` instead of a finding. In ``review`` mode
the ``proposed_value`` is used, and everything it produces is marked ``proposed_not_approved``. Review mode exists so
management can see what a proposal would surface before approving it; it is never published.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas_commander.interpretation_policy import APPROVED, RULE_NOT_APPROVED, InterpretationPolicy

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "intelligence-v2.json"
CAPABILITIES_PATH = ROOT / "config" / "intelligence-v2-data-capabilities.json"

APPROVED_ONLY = "approved_only"
REVIEW = "review"
MODES = (APPROVED_ONLY, REVIEW)
PROPOSED_NOT_APPROVED = "proposed_not_approved"

# Gate reasons: why a detector produced no finding for a subject. Each is a data state or a governance state, never a
# performance state (D47).
INSUFFICIENT_SAMPLE = "insufficient_sample"
INSUFFICIENT_COMPARISON_GROUP = "insufficient_comparison_group"
INSUFFICIENT_RECENT_WINDOW = "insufficient_recent_window"
INSUFFICIENT_OUTCOMES = "insufficient_outcome_events"
INSUFFICIENT_EDITORS = "insufficient_qualifying_editors"
MISSING_DATA = "missing_data"
INCOMPLETE_TIMESTAMPS = "incomplete_timestamp_coverage"
NO_EFFECT = "no_effect_at_approved_threshold"
GATE_REASONS = frozenset({RULE_NOT_APPROVED, INSUFFICIENT_SAMPLE, INSUFFICIENT_COMPARISON_GROUP, INSUFFICIENT_RECENT_WINDOW,
                          INSUFFICIENT_OUTCOMES, INSUFFICIENT_EDITORS, MISSING_DATA, INCOMPLETE_TIMESTAMPS, NO_EFFECT})


class RuleNotApproved(Exception):
    """Raised inside a detector when a parameter it needs is unavailable in the current mode."""

    def __init__(self, names: Iterable[str]) -> None:
        self.names = sorted(set(names))
        super().__init__(", ".join(self.names))


@dataclass(frozen=True)
class Parameter:
    name: str
    status: str
    decision_id: str | None
    value: Any
    proposed_value: Any
    source: str | None
    meaning: str
    basis: str | None

    @property
    def approved(self) -> bool:
        return self.status == APPROVED and bool(self.decision_id) and self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": APPROVED if self.approved else RULE_NOT_APPROVED, "decision_id": self.decision_id,
                "value": self.value, "proposed_value": self.proposed_value, "from_contract": self.source, "meaning": self.meaning,
                "basis": self.basis}


@dataclass(frozen=True)
class ParameterUse:
    """One parameter as a detector used it, published in the finding that depends on it."""

    name: str
    value: Any
    status: str          # approved | proposed_not_approved
    decision_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "status": self.status, "decision_id": self.decision_id}


def _dig(contract: Mapping[str, Any], dotted: str) -> Any:
    value: Any = contract
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, Mapping) else None
    return value


# Where each reused contract value's own approval lives, so a V2 parameter is approved only while the contract approves it.
def _contract_approval(policy: InterpretationPolicy, source: str) -> str:
    speed, deadline, trend, quality = policy.speed, policy.deadline, policy.trend, policy.quality
    table = {
        "speed_benchmark.minimum_editor_sample_size": speed.value_status.get("minimum_editor_sample_size"),
        "speed_benchmark.minimum_comparator_sample_size": speed.value_status.get("minimum_comparator_sample_size"),
        "speed_benchmark.minimum_comparator_editor_count": speed.value_status.get("minimum_comparator_editor_count"),
        "speed_benchmark.component.faster_band": speed.value_status.get("faster_band"),
        "speed_benchmark.component.slower_band": speed.value_status.get("slower_band"),
        "deadline.component.minimum_editor_sample_size": APPROVED if deadline.approved else RULE_NOT_APPROVED,
        "deadline.component.minimum_comparator_sample_size": APPROVED if deadline.approved else RULE_NOT_APPROVED,
        "interpretation.trend.minimum_sample_size": trend.value_status.get("minimum_sample_size"),
        "interpretation.quality_component.minimum_project_sample_size": quality.value_status.get("minimum_project_sample_size"),
    }
    if source not in table:
        raise ValueError(f"intelligence-v2 parameter reuses an unknown contract value {source!r}")
    return str(table[source])


@dataclass(frozen=True)
class IntelligencePolicy:
    """Every V2 parameter for one contract, and the mode detectors run in."""

    version: str
    mode: str
    parameters: Mapping[str, Parameter]
    config: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, contract: Mapping[str, Any], mode: str = APPROVED_ONLY, config: Mapping[str, Any] | None = None) -> IntelligencePolicy:
        if mode not in MODES:
            raise ValueError(f"unknown intelligence-v2 mode {mode!r}; expected one of {MODES}")
        data = dict(config) if config is not None else json.loads(CONFIG_PATH.read_text())
        errors = config_errors(data, contract)
        if errors:
            raise ValueError("invalid intelligence-v2 configuration: " + "; ".join(errors))
        interpretation = InterpretationPolicy.from_contract(contract)
        parameters: dict[str, Parameter] = {}
        for name, entry in data["parameters"].items():
            source = entry.get("from_contract")
            if source:
                value = _dig(contract, source)
                status = APPROVED if entry["status"] == APPROVED and _contract_approval(interpretation, source) == APPROVED else RULE_NOT_APPROVED
                value = value if status == APPROVED else None
            else:
                status, value = entry["status"], entry.get("value")
            parameters[name] = Parameter(name, status, entry.get("decision_id") if status == APPROVED else None, value,
                                         entry.get("proposed_value"), source, entry.get("meaning", ""), entry.get("basis"))
        return cls(str(data["intelligence_v2_version"]), mode, parameters, data)

    @property
    def publishable(self) -> bool:
        return self.mode == APPROVED_ONLY

    def use(self, name: str) -> ParameterUse | None:
        """The parameter as this mode may use it, or None when it is unavailable (``rule_not_approved``)."""
        parameter = self.parameters[name]
        if parameter.approved:
            return ParameterUse(name, parameter.value, APPROVED, parameter.decision_id)
        if self.mode == REVIEW and parameter.proposed_value is not None:
            return ParameterUse(name, parameter.proposed_value, PROPOSED_NOT_APPROVED, None)
        return None

    def require(self, *names: str) -> dict[str, ParameterUse]:
        """Every named parameter, or ``RuleNotApproved`` naming all the unavailable ones."""
        uses = {name: self.use(name) for name in names}
        missing = [name for name, value in uses.items() if value is None]
        if missing:
            raise RuleNotApproved(missing)
        return {name: value for name, value in uses.items() if value is not None}

    def value(self, name: str) -> Any:
        use = self.use(name)
        return use.value if use is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "mode": self.mode, "publishable": self.publishable,
                "parameters": [parameter.to_dict() for _, parameter in sorted(self.parameters.items())]}


def parameter_status(uses: Iterable[ParameterUse]) -> str:
    """``approved`` when every parameter behind a finding is approved, else ``proposed_not_approved``."""
    return APPROVED if all(use.status == APPROVED for use in uses) else PROPOSED_NOT_APPROVED


def config_errors(config: Mapping[str, Any], contract: Mapping[str, Any] | None = None) -> list[str]:
    """Everything that makes the V2 configuration unusable; empty for a valid, partly unapproved configuration."""
    errors: list[str] = []
    parameters = config.get("parameters")
    if not isinstance(parameters, Mapping) or not parameters:
        return ["parameters must be a non-empty object"]
    for name, entry in sorted(parameters.items()):
        if not isinstance(entry, Mapping):
            errors.append(f"{name} must be an object")
            continue
        status = entry.get("status")
        if status not in (APPROVED, RULE_NOT_APPROVED):
            errors.append(f"{name}.status must be approved or rule_not_approved")
        source = entry.get("from_contract")
        if source:
            if "value" in entry:
                errors.append(f"{name} reuses {source}; its value must come from the contract, not this file")
            if status == APPROVED and not entry.get("decision_id"):
                errors.append(f"{name} is approved without a decision_id (D25)")
            continue
        if status == APPROVED:
            if not entry.get("decision_id"):
                errors.append(f"{name} is approved without a decision_id (D25)")
            if entry.get("value") is None:
                errors.append(f"{name} is approved without a value")
        elif entry.get("value") is not None:
            errors.append(f"{name} has a value but is not approved (D25); unapproved proposals belong in proposed_value")
    publication = config.get("publication")
    if not isinstance(publication, Mapping) or publication.get("mode") != APPROVED_ONLY:
        errors.append("publication.mode must be approved_only (review output is never published)")
    # A reused contract value that the contract leaves unapproved (null) is not an error: the V2 parameter is simply unavailable.
    _ = contract
    return errors


def load_capability_map() -> dict[str, Any]:
    return dict(json.loads(CAPABILITIES_PATH.read_text()))
