"""The Reasoning V3 evaluation runner (Phase 19-B, ``REV/19`` #5, #6): executes the published Phase 19-A golden cases and hands what
Reasoning V3 did to the frozen Phase 19-A harness.

    result = run_evaluation(offline_plan(os.environ))          # offline: the deterministic offline model, PostgreSQL, no network
    result.code, result.passed, result.exit_code, result.to_json()

Division of labour. Phase 19-A (frozen: ``evaluation``, ``evaluation_types``, ``evaluation_metrics``, ``evaluation_thresholds``,
``store.evaluation_read``, the golden cases and ``release-thresholds-v1``) defines what is observed, every metric, every threshold and the
report. This module only **performs** each scenario step on the real Change Gate, ``ReasoningEngine`` with the Phase 15 guardrails,
Phase 18 ``RunOrchestrator`` / ``ProviderControls`` and PostgreSQL, then calls ``capture`` / ``observe_step`` / ``evaluate``. It computes no
metric and decides no outcome; the canonical ``EvaluationReport`` is Phase 19-A's, unchanged.

Every term of the closed scenario vocabulary (``evaluation_types.Op``, evidence variants, faults, human context, runtime keys) is implemented
here exactly as ``evaluation_types`` documents it. External systems are deterministic stand-ins: the model (``evaluation_offline_model``
offline, or the explicit live transport of ``evaluation_live``), contextual memory (``fake_honcho.FakeHoncho``, always), the breaker's
monotonic clock. The golden dataset is the synthetic showcase read through ``reasoning_input_boundary.showcase_documents``.

Result codes (``ResultCode``; stable, machine-readable; never a traceback on stdout):

=================================  ====  ==================================================================================
PASS                               0     the evaluation is a release PASS (Phase 19-A ``EvaluationReport.passed``)
EVALUATION_FAILED                  1     a valid evaluation that FAILs: a threshold, a structural expectation, coverage or
                                         release conformance (the report says which)
EVALUATION_CONFIGURATION_INVALID   2     the evaluation could not start: unsafe or missing database, invalid golden case or
                                         threshold file, invalid live configuration
EVALUATION_AUDIT_INCONSISTENCY     3     the canonical audit trail is inconsistent (a refused candidate without its provider call;
                                         an impossible metric count, numerator > denominator): no metric value is produced
EVALUATION_BUDGET_EXHAUSTED        4     live mode only: the operator's call budget ran out; the evaluation stopped safely
EVALUATION_INTERNAL_ERROR          5     an unexpected failure (a bug): reported by the CLI, never a PASS
=================================  ====  ==================================================================================

Only ``PASS`` exits 0. An audit inconsistency is never repaired (no clipping, no dropped row, no extra denominator): the run stops with
``EVALUATION_AUDIT_INCONSISTENCY`` and the offending case and step.

Database safety: the runner drops and re-creates the ``atlas_reasoning`` schema once per golden case, so it only ever runs on a
**disposable test database** (the database name contains ``test``, the rule of ``tests/reasoning_db``), never on the database
``ATLAS_REASONING_DATABASE_URL`` names, and only through ``ATLAS_REASONING_EVALUATION_DATABASE_URL`` (or ``_FILE``).
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlsplit

from atlas_reasoning import settings
from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.engine import ENGINE_LOCK_KEY, ReasoningEngine
from atlas_reasoning.enums import WorkStatus
from atlas_reasoning.evaluation import capture, evaluate, load_golden_cases, observe_step
from atlas_reasoning.evaluation_offline_model import OfflineModel, overclaim
from atlas_reasoning.evaluation_types import (
    GOLDEN_DATASET,
    REQUIRED_CASE_NUMBERS,
    EvaluationCase,
    EvaluationObservation,
    EvaluationReport,
    EvidenceVariant,
    FaultKind,
    FaultTarget,
    HumanKind,
    Op,
    Step,
    ThresholdSet,
)
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.gateway import ReasoningGateway
from atlas_reasoning.manager_notes import ManagerNotes
from atlas_reasoning.provider import ProviderAuthError, ProviderUnavailable
from atlas_reasoning.reasoning_context import HumanContext
from atlas_reasoning.reasoning_input_boundary import ReasoningInput, build_reasoning_input, showcase_documents, upstream_finding
from atlas_reasoning.reliability import CircuitBreaker, ProviderControls
from atlas_reasoning.run_control import OrchestrationPolicy, PassReport, RunOrchestrator
from atlas_reasoning.settings import GatewaySettings
from atlas_reasoning.store import evaluation_audit, evaluation_scenario
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.db import Database, DatabaseError, redact_url
from atlas_reasoning.store.reliability_metrics import reliability_report
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.teach_atlas import TeachAtlas
from atlas_reasoning.work_priority import prioritize

RUNNER_SCHEMA = "reasoning-evaluation-run-v1"
RUNNER_VERSION = "evaluation-runner-v1"
EVALUATION_DATABASE_ENV = "ATLAS_REASONING_EVALUATION_DATABASE_URL"
EVALUATION_DATABASE_FILE_ENV = "ATLAS_REASONING_EVALUATION_DATABASE_URL_FILE"
MANAGER = "manager@example.com"
# The "invalid metric count" refusal of the frozen Phase 19-A ``evaluation_types.MetricCount`` (numerator > denominator, or negative).
_INVALID_METRIC_COUNT = "invalid metric count"
# A disposable database names itself: ``test`` as a word of its name (``atlas_reasoning_test``, ``eval_test2``), never ``latest``.
_TEST_NAME = re.compile(r"(^|[_-])tests?([_-]|[0-9]|$)")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


class ResultCode(StrEnum):
    PASS = "PASS"
    EVALUATION_FAILED = "EVALUATION_FAILED"
    EVALUATION_CONFIGURATION_INVALID = "EVALUATION_CONFIGURATION_INVALID"
    EVALUATION_AUDIT_INCONSISTENCY = "EVALUATION_AUDIT_INCONSISTENCY"
    EVALUATION_BUDGET_EXHAUSTED = "EVALUATION_BUDGET_EXHAUSTED"
    EVALUATION_INTERNAL_ERROR = "EVALUATION_INTERNAL_ERROR"


EXIT_CODES: Mapping[ResultCode, int] = {ResultCode.PASS: 0, ResultCode.EVALUATION_FAILED: 1, ResultCode.EVALUATION_CONFIGURATION_INVALID: 2,
                                        ResultCode.EVALUATION_AUDIT_INCONSISTENCY: 3, ResultCode.EVALUATION_BUDGET_EXHAUSTED: 4,
                                        ResultCode.EVALUATION_INTERNAL_ERROR: 5}


class EvaluationConfigurationError(ValueError):
    """The evaluation cannot start safely (database, golden cases, thresholds, live configuration). Messages never carry a secret."""


class EvaluationRuntimeError(Exception):
    """A golden step could not be performed because Reasoning V3 did not reach the state the step needs (no open card, no question to
    answer, no pending work to claim): a failed evaluation (``EVALUATION_FAILED``, no report), never a configuration problem."""


class EvaluationInternalError(RuntimeError):
    """The evaluation broke after it started (for example the database went away mid-run): ``EVALUATION_INTERNAL_ERROR``."""


class AuditInconsistency(Exception):
    """The canonical audit trail of a step is inconsistent; the evaluation stops without producing a metric value."""

    def __init__(self, kind: str, fixture_id: str, step_id: str, detail: str) -> None:
        super().__init__(f"{kind}: {fixture_id}/{step_id}: {detail}")
        self.kind, self.fixture_id, self.step_id, self.detail = kind, fixture_id, step_id, detail

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "fixture_id": self.fixture_id, "step_id": self.step_id, "detail": self.detail}


class EvaluationBudgetExhausted(Exception):
    """Live mode: the operator's call budget is spent; the evaluation stopped before any further provider call."""


# --- the result -------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunnerResult:
    """What one evaluation run produced. ``report`` is the frozen Phase 19-A report (None when the run stopped before one existed)."""

    code: ResultCode
    report: EvaluationReport | None = None
    failures: tuple[str, ...] = ()
    audit: Mapping[str, str] | None = None
    mode: str = "offline"
    budget: Mapping[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return self.code == ResultCode.PASS and self.report is not None and self.report.passed

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.code]

    def to_dict(self) -> dict[str, Any]:
        canonical = self.report.canonical_json() if self.report is not None else None
        return {"schema": RUNNER_SCHEMA, "runner": RUNNER_VERSION, "mode": self.mode, "result": "PASS" if self.passed else "FAIL",
                "code": self.code.value, "exit_code": self.exit_code, "failures": list(self.failures), "audit": dict(self.audit) if self.audit else None,
                "budget": dict(self.budget) if self.budget else None,
                "report_sha256": hashlib.sha256(canonical.encode()).hexdigest() if canonical is not None else None,
                "report": json.loads(canonical) if canonical is not None else None}

    def to_json(self) -> str:
        """Deterministic: key-sorted, no timestamps. Equal evaluations give byte-equal output."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def report_result(report: EvaluationReport, *, mode: str = "offline", budget: Mapping[str, Any] | None = None) -> RunnerResult:
    """A complete evaluation: PASS only when the Phase 19-A report passes (published cases, thresholds and coverage 1-20 included)."""
    return RunnerResult(ResultCode.PASS if report.passed else ResultCode.EVALUATION_FAILED, report, tuple(report.failures), mode=mode, budget=budget)


# --- the disposable evaluation database -----------------------------------------------------------------------------------------


def _target(url: str) -> dict[str, str]:
    """The connection target libpq will use for ``url`` (its own parser: query parameters such as ``?dbname=`` or ``?host=`` override
    the path and authority). Refuses anything whose target is not fully stated in the URL itself."""
    try:
        if urlsplit(url).scheme not in ("postgresql", "postgres"):
            raise EvaluationConfigurationError("the evaluation database must be a postgresql:// URL")
        target = evaluation_scenario.connection_target(url)
    except (EvaluationConfigurationError, ImportError):
        raise
    except Exception:  # noqa: BLE001 - any parse failure (the driver's ProgrammingError, ValueError) is an unusable URL; the URL is not echoed
        raise EvaluationConfigurationError("the evaluation database URL cannot be parsed") from None
    if {"service", "servicefile"} & set(target):
        raise EvaluationConfigurationError("an evaluation database URL must not use a libpq service (the target must be explicit)")
    return target


def _same_database(left: Mapping[str, str], right: Mapping[str, str]) -> bool:
    """Conservative: the same database name, and hosts / ports that are equal or not stated (libpq would then use its defaults). Every
    local address (a Unix socket directory, localhost, a loopback address) counts as the same host."""
    def host(target: Mapping[str, str]) -> str:
        value = target.get("hostaddr") or target.get("host") or ""
        return "local" if value.startswith("/") or value.lower() in _LOCAL_HOSTS else value.lower()

    a, b = host(left), host(right)
    ports = left.get("port", "5432"), right.get("port", "5432")
    return left.get("dbname") == right.get("dbname") and (a == b or not a or not b) and ports[0] == ports[1]


def check_disposable(url: str, env: Mapping[str, str]) -> str:
    """``url`` when it names a disposable test database (the database name, as libpq resolves it, contains ``test``) that is not the
    canonical Reasoning V3 database; otherwise ``EvaluationConfigurationError``. The runner drops this database's schema once per case."""
    target = _target(url)
    if not _TEST_NAME.search(target.get("dbname", "")):
        raise EvaluationConfigurationError(f"refusing {redact_url(url)}: an evaluation database name must contain the word 'test' "
                                           "(e.g. atlas_reasoning_eval_test; it is reset per case)")
    production = settings.secret_value(env, settings.DATABASE_URL_ENV, settings.DATABASE_URL_FILE_ENV, required=False)
    if production:
        try:
            canonical = _target(production)
        except EvaluationConfigurationError:
            raise EvaluationConfigurationError(f"refusing {redact_url(url)}: {settings.DATABASE_URL_ENV} cannot be compared with it") from None
        if _same_database(target, canonical):
            raise EvaluationConfigurationError(f"refusing {redact_url(url)}: it is the database {settings.DATABASE_URL_ENV} names")
    return url


def evaluation_database_url(env: Mapping[str, str]) -> str:
    try:
        url = settings.secret_value(env, EVALUATION_DATABASE_ENV, EVALUATION_DATABASE_FILE_ENV)
    except settings.ReasoningConfigError as error:
        raise EvaluationConfigurationError(str(error)) from None
    assert url is not None
    return check_disposable(url, env)


def fresh_database(url: str) -> Database:
    """An empty, fully migrated Reasoning V3 schema on the (already checked) disposable database."""
    return evaluation_scenario.reset_schema(url)


# --- the golden dataset ------------------------------------------------------------------------------------------------------------


def gate_times(count: int) -> list[str]:
    """The fixed ``now`` of each Change Gate run of a case (the golden driver's clock)."""
    return [f"2026-09-{28 + i // 24:02d}T{i % 24:02d}:10:00Z" for i in range(count)]


def _subject(focus: str) -> str:
    parts = focus.split("|")
    if parts[1] != "editor":
        raise EvaluationRuntimeError(f"evidence variants that follow the focus need an Editor focus, not {focus}")
    return parts[2]


def _late_rate_row(findings: list[dict[str, Any]], editor: str) -> dict[str, Any]:
    return next(r for r in findings if r["finding_type"] == "change.editor" and r["scope"]["editor_id"] == editor
                and r["statements"][0]["params"].get("measure") == "late_rate")


class ShowcaseDataset:
    """The ``showcase-v1`` golden dataset and its evidence variants (``evaluation_types.EvidenceVariant``)."""

    name = GOLDEN_DATASET

    def __init__(self) -> None:
        self._documents = showcase_documents()

    def _payload(self, findings: list[dict[str, Any]], snapshot_id: str | None = None) -> ReasoningInput:
        intelligence, publication, profiles = self._documents
        base = build_reasoning_input(intelligence=intelligence, publication=publication, profiles=profiles)
        snapshot = dataclasses.replace(base.snapshot, source_snapshot_id=snapshot_id) if snapshot_id else base.snapshot
        return dataclasses.replace(base, findings=tuple(upstream_finding(row) for row in findings), snapshot=snapshot)

    def evidence(self, variant: EvidenceVariant, focus: str) -> ReasoningInput:
        intelligence, publication, profiles = self._documents
        findings = copy.deepcopy(intelligence["findings"])
        if variant == EvidenceVariant.SHOWCASE:
            return build_reasoning_input(intelligence=intelligence, publication=publication, profiles=profiles)
        if variant == EvidenceVariant.NON_MATERIAL:
            for row in findings:
                row["finding_id"] = f"{row['finding_id']}-renamed"
            return self._payload(findings, snapshot_id="golden-non-material")
        if variant == EvidenceVariant.NEW_TOPIC:
            extra = copy.deepcopy(next(r for r in findings if r["finding_type"] == "editor.speed_pattern"))
            extra["scope"]["editor_id"] = "editor-label-99"
            return self._payload(findings + [extra])
        editor = _subject(focus)
        if variant in (EvidenceVariant.MATERIAL_CHANGE, EvidenceVariant.MATERIAL_CHANGE_2):
            for statement in _late_rate_row(findings, editor)["statements"]:
                statement["params"]["current"] = 0.8125 if variant == EvidenceVariant.MATERIAL_CHANGE else 0.875
            return self._payload(findings)
        if variant == EvidenceVariant.FOCUS_REMOVED:
            return self._payload([r for r in findings if r["scope"].get("editor_id") != editor
                                  or r["finding_type"] in ("editor.speed_pattern", "contradiction.hidden_risk")])
        if variant == EvidenceVariant.WITHOUT_CONTRADICTION:
            return self._payload([r for r in findings if not (r["finding_type"] == "concentration.positive" and r["scope"].get("editor_id") == editor)])
        raise EvaluationRuntimeError(f"unknown evidence variant {variant!r}")


# --- the model side ---------------------------------------------------------------------------------------------------------------


class FaultableTransport(Protocol):
    """A provider ``Transport`` that also accepts queued faults (``evaluation_offline_model.ScriptedTransport``)."""

    provider_name: str

    def script(self, key: str, *answers: Any) -> Any: ...

    def complete(self, request: Any, *, model: str, timeout: float) -> Any: ...


@dataclass(frozen=True)
class ModelSetup:
    """How one golden case talks to its model: a fresh transport, gateway limits (concurrency comes from the case), and the gateway's
    sleep and secrets. ``exhausted`` reports a spent live budget (offline: never)."""

    transport: FaultableTransport
    gateway_settings: GatewaySettings
    sleep: Callable[[float], None] = lambda seconds: None
    secrets: tuple[str, ...] = field(default=(), repr=False)
    exhausted: Callable[[], bool] = lambda: False


def offline_model(case: EvaluationCase) -> ModelSetup:
    """The deterministic offline model with the golden driver's gateway limits (one retry, no backoff)."""
    return ModelSetup(OfflineModel(), GatewaySettings(max_retries=1, backoff_seconds=0, max_backoff_seconds=0,
                                                      concurrency=case.runtime.get("gateway_concurrency", 4)))


class _Clock:
    """The circuit breaker's monotonic clock; ``advance_clock`` moves it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


StepHook = Callable[[ReasoningStore, EvaluationCase, Step], None]


# --- one golden case ------------------------------------------------------------------------------------------------------------


class CaseRunner:
    """One golden case on one fresh database: one process's runtime (shared ProviderControls, gateway, engine, human context)."""

    def __init__(self, store: ReasoningStore, case: EvaluationCase, *, dataset: ShowcaseDataset, model: ModelSetup,
                 step_hook: StepHook | None = None) -> None:
        self.store, self.case, self.dataset, self.model, self.step_hook = store, case, dataset, model, step_hook
        self.transport = model.transport
        self.clock = _Clock()
        threshold = case.runtime.get("breaker_threshold")
        breaker = CircuitBreaker(threshold, case.runtime.get("breaker_cooldown_seconds", 60), monotonic=self.clock) if threshold else None
        self.controls = ProviderControls(model.gateway_settings.concurrency, breaker=breaker)
        self.honcho = FakeHoncho()          # contextual memory is always the offline stand-in: never a real Honcho workspace
        self.context = HumanContext(store, self.honcho, env={})
        gateway = ReasoningGateway(self.transport, model.gateway_settings, recorder=StoreCallRecorder(store), sleep=model.sleep,
                                   secrets=model.secrets, controls=self.controls)
        self.engine = ReasoningEngine(store, gateway, context=self.context, retries=case.runtime.get("validation_retries", 1))
        self.notes, self.teach = ManagerNotes(store, self.context.sync), TeachAtlas(store, self.context.sync)
        self.times: Iterator[str] = iter(gate_times(48))
        self.runs: list[str] = []
        self.decisions: dict[str, str] = {}

    # --- helpers --------------------------------------------------------------------------------------------------------------

    def _focus_case(self) -> str:
        case_id = evaluation_scenario.case_id_for(self.store, self.case.focus)
        if case_id is None:
            raise EvaluationRuntimeError(f"{self.case.fixture_id}: the focus case is not gated yet")
        return case_id

    def _focus_result(self) -> str:
        with self.store.transaction() as tx:
            result = tx.open_result(self._focus_case())
        if result is None:
            raise EvaluationRuntimeError(f"{self.case.fixture_id}: the focus case has no open card")
        return result.result_id

    def _targets(self, target: str) -> list[str]:
        if target == FaultTarget.FOCUS:
            return [self._focus_case()]
        if target == FaultTarget.ALL:
            return sorted(set(self.decisions.values()))
        if target == FaultTarget.FIRST_IN_PRIORITY:
            pending = prioritize(self.engine.pending_work())
            if not pending:
                raise EvaluationRuntimeError(f"{self.case.fixture_id}: no pending work for first_in_priority")
            return [pending[0].case_id]
        return []

    def _orchestrator(self, params: Mapping[str, Any]) -> RunOrchestrator:
        return RunOrchestrator(self.engine, policy=OrchestrationPolicy(max_calls_per_pass=params.get("budget"), max_attempts=params.get("max_attempts", 3)))

    def _latest_run(self) -> str:
        if not self.runs:
            raise EvaluationRuntimeError(f"{self.case.fixture_id}: an orchestration step before any gate")
        return self.runs[-1]

    # --- the vocabulary -------------------------------------------------------------------------------------------------------

    def perform(self, step: Step) -> list[PassReport]:
        passes: list[PassReport] = []
        for action in step.actions:
            params = dict(action.params)
            if action.op == Op.GATE:
                report = run_gate(self.dataset.evidence(EvidenceVariant(params["evidence"]), self.case.focus), self.store, now=next(self.times))
                self.runs.append(report.run_id)
                self.decisions = {decision.identity_key: decision.case_id for decision in report.decisions}
            elif action.op == Op.ORCHESTRATE:
                passes.append(self._orchestrator(params).run(self._latest_run()))
            elif action.op == Op.ORCHESTRATE_WHILE_BUSY:
                with self.store.session_lock(ENGINE_LOCK_KEY) as held:     # another engine (a concurrent worker) holds the lock
                    if not held:
                        raise EvaluationRuntimeError(f"{self.case.fixture_id}: could not take the engine lock to simulate a busy engine")
                    passes.append(self._orchestrator({}).run(self._latest_run()))
            elif action.op == Op.RESUME:
                passes.append(self._orchestrator(params).resume(self._latest_run()))
            elif action.op == Op.FAULT:
                self._fault(FaultKind(params["kind"]), params["target"], params.get("count", 1))
            elif action.op == Op.HUMAN:
                self._human(HumanKind(params["kind"]))
            elif action.op == Op.CLAIM:
                items = [row for row in self.engine.pending_work() if row.case_id in self._targets(params["target"])]
                if len(items) != 1:
                    raise EvaluationRuntimeError(f"{self.case.fixture_id}: claim expects exactly one pending item, found {len(items)}")
                with self.store.transaction() as tx:
                    tx.set_work_item_status(items[0].work_item_id, WorkStatus.IN_PROGRESS)    # claimed by a worker that then dies
            elif action.op == Op.AGE_CLAIMS:
                evaluation_scenario.age_claims(self.store, params["seconds"])
            elif action.op == Op.ADVANCE_CLOCK:
                self.clock.now += params["seconds"]
            else:  # pragma: no cover - the vocabulary is closed (evaluation.parse_case refuses anything else)
                raise EvaluationRuntimeError(f"unknown op {action.op!r}")
            if self.model.exhausted():           # live: stop before an action that needs what the refused calls never produced
                raise EvaluationBudgetExhausted(f"{self.case.fixture_id}/{step.step_id}: the live call budget is spent")
        return passes

    def _fault(self, kind: FaultKind, target: str, count: int) -> None:
        if kind == FaultKind.MEMORY_OUTAGE:
            self.honcho.outage()
            return
        if kind == FaultKind.MEMORY_RESTORE:
            self.honcho.restore()
            return
        for case_id in self._targets(target):
            if kind == FaultKind.PROVIDER_OUTAGE:
                attempts = self.model.gateway_settings.max_retries + 1      # the outage covers the attempt and every gateway retry
                self.transport.script(case_id, *(ProviderUnavailable("down") for _ in range(attempts)))
            elif kind == FaultKind.PROVIDER_AUTH:
                self.transport.script(case_id, ProviderAuthError("credential refused"))
            elif kind == FaultKind.OVERCLAIM:
                self.transport.script(case_id, *(overclaim for _ in range(count)))

    def _human(self, kind: HumanKind) -> None:
        editor = _subject(self.case.focus)
        if kind == HumanKind.NOTE:
            self.notes.create(self._focus_result(), "Class B work moved to another Editor this month.", author=MANAGER)
        elif kind == HumanKind.ANSWER:
            question = evaluation_scenario.first_open_question(self.store, self._focus_case())
            if question is None:
                raise EvaluationRuntimeError(f"{self.case.fixture_id}: the focus card has no open question to answer")
            self.context.questions.answer(question, "Yes, Class B work went to another Editor.", author=MANAGER)
        elif kind == HumanKind.TEACHING:
            self.teach.create(body="This Editor covers urgent Class B work.", scope_type="editor", scope_id=editor, teaching_type="context",
                              validity_mode="until_changed", author=MANAGER)
        elif kind == HumanKind.EXPIRED_TEACHING:
            self.teach.create(body="This Editor was on leave in January.", scope_type="editor", scope_id=editor, teaching_type="temporary_situation",
                              validity_mode="date_range", valid_from="2026-01-01", valid_until="2026-01-31", author=MANAGER)

    # --- observation (with the audit boundary) ----------------------------------------------------------------------------------

    def _audit(self, step: Step) -> None:
        """Refuse an inconsistent audit trail before any metric is counted: every refused candidate must have its provider call."""
        orphans = evaluation_audit.refusals_without_call(self.store)
        if orphans:
            raise AuditInconsistency("refusal_without_call", self.case.fixture_id, step.step_id,
                                     f"{len(orphans)} refused candidate(s) without their provider call")

    def _observe(self, step: Step, before: Any, passes: Sequence[PassReport], step_runs: Sequence[str]) -> Any:
        telemetry = reliability_report(self.store, step_runs) if step_runs else None
        after = capture(self.store)
        try:
            return observe_step(self.case, before, after, step_id=step.step_id, passes=passes, telemetry=telemetry, controls=self.controls)
        except ValueError as error:
            # The frozen Phase 19-A ``MetricCount`` refuses an impossible count (numerator > denominator, or negative). That is an
            # inconsistent canonical state, reported as such; any other ValueError is a bug and propagates.
            if str(error).startswith(_INVALID_METRIC_COUNT):
                raise AuditInconsistency("invalid_metric_count", self.case.fixture_id, step.step_id, str(error)) from None
            raise

    def run(self) -> EvaluationObservation:
        observed = []
        for step in self.case.steps:
            runs_before = len(self.runs)
            before = capture(self.store) if step.evaluated else None
            passes = self.perform(step)
            if self.step_hook is not None:
                self.step_hook(self.store, self.case, step)
            if self.model.exhausted():
                raise EvaluationBudgetExhausted(f"{self.case.fixture_id}/{step.step_id}: the live call budget is spent")
            self._audit(step)
            if before is None:
                continue
            step_runs = sorted(set(self.runs[runs_before:] or self.runs[-1:]))
            observed.append(self._observe(step, before, passes, step_runs))
        return EvaluationObservation(self.case.fixture_id, tuple(observed))


# --- the evaluation ---------------------------------------------------------------------------------------------------------------

ModelFactory = Callable[[EvaluationCase], ModelSetup]


@dataclass
class EvaluationPlan:
    """What to evaluate. Defaults are the release evaluation: every published golden case, the published thresholds, coverage 1-20."""

    database_url: str = field(repr=False)
    cases: Sequence[EvaluationCase] | None = None
    case_ids: Sequence[str] = ()
    thresholds: ThresholdSet | None = None
    required_numbers: Sequence[int] = REQUIRED_CASE_NUMBERS
    model: ModelFactory = offline_model
    mode: str = "offline"
    environment: Mapping[str, str] = field(default_factory=dict)
    step_hook: StepHook | None = None
    budget_snapshot: Callable[[], Mapping[str, Any]] | None = None


def select_cases(plan: EvaluationPlan) -> tuple[tuple[EvaluationCase, ...], list[EvaluationCase]]:
    """The published cases (every one is part of the report) and the selected ones to execute."""
    published = tuple(plan.cases) if plan.cases is not None else load_golden_cases()
    if plan.case_ids:
        unknown = sorted(set(plan.case_ids) - {case.fixture_id for case in published})
        if unknown:
            raise EvaluationConfigurationError(f"unknown golden case(s) {unknown}")
    return published, [case for case in published if not plan.case_ids or case.fixture_id in plan.case_ids]


def observe_cases(plan: EvaluationPlan, cases: Sequence[EvaluationCase]) -> list[EvaluationObservation]:
    """Execute ``cases`` (one fresh database each) and return their observations. Raises ``AuditInconsistency`` /
    ``EvaluationBudgetExhausted`` at the first inconsistent or unaffordable step."""
    check_disposable(plan.database_url, os.environ)      # every schema reset goes through the guard, however the plan was built
    dataset = ShowcaseDataset()
    observations = []
    for case in cases:
        store = ReasoningStore(fresh_database(plan.database_url))
        observations.append(CaseRunner(store, case, dataset=dataset, model=plan.model(case), step_hook=plan.step_hook).run())
    return observations


def run_evaluation(plan: EvaluationPlan) -> RunnerResult:
    """Execute the golden cases and evaluate them. Returns a ``RunnerResult`` for every evaluation outcome (PASS, FAIL, audit
    inconsistency, live budget exhausted); raises ``EvaluationConfigurationError`` / ``evaluation_types.FixtureError`` when the evaluation
    cannot start, and lets an unexpected exception (a bug) propagate: the CLI reports it as ``EVALUATION_INTERNAL_ERROR``."""
    published, selected = select_cases(plan)
    environment = {"dataset": GOLDEN_DATASET, "mode": plan.mode, "runner": RUNNER_VERSION, **plan.environment}

    def budget() -> Mapping[str, Any] | None:
        return plan.budget_snapshot() if plan.budget_snapshot is not None else None

    check_disposable(plan.database_url, os.environ)
    Database(plan.database_url).connect().close()      # an unreachable database is a configuration problem (DatabaseError) ...
    try:
        observations = observe_cases(plan, selected)
    except DatabaseError as error:                     # ... one that fails after the evaluation started is not
        raise EvaluationInternalError(f"the evaluation database failed mid-run: {error}") from None
    except EvaluationRuntimeError as failure:
        return RunnerResult(ResultCode.EVALUATION_FAILED, failures=(f"runtime: {failure}",), mode=plan.mode, budget=budget())
    except AuditInconsistency as inconsistency:
        return RunnerResult(ResultCode.EVALUATION_AUDIT_INCONSISTENCY, failures=(f"audit: {inconsistency}",), audit=inconsistency.to_dict(),
                            mode=plan.mode, budget=budget())
    except EvaluationBudgetExhausted as exhausted:
        return RunnerResult(ResultCode.EVALUATION_BUDGET_EXHAUSTED, failures=(f"budget: {exhausted}",), mode=plan.mode, budget=budget())
    report = evaluate(published, observations, thresholds=plan.thresholds, environment=environment, required_numbers=plan.required_numbers)
    return report_result(report, mode=plan.mode, budget=budget())


def offline_plan(env: Mapping[str, str], *, case_ids: Sequence[str] = ()) -> EvaluationPlan:
    """The offline release evaluation on the disposable database ``ATLAS_REASONING_EVALUATION_DATABASE_URL`` names."""
    return EvaluationPlan(database_url=evaluation_database_url(env), case_ids=tuple(case_ids), environment={"provider": "offline-model"})
