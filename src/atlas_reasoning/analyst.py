"""New-case reasoning (``REV/07``): one bounded ``ReasoningCase`` in, one structured, evidence-linked ``ReasoningResult`` out.

The model (GPT-5.6 Sol through ``gateway.ReasoningGateway``; never a direct HTTP call) writes only the **analyst fields** — the
result's patchable, user-visible content (``contracts.PATCHABLE_FIELDS``: title, observation, reasoning_summary, supporting and
counter evidence, interpretation, alternative explanations, confidence, limitations, management significance, questions for
management, suggested investigations). Python sets everything else: ``result_id`` (``contracts.new_result_id``), ``case_id``,
version 1, lifecycle ``new`` (Phase 09 owns every later transition), snapshot, evidence fingerprint, model metadata, prompt version
and timestamps. The model therefore cannot create or change a case ID, a result ID or a lifecycle status.

Determinism of the input. ``analyst_input(case)`` serializes only what the analyst needs, in a canonical order (findings by member
key, statements by member, level and code, evidence blocks and references sorted, keys sorted, compact JSON) and without volatile
values (Intelligence V2 finding IDs and ranks, snapshot ID, case creation time, event IDs). Two cases with the same identity,
evidence and context therefore produce byte-identical prompts (``tests/test_reasoning_analyst.py``). An input larger than
``MAX_INPUT_CHARS`` is refused (``CaseTooLarge``) instead of being truncated: the model either sees the whole case or nothing.

Validation. The model's JSON is checked inside the gateway call (so an invalid answer is retried within the gateway's bounds and
recorded in ``llm_calls``): the analyst-output schema, then the full assembled result against reasoning-v1
(``ReasoningResult.errors``), against its case (``result_case_errors``: only the case's ``ref_id``\\ s, counter-evidence for a
contradicted case, confidence never above the upstream ceiling) and ``output_checks`` (no number the case does not carry).
``reasoning_summary`` is the explicit summary written for management; there is no field for hidden reasoning and any unknown
field is refused.

Prompt: ``prompts/analyst-v1.md`` (``ANALYST_PROMPT_VERSION``). Changing the prompt text requires a new version; a test pins the
prompt's SHA-256.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from atlas_reasoning import contracts
from atlas_reasoning.contracts import PATCHABLE_FIELDS, ReasoningCase, ReasoningResult, result_case_errors, result_errors
from atlas_reasoning.enums import CONTRACT_VERSION, EvidenceLevel, LifecycleStatus
from atlas_reasoning.frozen import freeze
from atlas_reasoning.output_checks import unsupported_number_errors
from atlas_reasoning.provider import CallContext, Message, ProviderRequest, ProviderResponse, StructuredOutput
from atlas_reasoning.structured import inline_schema

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
ANALYST_PROMPT_VERSION = "analyst-v1"
ANALYST_PURPOSE = "analyst"
ANALYST_INPUT_VERSION = "analyst-input-v1"
MAX_INPUT_CHARS = 400_000   # about 100k tokens; the largest showcase case is about 152k characters (256 references)
MAX_OUTPUT_TOKENS = 6_000
REASONING_EFFORT = "medium"

# Placeholders used only to validate model output before Python assigns the real provenance.
_PLACEHOLDER_RESULT_ID = "rr1_" + "0" * 32
_PLACEHOLDER_TIME = "2000-01-01T00:00:00Z"
_LEVEL_ORDER = {level.value: i for i, level in enumerate(EvidenceLevel)}


class CaseTooLarge(ValueError):
    """The serialized case exceeds ``MAX_INPUT_CHARS``; it is refused, never truncated."""


@cache
def prompt_text(version: str) -> str:
    return (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")


def prompt_sha256(version: str) -> str:
    return hashlib.sha256(prompt_text(version).encode()).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# --- input --------------------------------------------------------------------------------------------------------------------


def _finding(row: Mapping[str, Any]) -> dict[str, Any]:
    return {"member_key": row["member_key"], "finding_type": row["finding_type"], "direction": row["direction"], "category": row["category"],
            "evidence_level": row["evidence_level"], "confidence": row["confidence"], "sample_size": row["sample_size"],
            "limitations": sorted(row["limitations"])}


def _reference(ref: Mapping[str, Any]) -> dict[str, Any]:
    return {"ref_id": ref["ref_id"], "member_key": ref["member_key"], "role": ref["role"], "evidence_code": ref["evidence_code"],
            "monday_item_id": ref["monday_item_id"], "cycle_id": ref["cycle_id"], "editor_id": ref["editor_id"],
            "video_type_key": ref["video_type_key"], "source_timestamps": sorted(ref["source_timestamps"]), "values": ref["values"]}


def case_evidence_input(case: Mapping[str, Any]) -> dict[str, Any]:
    """The bounded, canonical view of a case's identity, evidence and context shared by the analyst and update prompts."""
    evidence = case["current_evidence"]
    memory = case["memory_context"]
    return {
        "case": {"case_type": case["case_type"], "subject_type": case["subject_type"], "subject_id": case["subject_id"], "topic_key": case["topic_key"],
                 "identity_dimensions": case["identity_dimensions"],
                 "scope": {**case["scope"], **{key: sorted(case["scope"][key]) for key in ("affected_editor_ids", "affected_video_type_keys", "windows")}}},
        "orientation": case["orientation"],
        "supporting_findings": sorted((_finding(row) for row in case["supporting_findings"]), key=lambda row: row["member_key"]),
        "contradicting_findings": sorted((_finding(row) for row in case["contradicting_findings"]), key=lambda row: row["member_key"]),
        "statements": sorted(({key: row[key] for key in ("member_key", "level", "kind", "code", "params")} for row in evidence["statements"]),
                             key=lambda row: (row["member_key"], _LEVEL_ORDER[row["level"]], row["code"], canonical_json(row["params"]))),
        "evidence_blocks": sorted((dict(block) for block in evidence["blocks"]),
                                  key=lambda row: (row["member_key"], row["role"], row["evidence_code"], canonical_json(row))),
        "evidence_references": sorted((_reference(ref) for ref in evidence["references"]), key=lambda row: row["ref_id"]),
        "manager_context": sorted(({key: row[key] for key in ("source_type", "body", "author", "recorded_at")} for row in case["manager_context"]),
                                  key=lambda row: (row["recorded_at"], row["source_type"], row["body"])),
        "memory_context": sorted(({key: row[key] for key in ("source_type", "body", "recorded_at")} for row in memory["items"]),
                                 key=lambda row: (row["recorded_at"] or "", row["source_type"], row["body"])) if memory["status"] == "available" else [],
        "provenance": {"evidence_fingerprint": case["evidence_fingerprint"], "upstream_contract_version": case["upstream_contract_version"],
                       "intelligence_version": case["upstream"]["intelligence_version"]},
    }


def analyst_input(case: ReasoningCase | Mapping[str, Any]) -> dict[str, Any]:
    document = case.to_dict() if isinstance(case, ReasoningCase) else case
    return {"input_version": ANALYST_INPUT_VERSION, **case_evidence_input(document)}


def bounded_json(payload: Mapping[str, Any]) -> str:
    text = canonical_json(payload)
    if len(text) > MAX_INPUT_CHARS:
        raise CaseTooLarge(f"the case input is {len(text)} characters; the limit is {MAX_INPUT_CHARS}")
    return text


def analyst_messages(case: ReasoningCase) -> tuple[Message, ...]:
    return (Message("system", prompt_text(ANALYST_PROMPT_VERSION)),
            Message("user", "Reason about this case. Case input (JSON):\n" + bounded_json(analyst_input(case))))


# --- output -------------------------------------------------------------------------------------------------------------------


@cache
def analyst_output_schema() -> dict[str, Any]:
    """The analyst fields of reasoning-result-v1, self-contained (strict structured output)."""
    result = inline_schema(contracts.RESULT_SCHEMA)
    return {"type": "object", "additionalProperties": False, "required": list(PATCHABLE_FIELDS),
            "properties": {name: result["properties"][name] for name in PATCHABLE_FIELDS}}


@dataclass(frozen=True)
class Provenance:
    result_id: str
    provider: str
    model: str
    request_ids: tuple[str, ...]
    prompt_version: str
    now: str


def assemble_result(case: Mapping[str, Any], output: Mapping[str, Any], provenance: Provenance) -> dict[str, Any]:
    """A version-1 result document: the model's analyst fields plus the identity and provenance Python owns."""
    return {"contract_version": CONTRACT_VERSION, "result_id": provenance.result_id, "case_id": case["case_id"], "version": 1,
            **{name: output[name] for name in PATCHABLE_FIELDS},
            "lifecycle_status": LifecycleStatus.NEW.value, "superseded_by": None, "source_snapshot_id": case["source_snapshot_id"],
            "evidence_fingerprint": case["evidence_fingerprint"],
            "model_metadata": {"provider": provenance.provider, "model": provenance.model, "request_ids": list(provenance.request_ids)},
            "prompt_version": provenance.prompt_version, "created_at": provenance.now, "updated_at": provenance.now}


def field_set_errors(output: Any, expected: Sequence[str]) -> list[str]:
    """A model answer must be an object with exactly the expected fields (hidden-reasoning or identity fields are unknown fields)."""
    if not isinstance(output, Mapping):
        return ["SCHEMA_INVALID: <root>: the answer is not a JSON object"]
    errors = [f"UNKNOWN_FIELD: {name}: not an output field" for name in sorted(set(output) - set(expected), key=str)]
    errors += [f"SCHEMA_INVALID: {name}: required output field is missing" for name in expected if name not in output]
    return errors


def analyst_output_errors(output: Any, case: Mapping[str, Any]) -> list[str]:
    """Everything wrong with a model answer for ``case``: schema, contract, case consistency and unsupported numbers."""
    errors = field_set_errors(output, PATCHABLE_FIELDS)
    if errors:
        return errors
    placeholder = Provenance(_PLACEHOLDER_RESULT_ID, "validation", "validation", ("validation",), ANALYST_PROMPT_VERSION, _PLACEHOLDER_TIME)
    document = assemble_result(case, output, placeholder)
    errors = result_errors(document)
    if errors:
        return errors
    return result_case_errors(document, case) + unsupported_number_errors(output, case)


def analyst_output(case: ReasoningCase) -> StructuredOutput:
    document = case.to_dict()
    return StructuredOutput("atlas_analyst_result_v1", freeze(analyst_output_schema()), lambda value: analyst_output_errors(value, document))


def analyst_request(case: ReasoningCase, *, run_id: str | None = None, work_item_id: str | None = None) -> ProviderRequest:
    context = CallContext(purpose=ANALYST_PURPOSE, run_id=run_id, case_id=case.case_id, work_item_id=work_item_id, prompt_version=ANALYST_PROMPT_VERSION,
                          source_snapshot_id=case.source_snapshot_id, evidence_fingerprint=case.evidence_fingerprint)
    return ProviderRequest(context, analyst_messages(case), analyst_output(case), max_output_tokens=MAX_OUTPUT_TOKENS, reasoning_effort=REASONING_EFFORT)


def result_from_response(case: ReasoningCase, response: ProviderResponse, *, provider: str, result_id: str, now: str) -> ReasoningResult:
    """The validated ``ReasoningResult`` (version 1, lifecycle ``new``) for a successful analyst call."""
    document = case.to_dict()
    errors = analyst_output_errors(response.parsed, document)
    if errors:
        raise contracts.ContractViolation("ReasoningResult", errors)
    provenance = Provenance(result_id, provider, response.model, (response.request_id,), ANALYST_PROMPT_VERSION, now)
    return ReasoningResult.from_dict(assemble_result(document, response.parsed, provenance))
