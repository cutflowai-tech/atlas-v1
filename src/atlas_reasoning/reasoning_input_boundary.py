"""The single approved input path from deterministic Atlas into Reasoning V3 (``REV/01``).

    Intelligence V2 document ─┐
    publication.json ─────────┼─► build_reasoning_input ─► ReasoningInput (typed, deeply immutable) ─► Reasoning V3
    profiles/<editor>.json ───┘

Reasoning V3 reads upstream Atlas **only** through this module, and this module reads only the language-neutral documents a
contract 1.5.0+ site build already writes (``intelligence-v2.json``, ``publication.json``, ``profiles/<editor_id>.json``). It
never imports the metric engine, never recomputes anything, and never writes: every value it returns is a deep copy, frozen, so
no code downstream can mutate an Editor Profile, a component state, Overall Status, Trend, Recent Change or an Intelligence V2
finding through it (``tests/test_reasoning_boundary.py``).

Every field of the payload is classified by ``field(metadata={"kind": ...})`` (``field_kinds``):

- ``source_fact``: read from Monday (item IDs, event IDs, source timestamps, V2 ``fact`` statements);
- ``deterministic_derived_value``: computed by an approved deterministic rule (identity resolution, metrics, V2 ``metric`` /
  ``pattern`` / ``association`` statements, component states, Overall Status, upstream confidence);
- ``upstream_interpretation``: V2's deterministic interpretation and hypothesis templates, labelled so they are never mistaken
  for evidence;
- ``evidence_reference``: identifiers that resolve a value back to Monday (finding IDs, evidence blocks and records);
- ``contract_metadata``: the upstream contract and document versions the payload was built from;
- ``snapshot_metadata``: the source snapshot (``source_snapshot_id``) and release identity every future reasoning run records.

A statement's ``params`` take the kind of its level (``UpstreamStatement.kind``); ``UpstreamFinding`` groups its statements by that
kind (``source_facts``, ``derived_values``, ``upstream_interpretations``).

Only a publishable (``approved_only``) Intelligence V2 document is accepted: review-mode output, which may use unapproved
parameters, never reaches Reasoning V3. Contracts without ``editor_intelligence`` (through 1.4.0) have no Intelligence V2 and are
refused with ``ReasoningInputUnavailable``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from atlas_commander.capabilities import capabilities
from atlas_commander.contracts import schema_errors
from atlas_commander.investigation.engine import SCHEMA as INTELLIGENCE_SCHEMA
from atlas_commander.investigation.engine import consistency_errors
from atlas_commander.investigation.policy import APPROVED_ONLY
from atlas_reasoning.frozen import FrozenMap, freeze, freeze_map, thaw

BOUNDARY_VERSION = "reasoning-input-v1"

INTELLIGENCE_JSON = "intelligence-v2.json"
PUBLICATION_JSON = "publication.json"
PROFILES_DIR = "profiles"

SOURCE_FACT = "source_fact"
DERIVED_VALUE = "deterministic_derived_value"
UPSTREAM_INTERPRETATION = "upstream_interpretation"
EVIDENCE_REFERENCE = "evidence_reference"
CONTRACT_METADATA = "contract_metadata"
SNAPSHOT_METADATA = "snapshot_metadata"
FIELD_KINDS = (SOURCE_FACT, DERIVED_VALUE, UPSTREAM_INTERPRETATION, EVIDENCE_REFERENCE, CONTRACT_METADATA, SNAPSHOT_METADATA)
# A statement's ``params`` carry the kind its level implies (``UpstreamStatement.kind``).
BY_STATEMENT_LEVEL = "by_statement_level"

# Intelligence V2 statement levels (atlas_commander.investigation.models) by the kind of value they carry.
STATEMENT_KINDS = {"fact": SOURCE_FACT, "metric": DERIVED_VALUE, "pattern": DERIVED_VALUE, "association": DERIVED_VALUE,
                   "interpretation": UPSTREAM_INTERPRETATION, "hypothesis": UPSTREAM_INTERPRETATION}


class ReasoningInputError(ValueError):
    """The upstream documents are invalid or inconsistent; Reasoning V3 must not run on them."""


class ReasoningInputUnavailable(ReasoningInputError):
    """There is no Intelligence V2 input to reason about (contract without ``editor_intelligence``, or the artifact is absent)."""


@dataclass(frozen=True)
class UpstreamContract:
    executable_contract_version: str = field(metadata={"kind": CONTRACT_METADATA})
    intelligence_version: str = field(metadata={"kind": CONTRACT_METADATA})
    intelligence_document_version: str = field(metadata={"kind": CONTRACT_METADATA})
    intelligence_mode: str = field(metadata={"kind": CONTRACT_METADATA})
    publication_view_version: str = field(metadata={"kind": CONTRACT_METADATA})
    boundary_version: str = field(metadata={"kind": CONTRACT_METADATA})


@dataclass(frozen=True)
class SnapshotMetadata:
    source_snapshot_id: str = field(metadata={"kind": SNAPSHOT_METADATA})
    release_id: str = field(metadata={"kind": SNAPSHOT_METADATA})
    generated_at: str = field(metadata={"kind": SNAPSHOT_METADATA})
    retrieved_at: str = field(metadata={"kind": SNAPSHOT_METADATA})
    source_run_id: str | None = field(metadata={"kind": SNAPSHOT_METADATA})
    monday_board_id: str | None = field(metadata={"kind": SNAPSHOT_METADATA})
    activity_log_window: FrozenMap = field(metadata={"kind": SNAPSHOT_METADATA})
    windows: FrozenMap = field(metadata={"kind": SNAPSHOT_METADATA})


@dataclass(frozen=True)
class UpstreamStatement:
    """One typed Intelligence V2 statement. ``kind`` follows its evidence level (``STATEMENT_KINDS``)."""

    level: str = field(metadata={"kind": EVIDENCE_REFERENCE})
    code: str = field(metadata={"kind": EVIDENCE_REFERENCE})
    kind: str = field(metadata={"kind": CONTRACT_METADATA})
    params: FrozenMap = field(metadata={"kind": BY_STATEMENT_LEVEL})


@dataclass(frozen=True)
class EvidenceRecordRef:
    """One Monday project behind an evidence block: enough to reopen it in Monday and recompute the value used."""

    monday_item_id: str = field(metadata={"kind": SOURCE_FACT})
    cycle_id: str | None = field(metadata={"kind": EVIDENCE_REFERENCE})
    editor_id: str | None = field(metadata={"kind": DERIVED_VALUE})
    cohort_key: str | None = field(metadata={"kind": DERIVED_VALUE})
    event_ids: tuple[str, ...] = field(metadata={"kind": SOURCE_FACT})
    source_timestamps: tuple[str, ...] = field(metadata={"kind": SOURCE_FACT})
    values: FrozenMap = field(metadata={"kind": DERIVED_VALUE})


@dataclass(frozen=True)
class EvidenceBlockRef:
    role: str = field(metadata={"kind": EVIDENCE_REFERENCE})
    code: str = field(metadata={"kind": EVIDENCE_REFERENCE})
    calculation: str = field(metadata={"kind": CONTRACT_METADATA})
    monday_board_id: str | None = field(metadata={"kind": SOURCE_FACT})
    column_ids: tuple[str, ...] = field(metadata={"kind": SOURCE_FACT})
    sample: FrozenMap = field(metadata={"kind": DERIVED_VALUE})
    comparison: FrozenMap = field(metadata={"kind": DERIVED_VALUE})
    exclusions: tuple[FrozenMap, ...] = field(metadata={"kind": DERIVED_VALUE})
    time_window: FrozenMap | None = field(metadata={"kind": SNAPSHOT_METADATA})
    records: tuple[EvidenceRecordRef, ...] = field(metadata={"kind": EVIDENCE_REFERENCE})


@dataclass(frozen=True)
class FindingScope:
    kind: str = field(metadata={"kind": DERIVED_VALUE})
    editor_id: str | None = field(metadata={"kind": DERIVED_VALUE})
    cohort_key: str | None = field(metadata={"kind": DERIVED_VALUE})
    stage: str | None = field(metadata={"kind": DERIVED_VALUE})
    monday_item_id: str | None = field(metadata={"kind": SOURCE_FACT})


@dataclass(frozen=True)
class ParameterValue:
    name: str = field(metadata={"kind": CONTRACT_METADATA})
    value: Any = field(metadata={"kind": CONTRACT_METADATA})
    status: str = field(metadata={"kind": CONTRACT_METADATA})
    decision_id: str | None = field(metadata={"kind": CONTRACT_METADATA})


@dataclass(frozen=True)
class UpstreamFinding:
    """One published Intelligence V2 finding, exactly as the document states it, split by kind of value."""

    finding_id: str = field(metadata={"kind": EVIDENCE_REFERENCE})
    finding_type: str = field(metadata={"kind": CONTRACT_METADATA})
    detector_version: str = field(metadata={"kind": CONTRACT_METADATA})
    category: str = field(metadata={"kind": DERIVED_VALUE})
    direction: str = field(metadata={"kind": DERIVED_VALUE})
    scope: FindingScope = field(metadata={"kind": DERIVED_VALUE})
    evidence_level: str = field(metadata={"kind": DERIVED_VALUE})
    confidence_level: str = field(metadata={"kind": DERIVED_VALUE})
    confidence_factors: tuple[FrozenMap, ...] = field(metadata={"kind": DERIVED_VALUE})
    rank: int | None = field(metadata={"kind": DERIVED_VALUE})
    severity: str | None = field(metadata={"kind": DERIVED_VALUE})
    sample_size: int = field(metadata={"kind": DERIVED_VALUE})
    affected_editors: tuple[str, ...] = field(metadata={"kind": DERIVED_VALUE})
    affected_video_types: tuple[str, ...] = field(metadata={"kind": DERIVED_VALUE})
    affected_projects: tuple[str, ...] = field(metadata={"kind": SOURCE_FACT})
    time_window: FrozenMap | None = field(metadata={"kind": SNAPSHOT_METADATA})
    parameter_status: str = field(metadata={"kind": CONTRACT_METADATA})
    parameters: tuple[ParameterValue, ...] = field(metadata={"kind": CONTRACT_METADATA})
    limitations: tuple[str, ...] = field(metadata={"kind": DERIVED_VALUE})
    source_facts: tuple[UpstreamStatement, ...] = field(metadata={"kind": SOURCE_FACT})
    derived_values: tuple[UpstreamStatement, ...] = field(metadata={"kind": DERIVED_VALUE})
    upstream_interpretations: tuple[UpstreamStatement, ...] = field(metadata={"kind": UPSTREAM_INTERPRETATION})
    significance: UpstreamStatement = field(metadata={"kind": UPSTREAM_INTERPRETATION})
    suggested_investigations: tuple[UpstreamStatement, ...] = field(metadata={"kind": UPSTREAM_INTERPRETATION})
    supporting_evidence: tuple[EvidenceBlockRef, ...] = field(metadata={"kind": EVIDENCE_REFERENCE})
    contradicting_evidence: tuple[EvidenceBlockRef, ...] = field(metadata={"kind": EVIDENCE_REFERENCE})
    context_evidence: tuple[EvidenceBlockRef, ...] = field(metadata={"kind": EVIDENCE_REFERENCE})

    @property
    def statements(self) -> tuple[UpstreamStatement, ...]:
        """Every statement in the document's order of evidence level (facts first)."""
        return self.source_facts + self.derived_values + self.upstream_interpretations

    @property
    def evidence_blocks(self) -> tuple[EvidenceBlockRef, ...]:
        return self.supporting_evidence + self.contradicting_evidence + self.context_evidence


@dataclass(frozen=True)
class RecentChangeValue:
    measurement: str = field(metadata={"kind": DERIVED_VALUE})
    current: Any = field(metadata={"kind": DERIVED_VALUE})
    comparison: Any = field(metadata={"kind": DERIVED_VALUE})
    difference: Any = field(metadata={"kind": DERIVED_VALUE})
    current_sample: int | None = field(metadata={"kind": DERIVED_VALUE})
    comparison_sample: int | None = field(metadata={"kind": DERIVED_VALUE})
    trend: str | None = field(metadata={"kind": DERIVED_VALUE})
    trend_reason: str | None = field(metadata={"kind": DERIVED_VALUE})


@dataclass(frozen=True)
class EditorState:
    """An Editor's published deterministic state (contract 1.5.0 profile): read-only context, never re-derived here."""

    editor_id: str = field(metadata={"kind": DERIVED_VALUE})
    display_name: str | None = field(metadata={"kind": SOURCE_FACT})
    overall_status: str | None = field(metadata={"kind": DERIVED_VALUE})
    overall_status_state: str | None = field(metadata={"kind": DERIVED_VALUE})
    component_states: FrozenMap = field(metadata={"kind": DERIVED_VALUE})
    recent_change: tuple[RecentChangeValue, ...] = field(metadata={"kind": DERIVED_VALUE})


@dataclass(frozen=True)
class ReasoningInput:
    """Everything Reasoning V3 may consume from one Atlas snapshot. Deeply immutable; built only by ``build_reasoning_input``."""

    contract: UpstreamContract = field(metadata={"kind": CONTRACT_METADATA})
    snapshot: SnapshotMetadata = field(metadata={"kind": SNAPSHOT_METADATA})
    findings: tuple[UpstreamFinding, ...] = field(metadata={"kind": EVIDENCE_REFERENCE})
    editors: tuple[EditorState, ...] = field(metadata={"kind": DERIVED_VALUE})
    video_types: FrozenMap = field(metadata={"kind": SOURCE_FACT})

    def finding(self, finding_id: str) -> UpstreamFinding:
        return next(row for row in self.findings if row.finding_id == finding_id)

    def editor(self, editor_id: str) -> EditorState | None:
        return next((row for row in self.editors if row.editor_id == editor_id), None)

    def to_dict(self) -> dict[str, Any]:
        """A plain JSON-ready copy (for debugging and persistence); mutating it never affects this payload."""
        return _plain(self)


def field_kinds(cls: type) -> dict[str, str]:
    """The kind (``FIELD_KINDS``) of every field of a boundary dataclass."""
    return {item.name: item.metadata["kind"] for item in fields(cls)}


def build_reasoning_input(*, intelligence: Mapping[str, Any] | None, publication: Mapping[str, Any] | None,
                          profiles: Iterable[Mapping[str, Any]]) -> ReasoningInput:
    """The typed, immutable Reasoning V3 input for one site build. Raises ``ReasoningInputError`` when the documents are not a
    valid, publishable, single-snapshot set; never modifies them."""
    if intelligence is None:
        raise ReasoningInputUnavailable("no Intelligence V2 document: Reasoning V3 needs a contract 1.5.0+ build with the Intelligence V2 gate on")
    contract_version = str(intelligence.get("executable_contract_version"))
    if not capabilities(contract_version).editor_intelligence:
        raise ReasoningInputUnavailable(f"contract {contract_version} has no Intelligence V2 (editor_intelligence)")
    problems = schema_errors(intelligence, INTELLIGENCE_SCHEMA)[:5]
    if not problems:
        problems = consistency_errors(intelligence)[:5]
    if problems:
        raise ReasoningInputError(f"{INTELLIGENCE_JSON} is not a valid Intelligence V2 document: {problems}")
    if intelligence.get("publishable") is not True or intelligence.get("mode") != APPROVED_ONLY:
        raise ReasoningInputError("only a publishable (approved_only) Intelligence V2 document may reach Reasoning V3, never review output")
    if publication is None:
        raise ReasoningInputError(f"{PUBLICATION_JSON} is required: it names the source snapshot every reasoning run records")
    source = intelligence["source"]
    if publication.get("executable_contract_version") != contract_version:
        raise ReasoningInputError(f"{PUBLICATION_JSON} and {INTELLIGENCE_JSON} were built with different contracts")
    if (publication.get("source") or {}).get("retrieved_at") != source.get("retrieved_at"):
        raise ReasoningInputError(f"{PUBLICATION_JSON} and {INTELLIGENCE_JSON} come from different Monday snapshots")
    for name in ("snapshot_id", "release_id", "generated_at", "publication_view_version"):
        if not isinstance(publication.get(name), str) or not publication[name]:
            raise ReasoningInputError(f"{PUBLICATION_JSON} has no {name}")
    editors = []
    for profile in sorted(profiles, key=lambda row: str((row.get("editor") or {}).get("editor_id"))):
        if profile.get("executable_contract_version") != contract_version:
            raise ReasoningInputError(f"profile {(profile.get('editor') or {}).get('editor_id')} was built with another contract")
        snapshot = (profile.get("publication") or {}).get("snapshot_id")
        if snapshot is not None and snapshot != publication["snapshot_id"]:
            raise ReasoningInputError(f"profile {(profile.get('editor') or {}).get('editor_id')} comes from another snapshot")
        editors.append(_editor_state(profile))
    return ReasoningInput(
        contract=UpstreamContract(contract_version, str(intelligence["intelligence_version"]), str(intelligence["document_version"]),
                                  str(intelligence["mode"]), str(publication["publication_view_version"]), BOUNDARY_VERSION),
        snapshot=SnapshotMetadata(publication["snapshot_id"], publication["release_id"], publication["generated_at"], str(source["retrieved_at"]),
                                  source.get("run_id"), source.get("monday_board_id"), freeze_map(source.get("activity_log_window")),
                                  freeze_map(intelligence.get("windows"))),
        findings=tuple(_finding(row) for row in intelligence["findings"]),
        editors=tuple(editors),
        video_types=freeze_map(intelligence.get("video_types")),
    )


def load_reasoning_input(site: Path) -> ReasoningInput:
    """Read a built (staged or published) site directory and build its ``ReasoningInput``. Reads files; writes nothing."""
    intelligence_path = site / INTELLIGENCE_JSON
    if not intelligence_path.is_file():
        raise ReasoningInputUnavailable(f"{site} has no {INTELLIGENCE_JSON}")
    publication_path = site / PUBLICATION_JSON
    publication = json.loads(publication_path.read_text()) if publication_path.is_file() else None
    profiles = [json.loads(path.read_text()) for path in sorted((site / PROFILES_DIR).glob("*.json"))]
    return build_reasoning_input(intelligence=json.loads(intelligence_path.read_text()), publication=publication, profiles=profiles)


def _statement(row: Mapping[str, Any]) -> UpstreamStatement:
    return UpstreamStatement(str(row["level"]), str(row["code"]), STATEMENT_KINDS[row["level"]], freeze_map(row.get("params")))


def _record(row: Mapping[str, Any]) -> EvidenceRecordRef:
    return EvidenceRecordRef(str(row["monday_item_id"]), row.get("cycle_id"), row.get("editor_id"), row.get("cohort_key"),
                             tuple(row["event_ids"]), tuple(row["source_timestamps"]), freeze_map(row.get("values")))


def _block(row: Mapping[str, Any]) -> EvidenceBlockRef:
    return EvidenceBlockRef(str(row["role"]), str(row["code"]), str(row.get("calculation") or ""), row.get("monday_board_id"),
                            tuple(row.get("column_ids") or ()), freeze_map(row.get("sample")), freeze_map(row.get("comparison")),
                            tuple(freeze_map(item) for item in row.get("exclusions") or ()),
                            freeze_map(row["time_window"]) if row.get("time_window") else None,
                            tuple(_record(record) for record in row.get("records") or ()))


def upstream_finding(row: Mapping[str, Any]) -> UpstreamFinding:
    """One finding of an already validated Intelligence V2 document, as the boundary types it (used by ``build_reasoning_input``;
    exposed for tests and tools that work on single findings)."""
    return _finding(row)


def _finding(row: Mapping[str, Any]) -> UpstreamFinding:
    statements = [_statement(item) for item in row["statements"]]
    scope = row["scope"]
    confidence = row.get("confidence") or {}
    return UpstreamFinding(
        finding_id=str(row["finding_id"]), finding_type=str(row["finding_type"]), detector_version=str(row["detector_version"]),
        category=str(row["category"]), direction=str(row["direction"]),
        scope=FindingScope(str(scope["kind"]), scope.get("editor_id"), scope.get("cohort_key"), scope.get("stage"), scope.get("monday_item_id")),
        evidence_level=str(row["evidence_level"]), confidence_level=str(confidence.get("level")),
        confidence_factors=tuple(freeze_map({key: item.get(key) for key in ("factor", "assessment", "value")}) for item in confidence.get("factors") or ()),
        rank=(row.get("importance") or {}).get("rank"), severity=row.get("severity"), sample_size=int(row["sample_size"]),
        affected_editors=tuple(row["affected_editors"]), affected_video_types=tuple(row["affected_video_types"]),
        affected_projects=tuple(row["affected_projects"]), time_window=freeze_map(row["time_window"]) if row.get("time_window") else None,
        parameter_status=str(row["parameter_status"]),
        parameters=tuple(ParameterValue(str(item["name"]), freeze(item.get("value")), str(item["status"]), item.get("decision_id"))
                         for item in row.get("parameters") or ()),
        limitations=tuple(row.get("limitations") or ()),
        source_facts=tuple(item for item in statements if item.kind == SOURCE_FACT),
        derived_values=tuple(item for item in statements if item.kind == DERIVED_VALUE),
        upstream_interpretations=tuple(item for item in statements if item.kind == UPSTREAM_INTERPRETATION),
        significance=_statement(row["significance"]),
        suggested_investigations=tuple(_statement(item) for item in row.get("suggested_investigations") or ()),
        supporting_evidence=tuple(_block(item) for item in row.get("supporting_evidence") or ()),
        contradicting_evidence=tuple(_block(item) for item in row.get("contradicting_evidence") or ()),
        context_evidence=tuple(_block(item) for item in row.get("context_evidence") or ()),
    )


def _editor_state(profile: Mapping[str, Any]) -> EditorState:
    editor = profile.get("editor") or {}
    overall = profile.get("overall") or {}
    recent = ((profile.get("trend") or {}).get("recent_change") or {})
    changes = tuple(RecentChangeValue(str(name), freeze(row.get("current")), freeze(row.get("comparison")), freeze(row.get("difference")),
                                      row.get("current_sample"), row.get("comparison_sample"), row.get("trend"), row.get("trend_reason"))
                    for name, row in sorted(recent.items()) if isinstance(row, Mapping))
    return EditorState(str(editor.get("editor_id")), editor.get("display_name"), overall.get("status"), overall.get("status_state"),
                       freeze_map(overall.get("component_states")), changes)


def _plain(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return thaw(value)
