"""Update-only reasoning (``REV/08``): an existing result is patched, never regenerated.

Input (``update_input``): the previous canonical result's patchable fields, the exact material delta from the evidence that result
was reasoned on to the current evidence, both fingerprints, the current case evidence and bounded context (the same canonical view
the analyst sees, ``analyst.case_evidence_input``), and ``fields_requiring_change``: fields Python has determined cannot stay as they
are (``required_changes``: they cite evidence that no longer exists, use numbers the current case no longer carries, exceed the new
confidence ceiling, or ignore new counter-evidence).

Output: the model answers with a patch description (``update_output_schema``): ``action``, ``change_rationale``, ``changed_fields``,
``preserved_fields`` and ``patch`` (every patchable field, null unless changed). It cannot name an identity, a version, a
fingerprint or a lifecycle status. Python turns the answer into a ``ReasoningUpdate`` (case, result, base version and fingerprints
are Python's), validates it against reasoning-v1, the previous result and the case, then merges it deterministically
(``patch.merge``) and validates the merged version like a new result (contract, case consistency, no unsupported numbers). Every
check runs inside the gateway call, so an invalid patch is retried within the gateway's bounds and recorded in ``llm_calls``.

Prompt: ``prompts/update-v2.md`` (``UPDATE_PROMPT_VERSION``), separate from the analyst prompt and pinned by its SHA-256.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from atlas_reasoning import contracts
from atlas_reasoning.analyst import (
    MAX_OUTPUT_TOKENS,
    REASONING_EFFORT,
    bounded_json,
    case_evidence_input,
    field_set_errors,
    prompt_text,
    provider_schema,
)
from atlas_reasoning.contracts import (
    PATCHABLE_FIELDS,
    ReasoningCase,
    ReasoningResult,
    ReasoningUpdate,
    result_case_errors,
    result_errors,
    update_case_errors,
    update_errors,
    update_result_errors,
)
from atlas_reasoning.enums import CONFIDENCE_ORDER, CONTRACT_VERSION, ConfidenceLevel, EvidenceRole, UpdateAction
from atlas_reasoning.frozen import freeze
from atlas_reasoning.output_checks import unsupported_number_errors
from atlas_reasoning.patch import VersionProvenance, merge
from atlas_reasoning.provider import CallContext, Message, ProviderRequest, ProviderResponse, StructuredOutput
from atlas_reasoning.structured import inline_schema

UPDATE_PROMPT_VERSION = "update-v2"   # v2 (07-14 integration): how to use human context; v1 kept for history
UPDATE_PURPOSE = "update"
UPDATE_INPUT_VERSION = "update-input-v1"
OUTPUT_FIELDS = ("action", "change_rationale", "changed_fields", "preserved_fields", "patch")

# Why a field cannot stay as it is (``fields_requiring_change``).
STALE_EVIDENCE_REF = "cites_evidence_no_longer_in_the_case"
STALE_NUMBER = "uses_numbers_no_longer_in_the_case"
CONFIDENCE_CEILING = "exceeds_the_current_confidence_ceiling"
NEW_COUNTER_EVIDENCE = "case_now_has_counter_evidence"

_PLACEHOLDER_MODEL = {"provider": "validation", "model": "validation", "request_ids": ["validation"]}


def cited_refs(value: Any) -> set[str]:
    """Every evidence reference cited anywhere inside one field value."""
    if isinstance(value, Mapping):
        refs = {ref for ref in value.get("evidence_refs") or [] if isinstance(ref, str)} if isinstance(value.get("evidence_refs"), list) else set()
        return refs.union(*(cited_refs(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(cited_refs(item) for item in value))
    return set()


def required_changes(previous: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, list[str]]:
    """Patchable fields of ``previous`` that are no longer valid for ``case``, with the reasons. Deterministic."""
    known = {ref["ref_id"] for ref in case["current_evidence"]["references"]}
    reasons: dict[str, set[str]] = {}
    for name in PATCHABLE_FIELDS:
        if cited_refs(previous[name]) - known:
            reasons.setdefault(name, set()).add(STALE_EVIDENCE_REF)
        if unsupported_number_errors({name: previous[name]}, case, include_delta=False):   # stale: quotes values that are no longer current
            reasons.setdefault(name, set()).add(STALE_NUMBER)
    ceiling = max((CONFIDENCE_ORDER.index(ConfidenceLevel(row["confidence"])) for row in case["supporting_findings"]), default=0)
    if CONFIDENCE_ORDER.index(ConfidenceLevel(previous["confidence"]["level"])) > ceiling:
        reasons.setdefault("confidence", set()).add(CONFIDENCE_CEILING)
    contradicted = bool(case["contradicting_findings"]) or any(ref["role"] == EvidenceRole.CONTRADICTING for ref in case["current_evidence"]["references"])
    if contradicted and not previous["counter_evidence"]:
        reasons.setdefault("counter_evidence", set()).add(NEW_COUNTER_EVIDENCE)
    return {name: sorted(reasons[name]) for name in PATCHABLE_FIELDS if name in reasons}


def update_input(previous: ReasoningResult | Mapping[str, Any], case: ReasoningCase | Mapping[str, Any]) -> dict[str, Any]:
    result = previous.to_dict() if isinstance(previous, ReasoningResult) else previous
    document = case.to_dict() if isinstance(case, ReasoningCase) else case
    if document["material_delta"] is None:
        raise ValueError("an update needs the material delta from the previous result's evidence")
    return {"input_version": UPDATE_INPUT_VERSION,
            "previous_result": {"version": result["version"], "fields": {name: result[name] for name in PATCHABLE_FIELDS}},
            "fingerprints": {"before": result["evidence_fingerprint"], "after": document["evidence_fingerprint"]},
            "material_delta": document["material_delta"],
            "fields_requiring_change": required_changes(result, document),
            **case_evidence_input(document)}


def update_messages(previous: ReasoningResult, case: ReasoningCase) -> tuple[Message, ...]:
    return (Message("system", prompt_text(UPDATE_PROMPT_VERSION)),
            Message("user", "Review this card against the changed evidence. Update input (JSON):\n" + bounded_json(update_input(previous, case))))


@cache
def update_output_schema() -> dict[str, Any]:
    result = inline_schema(contracts.RESULT_SCHEMA)
    field_enum = {"type": "string", "enum": list(PATCHABLE_FIELDS)}
    return {"type": "object", "additionalProperties": False, "required": list(OUTPUT_FIELDS),
            "properties": {
                "action": {"type": "string", "enum": [action.value for action in UpdateAction]},
                "change_rationale": {"type": "string", "minLength": 1, "maxLength": 2000},
                "changed_fields": {"type": "array", "items": field_enum, "uniqueItems": True},
                "preserved_fields": {"type": "array", "items": field_enum, "uniqueItems": True},
                "patch": {"type": "object", "additionalProperties": False, "required": list(PATCHABLE_FIELDS),
                          "properties": {name: {"anyOf": [result["properties"][name], {"type": "null"}]} for name in PATCHABLE_FIELDS}}}}


def build_update(output: Mapping[str, Any], previous: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    """The ``ReasoningUpdate`` document for a model answer: the model's field lists, values and rationale; Python's identity,
    base version and fingerprints."""
    patch = output["patch"] if isinstance(output.get("patch"), Mapping) else {}
    raw = output.get("changed_fields")
    changed: list[Any] = raw if isinstance(raw, list) else []
    return {"contract_version": CONTRACT_VERSION, "case_id": previous["case_id"], "result_id": previous["result_id"], "base_version": previous["version"],
            "action": output.get("action"), "changed_fields": [{"field": name, "value": patch.get(name) if isinstance(name, str) else None} for name in changed],
            "preserved_fields": output.get("preserved_fields"), "change_rationale": output.get("change_rationale"),
            "evidence_fingerprint_before": previous["evidence_fingerprint"], "evidence_fingerprint_after": case["evidence_fingerprint"]}


def update_output_errors(output: Any, previous: Mapping[str, Any], case: Mapping[str, Any]) -> list[str]:
    """Everything wrong with a model answer: shape, update contract, required changes, and the merged version as a result."""
    errors = field_set_errors(output, OUTPUT_FIELDS)
    if errors:
        return errors
    patch = output["patch"]
    errors = field_set_errors(patch, PATCHABLE_FIELDS)
    changed = output["changed_fields"] if isinstance(output["changed_fields"], list) else []
    for name in PATCHABLE_FIELDS:
        if isinstance(patch, Mapping) and name in patch and (patch[name] is not None) != (name in changed):
            errors.append(f"PATCH_VALUE_MISMATCH: {name}: a value is given exactly for each changed field")
    update = build_update(output, previous, case)
    errors += update_errors(update)
    if errors:
        return errors
    errors = update_result_errors(update, previous) + update_case_errors(update, case)
    # A "change" that keeps the exact previous value is not a change: a patch must really change every field it lists.
    errors += [f"UNCHANGED_PATCH_VALUE: {row['field']} is listed as changed but keeps its previous value" for row in update["changed_fields"]
               if row["value"] == previous[row["field"]]]
    missing = [name for name in required_changes(previous, case) if name not in changed]
    errors += [f"REQUIRED_CHANGE_MISSING: {name} cannot stay as it is" for name in missing]
    if errors:
        return errors
    placeholder = VersionProvenance(case["source_snapshot_id"], case["evidence_fingerprint"], _PLACEHOLDER_MODEL, UPDATE_PROMPT_VERSION,
                                    previous["updated_at"], previous["lifecycle_status"])
    try:
        merged = merge(previous, update, placeholder)
    except contracts.ContractViolation as violation:
        return violation.errors
    return result_errors(merged) or (result_case_errors(merged, case) + unsupported_number_errors(merged, case))


def update_output(previous: ReasoningResult, case: ReasoningCase) -> StructuredOutput:
    result, document = previous.to_dict(), case.to_dict()
    return StructuredOutput("atlas_update_patch_v1", freeze(provider_schema(update_output_schema())), lambda value: update_output_errors(value, result, document))


def update_request(previous: ReasoningResult, case: ReasoningCase, *, run_id: str | None = None, work_item_id: str | None = None) -> ProviderRequest:
    context = CallContext(purpose=UPDATE_PURPOSE, run_id=run_id, case_id=case.case_id, work_item_id=work_item_id, prompt_version=UPDATE_PROMPT_VERSION,
                          source_snapshot_id=case.source_snapshot_id, evidence_fingerprint=case.evidence_fingerprint)
    return ProviderRequest(context, update_messages(previous, case), update_output(previous, case), max_output_tokens=MAX_OUTPUT_TOKENS,
                           reasoning_effort=REASONING_EFFORT)


@dataclass(frozen=True)
class AppliedUpdate:
    update: ReasoningUpdate
    result: ReasoningResult
    previous: ReasoningResult

    @property
    def is_patch(self) -> bool:
        return self.update.action == UpdateAction.PATCH


def apply_response(previous: ReasoningResult, case: ReasoningCase, response: ProviderResponse, *, provider: str, now: str,
                   lifecycle_status: str) -> AppliedUpdate:
    """Validate a model answer and merge it into the next version (lifecycle chosen by the caller, never by the model)."""
    result, document = previous.to_dict(), case.to_dict()
    errors = update_output_errors(response.parsed, result, document)
    if errors:
        raise contracts.ContractViolation("ReasoningUpdate", errors)
    update = ReasoningUpdate.from_dict(build_update(response.parsed, result, document))
    provenance = VersionProvenance(case.source_snapshot_id, case.evidence_fingerprint,
                                   {"provider": provider, "model": response.model, "request_ids": [response.request_id]}, UPDATE_PROMPT_VERSION, now,
                                   lifecycle_status)
    merged = merge(result, copy.deepcopy(update.to_dict()), provenance)
    return AppliedUpdate(update, ReasoningResult.from_dict(merged), previous)
