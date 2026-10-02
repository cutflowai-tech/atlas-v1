"""Executive intelligence synthesis (``REV/17``): one versioned, reference-grounded ExecutiveBrief from canonical reasoning results.

    synthesizer = ExecutiveSynthesizer(ExecutiveStore(store), gateway)
    outcome = synthesizer.synthesize(run_id)     # after ReasoningEngine.process_run(run_id)

Executive synthesis is **downstream of validated canonical ReasoningResults only**. Its input is selected by Python from the canonical
store (``store.executive.ExecutiveTransaction.canonical_results``): the current version of every result whose lifecycle is ``new``,
``active`` or ``updated``, plus results ``resolved`` within the last ``resolved_lookback_runs`` runs. A refused (Phase 15) candidate is
never a result, a ``cooling`` or ``superseded`` result is never eligible, and nothing upstream — Monday events or items, cycles, metrics,
Intelligence V2 findings, evidence records, manager notes or Honcho memory — is part of the input.

Steps of ``synthesize`` (one synthesizer at a time: a session advisory lock; a second one does nothing):

1. **input** (``executive_input``): a bounded, canonical view of each eligible result — identity of its subject, lifecycle and what
   changed, its own management wording, confidence, limitations, open Atlas questions, suggested investigations — in a stable order,
   compact key-sorted JSON. ``input_fingerprint`` hashes it (``ei1_`` + SHA-256). Generated prose never takes part in the fingerprint;
   result versions do not either (a no-change review changes no visible field and must not cause a new brief);
2. **preserve policy** (``decide``): the same fingerprint as the current brief → ``unchanged``: the current brief stays exactly as it
   is (no new version, no new wording) and **no model call** is made; the run is recorded. No eligible result → a deterministic empty
   brief written by Python, without a model call;
3. **synthesis**: one call through ``gateway.ReasoningGateway`` (pinned model, its retries, structured output, no redirects, secret
   redaction) with the versioned prompt ``prompts/executive-v1.md``; the gateway checks only the answer's shape;
4. **validation** (``executive_validator.validate_brief``): every statement grounded in the input results it cites; identity,
   provenance and model checked; a refused answer is re-asked with its codes at most ``retries`` times (``settings.validation_retries``);
5. **persist** (``ExecutiveTransaction.append_brief``): the next version on top of the version read before the call (optimistic
   concurrency). A provider failure, a refused answer or a version conflict never replaces the current brief: the previous valid brief
   stays current and the failure is recorded with the run (``executive_brief_runs``; a refused candidate is kept there for debugging
   only and is never returned as a brief).

No UI, route or file is produced here: the brief is persisted in PostgreSQL and read through ``store.executive``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from atlas_reasoning import executive_validator
from atlas_reasoning.analyst import canonical_json, prompt_sha256, prompt_text, provider_schema
from atlas_reasoning.contracts import ReasoningResult
from atlas_reasoning.enums import CONFIDENCE_ORDER, ConfidenceLevel, LifecycleStatus
from atlas_reasoning.executive_contracts import (
    BRIEF_CONTRACT_VERSION,
    COMPANY_SCOPE,
    ELIGIBLE_LIFECYCLE,
    GENERATOR_EMPTY,
    GENERATOR_MODEL,
    SECTIONS,
    ExecutiveBrief,
    model_output_errors,
    model_output_schema,
    new_brief_id,
    statement_id,
)
from atlas_reasoning.frozen import freeze, thaw
from atlas_reasoning.gateway import ReasoningGateway, new_request_id
from atlas_reasoning.provider import CallContext, Message, ProviderError, ProviderRequest, ProviderResponse, StructuredOutput
from atlas_reasoning.settings import validation_retries
from atlas_reasoning.store.repository import VersionConflict

LOG = logging.getLogger("atlas_reasoning.executive")

EXECUTIVE_PROMPT_VERSION = "executive-v1"
EXECUTIVE_PURPOSE = "executive"
EXECUTIVE_INPUT_VERSION = "executive-input-v1"
POLICY_VERSION = "executive-policy-v1"
MAX_INPUT_RESULTS = 60          # results per brief; the rest are counted in omitted_results, never cited
MAX_INPUT_CHARS = 300_000       # refused, never truncated, beyond this
MAX_OUTPUT_TOKENS = 16_000
REASONING_EFFORT = "medium"
RESOLVED_LOOKBACK_RUNS = 3      # resolved results stay in the input for the run that resolved them and the next two

# Input order: what changed first, then by confidence; ties by subject and result ID (never by database order).
_LIFECYCLE_ORDER = {LifecycleStatus.NEW: 0, LifecycleStatus.UPDATED: 1, LifecycleStatus.ACTIVE: 2, LifecycleStatus.RESOLVED: 3}
_CONFIDENCE_RANK = {level: -i for i, level in enumerate(CONFIDENCE_ORDER)}


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def executive_prompt() -> str:
    return prompt_text(EXECUTIVE_PROMPT_VERSION)


def executive_prompt_sha256() -> str:
    return prompt_sha256(EXECUTIVE_PROMPT_VERSION)


class InputTooLarge(ValueError):
    """The serialized synthesis input exceeds ``MAX_INPUT_CHARS``; it is refused, never truncated."""


class IneligibleResult(ValueError):
    """A row offered as synthesis input is not a canonical, eligible result version."""


# --- input --------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CanonicalResult:
    """One canonical result as the store reads it: its current version plus the canonical context executive synthesis needs. Built
    only by ``store.executive`` from ``reasoning_results`` (never from a failed candidate or model output)."""

    result: ReasoningResult
    lifecycle_status: LifecycleStatus           # reasoning_results.lifecycle_status (must equal the current version's)
    current_version: int                        # reasoning_results.current_version (must equal the document's version)
    case_type: str
    subject_type: str
    subject_id: str
    topic_key: str
    dimensions: Mapping[str, str]               # the case's identity dimensions (video type, workflow stage, ...)
    orientation: str                            # of the case evidence state the version was reasoned on
    affected_editor_ids: tuple[str, ...]        # of the same evidence state
    lifecycle_reason: str | None                # reason code of the transition into the current lifecycle status
    patched_fields: tuple[str, ...] = ()        # fields of the latest accepted patch (``updated`` only)
    open_questions: tuple[tuple[str, str], ...] = ()   # (question text, expected context type) of open canonical Atlas questions


@dataclass(frozen=True)
class InputPolicy:
    max_results: int = MAX_INPUT_RESULTS
    resolved_lookback_runs: int = RESOLVED_LOOKBACK_RUNS


@dataclass(frozen=True)
class ExecutiveInput:
    """The bounded synthesis input: what the model sees (``payload``), its fingerprint, and the result versions it contains."""

    payload: Mapping[str, Any]
    fingerprint: str
    results: tuple[tuple[str, int, LifecycleStatus], ...]       # (result_id, version, lifecycle) in input order
    omitted: int

    @property
    def result_ids(self) -> frozenset[str]:
        return frozenset(row[0] for row in self.results)

    def by_id(self) -> dict[str, Mapping[str, Any]]:
        return {row["result_id"]: row for row in self.payload["results"]}

    def input_results(self) -> list[dict[str, Any]]:
        return [{"result_id": result_id, "result_version": version, "lifecycle_status": status.value} for result_id, version, status in self.results]


def _check_eligible(row: CanonicalResult) -> None:
    document = row.result
    if row.lifecycle_status not in ELIGIBLE_LIFECYCLE:
        raise IneligibleResult(f"{document.result_id}: lifecycle {row.lifecycle_status.value} is not eligible for executive synthesis")
    if document.lifecycle_status != row.lifecycle_status or document.version != row.current_version:
        raise IneligibleResult(f"{document.result_id}: not the canonical current version")


def _result_input(row: CanonicalResult) -> dict[str, Any]:
    result = row.result
    change: dict[str, Any] = {"lifecycle_reason": row.lifecycle_reason}
    if row.lifecycle_status == LifecycleStatus.UPDATED:
        change["patched_fields"] = sorted(row.patched_fields)
    return {
        "result_id": result.result_id,
        "subject": {"case_type": row.case_type, "subject_type": row.subject_type, "subject_id": row.subject_id, "topic_key": row.topic_key,
                    "dimensions": dict(sorted(row.dimensions.items())), "orientation": row.orientation,
                    "affected_editor_ids": sorted(set(row.affected_editor_ids))},
        "lifecycle_status": row.lifecycle_status.value,
        "change": change,
        "title": result.title,
        "summary": result.reasoning_summary,
        "observation": result.observation.statement,
        "interpretation": result.interpretation.statement,
        "management_significance": result.management_significance.statement,
        "confidence": {"level": result.confidence.level.value, "rationale": result.confidence.rationale},
        "limitations": list(result.limitations),
        "open_questions": sorted(({"text": text, "expected_context_type": kind} for text, kind in set(row.open_questions)),
                                 key=lambda q: (q["text"], q["expected_context_type"])),
        "suggested_investigations": [row.text for row in result.suggested_investigations],
    }


def _order(row: CanonicalResult) -> tuple[Any, ...]:
    return (_LIFECYCLE_ORDER[row.lifecycle_status], _CONFIDENCE_RANK[ConfidenceLevel(row.result.confidence.level)], row.subject_type, row.subject_id,
            row.topic_key, row.result.result_id)


def input_fingerprint(payload: Mapping[str, Any]) -> str:
    return "ei1_" + hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def executive_input(rows: Iterable[CanonicalResult], *, policy: InputPolicy | None = None) -> ExecutiveInput:
    """The canonical synthesis input of ``rows``: eligibility re-checked, deterministic order, bounded count. Equivalent canonical
    state gives a byte-identical payload (and fingerprint) whatever order the rows come in."""
    policy = policy or InputPolicy()
    rows = list(rows)
    for row in rows:
        _check_eligible(row)
    ids = [row.result.result_id for row in rows]
    if len(ids) != len(set(ids)):
        raise IneligibleResult("a result is offered more than once")
    ordered = sorted(rows, key=_order)
    kept, omitted = ordered[: policy.max_results], len(ordered) - min(len(ordered), policy.max_results)
    payload = {"input_version": EXECUTIVE_INPUT_VERSION, "results": [_result_input(row) for row in kept], "omitted_results": omitted}
    text = canonical_json(payload)
    if len(text) > MAX_INPUT_CHARS:
        raise InputTooLarge(f"the executive input is {len(text)} characters; the limit is {MAX_INPUT_CHARS}")
    frozen = freeze(payload)
    return ExecutiveInput(frozen, input_fingerprint(payload),
                          tuple((row.result.result_id, row.result.version, row.lifecycle_status) for row in kept), omitted)


# --- preserve policy -------------------------------------------------------------------------------------------------------------


class Decision(StrEnum):
    """What a synthesis run does (``executive_brief_runs.decision``)."""

    SYNTHESIZED = "synthesized"              # a new version written by the model and accepted by the validator
    SYNTHESIZED_EMPTY = "synthesized_empty"  # a new deterministic empty version: no eligible result (no model call)
    UNCHANGED = "unchanged"                  # same input fingerprint as the current brief: preserved, no model call
    FAILED = "failed"                        # provider failure, refused answer or version conflict: the current brief is preserved


def decide(current: ExecutiveBrief | None, inp: ExecutiveInput) -> Decision:
    """The deterministic preserve policy. Only the canonical input identity decides; generated prose and freshness never do."""
    if current is not None and current.input_fingerprint == inp.fingerprint:
        return Decision.UNCHANGED
    return Decision.SYNTHESIZED_EMPTY if not inp.results and not inp.omitted else Decision.SYNTHESIZED


# --- request and assembly -----------------------------------------------------------------------------------------------------------


def executive_messages(inp: ExecutiveInput) -> tuple[Message, ...]:
    return (Message("system", executive_prompt()),
            Message("user", "Write the executive brief. Canonical results (JSON):\n" + canonical_json(thaw(inp.payload))))


# Only keywords the production strict schemas already use (verified live by the Phase 15 gate) are sent; ``maxItems`` never was, so it is
# dropped from the provider copy too. The local validation (``model_output_errors``) still enforces every bound.
PROVIDER_DROPPED_KEYWORDS = ("maxItems",)


def _without(schema: Any, keywords: tuple[str, ...]) -> Any:
    if isinstance(schema, Mapping):
        return {key: _without(value, keywords) for key, value in schema.items() if key not in keywords}
    if isinstance(schema, list):
        return [_without(item, keywords) for item in schema]
    return schema


def executive_output() -> StructuredOutput:
    sent = _without(provider_schema(model_output_schema()), PROVIDER_DROPPED_KEYWORDS)
    return StructuredOutput("atlas_executive_brief_v1", freeze(sent), model_output_errors)


def executive_request(inp: ExecutiveInput, *, run_id: str) -> ProviderRequest:
    context = CallContext(purpose=EXECUTIVE_PURPOSE, run_id=run_id, prompt_version=EXECUTIVE_PROMPT_VERSION)
    return ProviderRequest(context, executive_messages(inp), executive_output(), max_output_tokens=MAX_OUTPUT_TOKENS, reasoning_effort=REASONING_EFFORT)


@dataclass(frozen=True)
class BriefProvenance:
    brief_id: str
    version: int
    run_id: str
    created_at: str
    provider: str | None = None
    model: str | None = None
    request_ids: tuple[str, ...] = ()


def assemble_brief(output: Mapping[str, Any], inp: ExecutiveInput, provenance: BriefProvenance, *, generator: str = GENERATOR_MODEL) -> dict[str, Any]:
    """The complete brief document: the model's sections (statement IDs assigned here) plus Python's identity and provenance. Not
    validated here (``executive_validator.validate_brief`` decides). Tolerant of a malformed answer so the validator can name it."""
    sections_in = output.get("sections") if isinstance(output, Mapping) else None
    sections: dict[str, Any] = {}
    for name in SECTIONS:
        rows = sections_in.get(name) if isinstance(sections_in, Mapping) else []
        out = []
        for i, row in enumerate(rows if isinstance(rows, list) else []):
            if isinstance(row, Mapping):
                out.append({"statement_id": statement_id(name, i + 1), **{key: value for key, value in row.items() if key != "statement_id"}})
            else:
                out.append(row)
        sections[name] = out
    model_brief = generator == GENERATOR_MODEL
    return {"contract_version": BRIEF_CONTRACT_VERSION, "brief_id": provenance.brief_id, "version": provenance.version, "scope": COMPANY_SCOPE,
            "run_id": provenance.run_id, "input_version": EXECUTIVE_INPUT_VERSION, "input_fingerprint": inp.fingerprint,
            "input_results": inp.input_results(), "omitted_result_count": inp.omitted, "sections": sections,
            "generator": {"kind": generator, "provider": provenance.provider if model_brief else None, "model": provenance.model if model_brief else None,
                          "request_ids": list(provenance.request_ids) if model_brief else []},
            "prompt_version": EXECUTIVE_PROMPT_VERSION if model_brief else None, "validator_version": executive_validator.VALIDATOR_VERSION,
            "created_at": provenance.created_at}


def empty_brief(inp: ExecutiveInput, provenance: BriefProvenance) -> ExecutiveBrief:
    """The deterministic brief when no canonical result is eligible: every section empty, no model call."""
    return ExecutiveBrief.from_dict(assemble_brief({"sections": {name: [] for name in SECTIONS}}, inp, provenance, generator=GENERATOR_EMPTY))


# --- the synthesizer ----------------------------------------------------------------------------------------------------------------

# pg_try_advisory_lock key: one executive synthesizer at a time ("AtlaEXEC").
EXECUTIVE_LOCK_KEY = 0x41746C6145584543


@dataclass(frozen=True)
class SynthesisOutcome:
    run_id: str
    decision: Decision | None                  # None when skipped (another synthesizer held the lock)
    input_fingerprint: str | None = None
    brief_id: str | None = None
    brief_version: int | None = None           # the current version after this run (unchanged on failure)
    llm_calls: int = 0
    failure: str | None = None                 # provider:<class> | validation:<codes> | conflict:VersionConflict | input:<error>
    skipped: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**dataclasses.asdict(self), "decision": self.decision.value if self.decision else None}


class ExecutiveSynthesizer:
    def __init__(self, store: Any, gateway: ReasoningGateway, *, clock: Callable[[], str] = utc_now, brief_ids: Callable[[], str] = new_brief_id,
                 policy: InputPolicy | None = None, retries: int | None = None) -> None:
        self.store, self.gateway, self.clock, self.brief_ids = store, gateway, clock, brief_ids
        self.policy = policy or InputPolicy()
        self.retries = validation_retries() if retries is None else retries

    def synthesize(self, run_id: str) -> SynthesisOutcome:
        with self.store.session_lock(EXECUTIVE_LOCK_KEY) as acquired:
            if not acquired:
                LOG.warning("another executive synthesizer is running; run_id=%s skipped", run_id)
                return SynthesisOutcome(run_id, None, skipped="executive_busy")
            return self._synthesize(run_id)

    def _synthesize(self, run_id: str) -> SynthesisOutcome:
        try:
            with self.store.snapshot() as tx:        # one consistent snapshot: rows, reasons, patches and questions agree
                tx.get_run(run_id)
                inp = executive_input(tx.canonical_results(run_id, resolved_lookback_runs=self.policy.resolved_lookback_runs), policy=self.policy)
                current = tx.current_brief(COMPANY_SCOPE)
        except (InputTooLarge, IneligibleResult) as error:
            return self._failed(run_id, None, None, f"input:{type(error).__name__}", calls=0)
        decision = decide(current, inp)
        brief_id = current.brief_id if current is not None else self.brief_ids()
        version = current.version + 1 if current is not None else 1
        if decision == Decision.UNCHANGED:
            assert current is not None
            with self.store.transaction() as tx:
                tx.record_run(run_id=run_id, decision=decision, input_fingerprint=inp.fingerprint, brief_id=current.brief_id, brief_version=current.version)
            LOG.info("executive brief unchanged run_id=%s version=%s", run_id, current.version)
            return SynthesisOutcome(run_id, decision, inp.fingerprint, current.brief_id, current.version)
        provenance = BriefProvenance(brief_id, version, run_id, self.clock())
        if decision == Decision.SYNTHESIZED_EMPTY:
            return self._commit(run_id, decision, inp, empty_brief(inp, provenance), current, calls=0)
        return self._call_and_commit(run_id, inp, provenance, current)

    def _call_and_commit(self, run_id: str, inp: ExecutiveInput, provenance: BriefProvenance, current: ExecutiveBrief | None) -> SynthesisOutcome:
        request = executive_request(inp, run_id=run_id)
        calls, attempt = 0, 0
        request_ids: list[str] = []
        while True:
            attempt += 1
            request = dataclasses.replace(request, context=dataclasses.replace(request.context, request_id=new_request_id()))
            request_ids.append(request.context.request_id)
            calls += 1
            try:
                response = self.gateway.call(request)
            except ProviderError as error:
                return self._failed(run_id, inp, current, f"provider:{error.error_class}", calls=calls, request_ids=request_ids)
            candidate = self._candidate(inp, provenance, response)
            with self.store.transaction() as tx:
                references = tx.classify_references(executive_validator.out_of_input_references(candidate, inp))
            expected = executive_validator.ExpectedBrief(brief_id=provenance.brief_id, version=provenance.version, run_id=run_id,
                                                          model=self.gateway.model, request_id=request.context.request_id,
                                                          prompt_version=EXECUTIVE_PROMPT_VERSION)
            report = executive_validator.validate_brief(candidate, inp, expected, references)
            if report.ok:
                return self._commit(run_id, Decision.SYNTHESIZED, inp, ExecutiveBrief.from_dict(candidate), current, calls=calls)
            LOG.warning("executive candidate refused run_id=%s attempt=%s codes=%s", run_id, attempt, ",".join(report.codes))
            if not report.retryable or attempt > self.retries:
                return self._failed(run_id, inp, current, f"validation:{','.join(report.codes)}", calls=calls, report=report, candidate=candidate,
                                    model=response.model, request_ids=request_ids)
            request = dataclasses.replace(request, messages=(*request.messages, Message("assistant", response.content),
                                                             Message("user", executive_validator.correction_message(report))))

    def _candidate(self, inp: ExecutiveInput, provenance: BriefProvenance, response: ProviderResponse) -> dict[str, Any]:
        stamped = dataclasses.replace(provenance, provider=self.gateway.transport.provider_name, model=response.model, request_ids=(response.request_id,))
        return assemble_brief(response.parsed, inp, stamped)

    def _commit(self, run_id: str, decision: Decision, inp: ExecutiveInput, brief: ExecutiveBrief, current: ExecutiveBrief | None, *,
                calls: int) -> SynthesisOutcome:
        try:
            with self.store.transaction() as tx:
                tx.append_brief(brief, expected_version=current.version if current is not None else None)
                tx.record_run(run_id=run_id, decision=decision, input_fingerprint=inp.fingerprint, brief_id=brief.brief_id, brief_version=brief.version,
                              llm_calls=calls, model=brief.generator.model, prompt_version=brief.prompt_version,
                              request_ids=brief.generator.request_ids)
        except VersionConflict:
            return self._failed(run_id, inp, None, "conflict:VersionConflict", calls=calls)
        except Exception as error:  # noqa: BLE001 - rolled back: the current brief is untouched; the run is still recorded
            return self._failed(run_id, inp, None, f"store:{type(error).__name__}", calls=calls)
        LOG.info("executive brief %s run_id=%s brief_id=%s version=%s", decision.value, run_id, brief.brief_id, brief.version)
        return SynthesisOutcome(run_id, decision, inp.fingerprint, brief.brief_id, brief.version, llm_calls=calls)

    def _failed(self, run_id: str, inp: ExecutiveInput | None, current: ExecutiveBrief | None, failure: str, *, calls: int,
                report: executive_validator.ExecutiveReport | None = None, candidate: Mapping[str, Any] | None = None, model: str | None = None,
                request_ids: Sequence[str] = ()) -> SynthesisOutcome:
        """Record a failed run; the current brief (re-read: after a conflict it is the other writer's) stays current, untouched."""
        LOG.warning("executive synthesis failed run_id=%s failure=%s", run_id, failure)
        kept: ExecutiveBrief | None = None
        # The audit must survive a candidate the database cannot store: retry without it (its violations are kept).
        for stored in ((candidate, None), (None, "candidate could not be stored")) if candidate is not None else ((None, None),):
            try:
                with self.store.transaction() as tx:
                    kept = tx.current_brief(COMPANY_SCOPE)
                    tx.record_run(run_id=run_id, decision=Decision.FAILED, input_fingerprint=inp.fingerprint if inp else None,
                                  brief_id=kept.brief_id if kept else None, brief_version=kept.version if kept else None, llm_calls=calls,
                                  failure=failure, error_codes=report.codes if report else (),
                                  violations=[row.to_dict() for row in report.violations] if report else [], rejected_candidate=stored[0],
                                  candidate_omitted=stored[1], model=model, prompt_version=EXECUTIVE_PROMPT_VERSION if calls else None,
                                  request_ids=request_ids)
                break
            except Exception as error:  # noqa: BLE001 - never let the audit hide the failure it records
                LOG.error("executive failure not recorded run_id=%s error=%s", run_id, type(error).__name__)
        return SynthesisOutcome(run_id, Decision.FAILED, inp.fingerprint if inp else None, kept.brief_id if kept else None,
                                kept.version if kept else None, llm_calls=calls, failure=failure)

