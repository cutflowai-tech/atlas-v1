"""Fake-provider execution of the Phase 19 golden cases (test support; never a product runner — that is Phase 19-B's).

``run_case(store, case)`` executes every step of a golden case on the real Change Gate, engine, Phase 15 guardrails, Phase 18
orchestration and PostgreSQL, with an offline model (``ScriptedAnalyst``) and offline memory (``FakeHoncho``), and observes each
evaluated step through ``atlas_reasoning.evaluation`` (``capture`` before and after, ``observe_step``). No network, no credentials.

The scenario vocabulary (``evaluation_types.Op`` and friends) is implemented here exactly as documented there; nothing in this file
decides an outcome — it only performs the step and hands the canonical state to the harness.
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable
from typing import Any

import reasoning_snapshots as snapshots
from reasoning_engine_support import rows, times
from reasoning_fakes import ScriptedAnalyst, analyst_answer, update_answer

from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.engine import ENGINE_LOCK_KEY, ReasoningEngine
from atlas_reasoning.enums import WorkStatus
from atlas_reasoning.evaluation import capture, observe_step
from atlas_reasoning.evaluation_types import EvaluationCase, EvaluationObservation, EvidenceVariant, FaultKind, FaultTarget, HumanKind, Op, Step
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.gateway import ReasoningGateway
from atlas_reasoning.manager_notes import ManagerNotes
from atlas_reasoning.provider import ProviderAuthError, ProviderUnavailable
from atlas_reasoning.reasoning_context import HumanContext
from atlas_reasoning.reasoning_input_boundary import ReasoningInput, upstream_finding
from atlas_reasoning.reliability import CircuitBreaker, ProviderControls
from atlas_reasoning.run_control import OrchestrationPolicy, PassReport, RunOrchestrator
from atlas_reasoning.settings import GatewaySettings
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.reliability_metrics import reliability_report
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.teach_atlas import TeachAtlas
from atlas_reasoning.work_priority import prioritize

BOSS = "manager@example.com"


# --- evidence variants (the golden dataset: the synthetic showcase) -----------------------------------------------------------


def _subject(focus: str) -> str:
    parts = focus.split("|")
    if parts[1] != "editor":
        raise ValueError(f"evidence variants that follow the focus need an Editor focus, not {focus}")
    return parts[2]


def _late_rate_row(findings: list[dict[str, Any]], editor: str) -> dict[str, Any]:
    return next(r for r in findings if r["finding_type"] == "change.editor" and r["scope"]["editor_id"] == editor
                and r["statements"][0]["params"].get("measure") == "late_rate")


def _payload(findings: list[dict[str, Any]], snapshot_id: str | None = None) -> ReasoningInput:
    base = snapshots.reasoning_input()
    snapshot = dataclasses.replace(base.snapshot, source_snapshot_id=snapshot_id) if snapshot_id else base.snapshot
    return dataclasses.replace(base, findings=tuple(upstream_finding(row) for row in findings), snapshot=snapshot)


def evidence(variant: EvidenceVariant, focus: str) -> ReasoningInput:
    findings = rows()
    if variant == EvidenceVariant.SHOWCASE:
        return snapshots.reasoning_input()
    if variant == EvidenceVariant.NON_MATERIAL:
        for row in findings:
            row["finding_id"] = f"{row['finding_id']}-renamed"
        return _payload(findings, snapshot_id="golden-non-material")
    if variant == EvidenceVariant.NEW_TOPIC:
        extra = copy.deepcopy(next(r for r in findings if r["finding_type"] == "editor.speed_pattern"))
        extra["scope"]["editor_id"] = "editor-label-99"
        return _payload(findings + [extra])
    editor = _subject(focus)
    if variant in (EvidenceVariant.MATERIAL_CHANGE, EvidenceVariant.MATERIAL_CHANGE_2):
        for statement in _late_rate_row(findings, editor)["statements"]:
            statement["params"]["current"] = 0.8125 if variant == EvidenceVariant.MATERIAL_CHANGE else 0.875
        return _payload(findings)
    if variant == EvidenceVariant.FOCUS_REMOVED:
        return _payload([r for r in findings if r["scope"].get("editor_id") != editor
                         or r["finding_type"] in ("editor.speed_pattern", "contradiction.hidden_risk")])
    if variant == EvidenceVariant.WITHOUT_CONTRADICTION:
        return _payload([r for r in findings if not (r["finding_type"] == "concentration.positive" and r["scope"].get("editor_id") == editor)])
    raise ValueError(variant)


# --- the runtime of one golden case --------------------------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _overclaim(payload: dict[str, Any]) -> dict[str, Any]:
    """An answer claiming ``strong`` confidence (above any ceiling the golden data has): an analyst answer, or for an update request (it
    carries ``previous_result``) a patch of the confidence alone."""
    claim = {"level": "strong", "rationale": "Certain."}
    if "previous_result" in payload:
        return update_answer(payload, change={"confidence": claim})
    answer = analyst_answer(payload)
    answer["confidence"] = claim
    return answer


OUTAGE = (ProviderUnavailable("down"), ProviderUnavailable("down"))     # the attempt and the gateway's one retry
RATIONALES = ("The newest evidence changed the sample.", "The evidence moved again; the level still holds.")


def golden_update(payload: dict[str, Any]) -> dict[str, Any]:
    """A well-behaved update answer: it changes exactly the fields the updater says must change (``fields_requiring_change``), with
    values built only from the case, and otherwise only the confidence rationale (to a text different from the previous one)."""
    fresh = analyst_answer(payload)
    required = list(payload.get("fields_requiring_change") or {})
    change = {name: fresh[name] for name in required}
    if not change:
        previous = payload["previous_result"]["fields"]["confidence"]
        change = {"confidence": {"level": previous["level"], "rationale": RATIONALES[1] if previous["rationale"] == RATIONALES[0] else RATIONALES[0]}}
    return update_answer(payload, change=change)


class GoldenModel(ScriptedAnalyst):
    """``ScriptedAnalyst`` whose unscripted update answers are ``golden_update`` (scripted answers — faults — still come first)."""

    def complete(self, request: Any, *, model: str, timeout: float) -> Any:
        context = request.context
        with self._lock:
            scripted = bool(self._scripts.get(context.case_id or "") or self._scripts.get(context.purpose))
        if not scripted and context.purpose == "update":
            self.script(context.case_id or "", golden_update)
        return super().complete(request, model=model, timeout=timeout)


class GoldenRunner:
    """One golden case on one fresh database: a process's runtime (shared ProviderControls, gateway, engine, human context)."""

    def __init__(self, store: ReasoningStore, case: EvaluationCase) -> None:
        self.store, self.case = store, case
        self.transport = GoldenModel()
        self.clock = _Clock()
        threshold = case.runtime.get("breaker_threshold")
        breaker = CircuitBreaker(threshold, case.runtime.get("breaker_cooldown_seconds", 60), monotonic=self.clock) if threshold else None
        concurrency = case.runtime.get("gateway_concurrency", 4)
        self.controls = ProviderControls(concurrency, breaker=breaker)
        self.honcho = FakeHoncho()
        self.context = HumanContext(store, self.honcho, env={})
        gateway = ReasoningGateway(self.transport, GatewaySettings(max_retries=1, backoff_seconds=0, max_backoff_seconds=0, concurrency=concurrency),
                                   recorder=StoreCallRecorder(store), sleep=lambda seconds: None, controls=self.controls)
        self.engine = ReasoningEngine(store, gateway, context=self.context, retries=case.runtime.get("validation_retries", 1))
        self.notes, self.teach = ManagerNotes(store, self.context.sync), TeachAtlas(store, self.context.sync)
        self.times = iter(times(48))
        self.runs: list[str] = []
        self.decisions: dict[str, str] = {}          # identity key -> case_id of the latest gate

    # --- helpers --------------------------------------------------------------------------------------------------------------

    def _focus_case(self) -> str:
        with self.store.transaction() as tx:
            row = tx._one("SELECT case_id FROM reasoning_cases WHERE identity_key = %s", (self.case.focus,))
        if row is None:
            raise AssertionError(f"{self.case.fixture_id}: focus case not gated yet")
        return str(row["case_id"])

    def _focus_result(self) -> str:
        with self.store.transaction() as tx:
            result = tx.open_result(self._focus_case())
        if result is None:
            raise AssertionError(f"{self.case.fixture_id}: focus case has no open card")
        return result.result_id

    def _targets(self, target: str) -> list[str]:
        if target == FaultTarget.FOCUS:
            return [self._focus_case()]
        if target == FaultTarget.ALL:
            return sorted(set(self.decisions.values()))
        if target == FaultTarget.FIRST_IN_PRIORITY:
            return [prioritize(self.engine.pending_work())[0].case_id]
        return []

    def _orchestrator(self, params: dict[str, Any]) -> RunOrchestrator:
        return RunOrchestrator(self.engine, policy=OrchestrationPolicy(max_calls_per_pass=params.get("budget"), max_attempts=params.get("max_attempts", 3)))

    # --- the vocabulary -------------------------------------------------------------------------------------------------------

    def perform(self, step: Step) -> list[PassReport]:
        passes: list[PassReport] = []
        for action in step.actions:
            params = dict(action.params)
            if action.op == Op.GATE:
                report = run_gate(evidence(EvidenceVariant(params["evidence"]), self.case.focus), self.store, now=next(self.times))
                self.runs.append(report.run_id)
                self.decisions = {decision.identity_key: decision.case_id for decision in report.decisions}
            elif action.op == Op.ORCHESTRATE:
                passes.append(self._orchestrator(params).run(self.runs[-1]))
            elif action.op == Op.ORCHESTRATE_WHILE_BUSY:
                with self.store.session_lock(ENGINE_LOCK_KEY) as held:     # another engine (a concurrent worker) holds the lock
                    assert held
                    passes.append(self._orchestrator({}).run(self.runs[-1]))
            elif action.op == Op.RESUME:
                passes.append(self._orchestrator(params).resume(self.runs[-1]))
            elif action.op == Op.FAULT:
                self._fault(FaultKind(params["kind"]), params["target"], params.get("count", 1))
            elif action.op == Op.HUMAN:
                self._human(HumanKind(params["kind"]))
            elif action.op == Op.CLAIM:
                [item] = [row for row in self.engine.pending_work() if row.case_id in self._targets(params["target"])]
                with self.store.transaction() as tx:
                    tx.set_work_item_status(item.work_item_id, WorkStatus.IN_PROGRESS)
            elif action.op == Op.AGE_CLAIMS:
                with self.store.transaction() as tx:
                    tx._exec("UPDATE reasoning_work_items SET updated_at = now() - make_interval(secs => %s) WHERE status = 'in_progress'",
                             (params["seconds"],))
            elif action.op == Op.ADVANCE_CLOCK:
                self.clock.now += params["seconds"]
            else:  # pragma: no cover - the vocabulary is closed (parse_case)
                raise ValueError(action.op)
        return passes

    def _fault(self, kind: FaultKind, target: str, count: int) -> None:
        if kind == FaultKind.MEMORY_OUTAGE:
            self.honcho.outage()
            return
        if kind == FaultKind.MEMORY_RESTORE:
            self.honcho.restore()
            return
        answers: tuple[Any, ...] | Callable[..., Any]
        for case_id in self._targets(target):
            if kind == FaultKind.PROVIDER_OUTAGE:
                self.transport.script(case_id, *OUTAGE)
            elif kind == FaultKind.PROVIDER_AUTH:
                self.transport.script(case_id, ProviderAuthError("bad key"))
            elif kind == FaultKind.OVERCLAIM:
                answers = tuple(_overclaim for _ in range(count))
                self.transport.script(case_id, *answers)

    def _human(self, kind: HumanKind) -> None:
        editor = _subject(self.case.focus)
        if kind == HumanKind.NOTE:
            self.notes.create(self._focus_result(), "Class B work moved to another Editor this month.", author=BOSS)
        elif kind == HumanKind.ANSWER:
            with self.store.transaction() as tx:
                question = tx._one("SELECT question_id FROM atlas_questions WHERE case_id = %s AND state = 'open' ORDER BY dedup_key LIMIT 1",
                                   (self._focus_case(),))
            assert question is not None, "the focus card has no open question to answer"
            self.context.questions.answer(question["question_id"], "Yes, Class B work went to another Editor.", author=BOSS)
        elif kind == HumanKind.TEACHING:
            self.teach.create(body="This Editor covers urgent Class B work.", scope_type="editor", scope_id=editor, teaching_type="context",
                              validity_mode="until_changed", author=BOSS)
        elif kind == HumanKind.EXPIRED_TEACHING:
            self.teach.create(body="This Editor was on leave in January.", scope_type="editor", scope_id=editor, teaching_type="temporary_situation",
                              validity_mode="date_range", valid_from="2026-01-01", valid_until="2026-01-31", author=BOSS)

    # --- one golden case ------------------------------------------------------------------------------------------------------

    def run(self) -> EvaluationObservation:
        observed = []
        for step in self.case.steps:
            runs_before = len(self.runs)
            before = capture(self.store) if step.evaluated else None
            passes = self.perform(step)
            if before is None:
                continue
            step_runs = sorted(set(self.runs[runs_before:] or self.runs[-1:]))
            telemetry = reliability_report(self.store, step_runs) if step_runs else None
            observed.append(observe_step(self.case, before, capture(self.store), step_id=step.step_id, passes=passes, telemetry=telemetry,
                                         controls=self.controls))
        return EvaluationObservation(self.case.fixture_id, tuple(observed))


def run_case(store: ReasoningStore, case: EvaluationCase) -> EvaluationObservation:
    return GoldenRunner(store, case).run()
