"""Reasoning V3 evaluation harness (Phase 19, ``REV/19``): golden cases, structural observation, metrics, thresholds, report.

    cases = load_golden_cases()                              # the frozen golden cases (validated; duplicates refused)
    before = capture(store)                                  # canonical state (read only, content-free)
    ... a runner executes one step of a case (Change Gate, RunOrchestrator, faults, human context) ...
    after = capture(store)
    step = observe_step(case, before, after, step_id=..., passes=[pass_report], telemetry=reliability_report(store, run_ids),
                        controls=runtime.controls)
    report = evaluate(cases, observations, environment={"provider": "scripted-fake"})
    report.passed, report.canonical_json()

Division of labour (frozen for Phase 19-B):

- **Phase 19-A (this module)**: the golden cases and their vocabulary, ``capture`` / ``observe_step`` (what is observed and how),
  ``check_case`` (structural expectations), the metrics (``evaluation_metrics``), the release thresholds (``evaluation_thresholds``)
  and ``evaluate`` (the report). The fake-provider execution of the golden cases is a test fixture (``tests/reasoning_evaluation_driver.py``).
- **Phase 19-B**: the runner that executes golden cases (including the optional live-model command and repeated-run measurements) and
  the human review checklist, built on these interfaces without changing their meaning.

What is observed — only canonical outputs and Phase 18 telemetry: PostgreSQL rows (``capture``), the orchestrator's ``PassReport``,
the 18-C ``reliability_report`` and the shared breaker's ``ProviderControls.snapshot``. The harness never decides a run status, never
prioritises, budgets, retries or resumes; it records what Reasoning V3 did. It never reads prompts, responses or hidden reasoning (there
is none to read), and a fact never carries model text, an identifier or a timestamp — so equal behaviour gives byte-equal reports.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from atlas_reasoning import REASONING_PACKAGE_VERSION, analyst, change_gate, engine, guardrails, lifecycle, reliability_metrics, updater
from atlas_reasoning import run_control as orchestration
from atlas_reasoning.case_identity import IDENTITY_VERSION
from atlas_reasoning.enums import CONTRACT_VERSION
from atlas_reasoning.evaluation_metrics import (
    METRIC_NAMES,
    STEP_METRICS,
    declared_changes,
    duplicates,
    field_hashes,
    grounding_codes,
    identity_splits,
    step_counts,
    total,
    update_case,
)
from atlas_reasoning.evaluation_thresholds import GOLDEN_DIR, evaluate_thresholds, release_thresholds
from atlas_reasoning.evaluation_types import (
    ACTION_PARAMS,
    EVALUATION_SCHEMA_VERSION,
    FACTS,
    GOLDEN_DATASET,
    GOLDEN_SCHEMA_VERSION,
    REQUIRED_CASE_NUMBERS,
    REQUIRED_PARAMS,
    RUNTIME_KEYS,
    Action,
    CallState,
    CanonicalState,
    CaseState,
    Category,
    CheckResult,
    EvaluationCase,
    EvaluationMetric,
    EvaluationObservation,
    EvaluationReport,
    EvidenceVariant,
    ExpectedOutcome,
    FaultKind,
    FaultTarget,
    FixtureError,
    HumanKind,
    InjectionState,
    MetricCount,
    ObservationState,
    Op,
    QuestionState,
    RefusalState,
    ResultState,
    Step,
    StepObservation,
    ThresholdSet,
    TransitionState,
    VersionState,
    WorkState,
)
from atlas_reasoning.fingerprint import FINGERPRINT_VERSION
from atlas_reasoning.reliability import ProviderControls
from atlas_reasoning.reliability_metrics import ReliabilityReport
from atlas_reasoning.run_control import PassReport
from atlas_reasoning.settings import PINNED_MODEL
from atlas_reasoning.store.evaluation_read import canonical_rows
from atlas_reasoning.store.repository import ReasoningStore

CASE_KEYS = frozenset({"schema", "fixture_id", "number", "title", "requirement", "category", "dataset", "focus", "runtime", "metric_exclusions", "steps"})
REQUIRED_CASE_KEYS = frozenset({"schema", "fixture_id", "number", "title", "requirement", "category", "focus", "steps"})
STEP_KEYS = frozenset({"step_id", "actions", "expect"})
# The sha256 of the published golden set (``fixture_digest(load_golden_cases())``). Editing a golden case changes the digest and makes
# every result non-release until this constant is changed too — in review, with the reason, never to make a failing result pass.
PUBLISHED_FIXTURE_DIGEST = "sha256:61db42cc23594777d7876911845d0cfe2142525791881834cc5b5b896c18d15c"
_ENUMS: Mapping[str, type] = {"evidence": EvidenceVariant, "fault": FaultKind, "target": FaultTarget, "human": HumanKind}


# --- golden cases -------------------------------------------------------------------------------------------------------------


def _param(value: Any, kind: str, where: str) -> Any:
    if kind in _ENUMS:
        try:
            return _ENUMS[kind](value).value
        except ValueError as error:
            raise FixtureError(f"{where}: {value!r} is not a known {kind}") from error
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if kind == "positive" else 0):
        raise FixtureError(f"{where}: {value!r} must be a {'positive' if kind == 'positive' else 'non-negative'} integer")
    return value


def _action(document: Any, where: str) -> Action:
    if not isinstance(document, Mapping):
        raise FixtureError(f"{where}: an action is an object")
    try:
        op = Op(str(document.get("op")))
    except ValueError as error:
        raise FixtureError(f"{where}: unknown op {document.get('op')!r}") from error
    allowed, params = ACTION_PARAMS[op], {key: value for key, value in document.items() if key != "op"}
    unknown, missing = set(params) - set(allowed), REQUIRED_PARAMS.get(op, frozenset()) - set(params)
    if unknown or missing:
        raise FixtureError(f"{where}: {op.value} {'unknown params ' + str(sorted(unknown)) if unknown else 'missing params ' + str(sorted(missing))}")
    return Action(op, {key: _param(value, allowed[key], f"{where}.{key}") for key, value in sorted(params.items())})


def _expectation(name: str, value: Any, where: str) -> Any:
    spec = FACTS.get(name)
    if spec is None:
        raise FixtureError(f"{where}: unknown fact {name!r}")
    if value is None:
        if not spec.nullable:
            raise FixtureError(f"{where}: {name} is never null")
        return None
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise FixtureError(f"{where}: {name} expects true or false")
        return value
    if spec.kind == "enum":
        if value not in spec.values:
            raise FixtureError(f"{where}: {name} expects one of {list(spec.values)}")
        return value
    if spec.kind == "int":
        if isinstance(value, Mapping):
            if not value or set(value) - {"min", "max"}:
                raise FixtureError(f"{where}: {name} range takes only min / max")
            bounds = {key: _param(bound, "count", f"{where}.{key}") for key, bound in value.items()}
            if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
                raise FixtureError(f"{where}: {name} min > max")
            if "max" not in bounds and bounds.get("min") == 0:
                raise FixtureError(f"{where}: {name} {{min: 0}} can never fail")
            return dict(sorted(bounds.items()))
        return _param(value, "count", where)
    # list: exact (sorted distinct strings) or includes / excludes
    if isinstance(value, Mapping):
        if not value or set(value) - {"includes", "excludes"}:
            raise FixtureError(f"{where}: {name} takes only includes / excludes")
        parts = {key: _strings(items, f"{where}.{key}") for key, items in value.items()}
        if not all(parts.values()):
            raise FixtureError(f"{where}: {name} includes / excludes lists must not be empty (they could never fail)")
        if set(parts.get("includes", ())) & set(parts.get("excludes", ())):
            raise FixtureError(f"{where}: {name} includes and excludes the same value")
        return dict(sorted(parts.items()))
    return _strings(value, where)


def _strings(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise FixtureError(f"{where}: expects a list of strings")
    if value != sorted(set(value)):
        raise FixtureError(f"{where}: list values must be sorted and distinct")
    return list(value)


def parse_case(document: Any, *, source: str = "<case>") -> EvaluationCase:
    """One golden case, validated against the frozen vocabulary. Raises ``FixtureError`` naming ``source`` and the bad path."""
    if not isinstance(document, Mapping):
        raise FixtureError(f"{source}: a golden case is an object")
    if document.get("schema") != GOLDEN_SCHEMA_VERSION:
        raise FixtureError(f"{source}: schema must be {GOLDEN_SCHEMA_VERSION!r}")
    if set(document) - CASE_KEYS or REQUIRED_CASE_KEYS - set(document):
        raise FixtureError(f"{source}: unknown keys {sorted(set(document) - CASE_KEYS)}, missing keys {sorted(REQUIRED_CASE_KEYS - set(document))}")
    fixture_id, number = document["fixture_id"], document["number"]
    if not isinstance(fixture_id, str) or not fixture_id or fixture_id.strip() != fixture_id:
        raise FixtureError(f"{source}: fixture_id must be a non-empty string")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise FixtureError(f"{source}: number must be a positive integer")
    for key in ("title", "requirement", "focus"):
        if not isinstance(document[key], str) or not document[key].strip():
            raise FixtureError(f"{source}: {key} is required")
    if not document["focus"].startswith(f"{IDENTITY_VERSION}|"):
        raise FixtureError(f"{source}: focus must be a {IDENTITY_VERSION} identity key")
    try:
        category = Category(document["category"])
    except ValueError as error:
        raise FixtureError(f"{source}: unknown category {document['category']!r}") from error
    if document.get("dataset", GOLDEN_DATASET) != GOLDEN_DATASET:
        raise FixtureError(f"{source}: dataset must be {GOLDEN_DATASET!r}")
    runtime = document.get("runtime", {})
    if not isinstance(runtime, Mapping) or set(runtime) - set(RUNTIME_KEYS):
        raise FixtureError(f"{source}: runtime takes only {sorted(RUNTIME_KEYS)}")
    runtime = {key: _param(value, RUNTIME_KEYS[key], f"{source}.runtime.{key}") for key, value in sorted(runtime.items())}
    exclusions = document.get("metric_exclusions", {})
    if not isinstance(exclusions, Mapping) or set(exclusions) - set(STEP_METRICS):
        raise FixtureError(f"{source}: metric_exclusions may name only {list(STEP_METRICS)}")
    if not all(isinstance(reason, str) and reason.strip() for reason in exclusions.values()):
        raise FixtureError(f"{source}: every metric exclusion needs a written reason")
    steps_doc = document["steps"]
    if not isinstance(steps_doc, list) or not steps_doc:
        raise FixtureError(f"{source}: steps must be a non-empty list")
    steps: list[Step] = []
    for index, raw in enumerate(steps_doc):
        where = f"{source}.steps[{index}]"
        if not isinstance(raw, Mapping) or set(raw) - STEP_KEYS or not {"step_id", "actions"} <= set(raw):
            raise FixtureError(f"{where}: a step has step_id, actions and an optional expect")
        step_id = raw["step_id"]
        if not isinstance(step_id, str) or not step_id or step_id in {step.step_id for step in steps}:
            raise FixtureError(f"{where}: step_id must be a unique non-empty string")
        if not isinstance(raw["actions"], list) or not raw["actions"]:
            raise FixtureError(f"{where}: actions must be a non-empty list")
        actions = tuple(_action(action, f"{where}.actions[{n}]") for n, action in enumerate(raw["actions"]))
        expect = None
        if "expect" in raw:
            if not isinstance(raw["expect"], Mapping) or not raw["expect"]:
                raise FixtureError(f"{where}: expect must be a non-empty object")
            expect = ExpectedOutcome(tuple((name, _expectation(name, value, f"{where}.expect.{name}")) for name, value in sorted(raw["expect"].items())))
        steps.append(Step(step_id, actions, expect))
    if not any(step.evaluated for step in steps):
        raise FixtureError(f"{source}: a golden case needs at least one evaluated step (with expect)")
    return EvaluationCase(fixture_id, number, document["title"], document["requirement"], category, document["focus"], tuple(steps),
                          GOLDEN_DATASET, runtime, dict(sorted(exclusions.items())))


def parse_cases(documents: Iterable[tuple[str, Any]]) -> tuple[EvaluationCase, ...]:
    """Several golden cases; duplicate fixture IDs or numbers are refused. Ordered by (number, fixture_id) whatever the input order."""
    cases: list[EvaluationCase] = []
    for source, document in documents:
        case = parse_case(document, source=source)
        if case.fixture_id in {other.fixture_id for other in cases}:
            raise FixtureError(f"{source}: duplicate fixture_id {case.fixture_id!r}")
        if case.number in {other.number for other in cases}:
            raise FixtureError(f"{source}: duplicate number {case.number}")
        cases.append(case)
    return tuple(sorted(cases, key=lambda case: (case.number, case.fixture_id)))


def load_golden_cases(directory: Path = GOLDEN_DIR) -> tuple[EvaluationCase, ...]:
    """Every ``case-*.json`` of ``directory``, validated. The file name must be ``case-<fixture_id>.json``."""
    documents = []
    for path in sorted(directory.glob("case-*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise FixtureError(f"{path.name}: {error}") from error
        if isinstance(document, Mapping) and path.name != f"case-{document.get('fixture_id')}.json":
            raise FixtureError(f"{path.name}: file name must be case-<fixture_id>.json")
        documents.append((path.name, document))
    return parse_cases(documents)


def fixture_digest(cases: Sequence[EvaluationCase]) -> str:
    """sha256 of the canonical JSON of the golden cases: the report names exactly which fixtures it evaluated."""
    text = json.dumps([case.to_dict() for case in sorted(cases, key=lambda case: (case.number, case.fixture_id))], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


# --- canonical state ----------------------------------------------------------------------------------------------------------


def capture(store: ReasoningStore) -> CanonicalState:
    """The canonical state now, content-free: identifiers, statuses, counts, field hashes and grounding codes (``store.evaluation_read``)."""
    rows = canonical_rows(store)
    versions = []
    for row in rows["versions"]:
        document = row["document"]
        confidence = document.get("confidence") if isinstance(document.get("confidence"), Mapping) else {}
        codes: tuple[str, ...] = ()
        if row["change_kind"] == "created":
            codes = grounding_codes(document, row["case_document"], model=row["model"], prompt_version=row["prompt_version"])
        elif row["change_kind"] == "patched":
            case = (update_case(row["case_document"], row["previous_document"], row["evidence_before"], row["evidence_after"])
                    if row["case_document"] is not None and row["previous_document"] is not None else None)
            codes = grounding_codes(document, case, model=row["model"], prompt_version=row["prompt_version"], previous=row["previous_document"])
        versions.append(VersionState(row["result_id"], int(row["version"]), row["change_kind"], row["evidence_fingerprint"], field_hashes(document),
                                     declared_changes(row["update_document"]), confidence.get("level"), codes))
    return CanonicalState(
        cases=tuple(CaseState(r["case_id"], r["identity_key"], r["presence"], r["evidence_fingerprint"], int(r["contradicting"] or 0)) for r in rows["cases"]),
        results=tuple(ResultState(r["result_id"], r["case_id"], int(r["current_version"]), r["lifecycle_status"]) for r in rows["results"]),
        versions=tuple(versions),
        transitions=tuple(TransitionState(r["transition_id"], r["result_id"], int(r["result_version"]), r["from_status"], r["to_status"])
                          for r in rows["transitions"]),
        questions=tuple(QuestionState(r["question_id"], r["case_id"], r["dedup_key"], r["state"]) for r in rows["questions"]),
        calls=tuple(CallState(r["request_id"], r["case_id"], r["purpose"], r["status"], int(r["tokens"])) for r in rows["calls"]),
        refusals=tuple(RefusalState(r["candidate_id"], r["case_id"], tuple(r["error_codes"])) for r in rows["refusals"]),
        work=tuple(WorkState(r["work_item_id"], r["case_id"], r["status"], bool(r["requires_llm"])) for r in rows["work"]),
        injections=tuple(InjectionState(r["injection_id"], r["case_id"], r["purpose"], r["memory_status"], tuple(r["sources"])) for r in rows["injections"]),
        observations=tuple(ObservationState(r["run_id"], r["case_id"], r["action"]) for r in rows["observations"]),
        synced_memory=tuple((r["source_type"], r["source_id"], r["session_key"], r["content_sha256"]) for r in rows["synced_memory"]))


# --- observation --------------------------------------------------------------------------------------------------------------


def _new(rows: Sequence[Any], before: Sequence[Any], key: str) -> list[Any]:
    seen = {getattr(row, key) for row in before}
    return [row for row in rows if getattr(row, key) not in seen]


def _open_result(state: CanonicalState, case_id: str | None) -> ResultState | None:
    rows = [row for row in state.results if row.case_id == case_id and row.lifecycle_status != "superseded"]
    return max(rows, key=lambda row: (row.lifecycle_status in ("new", "active", "updated", "cooling"), row.version, row.result_id), default=None)


def _focus_facts(focus: str, before: CanonicalState, after: CanonicalState) -> dict[str, Any]:
    old_case, case = before.case_for_identity(focus), after.case_for_identity(focus)
    case_id = case.case_id if case else None
    old_result, result = _open_result(before, old_case.case_id if old_case else None), _open_result(after, case_id)
    if result is None:
        identity = "none"
    elif old_result is None:
        identity = "created"
    else:
        identity = "kept" if old_result.result_id == result.result_id else "replaced"
    new_versions = [row for row in _new_versions(before, after) if result is not None and row.result_id == result.result_id]
    current = next((row for row in after.versions if result is not None and row.result_id == result.result_id and row.version == result.version), None)
    seen_obs = {(row.run_id, row.case_id) for row in before.observations}
    actions = [row.action for row in after.observations if row.case_id == case_id and (row.run_id, row.case_id) not in seen_obs]
    closed = {(row.case_id, row.dedup_key) for row in after.questions if row.state in ("answered", "dismissed")}
    calls = [row for row in _new(after.calls, before.calls, "request_id") if row.case_id == case_id and row.purpose in ("analyst", "update")]
    injections = [row for row in _new(after.injections, before.injections, "injection_id") if row.case_id == case_id and row.purpose in ("analyst", "update")]
    return {
        "focus.case_id_stable": None if old_case is None or case is None else (old_case.case_id == case.case_id
                                                                              and old_case.case_id not in identity_splits(before, after)),
        "focus.present": None if case is None else case.presence == "present",
        "focus.gate_action": actions[-1] if actions else None,
        "focus.result": identity,
        "focus.content_versions": sum(1 for row in new_versions if row.change_kind in ("created", "patched", "no_change_review")),
        "focus.change_kinds": sorted({row.change_kind for row in new_versions}),
        "focus.lifecycle": result.lifecycle_status if result is not None else None,
        "focus.confidence": current.confidence if current is not None else None,
        "focus.contradicting_findings": case.contradicting_findings if case is not None else None,
        "focus.open_questions": sum(1 for row in after.questions if row.case_id == case_id and row.state == "open"),
        "focus.questions_opened": sum(1 for row in _new(after.questions, before.questions, "question_id") if row.case_id == case_id and row.state == "open"),
        "focus.reasked_answered": sum(1 for row in after.questions if row.case_id == case_id and row.state == "open"
                                      and (row.case_id, row.dedup_key) in closed),
        "focus.model_calls": len(calls),
        "focus.validation_refusals": sum(1 for row in _new(after.refusals, before.refusals, "candidate_id") if row.case_id == case_id),
        "focus.memory_status": sorted({row.memory_status for row in injections}),
        "focus.context_sources": sorted({source for row in injections for source in row.sources}),
    }


def _new_versions(before: CanonicalState, after: CanonicalState) -> list[VersionState]:
    seen = {(row.result_id, row.version) for row in before.versions}
    return [row for row in after.versions if (row.result_id, row.version) not in seen]


def _pass_facts(passes: Sequence[PassReport]) -> dict[str, Any]:
    ran = [report for report in passes if report.skipped is None]
    last = ran[-1] if ran else None
    return {
        "run.status": last.status if last is not None else None,
        "run.reasons": sorted(set(last.reasons)) if last is not None else [],
        "run.executive_ready": last.executive_ready if last is not None else None,
        "run.passes": len(ran),
        "run.skipped": sorted({str(report.skipped) for report in passes if report.skipped is not None}),
        "run.calls_used": sum(report.calls_used for report in ran),
        "run.admitted": sum(len(report.admitted) for report in ran),
        "run.deferred": sum(len(report.deferred) for report in ran),
        "run.retries": sum(len(report.retries) for report in ran),
        "run.recovered": sum(len(report.recovered) for report in ran),
    }


def _telemetry_facts(telemetry: ReliabilityReport | None) -> dict[str, Any]:
    if telemetry is None:
        return {"telemetry.refused_before_call": 0, "telemetry.corrective_reasks": 0, "telemetry.interrupted_passes": 0,
                "telemetry.retries_created": 0, "telemetry.skipped_unchanged": 0}
    aggregate = telemetry.aggregate
    return {"telemetry.refused_before_call": aggregate.work.refused, "telemetry.corrective_reasks": aggregate.validation.corrective_reasks,
            "telemetry.interrupted_passes": aggregate.orchestration.interrupted_passes,
            "telemetry.retries_created": aggregate.orchestration.retries_created, "telemetry.skipped_unchanged": aggregate.gate.unchanged}


def observe_step(case: EvaluationCase, before: CanonicalState, after: CanonicalState, *, step_id: str, passes: Sequence[PassReport] = (),
                 telemetry: ReliabilityReport | None = None, controls: ProviderControls | None = None) -> StepObservation:
    """The facts and metric counts of one evaluated step: ``before`` / ``after`` are ``capture`` results around it, ``passes`` the
    ``PassReport``s of its orchestration passes in order, ``telemetry`` the 18-C report of its runs, ``controls`` the shared Phase 18-B
    provider controls (for the breaker state)."""
    if step_id not in {step.step_id for step in case.evaluated_steps}:
        raise ValueError(f"{case.fixture_id}: {step_id!r} is not an evaluated step")
    calls = [row for row in _new(after.calls, before.calls, "request_id") if row.purpose in ("analyst", "update")]
    seen_obs = {(row.run_id, row.case_id) for row in before.observations}
    actions = [row.action for row in after.observations if (row.run_id, row.case_id) not in seen_obs]
    new_versions = _new_versions(before, after)
    breaker = controls.snapshot().get("breaker") if controls is not None else None
    injections = [row for row in _new(after.injections, before.injections, "injection_id") if row.purpose in ("analyst", "update")]
    facts: dict[str, Any] = {
        **_pass_facts(passes),
        "circuit.state": breaker["state"] if breaker else None,
        **_telemetry_facts(telemetry),
        "calls.reasoning": len(calls),
        "calls.failed": sum(1 for row in calls if row.status == "failed"),
        **{f"gate.{action}": actions.count(action) for action in ("unchanged", "new", "updated", "disappeared")},
        "work.open": sum(1 for row in after.work if row.requires_llm and row.status in ("pending", "in_progress")),
        "results.created": len(_new(after.results, before.results, "result_id")),
        "versions.content": sum(1 for row in new_versions if row.change_kind in ("created", "patched", "no_change_review")),
        "validation.refusals": len(_new(after.refusals, before.refusals, "candidate_id")),
        "questions.open": sum(1 for row in after.questions if row.state == "open"),
        "memory.degraded_calls": sum(1 for row in injections if row.memory_status in ("degraded", "unavailable")),
        "integrity.duplicates": duplicates(after),
        **_focus_facts(case.focus, before, after),
    }
    assert set(facts) == set(FACTS), sorted(set(facts) ^ set(FACTS))
    return StepObservation(step_id, facts, step_counts(before, after))


# --- checks, metrics, report --------------------------------------------------------------------------------------------------


def matches(expected: Any, observed: Any) -> bool:
    if isinstance(expected, Mapping) and ("min" in expected or "max" in expected):
        return isinstance(observed, int) and expected.get("min", observed) <= observed <= expected.get("max", observed)
    if isinstance(expected, Mapping):
        values = set(observed or ())
        return set(expected.get("includes", ())) <= values and not set(expected.get("excludes", ())) & values
    return bool(expected == observed and type(expected) is type(observed))


def check_case(case: EvaluationCase, observation: EvaluationObservation) -> tuple[CheckResult, ...]:
    """Every expectation of every evaluated step against the observation. A missing step observation fails each of its checks."""
    observed_steps = {step.step_id: step for step in observation.steps}
    results = []
    for step in case.evaluated_steps:
        assert step.expect is not None
        facts = observed_steps[step.step_id].facts if step.step_id in observed_steps else {}
        for name, expected in step.expect.checks:
            value = facts.get(name, "<not observed>")
            results.append(CheckResult(case.fixture_id, step.step_id, name, expected, value, step.step_id in observed_steps and matches(expected, value)))
    return tuple(results)


def compute_metrics(cases: Sequence[EvaluationCase], observations: Sequence[EvaluationObservation],
                    checks: Sequence[CheckResult]) -> tuple[EvaluationMetric, ...]:
    by_id = {observation.fixture_id: observation for observation in observations}
    metrics = []
    for name in STEP_METRICS:
        counts, excluded = [], []
        for case in cases:
            if name in case.metric_exclusions:
                excluded.append(case.fixture_id)
                continue
            evaluated = {step.step_id for step in case.evaluated_steps}
            observation = by_id.get(case.fixture_id)
            counts += [step.counts[name] for step in (observation.steps if observation else ()) if step.step_id in evaluated and name in step.counts]
        metrics.append(EvaluationMetric(name, total(counts), tuple(sorted(excluded))))
    metrics.append(EvaluationMetric("expectation_failure_rate", MetricCount(sum(1 for check in checks if not check.passed), len(checks))))
    return tuple(sorted(metrics, key=lambda metric: METRIC_NAMES.index(metric.name)))


def software_versions() -> dict[str, str]:
    """The versions an evaluation result is only valid for (code under test and the harness itself)."""
    return {"evaluation_schema": EVALUATION_SCHEMA_VERSION, "golden_schema": GOLDEN_SCHEMA_VERSION, "reasoning_package": REASONING_PACKAGE_VERSION,
            "reasoning_contract": CONTRACT_VERSION, "identity": IDENTITY_VERSION, "fingerprint": FINGERPRINT_VERSION, "change_gate": change_gate.GATE_VERSION,
            "engine": engine.ENGINE_VERSION, "analyst_prompt": analyst.ANALYST_PROMPT_VERSION, "update_prompt": updater.UPDATE_PROMPT_VERSION,
            "guardrails": guardrails.VALIDATOR_VERSION, "lifecycle_policy": lifecycle.LIFECYCLE_POLICY_VERSION,
            "run_control": orchestration.POLICY_VERSION, "reliability_metrics": reliability_metrics.METRICS_VERSION, "pinned_model": PINNED_MODEL}


def release_conformance(cases: Sequence[EvaluationCase], thresholds: ThresholdSet, required_numbers: Sequence[int]) -> list[str]:
    """Why a result is not a release result (empty: it is): only the published golden cases, the published release thresholds and the
    full required coverage can PASS — an edited fixture, a laxer threshold set or a narrowed coverage can only FAIL."""
    reasons = []
    if fixture_digest(cases) != PUBLISHED_FIXTURE_DIGEST:
        reasons.append("release: the golden cases differ from the published golden set (PUBLISHED_FIXTURE_DIGEST)")
    if thresholds != release_thresholds():
        reasons.append(f"release: thresholds {thresholds.version!r} are not the published release thresholds")
    if tuple(required_numbers) != REQUIRED_CASE_NUMBERS:
        reasons.append("release: the required coverage is not golden cases 1-20")
    return reasons


def evaluate(cases: Sequence[EvaluationCase], observations: Sequence[EvaluationObservation], *, thresholds: ThresholdSet | None = None,
             environment: Mapping[str, str] | None = None, metadata: Mapping[str, Any] | None = None,
             required_numbers: Sequence[int] = REQUIRED_CASE_NUMBERS) -> EvaluationReport:
    """The report. PASS only when the inputs are the published golden cases and release thresholds (``release_conformance``), every
    required golden case was observed in full, and every release threshold passes (which includes ``expectation_failure_rate`` <= 0:
    every structural expectation met). Pure: equal inputs give an equal ``canonical_json``."""
    thresholds = thresholds or release_thresholds()
    cases = tuple(sorted(cases, key=lambda case: (case.number, case.fixture_id)))
    known = {case.fixture_id for case in cases}
    stray = sorted({observation.fixture_id for observation in observations} - known)
    if stray:
        raise ValueError(f"observations for unknown golden cases {stray}")
    ordered = tuple(sorted(observations, key=lambda observation: [case.fixture_id for case in cases].index(observation.fixture_id)))
    if len({observation.fixture_id for observation in ordered}) != len(ordered):
        raise ValueError("more than one observation for a golden case")
    for observation in ordered:
        if len({step.step_id for step in observation.steps}) != len(observation.steps):
            raise ValueError(f"{observation.fixture_id}: a step is observed more than once")
    checks = tuple(check for case in cases for check in check_case(case, next((o for o in ordered if o.fixture_id == case.fixture_id),
                                                                               EvaluationObservation(case.fixture_id, ()))))
    metrics = compute_metrics(cases, ordered, checks)
    results = evaluate_thresholds(metrics, thresholds)
    observed = {o.fixture_id: {step.step_id for step in o.steps} for o in ordered}
    complete = sorted(case.number for case in cases if {step.step_id for step in case.evaluated_steps} <= observed.get(case.fixture_id, set()))
    missing = sorted(set(required_numbers) - set(complete))
    counts = {metric.name: metric.count for metric in metrics}
    failures = [f"coverage: golden cases {missing} not observed in full"] if missing else []
    failures += release_conformance(cases, thresholds, required_numbers)
    for result in results:
        if not result.passed:
            count = counts[result.threshold.metric]
            value = "no data" if result.no_data else f"{count.numerator}/{count.denominator}"
            failures.append(f"threshold: {result.threshold.metric} {result.threshold.comparator.value} {result.threshold.bound} (value {value})")
    failures += [f"expectation: {check.fixture_id}/{check.step_id} {check.fact}" for check in checks if not check.passed]
    coverage = {"required": list(required_numbers), "observed_in_full": complete, "missing": missing, "fixture_digest": fixture_digest(cases),
                "golden_cases": len(cases), "evaluated_steps": sum(len(case.evaluated_steps) for case in cases), "checks": len(checks)}
    coverage["release_conformant"] = not release_conformance(cases, thresholds, required_numbers)
    passed = not missing and bool(coverage["release_conformant"]) and all(result.passed for result in results)
    return EvaluationReport(passed, cases, ordered, checks, metrics, thresholds, results, coverage, software_versions(),
                            dict(environment or {}), tuple(failures), dict(metadata or {}))
