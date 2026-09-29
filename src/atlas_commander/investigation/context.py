"""What every detector receives, and the result shape every detector returns."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from atlas_commander.investigation.baselines import Baselines
from atlas_commander.investigation.facts import FactBase, ProjectFact
from atlas_commander.investigation.models import Evidence, EvidenceRecord, Finding, Scope, not_evaluated
from atlas_commander.investigation.policy import IntelligencePolicy, ParameterUse, RuleNotApproved

ROLE_COLUMNS = {"status": "status", "editor": "editor", "video_type": "video_type", "requested_eta": "requested_eta",
                "labels": "performance_issues", "bonus": "for_bonus"}


@dataclass
class RunContext:
    facts: FactBase
    baselines: Baselines
    policy: IntelligencePolicy
    profiles: Mapping[str, Mapping[str, Any]]      # editor_id -> finished editor-profile 1.5 document
    as_of: str

    def evidence(self, role: str, code: str, calculation: str, sample: Mapping[str, Any], records: Sequence[EvidenceRecord], *,
                 columns: Sequence[str] = ("status",), comparison: Mapping[str, Any] | None = None,
                 time_window: Mapping[str, Any] | None = None, exclusions: Sequence[Mapping[str, Any]] = ()) -> Evidence:
        return Evidence(role, code, calculation, sample, list(records), comparison or {}, time_window, list(exclusions), self.facts.board_id,
                        [self.facts.column_ids[ROLE_COLUMNS[column]] for column in columns if self.facts.column_ids.get(ROLE_COLUMNS[column])])

    def window(self, name: str = "current") -> dict[str, Any]:
        return self.facts.windows.range(name)

    @property
    def history_window(self) -> dict[str, Any]:
        return {"window": "all_history", "timezone": "Africa/Cairo", "start_date": None,
                "end_date_exclusive": self.facts.windows.current_end.isoformat(),
                "description": "every completed project in the ingested history up to the end of the current window"}

    def name(self, editor_id: str | None) -> str | None:
        return self.facts.editor_names.get(editor_id or "")


@dataclass
class DetectorResult:
    findings: list[Finding] = field(default_factory=list)
    not_evaluated: list[dict[str, Any]] = field(default_factory=list)
    analyses_run: int = 0

    def skip(self, detector: str, scope: Scope, reasons: Sequence[str], facts: Mapping[str, Any] | None = None, parameters: Sequence[str] = ()) -> None:
        self.analyses_run += 1
        self.not_evaluated.append(not_evaluated(detector, scope, reasons, facts, parameters))

    def add(self, finding: Finding) -> None:
        self.analyses_run += 1
        self.findings.append(finding)


@dataclass(frozen=True)
class Detector:
    """A registered detector and its catalog entry (docs/INTELLIGENCE-V2.md, Task 74)."""

    detector_id: str
    version: str
    task: str
    purpose: str
    required_signals: tuple[str, ...]
    parameters: tuple[str, ...]
    minimum_sample: str
    output: str
    confidence_rules: str
    limitations: tuple[str, ...]
    run: Callable[[RunContext], DetectorResult]

    def catalog_entry(self) -> dict[str, Any]:
        return {"detector": self.detector_id, "version": self.version, "task": self.task, "purpose": self.purpose,
                "required_signals": list(self.required_signals), "parameters": list(self.parameters), "minimum_sample": self.minimum_sample,
                "output": self.output, "confidence_rules": self.confidence_rules, "limitations": list(self.limitations)}


def run_guarded(detector: Detector, ctx: RunContext) -> DetectorResult:
    """Run a detector; a missing approval anywhere becomes one ``rule_not_approved`` record instead of a finding."""
    try:
        return detector.run(ctx)
    except RuleNotApproved as missing:
        result = DetectorResult()
        result.skip(detector.detector_id, Scope("team"), ["rule_not_approved"], parameters=missing.names)
        return result


def uses(ctx: RunContext, *names: str) -> tuple[dict[str, Any], list[ParameterUse]]:
    """Values and the ParameterUse records for every named parameter (raises RuleNotApproved when any is unavailable)."""
    required = ctx.policy.require(*names)
    return {name: use.value for name, use in required.items()}, list(required.values())


def editor_scope(project: ProjectFact) -> Scope:
    return Scope("editor", editor_id=project.editor_id)
