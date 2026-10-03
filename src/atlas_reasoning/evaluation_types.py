"""Reasoning V3 evaluation (Phase 19, ``REV/19``): the frozen data model of the evaluation harness.

Phase 19-A owns these types; Phase 19-B's runner (fake or live model) depends on them, so they are **frozen**: names, fields and
meanings never change within ``EVALUATION_SCHEMA_VERSION``; a change is a new version.

    EvaluationCase       one golden case: a scenario (ordered steps of declarative actions) and, per evaluated step, an ExpectedOutcome
    ExpectedOutcome      structural expectations: fact name -> expected value (``FACTS`` is the closed vocabulary)
    CanonicalState       what PostgreSQL holds at one instant, reduced to identifiers, statuses, counts and hashes (never text)
    StepObservation      the facts and metric counts observed for one evaluated step (``evaluation.observe_step``)
    EvaluationObservation  every evaluated step of one golden case
    CheckResult          one expectation compared with its observation
    MetricCount          numerator / denominator of one metric (exact integers)
    EvaluationMetric     a metric aggregated over the suite (``evaluation_metrics``)
    Threshold / ThresholdSet / ThresholdResult   versioned release thresholds and their exact evaluation (``evaluation_thresholds``)
    EvaluationReport     the deterministic machine-readable report (``evaluation.evaluate``)

What an expectation may name is **structural only** — identity, versions, lifecycle, counts, statuses, codes. No fact carries model
text, and no type here has a field for hidden reasoning: the harness cannot evaluate chain-of-thought because it never sees any.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from typing import Any

EVALUATION_SCHEMA_VERSION = "reasoning-evaluation-v1"
GOLDEN_SCHEMA_VERSION = "reasoning-golden-case-v1"
THRESHOLD_SCHEMA_VERSION = "reasoning-release-thresholds-v1"
GOLDEN_DATASET = "showcase-v1"           # the synthetic showcase extract (``atlas_commander.demo``): the only golden dataset of v1
REQUIRED_CASE_NUMBERS = tuple(range(1, 21))   # REV/19 #1 (1-13) and the Phase 18 structural coverage (14-20)


class FixtureError(ValueError):
    """A golden case (or a threshold file) that does not validate. The message names the fixture and the offending path."""


class Category(StrEnum):
    STABILITY = "stability"
    HUMAN_CONTEXT = "human_context"
    RELIABILITY = "reliability"


# --- the scenario vocabulary (closed; a runner implements every term) ---------------------------------------------------------


class Op(StrEnum):
    GATE = "gate"                 # run the Change Gate on an evidence variant (a new run)
    ORCHESTRATE = "orchestrate"   # RunOrchestrator.run on the latest run (params: budget, max_attempts)
    ORCHESTRATE_WHILE_BUSY = "orchestrate_while_busy"   # RunOrchestrator.run while another engine holds the engine lock
    RESUME = "resume"             # RunOrchestrator.resume on the latest run (params: budget, max_attempts)
    FAULT = "fault"               # inject a fault before the next orchestration (params: kind, target, count)
    HUMAN = "human"               # add management context (params: kind)
    CLAIM = "claim"               # a worker claims the target's pending work item and dies (params: target)
    AGE_CLAIMS = "age_claims"     # claims in progress become older than the stale-claim limit (params: seconds)
    ADVANCE_CLOCK = "advance_clock"   # the circuit breaker's monotonic clock moves (params: seconds)


class EvidenceVariant(StrEnum):
    SHOWCASE = "showcase"                         # the golden snapshot as built
    NON_MATERIAL = "non_material"                 # same evidence; new snapshot ID and renamed Intelligence V2 finding IDs
    MATERIAL_CHANGE = "material_change"           # the focus Editor's current late rate moves (one material value change)
    MATERIAL_CHANGE_2 = "material_change_2"       # ... and moves again
    FOCUS_REMOVED = "focus_removed"               # the focus Editor's deadline findings are gone (the case disappears)
    NEW_TOPIC = "new_topic"                       # one more Editor speed pattern (a case never seen before)
    WITHOUT_CONTRADICTION = "without_contradiction"   # the focus case's contradicting finding is gone


class FaultKind(StrEnum):
    PROVIDER_OUTAGE = "provider_outage"     # the provider is unavailable for the target's next call (every attempt of it)
    PROVIDER_AUTH = "provider_auth"         # the provider refuses the credential for the target (never retryable)
    OVERCLAIM = "overclaim"                 # the target's next ``count`` answers claim more confidence than its evidence allows
    MEMORY_OUTAGE = "memory_outage"         # contextual memory (Honcho) is unavailable
    MEMORY_RESTORE = "memory_restore"       # ... and back


class FaultTarget(StrEnum):
    FOCUS = "focus"                         # the golden case's focus case
    ALL = "all"                             # every case of the latest run
    FIRST_IN_PRIORITY = "first_in_priority"   # the first pending item in Phase 18 priority order
    NONE = "none"                           # not case-specific (memory faults)


class HumanKind(StrEnum):
    NOTE = "note"                           # a manager interpretation note on the focus card
    ANSWER = "answer"                       # a management answer to the focus card's first open Atlas question
    TEACHING = "teaching"                   # a teaching scoped to the focus Editor, valid until changed
    EXPIRED_TEACHING = "expired_teaching"   # a teaching scoped to the focus Editor whose validity ended in the past


ACTION_PARAMS: Mapping[Op, Mapping[str, str]] = {
    Op.GATE: {"evidence": "evidence"},
    Op.ORCHESTRATE: {"budget": "count", "max_attempts": "positive"},
    Op.ORCHESTRATE_WHILE_BUSY: {},
    Op.RESUME: {"budget": "count", "max_attempts": "positive"},
    Op.FAULT: {"kind": "fault", "target": "target", "count": "positive"},
    Op.HUMAN: {"kind": "human"},
    Op.CLAIM: {"target": "target"},
    Op.AGE_CLAIMS: {"seconds": "positive"},
    Op.ADVANCE_CLOCK: {"seconds": "positive"},
}
REQUIRED_PARAMS: Mapping[Op, frozenset[str]] = {
    Op.GATE: frozenset({"evidence"}), Op.FAULT: frozenset({"kind", "target"}), Op.HUMAN: frozenset({"kind"}), Op.CLAIM: frozenset({"target"}),
    Op.AGE_CLAIMS: frozenset({"seconds"}), Op.ADVANCE_CLOCK: frozenset({"seconds"}),
}
# Per-case runtime configuration (Phase 18-B controls of the case's process): the breaker threshold and cooldown, the gateway's
# concurrency and the engine's corrective re-asks. Absent keys use the runner's defaults (no breaker; concurrency 4; one re-ask).
RUNTIME_KEYS: Mapping[str, str] = {"breaker_threshold": "positive", "breaker_cooldown_seconds": "positive", "gateway_concurrency": "positive",
                                   "validation_retries": "count"}


@dataclass(frozen=True)
class Action:
    op: Op
    params: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op.value, **{key: self.params[key] for key in sorted(self.params)}}


# --- facts: what an expectation may name (closed vocabulary) -------------------------------------------------------------------

RUN_STATUSES = ("complete", "partial", "degraded", "failed")
LIFECYCLE_STATES = ("new", "active", "updated", "cooling", "resolved", "superseded")
GATE_ACTIONS = ("unchanged", "new", "updated", "disappeared")
CHANGE_KINDS = ("created", "patched", "no_change_review", "lifecycle")
RESULT_IDENTITY = ("none", "kept", "created", "replaced")     # the focus card across the step: kept = the same result_id
CONFIDENCE_LEVELS = ("weak", "moderate", "strong")
CIRCUIT_STATES = ("closed", "open", "half_open")


@dataclass(frozen=True)
class FactSpec:
    """``kind``: ``int`` (count), ``bool``, ``enum`` (one of ``values``), ``list`` (sorted distinct strings). ``nullable``: None is a
    legitimate observation (e.g. no focus card yet)."""

    kind: str
    description: str
    values: tuple[str, ...] = ()
    nullable: bool = False


FACTS: Mapping[str, FactSpec] = {
    # Phase 18 orchestration (RunOrchestrator PassReports of the step; the last non-skipped pass decides status and reasons)
    "run.status": FactSpec("enum", "run status after the step's last pass", RUN_STATUSES, nullable=True),
    "run.reasons": FactSpec("list", "status reason codes of the step's last pass"),
    "run.executive_ready": FactSpec("bool", "whether the last pass let executive synthesis run", nullable=True),
    "run.passes": FactSpec("int", "orchestration passes that ran in the step (skipped passes excluded)"),
    "run.skipped": FactSpec("list", "why passes of the step were skipped (e.g. engine_busy)"),
    "run.calls_used": FactSpec("int", "provider calls charged to the step's pass budgets"),
    "run.admitted": FactSpec("int", "work items admitted by the step's passes"),
    "run.deferred": FactSpec("int", "work items deferred by the step's passes"),
    "run.retries": FactSpec("int", "retry work items created by the step's passes"),
    "run.recovered": FactSpec("int", "stale claims recovered by the step's passes"),
    "circuit.state": FactSpec("enum", "the shared circuit breaker after the step (where the runtime exposes it)", CIRCUIT_STATES, nullable=True),
    # Phase 18 telemetry (18-C reliability_report over the step's runs; cumulative over those runs)
    "telemetry.refused_before_call": FactSpec("int", "work items failed by a breaker / budget refusal before any provider request"),
    "telemetry.corrective_reasks": FactSpec("int", "model calls made again for a work item after a refused candidate"),
    "telemetry.interrupted_passes": FactSpec("int", "passes closed as interrupted"),
    "telemetry.retries_created": FactSpec("int", "retry work items of the step's runs"),
    "telemetry.skipped_unchanged": FactSpec("int", "cases the Change Gate skipped as unchanged (zero model work)"),
    # canonical deltas of the step (all cases)
    "calls.reasoning": FactSpec("int", "analyst + update provider calls recorded in the step (llm_calls rows)"),
    "calls.failed": FactSpec("int", "of which failed"),
    "gate.unchanged": FactSpec("int", "Change Gate decisions of the step: unchanged"),
    "gate.new": FactSpec("int", "Change Gate decisions of the step: new"),
    "gate.updated": FactSpec("int", "Change Gate decisions of the step: updated"),
    "gate.disappeared": FactSpec("int", "Change Gate decisions of the step: disappeared"),
    "work.open": FactSpec("int", "LLM work items pending or in progress after the step (work remaining)"),
    "results.created": FactSpec("int", "result cards created in the step"),
    "versions.content": FactSpec("int", "content versions committed in the step (created + patched + no_change_review)"),
    "validation.refusals": FactSpec("int", "candidates the Phase 15 guardrails refused in the step"),
    "questions.open": FactSpec("int", "open Atlas questions after the step"),
    "memory.degraded_calls": FactSpec("int", "reasoning calls of the step whose contextual memory was degraded or unavailable"),
    "integrity.duplicates": FactSpec("int", "duplicate canonical state after the step (must be 0; see evaluation_metrics.duplicates)"),
    # the focus case (the golden case's ``focus`` identity key)
    "focus.case_id_stable": FactSpec("bool", "the focus case kept its case_id across the step and was not split into a new case", nullable=True),
    "focus.present": FactSpec("bool", "the focus case is present in the latest snapshot", nullable=True),
    "focus.gate_action": FactSpec("enum", "the step's Change Gate decision for the focus case", GATE_ACTIONS, nullable=True),
    "focus.result": FactSpec("enum", "the focus card across the step", RESULT_IDENTITY),
    "focus.content_versions": FactSpec("int", "content versions committed for the focus card in the step"),
    "focus.change_kinds": FactSpec("list", "kinds of versions written for the focus card in the step (lifecycle included)"),
    "focus.lifecycle": FactSpec("enum", "the focus card's lifecycle state after the step", LIFECYCLE_STATES, nullable=True),
    "focus.confidence": FactSpec("enum", "the focus card's confidence level after the step", CONFIDENCE_LEVELS, nullable=True),
    "focus.contradicting_findings": FactSpec("int", "contradicting findings of the focus case's latest evidence", nullable=True),
    "focus.open_questions": FactSpec("int", "open Atlas questions of the focus case after the step"),
    "focus.questions_opened": FactSpec("int", "Atlas questions of the focus case opened in the step and still open after it"),
    "focus.reasked_answered": FactSpec("int", "open questions of the focus case that repeat one management answered or dismissed"),
    "focus.model_calls": FactSpec("int", "analyst + update calls for the focus case in the step"),
    "focus.validation_refusals": FactSpec("int", "refused candidates for the focus case in the step"),
    "focus.memory_status": FactSpec("list", "memory status of the focus case's reasoning calls in the step"),
    "focus.context_sources": FactSpec("list", "source types of the human context injected into the focus case's calls in the step"),
}


@dataclass(frozen=True)
class ExpectedOutcome:
    """Fact name -> expectation. An expectation is an exact value, or for ``int`` facts ``{"min": a, "max": b}`` (either bound may be
    absent), or for ``list`` facts ``{"includes": [...], "excludes": [...]}``. Validated against ``FACTS`` (``evaluation.parse_case``)."""

    checks: tuple[tuple[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {name: value for name, value in self.checks}


@dataclass(frozen=True)
class Step:
    step_id: str
    actions: tuple[Action, ...]
    expect: ExpectedOutcome | None = None        # None: a setup step (executed, never evaluated, never measured)

    @property
    def evaluated(self) -> bool:
        return self.expect is not None

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {"step_id": self.step_id, "actions": [action.to_dict() for action in self.actions]}
        if self.expect is not None:
            document["expect"] = self.expect.to_dict()
        return document


@dataclass(frozen=True)
class EvaluationCase:
    """One golden case. ``number`` is its REV/19 coverage number (1-20); ``focus`` the identity key the ``focus.*`` facts follow;
    ``metric_exclusions`` maps a metric field to the documented reason this case is excluded from it (e.g. an injected fault)."""

    fixture_id: str
    number: int
    title: str
    requirement: str
    category: Category
    focus: str
    steps: tuple[Step, ...]
    dataset: str = GOLDEN_DATASET
    runtime: Mapping[str, int] = field(default_factory=dict)
    metric_exclusions: Mapping[str, str] = field(default_factory=dict)

    @property
    def evaluated_steps(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.evaluated)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": GOLDEN_SCHEMA_VERSION, "fixture_id": self.fixture_id, "number": self.number, "title": self.title,
                "requirement": self.requirement, "category": self.category.value, "dataset": self.dataset, "focus": self.focus,
                "runtime": dict(sorted(self.runtime.items())), "metric_exclusions": dict(sorted(self.metric_exclusions.items())),
                "steps": [step.to_dict() for step in self.steps]}


# --- canonical state (what an observation is computed from) -------------------------------------------------------------------


@dataclass(frozen=True)
class CaseState:
    case_id: str
    identity_key: str
    presence: str
    evidence_fingerprint: str
    contradicting_findings: int


@dataclass(frozen=True)
class ResultState:
    result_id: str
    case_id: str
    version: int
    lifecycle_status: str


@dataclass(frozen=True)
class VersionState:
    """One result version. ``fields``: patchable field -> sha256 of its canonical JSON (never the text); ``declared_changes``: the
    fields the accepted update declared changed (patched versions); ``grounding_codes``: the Phase 15 grounding re-check of a created or
    patched version (``evaluation_metrics.GROUNDING_CODES``)."""

    result_id: str
    version: int
    change_kind: str
    evidence_fingerprint: str
    fields: tuple[tuple[str, str], ...]
    declared_changes: tuple[str, ...] = ()
    confidence: str | None = None
    grounding_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransitionState:
    transition_id: str
    result_id: str
    result_version: int
    from_status: str | None
    to_status: str


@dataclass(frozen=True)
class QuestionState:
    question_id: str
    case_id: str
    dedup_key: str
    state: str


@dataclass(frozen=True)
class CallState:
    request_id: str
    case_id: str | None
    purpose: str
    status: str
    tokens: int


@dataclass(frozen=True)
class RefusalState:
    candidate_id: str
    case_id: str
    codes: tuple[str, ...]


@dataclass(frozen=True)
class WorkState:
    work_item_id: str
    case_id: str
    status: str
    requires_llm: bool


@dataclass(frozen=True)
class InjectionState:
    injection_id: str
    case_id: str
    purpose: str
    memory_status: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class ObservationState:
    run_id: str
    case_id: str
    action: str


@dataclass(frozen=True)
class CanonicalState:
    """PostgreSQL at one instant (``evaluation.capture``), content-free. Identifiers are kept only to diff two states; they never
    reach a report."""

    cases: tuple[CaseState, ...] = ()
    results: tuple[ResultState, ...] = ()
    versions: tuple[VersionState, ...] = ()
    transitions: tuple[TransitionState, ...] = ()
    questions: tuple[QuestionState, ...] = ()
    calls: tuple[CallState, ...] = ()
    refusals: tuple[RefusalState, ...] = ()
    work: tuple[WorkState, ...] = ()
    injections: tuple[InjectionState, ...] = ()
    observations: tuple[ObservationState, ...] = ()
    synced_memory: tuple[tuple[str, str, str, str], ...] = ()     # (source_type, source_id, session_key, content_sha256) of synced copies

    def case_for_identity(self, identity_key: str) -> CaseState | None:
        return next((case for case in self.cases if case.identity_key == identity_key), None)


# --- observations, checks, metrics, thresholds, report ------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricCount:
    numerator: int = 0
    denominator: int = 0

    def __post_init__(self) -> None:
        if self.numerator < 0 or self.denominator < 0 or self.numerator > self.denominator:
            raise ValueError(f"invalid metric count {self.numerator}/{self.denominator}")

    def __add__(self, other: MetricCount) -> MetricCount:
        return MetricCount(self.numerator + other.numerator, self.denominator + other.denominator)

    def to_dict(self) -> dict[str, int]:
        return {"numerator": self.numerator, "denominator": self.denominator}


@dataclass(frozen=True)
class StepObservation:
    step_id: str
    facts: Mapping[str, Any]
    counts: Mapping[str, MetricCount]

    def to_dict(self) -> dict[str, Any]:
        return {"step_id": self.step_id, "facts": {name: self.facts[name] for name in sorted(self.facts)},
                "counts": {name: self.counts[name].to_dict() for name in sorted(self.counts)}}


@dataclass(frozen=True)
class EvaluationObservation:
    fixture_id: str
    steps: tuple[StepObservation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"fixture_id": self.fixture_id, "steps": [step.to_dict() for step in self.steps]}


@dataclass(frozen=True)
class CheckResult:
    fixture_id: str
    step_id: str
    fact: str
    expected: Any
    observed: Any
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {"fixture_id": self.fixture_id, "step_id": self.step_id, "fact": self.fact, "expected": self.expected, "observed": self.observed,
                "passed": self.passed}


def decimal_string(value: Fraction | None, places: int = 6) -> str | None:
    """``value`` rounded half-even to ``places`` decimals, as a string (display only; comparisons use the exact Fraction)."""
    if value is None:
        return None
    scaled = round(value * 10 ** places)
    sign = "-" if scaled < 0 else ""
    digits = str(abs(scaled)).rjust(places + 1, "0")
    return f"{sign}{digits[:-places]}.{digits[-places:]}"


@dataclass(frozen=True)
class EvaluationMetric:
    """``value`` = numerator / denominator, exact; None when the denominator is 0 (no data: never 0 and never 1)."""

    name: str
    count: MetricCount
    excluded_fixtures: tuple[str, ...] = ()

    @property
    def value(self) -> Fraction | None:
        return Fraction(self.count.numerator, self.count.denominator) if self.count.denominator else None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, **self.count.to_dict(), "value": decimal_string(self.value), "no_data": self.value is None,
                "excluded_fixtures": list(self.excluded_fixtures)}


class Comparator(StrEnum):
    AT_LEAST = ">="
    AT_MOST = "<="


class NoData(StrEnum):
    FAIL = "fail"      # a metric with no data cannot show the property: the threshold fails (the release default)
    PASS = "pass"


@dataclass(frozen=True)
class Threshold:
    metric: str
    comparator: Comparator
    bound: str                       # a decimal string ("0", "0.05", "1"): parsed exactly, never as a float
    on_no_data: NoData = NoData.FAIL
    rationale: str = ""

    @property
    def exact_bound(self) -> Fraction:
        return Fraction(self.bound)

    def to_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "comparator": self.comparator.value, "bound": self.bound, "on_no_data": self.on_no_data.value,
                "rationale": self.rationale}


@dataclass(frozen=True)
class ThresholdSet:
    version: str
    thresholds: tuple[Threshold, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": THRESHOLD_SCHEMA_VERSION, "version": self.version, "thresholds": [threshold.to_dict() for threshold in self.thresholds]}


@dataclass(frozen=True)
class ThresholdResult:
    threshold: Threshold
    value: Fraction | None
    passed: bool
    no_data: bool

    def to_dict(self) -> dict[str, Any]:
        return {**self.threshold.to_dict(), "value": decimal_string(self.value), "no_data": self.no_data, "passed": self.passed,
                "exact_value": None if self.value is None else f"{self.value.numerator}/{self.value.denominator}"}


@dataclass(frozen=True)
class EvaluationReport:
    """The machine-readable result. ``canonical_json()`` is byte-identical for equal inputs; ``metadata`` (timestamps, host, the
    runner's free-form notes) is the only part excluded from it."""

    passed: bool
    fixtures: tuple[EvaluationCase, ...]
    observations: tuple[EvaluationObservation, ...]
    checks: tuple[CheckResult, ...]
    metrics: tuple[EvaluationMetric, ...]
    thresholds: ThresholdSet
    threshold_results: tuple[ThresholdResult, ...]
    coverage: Mapping[str, Any]
    versions: Mapping[str, str]
    environment: Mapping[str, str]
    failures: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = EVALUATION_SCHEMA_VERSION

    def to_dict(self, *, include_metadata: bool = True) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema": self.schema, "result": "PASS" if self.passed else "FAIL", "failures": list(self.failures),
            "versions": dict(sorted(self.versions.items())), "environment": dict(sorted(self.environment.items())),
            "fixtures": [fixture.to_dict() for fixture in self.fixtures], "observations": [observation.to_dict() for observation in self.observations],
            "checks": [check.to_dict() for check in self.checks], "metrics": [metric.to_dict() for metric in self.metrics],
            "thresholds": self.thresholds.to_dict(), "threshold_results": [result.to_dict() for result in self.threshold_results],
            "coverage": dict(self.coverage)}
        if include_metadata:
            document["metadata"] = dict(self.metadata)
        return document

    def canonical_json(self) -> str:
        """Deterministic JSON without ``metadata``: the reproducibility contract."""
        return json.dumps(self.to_dict(include_metadata=False), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)
