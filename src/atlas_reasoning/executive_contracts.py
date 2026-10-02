"""The ExecutiveBrief contract (``executive-brief-v1``, ``REV/17`` #1, #4, #5): schema, typed model and the model-output shape.

An ExecutiveBrief is a separate, versioned contract. It never changes ``reasoning-result-v1``: executive synthesis is downstream of
validated canonical ReasoningResults and refers to them only by ``result_id``.

    brief = ExecutiveBrief.from_dict(document)     # schema + semantic validation, then frozen typed objects
    document = brief.to_dict()                     # exact round trip
    errors = brief_errors(document)                # "<CODE>: <detail>" strings (contracts.ContractViolation codes)

Layers, like the reasoning-v1 contracts (``contracts``):

1. the JSON Schema ``contracts/executive-brief-v1.schema.json``: no unknown field at any level (so there is no place for hidden
   reasoning), eight fixed sections, every statement with at least one ``rr1_`` result ID;
2. semantic checks the schema cannot express (``brief_semantic_errors``): statement IDs are ``<section>-<position>``, input results
   are unique, every referenced result is one of the brief's ``input_results`` (``REFERENCE_NOT_IN_INPUT``), a deterministic empty
   brief has no input and no statement, a model brief names its provider, model, prompt version and request IDs;
3. frozen dataclasses built only through ``from_dict``.

The model never writes the whole document: it answers ``model_output_schema()`` (the eight sections; statements without IDs), and
Python adds identity, version, run, input fingerprint, statement IDs, generator, prompt and validator versions and the timestamp
(``executive.assemble_brief``). Grounding against the synthesis input is ``executive_validator``'s.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, ClassVar

from jsonschema import FormatChecker
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for

from atlas_reasoning.contracts import CONTRACTS_DIR, Contract
from atlas_reasoning.enums import LifecycleStatus

BRIEF_SCHEMA = "executive-brief-v1.schema.json"
BRIEF_CONTRACT_VERSION = "executive-brief-v1"
COMPANY_SCOPE = "company"

# The eight sections of REV/17 #4, in display order.
SECTIONS = ("what_changed", "top_concerns", "important_improvements", "system_patterns", "editor_context", "unresolved_questions", "uncertainty",
            "inspect_next")
EDITOR_SECTION = "editor_context"
# REV/17 #2: only canonical results in these lifecycle states may feed an ExecutiveBrief (never cooling or superseded).
ELIGIBLE_LIFECYCLE = (LifecycleStatus.NEW, LifecycleStatus.ACTIVE, LifecycleStatus.UPDATED, LifecycleStatus.RESOLVED)
GENERATOR_MODEL = "model"
GENERATOR_EMPTY = "deterministic_empty"


def new_brief_id() -> str:
    """A fresh brief identity (one per scope, kept across all its versions)."""
    return f"eb1_{uuid.uuid4().hex}"


def statement_id(section: str, position: int) -> str:
    """``<section>-<position>`` (1-based), assigned by Python."""
    return f"{section}-{position}"


# --- schema layer ---------------------------------------------------------------------------------------------------------------


@cache
def brief_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads((Path(CONTRACTS_DIR) / BRIEF_SCHEMA).read_text())
    return schema


@cache
def _validator() -> Any:
    schema = brief_schema()
    return validator_for(schema)(schema, format_checker=FormatChecker())


def _code(error: ValidationError) -> str:
    path = "/".join(str(part) for part in error.absolute_path) or "<root>"
    if error.validator == "additionalProperties":
        return f"UNKNOWN_FIELD: {path}: {error.message}"
    if error.validator in ("enum", "const"):
        return f"INVALID_ENUM: {path}: {error.message}"
    if (error.validator == "minItems" and path.endswith("result_ids")) or (error.validator == "required" and "'result_ids'" in error.message):
        return f"MISSING_RESULT_REFERENCE: {path}: {error.message}"
    return f"SCHEMA_INVALID: {path}: {error.message}"


def brief_schema_errors(document: Any) -> list[str]:
    return [_code(error) for error in sorted(_validator().iter_errors(document), key=lambda e: [str(p) for p in e.absolute_path])]


# --- semantic layer -------------------------------------------------------------------------------------------------------------


def statements(document: Any) -> list[tuple[str, int, dict[str, Any]]]:
    """(section, 0-based position, statement) of every statement of a brief or a model answer, tolerant of malformed input."""
    sections = document.get("sections") if isinstance(document, dict) else None
    found: list[tuple[str, int, dict[str, Any]]] = []
    if not isinstance(sections, dict):
        return found
    for section in SECTIONS:
        rows = sections.get(section)
        if isinstance(rows, list):
            found += [(section, i, row) for i, row in enumerate(rows) if isinstance(row, dict)]
    return found


def brief_semantic_errors(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section, i, row in statements(document):
        if row.get("statement_id") != statement_id(section, i + 1):
            errors.append(f"STATEMENT_ID_MISMATCH: sections/{section}/{i}: {row.get('statement_id')!r} is not {statement_id(section, i + 1)!r}")
    inputs = [row["result_id"] for row in document["input_results"]]
    if len(inputs) != len(set(inputs)):
        errors.append("DUPLICATE_INPUT_RESULT: input_results: a result appears more than once")
    supplied = set(inputs)
    for section, i, row in statements(document):
        missing = sorted(set(row["result_ids"]) - supplied)
        if missing:
            errors.append(f"REFERENCE_NOT_IN_INPUT: sections/{section}/{i}/result_ids: not part of the synthesis input: {missing}")
    generator = document["generator"]
    if generator["kind"] == GENERATOR_EMPTY:
        if inputs or statements(document) or document["omitted_result_count"]:
            errors.append("EMPTY_BRIEF_MISMATCH: generator: a deterministic empty brief has no input and no statement")
        if generator["provider"] is not None or generator["model"] is not None or generator["request_ids"] or document["prompt_version"] is not None:
            errors.append("GENERATOR_MISMATCH: generator: a deterministic empty brief names no provider, model, request or prompt")
    elif not (generator["provider"] and generator["model"] and generator["request_ids"] and document["prompt_version"]):
        errors.append("GENERATOR_MISMATCH: generator: a model brief names its provider, model, request IDs and prompt version")
    return errors


def brief_errors(document: Any) -> list[str]:
    errors = brief_schema_errors(document)
    return errors or brief_semantic_errors(document)


# --- typed model ----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class InputResult:
    result_id: str
    result_version: int
    lifecycle_status: LifecycleStatus


@dataclass(frozen=True)
class BriefStatement:
    statement_id: str
    text: str
    result_ids: tuple[str, ...]


@dataclass(frozen=True)
class EditorStatement:
    statement_id: str
    editor_id: str
    text: str
    result_ids: tuple[str, ...]


@dataclass(frozen=True)
class BriefSections:
    what_changed: tuple[BriefStatement, ...]
    top_concerns: tuple[BriefStatement, ...]
    important_improvements: tuple[BriefStatement, ...]
    system_patterns: tuple[BriefStatement, ...]
    editor_context: tuple[EditorStatement, ...]
    unresolved_questions: tuple[BriefStatement, ...]
    uncertainty: tuple[BriefStatement, ...]
    inspect_next: tuple[BriefStatement, ...]


@dataclass(frozen=True)
class Generator:
    kind: str
    provider: str | None
    model: str | None
    request_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExecutiveBrief(Contract):
    SCHEMA: ClassVar[str] = BRIEF_SCHEMA
    NAME: ClassVar[str] = "ExecutiveBrief"

    contract_version: str
    brief_id: str
    version: int
    scope: str
    run_id: str
    input_version: str
    input_fingerprint: str
    input_results: tuple[InputResult, ...]
    omitted_result_count: int
    sections: BriefSections
    generator: Generator
    prompt_version: str | None
    validator_version: str
    created_at: str

    @classmethod
    def errors(cls, data: Any) -> list[str]:
        return brief_errors(data)

    @property
    def referenced_result_ids(self) -> tuple[str, ...]:
        """Every result ID the brief's statements reference, sorted, each once."""
        found = {ref for section in SECTIONS for row in getattr(self.sections, section) for ref in row.result_ids}
        return tuple(sorted(found))


# --- the model's part -------------------------------------------------------------------------------------------------------------


def model_output_schema() -> dict[str, Any]:
    """What the model returns: the eight sections, statements without IDs. Result IDs are plain strings here so that a wrong reference
    reaches the deterministic validator (which names it: unknown, not supplied, failed candidate, raw source) instead of being hidden
    by the provider; the assembled brief is still validated against the full contract."""
    refs: dict[str, Any] = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20}
    statement: dict[str, Any] = {"type": "object", "additionalProperties": False, "required": ["text", "result_ids"],
                 "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 1200}, "result_ids": refs}}
    editor = {"type": "object", "additionalProperties": False, "required": ["editor_id", "text", "result_ids"],
              "properties": {"editor_id": {"type": "string", "minLength": 1, "maxLength": 200}, "text": statement["properties"]["text"], "result_ids": refs}}
    return {"type": "object", "additionalProperties": False, "required": ["sections"],
            "properties": {"sections": {"type": "object", "additionalProperties": False, "required": list(SECTIONS),
                                        "properties": {name: {"type": "array", "maxItems": 12, "items": editor if name == EDITOR_SECTION else statement}
                                                       for name in SECTIONS}}}}


@cache
def _output_validator() -> Any:
    schema = model_output_schema()
    return validator_for(schema)(schema)


def model_output_errors(output: Any) -> list[str]:
    """Shape errors of a model answer (the gateway retries only these)."""
    return [_code(error) for error in sorted(_output_validator().iter_errors(output), key=lambda e: [str(p) for p in e.absolute_path])]

