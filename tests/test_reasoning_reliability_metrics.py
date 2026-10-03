"""Phase 18-C reliability telemetry (``REV/18`` #8): the pure metrics model (no database) and the metrics of the real pipeline on
PostgreSQL (Change Gate → engine → Phase 15 guardrails → executive synthesis), with an offline model only. No network, ever."""

from __future__ import annotations

import contextlib
import io
import json
import os
import random
import unittest
from unittest import mock

import reasoning_snapshots as snapshots
from reasoning_db import TEST_DB_ENV, fresh_database, requires_db, test_database_url
from reasoning_engine_support import DEADLINE_12, changed_rows, payload_with, times
from reasoning_executive_support import ScriptedExecutive
from reasoning_fakes import ScriptedAnalyst, analyst_answer, gateway

from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.engine import ReasoningEngine
from atlas_reasoning.enums import WorkStatus
from atlas_reasoning.executive import ExecutiveSynthesizer
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.gateway import ReasoningGateway
from atlas_reasoning.provider import ProviderUnavailable
from atlas_reasoning.reasoning_context import HumanContext
from atlas_reasoning.reliability_metrics import METRICS_VERSION, Backlog, LatencyMetrics, RunRows, build_report
from atlas_reasoning.reliability_report import main as report_main
from atlas_reasoning.settings import GatewaySettings
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.executive import ExecutiveStore
from atlas_reasoning.store.reliability_metrics import reliability_report
from atlas_reasoning.store.repository import NotFound, ReasoningStore

RUN_A, RUN_B = "run_" + "a" * 32, "run_" + "b" * 32
REFUSED_TEXT = "Ahmed is lazy and should be fired."
# Keys that would mean content leaked into telemetry.
CONTENT_KEYS = {"content", "messages", "prompt", "response", "candidate", "rejected_candidate", "violations", "document", "case_document",
                "body", "statement", "title", "interpretation", "memory_context", "manager_context", "selected", "api_key", "password"}


def call(purpose="analyst", *, status="succeeded", attempts=1, latency=100, tokens=(1000, 400), work_item="wi_1", error=None):
    return {"request_id": f"req_{random.random()}", "work_item_id": work_item, "purpose": purpose, "status": status,
            "error_class": error if status == "failed" else None, "attempts": attempts, "latency_ms": latency,
            "input_tokens": tokens[0] if status == "succeeded" else None, "output_tokens": tokens[1] if status == "succeeded" else None}


def work(item, status="done", *, has_call=True, error_class=None, requires_llm=True, kind="new_result"):
    return {"work_item_id": item, "kind": kind, "status": status, "requires_llm": requires_llm, "error_class": error_class, "has_call": has_call}


def run(run_id=RUN_A, started="2026-09-28T00:10:00+00:00"):
    return {"run_id": run_id, "status": "gated", "started_at": started, "gated_at": started, "finished_at": None, "wall_ms": None}


def keys(value):
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys(item)}
    return set()


class MetricsModelTests(unittest.TestCase):
    """The pure model: the same rows always give the same numbers."""

    def test_successful_run(self):
        rows = RunRows(run(), calls=(call(work_item="wi_1"), call(work_item="wi_2", latency=300)),
                       work=(work("wi_1"), work("wi_2"), work("wi_3", requires_llm=False, kind="lifecycle", has_call=False)),
                       observations=(("new", 2), ("unchanged", 5)), versions=(("created", 2),), memory=(("available", 2),))
        metrics = build_report([rows]).run(RUN_A).to_dict()
        total = metrics["provider_calls"]["total"]
        self.assertEqual((total["logical_calls"], total["attempts"], total["retries"], total["succeeded"], total["failed"]), (2, 2, 0, 2, 0))
        self.assertEqual((metrics["work"]["llm_work_items"], metrics["work"]["lifecycle_work_items"], metrics["work"]["new_results"]), (2, 1, 2))
        self.assertEqual((metrics["gate"]["skipped_unchanged"], metrics["gate"]["observed_cases"]), (5, 7))
        self.assertEqual(metrics["status_inputs"]["committed_versions"], 2)
        self.assertFalse(metrics["memory"]["degraded"])

    def test_retries_attempts_and_logical_calls(self):
        rows = RunRows(run(), calls=(call(attempts=3, work_item="wi_1"), call(attempts=1, work_item="wi_2"),
                                     call(status="failed", attempts=2, work_item="wi_3", error="rate_limited")))
        total = build_report([rows]).aggregate.provider.total
        self.assertEqual((total.logical_calls, total.attempts, total.retries, total.retried_calls), (3, 6, 3, 2))
        self.assertEqual((total.failed, dict(total.failures_by_class)), (1, {"rate_limited": 1}))

    def test_token_aggregation_counts_unknown_usage(self):
        rows = RunRows(run(), calls=(call(tokens=(1200, 300)), call(tokens=(800, 100), work_item="wi_2"),
                                     call(status="failed", error="timeout", work_item="wi_3"),
                                     call("executive", tokens=(5000, 2000), work_item=None)))
        provider = build_report([rows]).aggregate.provider
        self.assertEqual((provider.total.input_tokens, provider.total.output_tokens, provider.total.calls_without_usage), (7000, 2400, 1))
        self.assertEqual(provider.to_dict()["total"]["total_tokens"], 9400)
        self.assertEqual((provider.purpose("executive").input_tokens, provider.purpose("analyst").output_tokens), (5000, 400))

    def test_latency_aggregation_is_integer_and_nearest_rank(self):
        latency = LatencyMetrics.of([400, 100, 300, 200, 1000])
        self.assertEqual(latency.to_dict(), {"total_ms": 2000, "max_ms": 1000, "mean_ms": 400, "p50_ms": 300, "p95_ms": 1000})
        self.assertEqual(LatencyMetrics.of([7]).to_dict(), {"total_ms": 7, "max_ms": 7, "mean_ms": 7, "p50_ms": 7, "p95_ms": 7})
        self.assertEqual(LatencyMetrics.of([1, 2]).mean_ms, 1)       # floor, never a float
        # The aggregate is computed from the union of the runs' calls, not by averaging per-run statistics.
        a = RunRows(run(RUN_A), calls=tuple(call(latency=10, work_item=f"wi_a{i}") for i in range(9)))
        b = RunRows(run(RUN_B, "2026-09-29T00:10:00+00:00"), calls=(call(latency=1000, work_item="wi_b"),))
        self.assertEqual(build_report([a, b]).aggregate.provider.total.latency.to_dict(),
                         {"total_ms": 1090, "max_ms": 1000, "mean_ms": 109, "p50_ms": 10, "p95_ms": 1000})

    def test_validation_failure_and_corrective_reasks(self):
        rows = RunRows(run(), calls=(call(work_item="wi_1"), call(work_item="wi_1"), call("review", work_item="wi_1"), call(work_item="wi_2")),
                       work=(work("wi_1", "failed", error_class="validation"), work("wi_2")),
                       refusals=({"work_item_id": "wi_1", "purpose": "analyst", "attempt": 1, "error_codes": ("UNSUPPORTED_PEOPLE_CLAIM",)},
                                 {"work_item_id": "wi_1", "purpose": "analyst", "attempt": 2,
                                  "error_codes": ("UNSUPPORTED_PEOPLE_CLAIM", "UNSUPPORTED_NUMBER")}),
                       versions=(("created", 1),))
        metrics = build_report([rows]).run(RUN_A)
        self.assertEqual(metrics.validation.to_dict(), {"refused_candidates": 2, "corrective_reasks": 1, "failed_work_items": 1,
                                                        "codes": {"UNSUPPORTED_NUMBER": 1, "UNSUPPORTED_PEOPLE_CLAIM": 2}})
        inputs = metrics.status_inputs
        self.assertEqual((inputs.failed_work_items, inputs.validation_failed_work_items, inputs.provider_failed_work_items,
                          inputs.other_failed_work_items, inputs.committed_versions), (1, 1, 0, 0, 1))

    def test_unchanged_zero_call_and_executive_preserve(self):
        rows = RunRows(run(), observations=(("unchanged", 12),),
                       executive=({"decision": "unchanged", "failure_class": None, "llm_calls": 0},))
        metrics = build_report([rows]).run(RUN_A).to_dict()
        self.assertEqual((metrics["provider_calls"]["total"]["logical_calls"], metrics["gate"]["skipped_unchanged"], metrics["work"]["llm_work_items"]),
                         (0, 12, 0))
        self.assertEqual((metrics["executive"]["unchanged_zero_call"], metrics["executive"]["model_calls"], metrics["executive"]["by_decision"]["unchanged"]),
                         (1, 0, 1))

    def test_partial_work_and_backlog_are_visible(self):
        rows = RunRows(run(), calls=(call(work_item="wi_1"),), work=(work("wi_1"), work("wi_2", "pending", has_call=False),
                                                                    work("wi_3", "in_progress", has_call=False)), versions=(("created", 1),))
        report = build_report([rows], Backlog((("pending", 4),), unreasoned_cases=2)).to_dict()
        self.assertEqual((report["runs"][0]["work"]["open"], report["runs"][0]["status_inputs"]["open_work_items"]), (2, 2))
        self.assertEqual(report["runs"][0]["work"]["by_status"]["pending"], 1)
        self.assertEqual(report["backlog"], {"open_llm_work_items": 4, "open_by_status": {"pending": 4, "in_progress": 0}, "unreasoned_cases": 2})

    def test_empty_run(self):
        report = build_report([RunRows(run())])
        metrics = report.run(RUN_A).to_dict()
        self.assertEqual(metrics["provider_calls"]["total"]["latency"], {"total_ms": 0, "max_ms": None, "mean_ms": None, "p50_ms": None, "p95_ms": None})
        self.assertEqual(metrics["provider_calls"]["by_purpose"], {})
        self.assertEqual(set(metrics["work"]["by_status"].values()), {0})
        self.assertEqual(set(metrics["status_inputs"].values()), {0})
        self.assertEqual(metrics, {**report.aggregate.to_dict(), "run": metrics["run"]})
        nothing = build_report([]).to_dict()
        self.assertEqual((nothing["run_ids"], nothing["runs"], nothing["metrics_version"]), ([], [], METRICS_VERSION))

    def test_output_is_deterministic_whatever_the_row_order(self):
        calls = [call(work_item=f"wi_{i}", latency=10 * i, attempts=1 + i % 3) for i in range(20)]
        a = RunRows(run(RUN_A), calls=tuple(calls), observations=(("unchanged", 3), ("new", 2)), memory=(("degraded", 1), ("available", 3)))
        b = RunRows(run(RUN_B, "2026-09-29T00:10:00+00:00"), calls=tuple(reversed(calls)), observations=(("new", 2), ("unchanged", 3)),
                    memory=(("available", 3), ("degraded", 1)))
        first = build_report([a, b]).to_json()
        self.assertEqual(build_report([b, a]).to_json(), first)
        self.assertEqual(json.loads(first)["run_ids"], [RUN_A, RUN_B])
        self.assertEqual(json.dumps(json.loads(first), sort_keys=True, separators=(",", ":"), ensure_ascii=False), first)

    def test_status_inputs_never_decide_a_status(self):
        metrics = build_report([RunRows(run())]).run(RUN_A).to_dict()
        self.assertNotIn("status", metrics["status_inputs"])
        self.assertFalse(any(name in metrics["status_inputs"] for name in ("complete", "partial", "degraded", "failed")))


@requires_db
class PipelineMetricsTests(unittest.TestCase):
    """Telemetry derived from the canonical rows the real pipeline writes."""

    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.analyst = ScriptedAnalyst()
        self.honcho = FakeHoncho()
        self.engine = ReasoningEngine(self.store, gateway(self.analyst, recorder=StoreCallRecorder(self.store)), retries=1,
                                      context=HumanContext(self.store, self.honcho, env={}))
        self.executive = ScriptedExecutive()
        self.synthesizer = ExecutiveSynthesizer(ExecutiveStore(self.store), gateway(self.executive, recorder=StoreCallRecorder(self.store)), retries=1)
        self.t = times(10)
        self.runs = 0

    def gate(self, payload=None):
        report = run_gate(payload or snapshots.reasoning_input(), self.store, now=self.t[self.runs])
        self.runs += 1
        return report

    def run_snapshot(self, payload=None, *, executive=False):
        report = self.gate(payload)
        self.engine.process_run(report.run_id)
        if executive:
            self.synthesizer.synthesize(report.run_id)
        return report

    def metrics(self, run_id):
        return reliability_report(self.store, [run_id]).run(run_id).to_dict()

    def case_id(self, report, identity=DEADLINE_12):
        return next(d.case_id for d in report.decisions if d.identity_key == identity)

    def llm_work(self, report):
        return [d for d in report.decisions if d.action.value in ("new", "updated")]

    def test_successful_run(self):
        report = self.run_snapshot(executive=True)
        metrics = self.metrics(report.run_id)
        n = len(self.llm_work(report))
        self.assertGreater(n, 1)
        analyst = metrics["provider_calls"]["by_purpose"]["analyst"]
        self.assertEqual((analyst["logical_calls"], analyst["attempts"], analyst["retries"], analyst["failed"]), (n, n, 0, 0))
        self.assertEqual((analyst["input_tokens"], analyst["output_tokens"]), (1000 * n, 400 * n))      # ScriptedAnalyst's usage per call
        self.assertEqual((metrics["work"]["llm_work_items"], metrics["work"]["done"], metrics["work"]["new_results"], metrics["work"]["open"]),
                         (n, n, n, 0))
        self.assertEqual((metrics["gate"]["by_action"]["new"], metrics["gate"]["skipped_unchanged"]), (n, 0))
        self.assertEqual(metrics["executive"]["by_decision"]["synthesized"], 1)
        self.assertEqual(metrics["executive"]["model_calls"], metrics["provider_calls"]["by_purpose"]["executive"]["logical_calls"])
        self.assertEqual((metrics["memory"]["injected_calls"], metrics["memory"]["degraded"]), (n, False))
        self.assertEqual(metrics["run"]["run_id"], report.run_id)
        with self.store.transaction() as tx:
            calls = tx.llm_calls(run_id=report.run_id)
        self.assertEqual(metrics["provider_calls"]["total"]["latency"]["total_ms"], sum(row["latency_ms"] for row in calls))
        self.assertEqual(metrics["provider_calls"]["total"]["input_tokens"], sum(row["input_tokens"] or 0 for row in calls))

    def test_provider_retry_and_failure(self):
        report = self.gate()
        retried, failed = self.case_id(report), next(d.case_id for d in self.llm_work(report) if d.identity_key != DEADLINE_12)
        self.analyst.script(retried, ProviderUnavailable("busy"))
        self.analyst.script(failed, ProviderUnavailable("down"), ProviderUnavailable("down"))
        self.engine.process_run(report.run_id)
        metrics = self.metrics(report.run_id)
        n = len(self.llm_work(report))
        total = metrics["provider_calls"]["total"]
        self.assertEqual((total["logical_calls"], total["attempts"], total["retries"], total["retried_calls"]), (n, n + 2, 2, 2))
        self.assertEqual((total["failed"], total["failures_by_class"], total["calls_without_usage"]), (1, {"provider_unavailable": 1}, 1))
        self.assertEqual(metrics["work"]["failures_by_class"], {"provider": 1})
        inputs = metrics["status_inputs"]
        self.assertEqual((inputs["provider_failed_work_items"], inputs["provider_failed_calls"], inputs["committed_versions"], inputs["done_work_items"]),
                         (1, 1, n - 1, n - 1))

    def test_validation_failure(self):
        report = self.gate()
        case_id = self.case_id(report)

        def refusing(payload):
            value = analyst_answer(payload)
            value["interpretation"]["statement"] = REFUSED_TEXT
            return value

        self.analyst.script(case_id, refusing, refusing)
        self.engine.process_run(report.run_id)
        metrics = self.metrics(report.run_id)
        validation = metrics["validation"]
        self.assertEqual((validation["refused_candidates"], validation["corrective_reasks"], validation["failed_work_items"]), (2, 1, 1))
        self.assertTrue(validation["codes"])
        self.assertEqual(metrics["provider_calls"]["by_purpose"]["analyst"]["logical_calls"], len(self.llm_work(report)) + 1)
        self.assertEqual(metrics["status_inputs"]["validation_failed_work_items"], 1)
        self.assertNotIn(REFUSED_TEXT, json.dumps(metrics))

    def test_unchanged_zero_call_update_and_executive_preserve(self):
        first = self.run_snapshot(executive=True)
        same = self.run_snapshot(executive=True)
        metrics = self.metrics(same.run_id)
        self.assertEqual(metrics["gate"]["skipped_unchanged"], len(first.decisions))
        self.assertEqual((metrics["work"]["llm_work_items"], metrics["work"]["new_results"]), (0, 0))
        self.assertEqual(set(metrics["provider_calls"]["by_purpose"]), {"executive"})   # new -> active changed the brief's input once
        again = self.run_snapshot(executive=True)
        metrics = self.metrics(again.run_id)
        self.assertEqual((metrics["gate"]["skipped_unchanged"], metrics["provider_calls"]["total"]["logical_calls"]), (len(first.decisions), 0))
        self.assertEqual((metrics["executive"]["unchanged_zero_call"], metrics["executive"]["model_calls"]), (1, 0))
        self.assertEqual(metrics["provider_calls"]["by_purpose"], {})
        changed = self.run_snapshot(payload_with(changed_rows()), executive=True)
        metrics = self.metrics(changed.run_id)
        self.assertEqual((metrics["work"]["updates"] + metrics["work"]["no_change_reviews"], metrics["work"]["new_results"]), (1, 0))
        self.assertEqual(metrics["provider_calls"]["by_purpose"]["update"]["logical_calls"], 1)
        self.assertEqual(metrics["gate"]["skipped_unchanged"], len(first.decisions) - 1)
        aggregate = reliability_report(self.store, [first.run_id, same.run_id, again.run_id, changed.run_id]).to_dict()["aggregate"]
        self.assertEqual((aggregate["executive"]["synthesis_runs"], aggregate["executive"]["unchanged_zero_call"]), (4, 1))
        self.assertEqual(aggregate["work"]["new_results"], len(self.llm_work(first)))

    def test_executive_failure_preserves_and_is_counted(self):
        first = self.run_snapshot(executive=True)
        changed = self.run_snapshot(payload_with(changed_rows()))
        self.executive.script(ProviderUnavailable("down"), ProviderUnavailable("down"))
        self.synthesizer.synthesize(changed.run_id)
        metrics = self.metrics(changed.run_id)
        self.assertEqual((metrics["executive"]["by_decision"]["failed"], metrics["executive"]["failures_by_class"]), (1, {"provider": 1}))
        self.assertEqual((metrics["status_inputs"]["executive_failed_runs"], metrics["status_inputs"]["executive_ok_runs"]), (1, 0))
        self.assertEqual(self.metrics(first.run_id)["status_inputs"]["executive_ok_runs"], 1)

    def test_partial_work_is_visible(self):
        report = self.gate()
        n = len(self.llm_work(report))
        metrics = self.metrics(report.run_id)
        self.assertEqual((metrics["work"]["open"], metrics["work"]["by_status"]["pending"], metrics["status_inputs"]["open_work_items"]), (n, n, n))
        self.assertEqual(metrics["provider_calls"]["total"]["logical_calls"], 0)
        backlog = reliability_report(self.store, [report.run_id]).to_dict()["backlog"]
        self.assertEqual(backlog["open_llm_work_items"], n)
        self.engine.process_run(report.run_id)
        self.assertEqual(self.metrics(report.run_id)["work"]["open"], 0)
        self.assertEqual(reliability_report(self.store, [report.run_id]).backlog.to_dict()["open_llm_work_items"], 0)

    def test_memory_degraded(self):
        self.honcho.outage()
        report = self.run_snapshot()
        memory = self.metrics(report.run_id)["memory"]
        self.assertTrue(memory["degraded"])
        self.assertEqual(memory["degraded_calls"], len(self.llm_work(report)))
        self.assertEqual(self.metrics(report.run_id)["status_inputs"]["memory_degraded_calls"], len(self.llm_work(report)))

    def test_no_content_or_secrets_leak(self):
        report = self.gate()
        self.analyst.script(self.case_id(report), lambda payload: {**analyst_answer(payload), "interpretation": {
            **analyst_answer(payload)["interpretation"], "statement": REFUSED_TEXT}})
        self.engine.process_run(report.run_id)
        self.synthesizer.synthesize(report.run_id)
        text = reliability_report(self.store, [report.run_id]).to_json()
        self.assertFalse(keys(json.loads(text)) & CONTENT_KEYS)
        with self.store.transaction() as tx:
            titles = [row["title"] for row in tx._all("SELECT document ->> 'title' AS title FROM reasoning_result_versions")]
        for forbidden in [REFUSED_TEXT, "Bearer", "sk-or-", *titles, *[r.messages[0].content[:80] for r in self.analyst.requests]]:
            self.assertNotIn(forbidden, text)
        password = (test_database_url() or "").partition("://")[2].partition("@")[0].partition(":")[2]
        if password:
            self.assertNotIn(password, text)

    def test_deterministic_report_and_order(self):
        first = self.run_snapshot(executive=True)
        second = self.run_snapshot(payload_with(changed_rows()), executive=True)
        forward = reliability_report(self.store, [first.run_id, second.run_id]).to_json()
        self.assertEqual(reliability_report(self.store, [second.run_id, first.run_id, first.run_id]).to_json(), forward)
        self.assertEqual(reliability_report(self.store, latest=2).to_json(), forward)
        self.assertEqual(json.loads(forward)["run_ids"], [first.run_id, second.run_id])

    def test_empty_run_and_unknown_run(self):
        with self.store.transaction() as tx:
            run_id = tx.create_run(source_snapshot_id="snap-empty", release_id=None, upstream_contract_version="1.5", intelligence_version="v2",
                                   boundary_version="b1", identity_version="i1", fingerprint_version="f1")
        metrics = self.metrics(run_id)
        self.assertEqual(set(metrics["status_inputs"].values()), {0})
        self.assertEqual(metrics["provider_calls"]["total"]["latency"]["p95_ms"], None)
        self.assertEqual((metrics["run"]["status"], metrics["run"]["finished_at"], metrics["run"]["wall_ms"]), ("started", None, None))
        with self.assertRaises(NotFound):
            reliability_report(self.store, ["run_" + "0" * 32])

    def test_operator_entry(self):
        report = self.run_snapshot()
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"ATLAS_REASONING_DATABASE_URL": os.environ[TEST_DB_ENV]}), contextlib.redirect_stdout(out):
            self.assertEqual(report_main(["--run", report.run_id]), 0)
        self.assertEqual(json.loads(out.getvalue())["run_ids"], [report.run_id])
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"ATLAS_REASONING_DATABASE_URL": os.environ[TEST_DB_ENV]}), contextlib.redirect_stdout(out):
            self.assertEqual(report_main(["--run", "run_" + "0" * 32]), 1)
        self.assertFalse(json.loads(out.getvalue())["ok"])


    # --- Phase 18 reconciliation (18-A orchestration in the telemetry) -----------------------------------------------------------

    def orchestrator(self, budget=None):
        from atlas_reasoning.run_control import OrchestrationPolicy, RunOrchestrator
        engine = ReasoningEngine(self.store, ReasoningGateway(self.analyst, GatewaySettings(max_retries=1, backoff_seconds=0, max_backoff_seconds=0,
                                                                                            concurrency=1),
                                                              recorder=StoreCallRecorder(self.store), sleep=lambda seconds: None), retries=1,
                                 context=HumanContext(self.store, self.honcho, env={}))
        return RunOrchestrator(engine, policy=OrchestrationPolicy(max_calls_per_pass=budget))

    def test_passes_budget_and_retries_are_reported(self):
        report = self.gate()
        total = len(self.llm_work(report))
        self.orchestrator(budget=3).run(report.run_id)
        self.orchestrator().resume(report.run_id)
        orchestration = self.metrics(report.run_id)["orchestration"]
        self.assertEqual((orchestration["passes"], orchestration["by_kind"]), (2, {"initial": 1, "resume": 1}))
        self.assertEqual((orchestration["budgeted_passes"], orchestration["budget_limit"]), (1, 3))
        self.assertEqual((orchestration["budget_calls_used"], orchestration["admitted"], orchestration["deferred"]), (total, total, total - 3))
        self.assertEqual((orchestration["last_status"], orchestration["last_reasons"], orchestration["retries_created"]), ("complete", [], 0))

    def test_a_deferred_item_called_again_in_a_later_pass_is_not_a_reask(self):
        report = self.gate()
        case_id = self.case_id(report)
        refusing = lambda payload: {**analyst_answer(payload), "interpretation": {**analyst_answer(payload)["interpretation"], "statement": REFUSED_TEXT}}
        self.analyst.script(case_id, refusing)
        from atlas_reasoning.work_priority import prioritize
        position = [row.case_id for row in prioritize(self.engine.pending_work())].index(case_id)
        first = self.orchestrator(budget=position + 1).run(report.run_id)          # its re-ask is refused by the budget: deferred
        self.assertIn("work:BUDGET_EXHAUSTED", {o.error for o in first.outcomes if o.case_id == case_id})
        self.orchestrator().resume(report.run_id)                                  # a fresh first call in a new pass
        validation = self.metrics(report.run_id)["validation"]
        self.assertEqual((validation["refused_candidates"], validation["corrective_reasks"]), (1, 0))

    def test_refusals_before_any_request_are_not_provider_failures(self):
        report = self.gate()
        item = self.engine.pending_work()[0]
        with self.store.transaction() as tx:
            tx.set_work_item_status(item.work_item_id, WorkStatus.IN_PROGRESS)
            tx.set_work_item_status(item.work_item_id, WorkStatus.FAILED, error="provider:circuit_open")
        metrics = self.metrics(report.run_id)
        self.assertEqual(metrics["work"]["refused_before_call"], 1)
        inputs = metrics["status_inputs"]
        self.assertEqual((inputs["refused_work_items"], inputs["provider_failed_work_items"], inputs["other_failed_work_items"]), (1, 0, 0))

    def test_a_driver_error_in_the_operator_report_is_json_without_detail(self):
        import psycopg
        out = io.StringIO()
        error = psycopg.errors.QueryCanceled("canceling statement due to statement timeout: SELECT secret_column")
        with mock.patch.dict(os.environ, {"ATLAS_REASONING_DATABASE_URL": os.environ[TEST_DB_ENV]}), contextlib.redirect_stdout(out), \
                mock.patch("atlas_reasoning.store.reliability_metrics.reliability_report", side_effect=error):
            self.assertEqual(report_main(["--latest", "1"]), 1)
        self.assertEqual(json.loads(out.getvalue()), {"ok": False, "error": "QueryCanceled"})


if __name__ == "__main__":
    unittest.main()
