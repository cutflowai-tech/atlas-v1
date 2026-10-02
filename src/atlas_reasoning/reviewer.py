"""Optional second reviewer for high-impact candidates (``REV/15`` #12). Off by default.

Order is fixed: the deterministic guardrails (``guardrails.validate_candidate``) always run first and are never skipped; the reviewer
runs only for a candidate they accepted, and only when the case is configured as high impact. The reviewer can refuse a candidate
(``REVIEWER_REJECTED``) but can never accept one the guardrails refused. Any reviewer failure — provider error, malformed verdict —
fails safe (``REVIEWER_FAILED``): the candidate is not committed and the previous valid result stays current.

Input is bounded and structured: the case's canonical evidence view (``analyst.case_evidence_input``, which already carries the
attributed management context) and the card's visible fields; never identities beyond the case's, credentials or provider metadata.
The model is the configured gateway's (pinned), through the same gateway (retries, concurrency, ``llm_calls`` records).

Configuration: ``ATLAS_REASONING_REVIEWER`` (``on`` / ``off``, default off), ``ATLAS_REASONING_REVIEWER_CASE_TYPES`` (comma-separated
case types, default ``editor_pattern``); a case is high impact when its type is listed and its orientation is adverse or mixed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from atlas_reasoning.analyst import MAX_OUTPUT_TOKENS, bounded_json, case_evidence_input, field_set_errors, prompt_text
from atlas_reasoning.contracts import PATCHABLE_FIELDS
from atlas_reasoning.enums import CaseType
from atlas_reasoning.frozen import freeze
from atlas_reasoning.gateway import ReasoningGateway, new_request_id
from atlas_reasoning.guardrails import ValidationCode, Violation
from atlas_reasoning.provider import CallContext, Message, ProviderRequest, StructuredOutput
from atlas_reasoning.settings import ReasoningConfigError, flag

REVIEWER_PROMPT_VERSION = "reviewer-v1"
REVIEW_PURPOSE = "review"
REVIEWER_ENV = "ATLAS_REASONING_REVIEWER"
REVIEWER_CASE_TYPES_ENV = "ATLAS_REASONING_REVIEWER_CASE_TYPES"
CONCERN_CODES = (ValidationCode.UNKNOWN_EVIDENCE, ValidationCode.NO_SUPPORTING_EVIDENCE, ValidationCode.UNSUPPORTED_NUMBER,
                 ValidationCode.CAUSAL_OVERCLAIM, ValidationCode.HR_JUDGMENT, ValidationCode.UNSUPPORTED_BLAME,
                 ValidationCode.CONFIDENCE_EXCEEDED, ValidationCode.CONTEXT_AS_EVIDENCE, ValidationCode.MEMORY_ATTRIBUTION_LOST,
                 ValidationCode.UNSUPPORTED_METRIC, ValidationCode.UNKNOWN_ENTITY)


@dataclass(frozen=True)
class ReviewVerdict:
    approved: bool
    violations: tuple[Violation, ...] = ()
    request_id: str | None = None


class CandidateReviewer(Protocol):
    def applies(self, case: Mapping[str, Any]) -> bool: ...

    def review(self, case: Mapping[str, Any], candidate: Mapping[str, Any], *, run_id: str | None, work_item_id: str | None,
               request_id: str | None = None) -> ReviewVerdict: ...


@dataclass(frozen=True)
class ReviewerPolicy:
    case_types: frozenset[str] = field(default_factory=lambda: frozenset({CaseType.EDITOR_PATTERN.value}))

    def applies(self, case: Mapping[str, Any]) -> bool:
        return case["case_type"] in self.case_types and case["orientation"] in ("adverse", "mixed")


def policy_from_env(env: Mapping[str, str] | None = None) -> ReviewerPolicy | None:
    """The reviewer policy, or None when the reviewer is off (the default)."""
    env = os.environ if env is None else env
    if not flag(env, REVIEWER_ENV):
        return None
    raw = env.get(REVIEWER_CASE_TYPES_ENV, "").strip()
    if not raw:
        return ReviewerPolicy()
    types = {item.strip() for item in raw.split(",") if item.strip()}
    unknown = sorted(types - {case_type.value for case_type in CaseType})
    if unknown:
        raise ReasoningConfigError(f"{REVIEWER_CASE_TYPES_ENV} names unknown case types: {unknown}")
    return ReviewerPolicy(frozenset(types))


def review_input(case: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {"input_version": "review-input-v1", "case": case_evidence_input(case), "card": {name: candidate[name] for name in PATCHABLE_FIELDS}}


def review_output_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["approve", "concerns"],
            "properties": {"approve": {"type": "boolean"},
                           "concerns": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["code", "field", "note"],
                                                                   "properties": {"code": {"type": "string", "enum": [code.value for code in CONCERN_CODES]},
                                                                                  "field": {"type": "string", "enum": list(PATCHABLE_FIELDS)},
                                                                                  "note": {"type": "string"}}}}}}


def review_output_errors(value: Any) -> list[str]:
    errors = field_set_errors(value, ("approve", "concerns"))
    if errors:
        return errors
    if not isinstance(value["approve"], bool) or not isinstance(value["concerns"], list):
        return ["SCHEMA_INVALID: approve is a boolean and concerns a list"]
    codes = {code.value for code in CONCERN_CODES}
    for concern in value["concerns"]:
        if not isinstance(concern, Mapping) or concern.get("code") not in codes or concern.get("field") not in PATCHABLE_FIELDS:
            return ["SCHEMA_INVALID: every concern names a known code and a card field"]
    if not value["approve"] and not value["concerns"]:
        return ["SCHEMA_INVALID: a refusal names at least one concern"]
    return []


class LLMReviewer:
    """``CandidateReviewer`` through the reasoning gateway (pinned model)."""

    def __init__(self, gateway: ReasoningGateway, policy: ReviewerPolicy) -> None:
        self.gateway = gateway
        self.policy = policy

    def applies(self, case: Mapping[str, Any]) -> bool:
        return self.policy.applies(case)

    def request(self, case: Mapping[str, Any], candidate: Mapping[str, Any], *, run_id: str | None, work_item_id: str | None,
                request_id: str | None = None) -> ProviderRequest:
        context = CallContext(purpose=REVIEW_PURPOSE, request_id=request_id or new_request_id(), run_id=run_id, case_id=case["case_id"], work_item_id=work_item_id,
                              prompt_version=REVIEWER_PROMPT_VERSION, source_snapshot_id=case["source_snapshot_id"],
                              evidence_fingerprint=case["evidence_fingerprint"])
        messages = (Message("system", prompt_text(REVIEWER_PROMPT_VERSION)),
                    Message("user", "Review this card against its case. Review input (JSON):\n" + bounded_json(review_input(case, candidate))))
        return ProviderRequest(context, messages, StructuredOutput("atlas_review_v1", freeze(review_output_schema()), review_output_errors),
                               max_output_tokens=MAX_OUTPUT_TOKENS // 4, reasoning_effort="low")

    def review(self, case: Mapping[str, Any], candidate: Mapping[str, Any], *, run_id: str | None, work_item_id: str | None,
               request_id: str | None = None) -> ReviewVerdict:
        request = self.request(case, candidate, run_id=run_id, work_item_id=work_item_id, request_id=request_id)
        try:
            response = self.gateway.call(request)
            verdict = response.parsed
            if verdict["approve"]:
                return ReviewVerdict(True, (), response.request_id)
            concerns = tuple(Violation(ValidationCode.REVIEWER_REJECTED, str(row["field"]), f"{row['code']}: {str(row['note'])[:300]}")
                             for row in verdict["concerns"])
            return ReviewVerdict(False, concerns, response.request_id)
        except Exception as error:  # noqa: BLE001 - any reviewer failure fails safe: no verdict, no commit
            reason = getattr(error, "error_class", type(error).__name__)
            return ReviewVerdict(False, (Violation(ValidationCode.REVIEWER_FAILED, "<review>", f"no verdict: {reason}"),), request.context.request_id)


def reviewer_from_env(gateway: ReasoningGateway, env: Mapping[str, str] | None = None) -> LLMReviewer | None:
    policy = policy_from_env(env)
    return LLMReviewer(gateway, policy) if policy is not None else None
