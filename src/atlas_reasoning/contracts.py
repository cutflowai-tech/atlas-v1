"""The Reasoning V3 machine contracts (``reasoning-v1``): ReasoningCase, ReasoningResult and ReasoningUpdate (``REV/02``).

Each contract has three layers:

1. a JSON Schema in ``contracts/`` (``reasoning-case-v1``, ``reasoning-result-v1``, ``reasoning-update-v1``, sharing
   ``reasoning-common-v1``): structure, strict enums, no unknown fields at any level;
2. semantic validators for cross-field invariants the schema cannot express (``case_errors``, ``result_errors``,
   ``update_errors``, and the cross-object checks ``result_case_errors``, ``update_result_errors``, ``update_case_errors``);
3. frozen, typed dataclasses (``ReasoningCase``, ``ReasoningResult``, ``ReasoningUpdate``) built only through ``from_dict``,
   which runs both layers first. ``to_dict`` round-trips exactly.

Every error is ``"<CODE>: <detail>"``; ``ContractViolation.codes`` lists the codes. Validation never consults an LLM, a prompt
or a database: a builder can construct, validate, store and render the three objects from this module alone.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import types
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any, ClassVar, Self, Union, get_args, get_origin, get_type_hints

from jsonschema import FormatChecker
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from atlas_reasoning.case_identity import identity_errors
from atlas_reasoning.enums import (
    CONFIDENCE_ORDER,
    CaseType,
    ConfidenceLevel,
    Direction,
    EvidenceLevel,
    EvidenceRole,
    ExpectedContextType,
    LifecycleStatus,
    MemoryStatus,
    NoteSource,
    StatementKind,
    SubjectType,
    TopicKey,
    UpdateAction,
)
from atlas_reasoning.frozen import FrozenMap, freeze, thaw

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
COMMON_SCHEMA = "reasoning-common-v1.schema.json"
CASE_SCHEMA = "reasoning-case-v1.schema.json"
RESULT_SCHEMA = "reasoning-result-v1.schema.json"
UPDATE_SCHEMA = "reasoning-update-v1.schema.json"
SCHEMA_FILES = (COMMON_SCHEMA, CASE_SCHEMA, RESULT_SCHEMA, UPDATE_SCHEMA)

# The only ReasoningResult fields a ReasoningUpdate may change. Everything else is identity, lifecycle, provenance or a timestamp,
# set deterministically by Python (case_id and result_id never change at all).
PATCHABLE_FIELDS = ("title", "observation", "reasoning_summary", "supporting_evidence", "counter_evidence", "interpretation",
                    "alternative_explanations", "confidence", "limitations", "management_significance", "questions_for_management",
                    "suggested_investigations")
IMMUTABLE_RESULT_FIELDS = ("contract_version", "result_id", "case_id", "version", "lifecycle_status", "superseded_by", "source_snapshot_id",
                           "evidence_fingerprint", "model_metadata", "prompt_version", "created_at", "updated_at")
# Result fields that hold visible conclusions; each cites deterministic evidence (the schema requires at least one reference).
CLAIM_FIELDS = ("observation", "interpretation", "management_significance")
CLAIM_LIST_FIELDS = ("supporting_evidence", "counter_evidence")

STATEMENT_KIND_BY_LEVEL = {EvidenceLevel.FACT: StatementKind.SOURCE_FACT, EvidenceLevel.METRIC: StatementKind.DERIVED_VALUE,
                           EvidenceLevel.PATTERN: StatementKind.DERIVED_VALUE, EvidenceLevel.ASSOCIATION: StatementKind.DERIVED_VALUE,
                           EvidenceLevel.INTERPRETATION: StatementKind.UPSTREAM_INTERPRETATION,
                           EvidenceLevel.HYPOTHESIS: StatementKind.UPSTREAM_INTERPRETATION}
OPPOSITE = {Direction.ADVERSE: Direction.FAVOURABLE, Direction.FAVOURABLE: Direction.ADVERSE}


class ContractViolation(ValueError):
    """A payload breaks a Reasoning V3 contract. ``errors`` are ``"<CODE>: <detail>"`` strings."""

    def __init__(self, contract: str, errors: list[str]) -> None:
        super().__init__(f"{contract} violates reasoning-v1: {errors[:8]}")
        self.contract, self.errors = contract, errors

    @property
    def codes(self) -> list[str]:
        return sorted({error.split(":", 1)[0] for error in self.errors})


# --- identifiers ---------------------------------------------------------------------------------------------------------


def new_result_id() -> str:
    """A fresh, immutable result identity (one per result, kept across all its versions)."""
    return f"rr1_{uuid.uuid4().hex}"


def evidence_ref_id(member_key: str, role: str, evidence_code: str, monday_item_id: str, cycle_id: str | None) -> str:
    """Stable reference to one evidence record of a case: the same record keeps the same ``ref_id`` across runs."""
    body = json.dumps([member_key, str(role), evidence_code, monday_item_id, cycle_id], separators=(",", ":"), ensure_ascii=True)
    return f"ev1_{hashlib.sha256(body.encode()).hexdigest()[:24]}"


# --- schema layer ----------------------------------------------------------------------------------------------------------


@cache
def _schemas() -> dict[str, dict[str, Any]]:
    return {name: json.loads((CONTRACTS_DIR / name).read_text()) for name in SCHEMA_FILES}


@cache
def _registry() -> Registry[Any]:
    registry: Registry[Any] = Registry()
    for name, schema in _schemas().items():
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(schema["$id"], resource).with_resource(name, resource)
    return registry


def _validator(schema: Mapping[str, Any]) -> Any:
    cls = validator_for(schema)
    return cls(schema, registry=_registry(), format_checker=FormatChecker())


def schema(name: str) -> dict[str, Any]:
    return _schemas()[name]


def _code(error: ValidationError) -> str:
    path = "/".join(str(part) for part in error.absolute_path) or "<root>"
    if error.validator == "additionalProperties":
        return f"UNKNOWN_FIELD: {path}: {error.message}"
    if error.validator in ("enum", "const"):
        return f"INVALID_ENUM: {path}: {error.message}"
    if (error.validator == "minItems" and ("evidence_refs" in path or path == "supporting_evidence")) \
            or (error.validator == "required" and "'evidence_refs'" in error.message):
        return f"MISSING_EVIDENCE: {path}: {error.message}"
    return f"SCHEMA_INVALID: {path}: {error.message}"


def schema_errors(instance: Any, name: str) -> list[str]:
    validator = _validator(schema(name))
    return [_code(error) for error in sorted(validator.iter_errors(instance), key=lambda e: [str(p) for p in e.absolute_path])]


def field_value_errors(field_name: str, value: Any) -> list[str]:
    """Errors of ``value`` against the ReasoningResult schema of one patchable field."""
    validator = _validator({"$ref": f"{RESULT_SCHEMA}#/properties/{field_name}"})
    return [_code(error) for error in validator.iter_errors(value)]


# --- semantic layer ---------------------------------------------------------------------------------------------------------


def _finding_refs(case: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [*case.get("supporting_findings", []), *case.get("contradicting_findings", [])]


def case_semantic_errors(case: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if (case["previous_result_id"] is None) != (case["previous_result_version"] is None):
        errors.append("PREVIOUS_RESULT_PAIRING: previous_result_id and previous_result_version are set together or not at all")
    delta = case["material_delta"]
    if delta is not None:
        if delta["fingerprint_after"] != case["evidence_fingerprint"]:
            errors.append("DELTA_FINGERPRINT_MISMATCH: material_delta.fingerprint_after must equal evidence_fingerprint")
        if delta["fingerprint_before"] == delta["fingerprint_after"]:
            errors.append("DELTA_NOT_A_CHANGE: a material delta needs two different fingerprints")
    orientation = Direction(case["orientation"])
    keys = [row["member_key"] for row in _finding_refs(case)]
    if len(keys) != len(set(keys)):
        errors.append("DUPLICATE_FINDING: a finding appears twice in the case")
    for row in case["supporting_findings"]:
        if orientation in OPPOSITE and row["direction"] == OPPOSITE[orientation]:
            errors.append(f"ORIENTATION_CONFLICT: supporting finding {row['member_key']} opposes the case orientation {orientation}")
    for row in case["contradicting_findings"]:
        if orientation not in OPPOSITE or row["direction"] != OPPOSITE[orientation]:
            errors.append(f"ORIENTATION_CONFLICT: contradicting finding {row['member_key']} does not oppose the case orientation {orientation}")
    members = set(keys)
    evidence = case["current_evidence"]
    for statement in evidence["statements"]:
        if statement["member_key"] not in members:
            errors.append(f"UNKNOWN_MEMBER: statement {statement['code']} names unknown finding {statement['member_key']}")
        if STATEMENT_KIND_BY_LEVEL[EvidenceLevel(statement["level"])] != statement["kind"]:
            errors.append(f"STATEMENT_KIND_MISMATCH: a {statement['level']} statement is not a {statement['kind']}")
    ref_ids = [ref["ref_id"] for ref in evidence["references"]]
    if len(ref_ids) != len(set(ref_ids)):
        errors.append("DUPLICATE_REF: evidence reference IDs must be unique")
    referenced = set()
    for ref in evidence["references"]:
        referenced.add(ref["member_key"])
        if ref["member_key"] not in members:
            errors.append(f"UNKNOWN_MEMBER: evidence {ref['ref_id']} names unknown finding {ref['member_key']}")
        expected = evidence_ref_id(ref["member_key"], ref["role"], ref["evidence_code"], ref["monday_item_id"], ref["cycle_id"])
        if ref["ref_id"] != expected:
            errors.append(f"REF_ID_MISMATCH: evidence {ref['ref_id']} should be {expected}")
    for key in sorted(members - referenced):
        errors.append(f"FINDING_WITHOUT_EVIDENCE: finding {key} has no deterministic evidence reference")
    return errors + _extension_errors(case)


# Later foundation phases register deterministic recomputation checks here (case identity, evidence fingerprint), so a case whose
# case_id or fingerprint does not match its own content is rejected.
CASE_CHECKS: list[Callable[[Mapping[str, Any]], list[str]]] = [identity_errors]


def _extension_errors(case: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for check in CASE_CHECKS:
        errors.extend(check(case))
    return errors


def result_semantic_errors(result: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    superseded = result["lifecycle_status"] == LifecycleStatus.SUPERSEDED
    link = result["superseded_by"]
    if superseded != (link is not None):
        errors.append("SUPERSEDED_LINK: a superseded result names its replacement, and only a superseded result does")
    if link is not None and link["result_id"] == result["result_id"]:
        errors.append("SUPERSEDED_LINK: a result cannot supersede itself")
    if _instant(result["updated_at"]) < _instant(result["created_at"]):
        errors.append("TIMESTAMP_ORDER: updated_at precedes created_at")
    return errors


def update_semantic_errors(update: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    changed = [row.get("field") for row in update.get("changed_fields") or [] if isinstance(row, Mapping)]
    preserved = list(update.get("preserved_fields") or [])
    for name in [*changed, *preserved]:
        if name in IMMUTABLE_RESULT_FIELDS:
            errors.append(f"IMMUTABLE_FIELD: {name} is not patchable")
        elif name not in PATCHABLE_FIELDS:
            errors.append(f"UNKNOWN_FIELD: {name} is not a ReasoningResult field")
    if len(changed) != len(set(changed)):
        errors.append("DUPLICATE_CHANGE: a field is changed twice")
    overlap = sorted(set(changed) & set(preserved), key=str)
    if overlap:
        errors.append(f"FIELD_ACCOUNTING: fields both changed and preserved: {overlap}")
    missing = [name for name in PATCHABLE_FIELDS if name not in changed and name not in preserved]
    if missing:
        errors.append(f"FIELD_ACCOUNTING: every patchable field must be listed as changed or preserved; missing {missing}")
    action = update.get("action")
    if action == UpdateAction.NO_CHANGE and changed:
        errors.append("ACTION_MISMATCH: a no_change update changes nothing")
    if action == UpdateAction.PATCH and not changed:
        errors.append("ACTION_MISMATCH: a patch changes at least one field")
    for row in update.get("changed_fields") or []:
        if isinstance(row, Mapping) and row.get("field") in PATCHABLE_FIELDS:
            errors.extend(f"INVALID_FIELD_VALUE: {row['field']}: {error}" for error in field_value_errors(str(row["field"]), row.get("value")))
    return errors


def case_errors(case: Any) -> list[str]:
    errors = schema_errors(case, CASE_SCHEMA)
    return errors or case_semantic_errors(case)


def result_errors(result: Any) -> list[str]:
    errors = schema_errors(result, RESULT_SCHEMA)
    return errors or result_semantic_errors(result)


def update_errors(update: Any) -> list[str]:
    semantic = update_semantic_errors(update) if isinstance(update, Mapping) else []
    errors = schema_errors(update, UPDATE_SCHEMA)
    if isinstance(update, Mapping):
        # Name an immutable or unknown target once, by its own code, rather than as an enum error.
        errors = [error for error in errors if not (error.startswith("INVALID_ENUM") and ("changed_fields" in error or "preserved_fields" in error))]
    return sorted(set(errors + semantic), key=(errors + semantic).index)


def claim_refs(result: Mapping[str, Any]) -> set[str]:
    """Every evidence reference a result cites."""
    refs: set[str] = set()
    for name in CLAIM_FIELDS:
        refs.update(result[name]["evidence_refs"])
    for name in CLAIM_LIST_FIELDS:
        for claim in result[name]:
            refs.update(claim["evidence_refs"])
    for row in [*result["alternative_explanations"], *result["suggested_investigations"]]:
        refs.update(row["evidence_refs"])
    return refs


def result_case_errors(result: Mapping[str, Any], case: Mapping[str, Any]) -> list[str]:
    """A result must belong to its case, cite only that case's evidence, handle its counter-evidence and never be more confident
    than the strongest upstream finding behind it."""
    errors: list[str] = []
    if result["case_id"] != case["case_id"]:
        errors.append("CASE_MISMATCH: the result belongs to another case")
    if result["evidence_fingerprint"] != case["evidence_fingerprint"]:
        errors.append("EVIDENCE_FINGERPRINT_MISMATCH: the result was reasoned on other evidence than the case carries")
    known = {ref["ref_id"] for ref in case["current_evidence"]["references"]}
    unknown = sorted(claim_refs(result) - known)
    if unknown:
        errors.append(f"UNKNOWN_EVIDENCE_REF: references not in the case: {unknown}")
    contradicted = bool(case["contradicting_findings"]) or any(ref["role"] == EvidenceRole.CONTRADICTING for ref in case["current_evidence"]["references"])
    if contradicted and not result["counter_evidence"]:
        errors.append("COUNTER_EVIDENCE_MISSING: the case has contradicting evidence the result does not address")
    ceiling = max((CONFIDENCE_ORDER.index(ConfidenceLevel(row["confidence"])) for row in case["supporting_findings"]), default=0)
    if CONFIDENCE_ORDER.index(ConfidenceLevel(result["confidence"]["level"])) > ceiling:
        errors.append(f"CONFIDENCE_EXCEEDS_UPSTREAM: result confidence exceeds the strongest supporting finding ({CONFIDENCE_ORDER[ceiling]})")
    return errors


def update_result_errors(update: Mapping[str, Any], result: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if update["case_id"] != result["case_id"]:
        errors.append("IMMUTABLE_FIELD: case_id of the update differs from the result's")
    if update["result_id"] != result["result_id"]:
        errors.append("IMMUTABLE_FIELD: result_id of the update differs from the result's")
    if update["base_version"] != result["version"]:
        errors.append(f"STALE_BASE_VERSION: the update targets version {update['base_version']}, the result is at {result['version']}")
    if update["evidence_fingerprint_before"] != result["evidence_fingerprint"]:
        errors.append("EVIDENCE_FINGERPRINT_MISMATCH: evidence_fingerprint_before is not the result's fingerprint")
    return errors


def update_case_errors(update: Mapping[str, Any], case: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if update["case_id"] != case["case_id"]:
        errors.append("CASE_MISMATCH: the update belongs to another case")
    if update["evidence_fingerprint_after"] != case["evidence_fingerprint"]:
        errors.append("EVIDENCE_FINGERPRINT_MISMATCH: evidence_fingerprint_after is not the case's current fingerprint")
    known = {ref["ref_id"] for ref in case["current_evidence"]["references"]}
    for row in update["changed_fields"]:
        cited = _refs_in(row["value"])
        if cited - known:
            errors.append(f"UNKNOWN_EVIDENCE_REF: {row['field']} cites references not in the case: {sorted(cited - known)}")
    return errors


def _refs_in(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        found = set(value.get("evidence_refs") or []) if isinstance(value.get("evidence_refs"), list) else set()
        for item in value.values():
            found |= _refs_in(item)
        return found
    if isinstance(value, list):
        return set().union(*(_refs_in(item) for item in value)) if value else set()
    return set()


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- typed models -----------------------------------------------------------------------------------------------------------

def _decode(tp: Any, value: Any) -> Any:
    origin = get_origin(tp)
    if tp is Any:
        return freeze(value)
    if origin in (Union, types.UnionType):
        args = [arg for arg in get_args(tp) if arg is not type(None)]
        return None if value is None else _decode(args[0], value)
    if origin is tuple:
        return tuple(_decode(get_args(tp)[0], item) for item in value)
    if origin is not None and isinstance(origin, type) and issubclass(origin, Mapping):
        return freeze(value)
    if tp is FrozenMap:
        return freeze(value)
    if dataclasses.is_dataclass(tp):
        hints = get_type_hints(tp)
        builder: Any = tp
        return builder(**{item.name: _decode(hints[item.name], value[item.name]) for item in fields(tp) if item.name in value})
    if isinstance(tp, type) and issubclass(tp, StrEnum):
        return tp(value)
    return value


def _encode(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {item.name: _encode(getattr(value, item.name)) for item in fields(value) if not (item.metadata.get("omit_none") and getattr(value, item.name) is None)}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return thaw(value)


@dataclass(frozen=True)
class Claim:
    statement: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class FindingRef:
    finding_id: str
    member_key: str
    finding_type: str
    direction: Direction
    category: str
    evidence_level: EvidenceLevel
    confidence: ConfidenceLevel
    sample_size: int
    rank: int | None


@dataclass(frozen=True)
class CaseStatement:
    member_key: str
    level: EvidenceLevel
    kind: StatementKind
    code: str
    params: FrozenMap


@dataclass(frozen=True)
class EvidenceReference:
    ref_id: str
    member_key: str
    finding_id: str
    role: EvidenceRole
    evidence_code: str
    monday_item_id: str
    cycle_id: str | None
    editor_id: str | None
    video_type_key: str | None
    event_ids: tuple[str, ...]
    source_timestamps: tuple[str, ...]
    values: FrozenMap


@dataclass(frozen=True)
class CurrentEvidence:
    statements: tuple[CaseStatement, ...]
    references: tuple[EvidenceReference, ...]


@dataclass(frozen=True)
class EvidenceKey:
    ref_id: str
    member_key: str
    role: EvidenceRole
    evidence_code: str
    monday_item_id: str
    cycle_id: str | None


@dataclass(frozen=True)
class ContradictionChange:
    kind: str
    member_key: str
    ref_id: str | None


@dataclass(frozen=True)
class ValueChange:
    member_key: str | None
    path: str
    before: Any
    after: Any


@dataclass(frozen=True)
class ConfidenceChange:
    member_key: str
    before: ConfidenceLevel
    after: ConfidenceLevel


@dataclass(frozen=True)
class OrientationChange:
    before: Direction
    after: Direction


@dataclass(frozen=True)
class MaterialDelta:
    delta_version: str
    fingerprint_before: str
    fingerprint_after: str
    orientation_change: OrientationChange | None
    added_findings: tuple[str, ...]
    removed_findings: tuple[str, ...]
    added_evidence: tuple[EvidenceKey, ...]
    removed_evidence: tuple[EvidenceKey, ...]
    changed_values: tuple[ValueChange, ...]
    changed_confidence: tuple[ConfidenceChange, ...]
    added_contradictions: tuple[ContradictionChange, ...]
    removed_contradictions: tuple[ContradictionChange, ...]

    @property
    def is_empty(self) -> bool:
        return not any((self.orientation_change, self.added_findings, self.removed_findings, self.added_evidence, self.removed_evidence,
                        self.changed_values, self.changed_confidence, self.added_contradictions, self.removed_contradictions))


@dataclass(frozen=True)
class CaseScope:
    affected_editor_ids: tuple[str, ...]
    affected_video_type_keys: tuple[str, ...]
    affected_project_count: int
    windows: tuple[str, ...]


@dataclass(frozen=True)
class UpstreamVersions:
    intelligence_version: str
    intelligence_document_version: str
    boundary_version: str


@dataclass(frozen=True)
class IdentityDimensions:
    video_type: str | None = dataclasses.field(default=None, metadata={"omit_none": True})
    workflow_stage: str | None = dataclasses.field(default=None, metadata={"omit_none": True})
    detector_family: str | None = dataclasses.field(default=None, metadata={"omit_none": True})
    signal: str | None = dataclasses.field(default=None, metadata={"omit_none": True})


@dataclass(frozen=True)
class ContextItem:
    source_type: NoteSource
    source_id: str
    body: str
    author: str | None
    recorded_at: str


@dataclass(frozen=True)
class MemoryItem:
    source_type: NoteSource
    memory_ref: str
    session_key: str
    body: str
    recorded_at: str | None


@dataclass(frozen=True)
class MemoryContext:
    status: MemoryStatus
    items: tuple[MemoryItem, ...]


NO_MEMORY = MemoryContext(MemoryStatus.NOT_REQUESTED, ())


class Contract:
    """Shared construction, validation and serialization of the three top-level contracts."""

    SCHEMA: ClassVar[str]
    NAME: ClassVar[str]

    @classmethod
    def errors(cls, data: Any) -> list[str]:
        raise NotImplementedError

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        errors = cls.errors(data)
        if errors:
            raise ContractViolation(cls.NAME, errors)
        return _decode(cls, data)

    def to_dict(self) -> dict[str, Any]:
        return _encode(self)

    def validated(self) -> Self:
        """Validate an object built in Python (both layers); returns it unchanged or raises ``ContractViolation``."""
        errors = type(self).errors(self.to_dict())
        if errors:
            raise ContractViolation(type(self).NAME, errors)
        return self


@dataclass(frozen=True)
class ReasoningCase(Contract):
    SCHEMA: ClassVar[str] = CASE_SCHEMA
    NAME: ClassVar[str] = "ReasoningCase"

    contract_version: str
    case_id: str
    case_type: CaseType
    identity_version: str
    identity_key: str
    subject_type: SubjectType
    subject_id: str
    topic_key: TopicKey
    identity_dimensions: IdentityDimensions
    scope: CaseScope
    source_snapshot_id: str
    upstream_contract_version: str
    upstream: UpstreamVersions
    orientation: Direction
    supporting_findings: tuple[FindingRef, ...]
    contradicting_findings: tuple[FindingRef, ...]
    current_evidence: CurrentEvidence
    previous_result_id: str | None
    previous_result_version: int | None
    evidence_fingerprint: str
    material_delta: MaterialDelta | None
    manager_context: tuple[ContextItem, ...]
    memory_context: MemoryContext
    created_at: str

    @classmethod
    def errors(cls, data: Any) -> list[str]:
        return case_errors(data)

    @property
    def findings(self) -> tuple[FindingRef, ...]:
        return self.supporting_findings + self.contradicting_findings


@dataclass(frozen=True)
class AlternativeExplanation:
    explanation: str
    evidence_refs: tuple[str, ...]
    requires_context: bool


@dataclass(frozen=True)
class ResultConfidence:
    level: ConfidenceLevel
    rationale: str


@dataclass(frozen=True)
class ManagementQuestion:
    text: str
    reason: str
    expected_context_type: ExpectedContextType


@dataclass(frozen=True)
class Investigation:
    text: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class SupersededBy:
    case_id: str
    result_id: str


@dataclass(frozen=True)
class ModelMetadata:
    provider: str
    model: str
    request_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReasoningResult(Contract):
    SCHEMA: ClassVar[str] = RESULT_SCHEMA
    NAME: ClassVar[str] = "ReasoningResult"

    contract_version: str
    result_id: str
    case_id: str
    version: int
    title: str
    observation: Claim
    reasoning_summary: str
    supporting_evidence: tuple[Claim, ...]
    counter_evidence: tuple[Claim, ...]
    interpretation: Claim
    alternative_explanations: tuple[AlternativeExplanation, ...]
    confidence: ResultConfidence
    limitations: tuple[str, ...]
    management_significance: Claim
    questions_for_management: tuple[ManagementQuestion, ...]
    suggested_investigations: tuple[Investigation, ...]
    lifecycle_status: LifecycleStatus
    superseded_by: SupersededBy | None
    source_snapshot_id: str
    evidence_fingerprint: str
    model_metadata: ModelMetadata
    prompt_version: str
    created_at: str
    updated_at: str

    @classmethod
    def errors(cls, data: Any) -> list[str]:
        return result_errors(data)


@dataclass(frozen=True)
class FieldChange:
    field: str
    value: Any


@dataclass(frozen=True)
class ReasoningUpdate(Contract):
    SCHEMA: ClassVar[str] = UPDATE_SCHEMA
    NAME: ClassVar[str] = "ReasoningUpdate"

    contract_version: str
    case_id: str
    result_id: str
    base_version: int
    action: UpdateAction
    changed_fields: tuple[FieldChange, ...]
    preserved_fields: tuple[str, ...]
    change_rationale: str
    evidence_fingerprint_before: str
    evidence_fingerprint_after: str

    @classmethod
    def errors(cls, data: Any) -> list[str]:
        return update_errors(data)

    @property
    def changed_names(self) -> tuple[str, ...]:
        return tuple(row.field for row in self.changed_fields)

