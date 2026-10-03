"""Phase 18-B (``REV/18`` #1, #10): provider reliability and budget controls — configured limits, the per-run call budget, shared
provider capacity, the circuit breaker, size refusals and failure preservation. Offline transports only; no network, ever."""

from __future__ import annotations

import logging
import threading
import unittest
from unittest import mock

import reasoning_snapshots as snapshots
from reasoning_db import fresh_database, requires_db
from reasoning_engine_support import changed_case, changed_rows, first_result, new_case, payload_with, times
from reasoning_executive_support import ScriptedExecutive
from reasoning_fakes import ScriptedAnalyst, gateway

from atlas_reasoning import analyst, executive, updater
from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.engine import ReasoningEngine
from atlas_reasoning.executive import Decision, ExecutiveSynthesizer, executive_input
from atlas_reasoning.fake_provider import FakeError, FakeProvider, FakeReply
from atlas_reasoning.gateway import MemoryRecorder, ReasoningGateway
from atlas_reasoning.provider import (
    CallContext,
    Message,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderRateLimited,
    ProviderRequest,
    ProviderTimeout,
    ProviderTruncated,
    ProviderUnavailable,
    StructuredOutputError,
)
from atlas_reasoning.reliability import (
    OUTAGE_CLASSES,
    Admission,
    BreakerState,
    BudgetDecision,
    BudgetExhausted,
    CallBudget,
    CircuitBreaker,
    CircuitOpen,
    ExecutiveBudgetExhausted,
    ProviderControls,
)
from atlas_reasoning.settings import PINNED_MODEL, GatewaySettings, ReasoningConfigError, ReliabilitySettings, model_identity_matches, reliability_settings
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.executive import ExecutiveStore
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.structured import schema_output

SECRET = "sk-or-v1-reliabilitysecret0123456789"
OK = {"type": "object", "additionalProperties": False, "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}


def request(purpose: str = "analyst", case_id: str | None = None, text: str = "prompt text that must never be logged") -> ProviderRequest:
    return ProviderRequest(CallContext(purpose=purpose, case_id=case_id), (Message("user", text),), schema_output("ok", OK))


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def gw(fake: FakeProvider, *, retries: int = 0, controls: ProviderControls | None = None, budget: CallBudget | None = None,
       recorder: MemoryRecorder | None = None, sleeps: list[float] | None = None, concurrency: int = 4) -> ReasoningGateway:
    return ReasoningGateway(fake, GatewaySettings(max_retries=retries, backoff_seconds=1, max_backoff_seconds=5, concurrency=concurrency),
                            recorder=recorder or MemoryRecorder(), sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
                            jitter=lambda: 0.0, controls=controls, budget=budget, secrets=(SECRET,))


class SettingsTests(unittest.TestCase):
    def test_defaults_are_backward_compatible(self):
        settings = reliability_settings({})
        self.assertEqual(settings, ReliabilitySettings())
        self.assertIsNone(settings.run_call_budget)                       # no run budget unless configured
        self.assertEqual((settings.max_input_chars, settings.max_output_tokens), (analyst.MAX_INPUT_CHARS, analyst.MAX_OUTPUT_TOKENS))
        self.assertEqual((settings.executive_max_input_chars, settings.executive_max_output_tokens),
                         (executive.MAX_INPUT_CHARS, executive.MAX_OUTPUT_TOKENS))

    def test_every_value_is_configured_and_bounded(self):
        env = {"ATLAS_REASONING_RUN_CALL_BUDGET": "40", "ATLAS_REASONING_EXECUTIVE_CALL_BUDGET": "2", "ATLAS_REASONING_MAX_INPUT_CHARS": "50000",
               "ATLAS_REASONING_MAX_OUTPUT_TOKENS": "8000", "ATLAS_REASONING_EXECUTIVE_MAX_INPUT_CHARS": "60000",
               "ATLAS_REASONING_EXECUTIVE_MAX_OUTPUT_TOKENS": "6000", "ATLAS_REASONING_BREAKER_THRESHOLD": "3",
               "ATLAS_REASONING_BREAKER_COOLDOWN_SECONDS": "30"}
        self.assertEqual(reliability_settings(env), ReliabilitySettings(40, 2, 50_000, 8_000, 60_000, 6_000, 3, 30.0))
        for name, bad in (("ATLAS_REASONING_RUN_CALL_BUDGET", "0"), ("ATLAS_REASONING_EXECUTIVE_CALL_BUDGET", "11"),
                          ("ATLAS_REASONING_MAX_INPUT_CHARS", "100"), ("ATLAS_REASONING_MAX_OUTPUT_TOKENS", "999999"),
                          ("ATLAS_REASONING_BREAKER_THRESHOLD", "0"), ("ATLAS_REASONING_BREAKER_COOLDOWN_SECONDS", "x")):
            with self.subTest(name=name), self.assertRaises(ReasoningConfigError) as caught:
                reliability_settings({name: bad})
            self.assertNotIn(SECRET, str(caught.exception))

    def test_settings_never_hold_a_credential(self):
        self.assertFalse(any("key" in name or "secret" in name or "token" == name for name in ReliabilitySettings().to_dict()))


class BudgetTests(unittest.TestCase):
    def test_budget_is_checked_before_the_call_and_refusal_costs_nothing(self):
        fake, recorder = FakeProvider(default=FakeReply({"ok": True})), MemoryRecorder()
        budget = CallBudget(2)
        gateway_ = gw(fake, budget=budget, recorder=recorder)
        gateway_.call(request())
        gateway_.call(request())
        with self.assertRaises(BudgetExhausted) as caught:
            gateway_.call(request())
        self.assertFalse(caught.exception.retryable)
        self.assertEqual((len(fake.requests), len(recorder.calls)), (2, 2))          # no provider request, no llm_calls record
        self.assertEqual(budget.snapshot(), {"limit": 2, "used": 2, "executive_limit": None, "executive_used": 0,
                                             "refused": {"budget_exhausted": 1, "executive_budget_exhausted": 0}})

    def test_executive_budget_is_separate_and_also_charges_the_run(self):
        fake = FakeProvider(default=FakeReply({"ok": True}))
        budget = CallBudget(3, executive_limit=1)
        gateway_ = gw(fake, budget=budget)
        gateway_.call(request("executive"))
        with self.assertRaises(ExecutiveBudgetExhausted):
            gateway_.call(request("executive"))
        gateway_.call(request("analyst"))                                         # case reasoning is not limited by the executive budget
        gateway_.call(request("update"))
        with self.assertRaises(BudgetExhausted) as caught:                         # the run budget covers both
            gateway_.call(request("analyst"))
        self.assertNotIsInstance(caught.exception, ExecutiveBudgetExhausted)
        self.assertEqual((budget.used, budget.snapshot()["executive_used"], len(fake.requests)), (3, 1, 3))

    def test_transport_retries_of_one_logical_call_cost_one_unit(self):
        fake = FakeProvider(default=FakeReply({"ok": True}))
        fake.script("analyst", FakeError(ProviderTimeout("slow")), FakeError(ProviderUnavailable("busy", status=503)))
        budget = CallBudget(5)
        gw(fake, retries=3, budget=budget).call(request())
        self.assertEqual((budget.used, len(fake.requests)), (1, 3))

    def test_budget_is_thread_safe_and_exact(self):
        budget = CallBudget(37)
        results: list[BudgetDecision] = []
        lock = threading.Lock()

        def take():
            for _ in range(20):
                decision = budget.acquire("analyst")
                with lock:
                    results.append(decision)

        threads = [threading.Thread(target=take) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count(BudgetDecision.ALLOWED), 37)
        self.assertEqual(budget.used, 37)
        self.assertEqual(budget.remaining, 0)

    def test_with_budget_shares_everything_else(self):
        fake = FakeProvider(default=FakeReply({"ok": True}))
        controls = ProviderControls(2)
        base = gw(fake, controls=controls)
        view = base.with_budget(CallBudget(1))
        self.assertIs(view.transport, base.transport)
        self.assertIs(view._slots, base._slots)
        self.assertIsNone(base.budget)
        base.call(request()), base.call(request())                                 # the base gateway stays unbudgeted
        view.call(request())
        with self.assertRaises(BudgetExhausted):
            view.call(request())


class ConcurrencyTests(unittest.TestCase):
    def test_gateways_sharing_controls_share_one_bound(self):
        fake = FakeProvider(default=FakeReply({"ok": True}, delay=0.05))
        controls = ProviderControls(2)
        reasoning, synthesis = gw(fake, controls=controls, concurrency=2), gw(fake, controls=controls, concurrency=2)

        def burst(gateway_: ReasoningGateway, purpose: str) -> None:
            gateway_.call_many([request(purpose, case_id=f"{purpose}-{i}") for i in range(6)])

        threads = [threading.Thread(target=burst, args=(reasoning, "analyst")), threading.Thread(target=burst, args=(synthesis, "executive"))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(fake.requests), 12)
        self.assertLessEqual(fake.peak_in_flight, 2)

    def test_without_shared_controls_each_gateway_has_its_own_bound(self):
        fake = FakeProvider(default=FakeReply({"ok": True}, delay=0.05))
        a, b = gw(fake, concurrency=2), gw(fake, concurrency=2)
        threads = [threading.Thread(target=lambda g=g: g.call_many([request(case_id=f"c{i}") for i in range(4)])) for g in (a, b)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertLessEqual(fake.peak_in_flight, 4)              # documented scope: a bound per gateway unless controls are shared


class RetryTests(unittest.TestCase):
    def test_timeouts_retry_with_capped_backoff_then_fail(self):
        fake, sleeps = FakeProvider(default=FakeError(ProviderTimeout("slow"))), []
        with self.assertRaises(ProviderTimeout):
            gw(fake, retries=4, sleeps=sleeps).call(request())
        self.assertEqual(len(fake.requests), 5)
        self.assertEqual(sleeps, [1, 2, 4, 5])                   # doubling, capped at max_backoff (5)

    def test_retry_after_is_honoured_but_capped(self):
        fake, sleeps = FakeProvider(default=FakeReply({"ok": True})), []
        fake.script("analyst", FakeError(ProviderRateLimited("slow down", status=429, retry_after=3600)))
        gw(fake, retries=2, sleeps=sleeps).call(request())
        self.assertEqual(sleeps, [5])

    def test_non_retryable_failures_are_not_retried(self):
        for error in (ProviderAuthError("no", status=401), ProviderBadRequest("bad", status=400), ProviderTruncated("cut")):
            fake = FakeProvider(default=FakeError(error))
            with self.subTest(error=error.error_class), self.assertRaises(type(error)):
                gw(fake, retries=3).call(request())
            self.assertEqual(len(fake.requests), 1)

    def test_refusals_are_never_retried(self):
        fake = FakeProvider(default=FakeReply({"ok": True}))
        gateway_ = gw(fake, retries=5, budget=CallBudget(0))
        with self.assertRaises(BudgetExhausted):
            gateway_.call(request())
        self.assertEqual(fake.requests, [])


class BreakerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.breaker = CircuitBreaker(3, 30, monotonic=self.clock)
        self.controls = ProviderControls(4, breaker=self.breaker)
        self.fake = FakeProvider(default=FakeError(ProviderUnavailable("down", status=503)))
        self.recorder = MemoryRecorder()
        self.gateway = gw(self.fake, retries=1, controls=self.controls, recorder=self.recorder)

    def fail(self, times_: int) -> None:
        for _ in range(times_):
            with self.assertRaises(ProviderUnavailable):
                self.gateway.call(request())

    def test_repeated_outages_open_the_circuit_and_it_blocks_calls(self):
        self.fail(2)
        self.assertEqual(self.breaker.state, BreakerState.CLOSED)
        self.fail(1)
        self.assertEqual(self.breaker.state, BreakerState.OPEN)
        sent, recorded = len(self.fake.requests), len(self.recorder.calls)
        self.assertEqual(sent, 6)                                         # 3 logical calls × (1 + 1 retry): counted per logical call
        for _ in range(5):
            with self.assertRaises(CircuitOpen) as caught:
                self.gateway.call(request())
            self.assertFalse(caught.exception.retryable)
        self.assertEqual((len(self.fake.requests), len(self.recorder.calls)), (sent, recorded))

    def test_half_open_probe_success_recovers(self):
        self.fail(3)
        self.clock.now = 29.9
        with self.assertRaises(CircuitOpen):
            self.gateway.call(request())
        self.clock.now = 30.0
        self.assertEqual(self.breaker.state, BreakerState.HALF_OPEN)
        self.fake.default = FakeReply({"ok": True})
        self.assertEqual(self.gateway.call(request()).parsed, {"ok": True})
        self.assertEqual(self.breaker.state, BreakerState.CLOSED)
        self.assertEqual(self.breaker.snapshot()["consecutive_failures"], 0)

    def test_half_open_probe_failure_reopens_for_another_cooldown(self):
        self.fail(3)
        self.clock.now = 31
        self.fail(1)                                                      # the probe
        self.assertEqual(self.breaker.state, BreakerState.OPEN)
        self.clock.now = 60
        with self.assertRaises(CircuitOpen):
            self.gateway.call(request())
        self.clock.now = 61
        self.assertEqual(self.breaker.state, BreakerState.HALF_OPEN)
        self.assertEqual(self.breaker.snapshot()["times_opened"], 2)

    def test_only_one_probe_at_a_time(self):
        self.fail(3)
        self.clock.now = 30
        first = self.breaker.admit()
        self.assertTrue(first.probe)
        with self.assertRaises(CircuitOpen):
            self.breaker.admit()
        self.breaker.release(first)                                       # a refused-by-budget probe gives its slot back
        self.assertTrue(self.breaker.admit().probe)

    def test_a_budget_refusal_never_holds_the_probe(self):
        self.fail(3)
        self.clock.now = 30
        with self.assertRaises(BudgetExhausted):
            self.gateway.with_budget(CallBudget(0)).call(request())
        self.assertTrue(self.breaker.admit().probe)                       # still available

    def test_non_outage_failures_and_validation_refusals_do_not_trip_it(self):
        for error in (ProviderBadRequest("bad", status=400), ProviderTruncated("cut")):
            self.fake.default = FakeError(error)
            for _ in range(5):
                with self.assertRaises(type(error)):
                    self.gateway.call(request())
        self.fake.default = FakeReply("not json")                         # invalid structured output, retried, then failed: not an outage
        for _ in range(5):
            with self.assertRaises(StructuredOutputError):
                self.gateway.call(request())
        self.fake.default = FakeReply({"ok": True})                       # answers a validator would refuse are provider successes
        for _ in range(5):
            self.gateway.call(request())
        self.assertEqual(self.breaker.state, BreakerState.CLOSED)
        self.assertEqual(self.breaker.snapshot()["times_opened"], 0)

    def test_a_non_outage_answer_resets_the_count(self):
        self.fail(2)
        self.fake.default = FakeError(ProviderBadRequest("bad", status=400))
        with self.assertRaises(ProviderBadRequest):
            self.gateway.call(request())
        self.fake.default = FakeError(ProviderUnavailable("down", status=503))
        self.fail(2)
        self.assertEqual(self.breaker.state, BreakerState.CLOSED)

    def test_outage_classes_are_provider_failures_only(self):
        self.assertTrue({"timeout", "rate_limited", "provider_unavailable", "network_error"} <= OUTAGE_CLASSES)
        self.assertFalse(OUTAGE_CLASSES & {"bad_request", "content_filtered", "truncated", "invalid_structured_output", "internal_error",
                                           "budget_exhausted", "circuit_open", "configuration"})

    def test_breaker_state_is_bounded_and_content_free(self):
        for _ in range(50):
            self.breaker.record(Admission(), "timeout")
        snapshot = self.breaker.snapshot()
        self.assertEqual(set(snapshot), {"state", "consecutive_failures", "threshold", "cooldown_seconds", "times_opened"})
        self.assertNotIn("prompt", repr(vars(self.breaker)))
        self.assertNotIn(SECRET, repr(vars(self.breaker)))

    def test_logs_are_safe(self):
        with self.assertLogs("atlas_reasoning", level="WARNING") as logs:
            self.fail(3)
            with self.assertRaises(CircuitOpen):
                self.gateway.call(request(text=f"secret prompt {SECRET}"))
        text = "\n".join(logs.output)
        self.assertIn("circuit open", text)
        self.assertIn("error_class=circuit_open", text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("prompt text", text)
        self.assertNotIn("secret prompt", text)


class SizeTests(unittest.TestCase):
    def test_oversized_case_input_is_refused_never_truncated(self):
        payload = {"x": "y" * 30_000}
        self.assertEqual(len(analyst.bounded_json(payload)), 30_008)               # default limit: accepted, whole
        with mock.patch.dict("os.environ", {"ATLAS_REASONING_MAX_INPUT_CHARS": "20000"}), self.assertRaises(analyst.CaseTooLarge) as caught:
            analyst.bounded_json(payload)
        self.assertIn("20000", str(caught.exception))
        fake = FakeProvider(default=FakeReply({"ok": True}))
        with mock.patch.dict("os.environ", {"ATLAS_REASONING_MAX_INPUT_CHARS": "20000"}), \
                mock.patch.object(analyst, "analyst_input", return_value=payload), self.assertRaises(analyst.CaseTooLarge):
            gw(fake).call(analyst.analyst_request(new_case()))                      # refused while building the request: no call
        self.assertEqual(fake.requests, [])

    def test_configured_limits_reach_every_request(self):
        case = new_case()
        env = {"ATLAS_REASONING_MAX_OUTPUT_TOKENS": "7000", "ATLAS_REASONING_EXECUTIVE_MAX_OUTPUT_TOKENS": "5000",
               "ATLAS_REASONING_MAX_INPUT_CHARS": "900000"}
        with mock.patch.dict("os.environ", env):
            self.assertEqual(analyst.analyst_request(case).max_output_tokens, 7000)
            self.assertEqual(analyst.max_input_chars(), 900_000)
            previous = first_result(case)
            changed = changed_case(previous)
            self.assertEqual(updater.update_request(previous, changed).max_output_tokens, 7000)
            self.assertEqual(executive.executive_request(executive_input([]), run_id="run_" + "1" * 32).max_output_tokens, 5000)
        self.assertEqual(analyst.analyst_request(case).max_output_tokens, analyst.MAX_OUTPUT_TOKENS)     # defaults unchanged

    def test_oversized_executive_input_is_refused(self):
        from reasoning_executive_support import standard_rows

        with mock.patch.dict("os.environ", {"ATLAS_REASONING_EXECUTIVE_MAX_INPUT_CHARS": "20000"}), \
                mock.patch.object(executive, "canonical_json", side_effect=lambda value: "x" * 20_001), self.assertRaises(executive.InputTooLarge):
            executive_input(standard_rows())

    def test_an_oversized_output_is_a_non_retryable_truncation(self):
        fake = FakeProvider(default=FakeError(ProviderTruncated("finish_reason=length")))
        breaker = CircuitBreaker(1, 30)
        with self.assertRaises(ProviderTruncated):
            gw(fake, retries=3, controls=ProviderControls(2, breaker=breaker)).call(request())
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(breaker.state, BreakerState.CLOSED)              # a truncation is not an outage


class IdentityTests(unittest.TestCase):
    def test_phase15_live_verified_model_identity_is_unchanged(self):
        self.assertTrue(model_identity_matches(PINNED_MODEL, PINNED_MODEL))
        self.assertTrue(model_identity_matches(PINNED_MODEL, f"{PINNED_MODEL}-20260709"))
        for other in (f"{PINNED_MODEL}-pro", f"{PINNED_MODEL}:batch", "openai/gpt-5.6", f"{PINNED_MODEL}-2026-07-09"):
            self.assertFalse(model_identity_matches(PINNED_MODEL, other), other)
        fake = FakeProvider(default=FakeReply({"ok": True}, model=f"{PINNED_MODEL}-pro"))
        response = gw(fake, controls=ProviderControls(2, breaker=CircuitBreaker(1, 1))).call(request())
        self.assertEqual(response.model, f"{PINNED_MODEL}-pro")             # reported as answered; the guardrails refuse the substitution


@requires_db
class FailurePreservationTests(unittest.TestCase):
    """Budget and breaker refusals fail only the affected work; canonical results and the brief stay as they were."""

    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.analyst = ScriptedAnalyst()
        self.clock = Clock()
        self.breaker = CircuitBreaker(2, 30, monotonic=self.clock)
        self.controls = ProviderControls(4, breaker=self.breaker)
        self.base = ReasoningGateway(self.analyst, GatewaySettings(max_retries=0, backoff_seconds=0, max_backoff_seconds=0, concurrency=4),
                                     recorder=StoreCallRecorder(self.store), sleep=lambda s: None, controls=self.controls)
        self.t = times(10)
        self.runs = 0

    def run_snapshot(self, payload=None, budget: CallBudget | None = None, gateway_: ReasoningGateway | None = None):
        report = run_gate(payload or snapshots.reasoning_input(), self.store, now=self.t[self.runs])
        self.runs += 1
        engine = ReasoningEngine(self.store, (gateway_ or self.base).with_budget(budget), retries=1)
        return report, engine.process_run(report.run_id)

    def results(self):
        with self.store.transaction() as tx:
            return {row["result_id"]: (row["current_version"], row["lifecycle_status"])
                    for row in tx._all("SELECT result_id, current_version, lifecycle_status FROM reasoning_results")}

    def test_budget_exhaustion_fails_only_the_unfunded_items_and_keeps_results(self):
        _, outcome = self.run_snapshot(budget=CallBudget(3))
        done = [row for row in outcome.outcomes if row.status == "done"]
        refused = [row for row in outcome.outcomes if row.error == "provider:budget_exhausted"]
        self.assertEqual(len(done), 3)
        self.assertEqual(len(refused), len(outcome.outcomes) - 3)
        self.assertTrue(refused)
        calls = len(self.analyst.requests)
        self.assertEqual(calls, 3)                                        # nothing sent past the budget
        before = self.results()
        _, again = self.run_snapshot(payload_with(changed_rows()), budget=CallBudget(0))
        self.assertEqual(len(self.analyst.requests), calls)
        self.assertEqual(self.results().keys(), before.keys())
        self.assertTrue(all(row.error in ("provider:budget_exhausted", None) for row in again.outcomes))
        for result_id, (version, _) in before.items():                    # every valid card kept its content version
            self.assertGreaterEqual(self.results()[result_id][0], version)

    def test_an_outage_opens_the_circuit_and_stops_sending(self):
        self.analyst.script("analyst", *[ProviderUnavailable("down", status=503)] * 100)
        _, outcome = self.run_snapshot()
        errors = [row.error for row in outcome.outcomes]
        self.assertEqual(self.breaker.state, BreakerState.OPEN)
        self.assertGreaterEqual(errors.count("provider:provider_unavailable"), 2)
        self.assertLessEqual(len(self.analyst.requests), 2 + 3)              # the threshold, plus calls already in flight when it opened
        self.assertEqual(errors.count("provider:circuit_open"), len(errors) - len(self.analyst.requests))
        self.assertEqual(self.results(), {})                                 # nothing half-written

    def test_an_open_circuit_keeps_every_valid_result(self):
        self.run_snapshot()
        before = {result_id: self.store.get_result(result_id).to_dict() for result_id in self.results()}
        for _ in range(2):
            self.breaker.record(self.breaker.admit(), "timeout")
        sent = len(self.analyst.requests)
        _, outcome = self.run_snapshot(payload_with(changed_rows()))
        self.assertEqual(len(self.analyst.requests), sent)                  # no provider request while open
        self.assertTrue([row for row in outcome.outcomes if row.error == "provider:circuit_open"])
        for result_id, document in before.items():                           # content of every card unchanged (lifecycle may move)
            now = self.store.get_result(result_id).to_dict()
            self.assertEqual({k: v for k, v in now.items() if k in analyst.PATCHABLE_FIELDS},
                             {k: v for k, v in document.items() if k in analyst.PATCHABLE_FIELDS})

    def test_executive_budget_and_unchanged_input(self):
        report, _ = self.run_snapshot()
        executive_store = ExecutiveStore(self.store)
        model = ScriptedExecutive()
        executive_gw = gateway(model, recorder=StoreCallRecorder(self.store), retries=0)
        budget = CallBudget(None, executive_limit=1)
        synthesizer = ExecutiveSynthesizer(executive_store, executive_gw, retries=1, budget=budget)
        first = synthesizer.synthesize(report.run_id)
        self.assertEqual((first.decision, first.llm_calls), (Decision.SYNTHESIZED, 1))
        again = synthesizer.synthesize(report.run_id)                      # same input: preserved, zero calls, no budget unit
        self.assertEqual((again.decision, again.llm_calls), (Decision.UNCHANGED, 0))
        self.assertEqual(budget.snapshot()["executive_used"], 1)
        second, _ = self.run_snapshot()                                             # new -> active: synthesis needed, executive budget spent
        before = executive_store.current_brief()
        refused = synthesizer.synthesize(second.run_id)
        self.assertEqual((refused.decision, refused.failure, refused.llm_calls), (Decision.FAILED, "provider:executive_budget_exhausted", 0))
        self.assertEqual(executive_store.current_brief().to_dict(), before.to_dict())
        self.assertEqual(len(model.requests), 1)
        row = executive_store.synthesis_runs(second.run_id)[-1]
        self.assertEqual((row["llm_calls"], row["failure"], row["request_ids"]), (0, "provider:executive_budget_exhausted", []))

    def test_executive_circuit_open_preserves_the_brief(self):
        report, _ = self.run_snapshot()
        executive_store = ExecutiveStore(self.store)
        model = ScriptedExecutive()
        executive_gw = ReasoningGateway(model, GatewaySettings(max_retries=0, backoff_seconds=0, max_backoff_seconds=0),
                                        recorder=StoreCallRecorder(self.store), sleep=lambda s: None, controls=self.controls)
        synthesizer = ExecutiveSynthesizer(executive_store, executive_gw, retries=1)
        synthesizer.synthesize(report.run_id)
        before = executive_store.current_brief()
        for _ in range(2):
            self.breaker.record(self.breaker.admit(), "timeout")           # the shared breaker opened (e.g. by case reasoning)
        second, _ = self.run_snapshot()
        refused = synthesizer.synthesize(second.run_id)
        self.assertEqual((refused.decision, refused.failure, refused.llm_calls), (Decision.FAILED, "provider:circuit_open", 0))
        self.assertEqual(executive_store.current_brief().to_dict(), before.to_dict())


if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()
