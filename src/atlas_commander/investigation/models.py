"""The Intelligence V2 domain model: Finding, Statement, Evidence and their invariants.

A detector emits *structured* statements (a code plus parameters, each tagged with an evidence level) and evidence blocks.
Natural language is produced later from those fields (``narrative``), so every sentence can be traced to a field and a
language layer (or an AI rewrite) can never add a fact.

Evidence levels, from least to most inference:

- ``fact``: read directly from Monday (a timestamp, a label, a status);
- ``metric``: calculated by an approved rule (a late rate, a median execution time);
- ``pattern``: a regularity across several projects (a share, a repeated combination);
- ``association``: two measurements move together in this sample (never causation);
- ``interpretation``: what a pattern may mean for management, stated as such;
- ``hypothesis``: a possible explanation that needs investigation.

A finding's ``evidence_level`` is the highest-inference statement it makes. An interpretation or a hypothesis is never
allowed without at least one fact, metric, pattern or association in the same finding (``finding_errors``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from atlas_commander.investigation.policy import ParameterUse, parameter_status

FACT, METRIC, PATTERN, ASSOCIATION, INTERPRETATION, HYPOTHESIS = "fact", "metric", "pattern", "association", "interpretation", "hypothesis"
EVIDENCE_LEVELS = (FACT, METRIC, PATTERN, ASSOCIATION, INTERPRETATION, HYPOTHESIS)
OBSERVED_LEVELS = frozenset({FACT, METRIC, PATTERN, ASSOCIATION})

# Management sections (brief Task 42 / 50). A finding belongs to exactly one.
NEEDS_ATTENTION = "needs_attention"
IMPORTANT_IMPROVEMENT = "important_improvement"
SYSTEM_PATTERN = "system_pattern"
EDITOR_SPECIFIC_PATTERN = "editor_specific_pattern"
HIDDEN_CONTEXT = "hidden_context"
EMERGING_RISK = "emerging_risk"
DATA_WARNING = "data_warning"
CATEGORIES = (NEEDS_ATTENTION, IMPORTANT_IMPROVEMENT, SYSTEM_PATTERN, EDITOR_SPECIFIC_PATTERN, HIDDEN_CONTEXT, EMERGING_RISK, DATA_WARNING)

# Direction of what a finding reports, used by de-duplication and the relationship graph (never a score).
ADVERSE, FAVOURABLE, MIXED, NEUTRAL = "adverse", "favourable", "mixed", "neutral"
DIRECTIONS = (ADVERSE, FAVOURABLE, MIXED, NEUTRAL)

# Subject scopes. A finding about a person is always scope "editor"; process findings name a Video Type, a stage or the team.
SCOPE_TEAM, SCOPE_EDITOR, SCOPE_VIDEO_TYPE, SCOPE_STAGE, SCOPE_PROJECT, SCOPE_DATA = "team", "editor", "video_type", "stage", "project", "data"
SCOPES = (SCOPE_TEAM, SCOPE_EDITOR, SCOPE_VIDEO_TYPE, SCOPE_STAGE, SCOPE_PROJECT, SCOPE_DATA)


@dataclass(frozen=True)
class Statement:
    level: str
    code: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.level not in EVIDENCE_LEVELS:
            raise ValueError(f"unknown evidence level {self.level!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "code": self.code, "params": _plain(self.params)}


@dataclass(frozen=True)
class EvidenceRecord:
    """One Monday project behind a finding: enough to reopen it in Monday and recompute the value used."""

    monday_item_id: str
    cycle_id: str | None
    event_ids: Sequence[str]
    source_timestamps: Sequence[str]
    values: Mapping[str, Any]
    editor_id: str | None = None
    cohort_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"monday_item_id": self.monday_item_id, "cycle_id": self.cycle_id, "editor_id": self.editor_id, "cohort_key": self.cohort_key,
                "event_ids": list(self.event_ids), "source_timestamps": list(self.source_timestamps), "values": _plain(self.values)}


@dataclass(frozen=True)
class Evidence:
    """A reconstructable evidence block: what was compared, how, over which projects and period."""

    role: str                      # "supporting" | "contradicting" | "context"
    code: str                      # what this block shows, e.g. "late_projects_by_video_type"
    calculation: str               # the formula in words, with the exact comparison
    sample: Mapping[str, Any]      # sizes of every compared group
    records: Sequence[EvidenceRecord]
    comparison: Mapping[str, Any] = field(default_factory=dict)   # the values compared (group values, reference values)
    time_window: Mapping[str, Any] | None = None
    exclusions: Sequence[Mapping[str, Any]] = ()
    board_id: str | None = None
    column_ids: Sequence[str] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "code": self.code, "source": "monday", "monday_board_id": self.board_id, "column_ids": sorted(set(self.column_ids)),
                "calculation": self.calculation, "sample": _plain(self.sample), "comparison": _plain(self.comparison),
                "time_window": _plain(self.time_window) if self.time_window else None,
                "records": [record.to_dict() for record in sorted(self.records, key=lambda r: (r.monday_item_id, r.cycle_id or ""))],
                "exclusions": [_plain(row) for row in self.exclusions]}


@dataclass(frozen=True)
class Scope:
    kind: str
    editor_id: str | None = None
    cohort_key: str | None = None
    stage: str | None = None
    monday_item_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in SCOPES:
            raise ValueError(f"unknown scope {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "editor_id": self.editor_id, "cohort_key": self.cohort_key, "stage": self.stage, "monday_item_id": self.monday_item_id}


@dataclass
class Finding:
    """One higher-order Atlas finding. Built by a detector; confidence, importance, relations and wording are added later."""

    finding_type: str
    detector_version: str
    category: str
    direction: str
    scope: Scope
    statements: list[Statement]
    supporting_evidence: list[Evidence]
    parameters: list[ParameterUse]
    time_window: Mapping[str, Any] | None
    limitations: list[str]
    significance: Statement
    investigations: list[Statement]
    key: Mapping[str, Any] = field(default_factory=dict)     # what makes the finding unique within its type (hashed into the id)
    contradicting_evidence: list[Evidence] = field(default_factory=list)
    context_evidence: list[Evidence] = field(default_factory=list)
    magnitude: float | None = None       # size of the effect in the finding's own unit, for ordering only
    headline_contradiction: bool = False  # the finding weakens a published headline (component state, raw rate)
    worsening: bool | None = None         # True when the adverse side grew between windows; None when not known
    persistent: bool | None = None        # True when the pattern holds in both windows / several months
    confidence: dict[str, Any] | None = None
    importance: dict[str, Any] | None = None
    severity: str | None = None
    related: list[dict[str, Any]] = field(default_factory=list)
    cluster: dict[str, Any] | None = None
    text: dict[str, Any] | None = None

    @property
    def finding_id(self) -> str:
        body = json.dumps({"type": self.finding_type, "scope": self.scope.to_dict(), "key": _plain(self.key),
                           "window": _plain(self.time_window) if self.time_window else None}, sort_keys=True)
        return f"{self.finding_type}:{hashlib.sha256(body.encode()).hexdigest()[:16]}"

    @property
    def evidence_level(self) -> str:
        return max((statement.level for statement in self.statements), key=EVIDENCE_LEVELS.index)

    @property
    def affected_projects(self) -> list[str]:
        return sorted({record.monday_item_id for block in self.supporting_evidence for record in block.records})

    @property
    def affected_editors(self) -> list[str]:
        editors = {record.editor_id for block in self.supporting_evidence for record in block.records if record.editor_id}
        if self.scope.editor_id:
            editors.add(self.scope.editor_id)
        return sorted(editors)

    @property
    def affected_video_types(self) -> list[str]:
        types = {record.cohort_key for block in self.supporting_evidence for record in block.records if record.cohort_key}
        if self.scope.cohort_key:
            types.add(self.scope.cohort_key)
        return sorted(types)

    @property
    def sample_size(self) -> int:
        return len({(record.monday_item_id, record.cycle_id) for block in self.supporting_evidence for record in block.records})

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "finding_type": self.finding_type,
            "detector_version": self.detector_version,
            "category": self.category,
            "direction": self.direction,
            "scope": self.scope.to_dict(),
            "evidence_level": self.evidence_level,
            "parameter_status": parameter_status(self.parameters),
            "statements": [statement.to_dict() for statement in self.statements],
            "significance": self.significance.to_dict(),
            "suggested_investigations": [statement.to_dict() for statement in self.investigations],
            "confidence": self.confidence,
            "importance": self.importance,
            "severity": self.severity,
            "sample_size": self.sample_size,
            "affected_editors": self.affected_editors,
            "affected_video_types": self.affected_video_types,
            "affected_projects": self.affected_projects,
            "time_window": _plain(self.time_window) if self.time_window else None,
            "supporting_evidence": [block.to_dict() for block in self.supporting_evidence],
            "contradicting_evidence": [block.to_dict() for block in self.contradicting_evidence],
            "context_evidence": [block.to_dict() for block in self.context_evidence],
            "limitations": sorted(set(self.limitations)),
            "parameters": [use.to_dict() for use in sorted(self.parameters, key=lambda use: use.name)],
            "headline_contradiction": self.headline_contradiction,
            "worsening": self.worsening,
            "persistent": self.persistent,
            "related": list(self.related),
            "cluster": self.cluster,
            "text": self.text,
        }


def finding_errors(finding: Finding) -> list[str]:
    """Invariants every finding must satisfy before it is published."""
    errors: list[str] = []
    if finding.category not in CATEGORIES:
        errors.append(f"unknown category {finding.category!r}")
    if finding.direction not in DIRECTIONS:
        errors.append(f"unknown direction {finding.direction!r}")
    if not finding.statements:
        errors.append("a finding needs at least one statement")
    elif not any(statement.level in OBSERVED_LEVELS for statement in finding.statements):
        errors.append("an interpretation or hypothesis needs a fact, metric, pattern or association in the same finding")
    if not finding.supporting_evidence or not any(block.records for block in finding.supporting_evidence):
        errors.append("a finding needs supporting evidence with at least one Monday record")
    for block in [*finding.supporting_evidence, *finding.contradicting_evidence, *finding.context_evidence]:
        for record in block.records:
            if not record.event_ids or not record.source_timestamps:
                errors.append(f"evidence record {record.monday_item_id} has no Monday event IDs or timestamps")
    if not finding.limitations:
        errors.append("a finding must declare its limitations")
    if finding.scope.kind == SCOPE_EDITOR and not finding.scope.editor_id:
        errors.append("an Editor finding must name the Editor")
    if finding.scope.kind == SCOPE_EDITOR and any("revision" in statement.code for statement in finding.statements if statement.level != FACT):
        errors.append("an Editor finding may not interpret revisions (D31): revisions are context only")
    return errors


def not_evaluated(detector: str, scope: Scope, reasons: Iterable[str], facts: Mapping[str, Any] | None = None,
                  parameters: Iterable[str] = ()) -> dict[str, Any]:
    """A subject a detector examined but could not conclude on, with the reason and the facts it did compute."""
    return {"detector": detector, "scope": scope.to_dict(), "reasons": sorted(set(reasons)), "facts": _plain(facts or {}),
            "parameters_needed": sorted(set(parameters))}


def _plain(value: Any) -> Any:
    """JSON-ready deterministic copy: mappings with sorted keys, tuples as lists, floats rounded for display stability."""
    if isinstance(value, Mapping):
        return {str(key): _plain(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(item) for item in value)
    if isinstance(value, float):
        return round(value, 4)
    return value


def plain(value: Any) -> Any:
    return _plain(value)
