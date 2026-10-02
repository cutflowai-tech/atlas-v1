"""Phase 18-A (REV/18 #2-#7, #9): run orchestration — deterministic priority, per-pass call budget, run status, bounded idempotent
resume, duplicate-work protection and failure isolation. Offline model only (``ScriptedAnalyst``); real Change Gate, engine, lifecycle
and guardrails on PostgreSQL."""

from __future__ import annotations

import random
import threading
import unittest
from typing import Any

import psycopg
import reasoning_snapshots as snapshots
from reasoning_db import fresh_database, requires_db
from reasoning_engine_support import DEADLINE_12, changed_rows, payload_with, times
from reasoning_fakes import ScriptedAnalyst, analyst_answer, gateway

from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.engine import ENGINE_LOCK_KEY, ReasoningEngine
from atlas_reasoning.enums import GateAction, RunStatus, WorkKind, WorkStatus
from atlas_reasoning.gateway import ReasoningGateway
from atlas_reasoning.provider import ProviderAuthError, ProviderUnavailable
from atlas_reasoning.run_control import OrchestrationPolicy, RunOrchestrator
from atlas_reasoning.settings import GatewaySettings
from atlas_reasoning.store import run_control as sql
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.health import database_health
from atlas_reasoning.store.migrate import apply_migrations
from atlas_reasoning.store.repository import ReasoningStore, WorkItemRow
from atlas_reasoning.work_priority import high_importance, prioritize, priority

OUTAGE = (ProviderUnavailable("down"), ProviderUnavailable("down"))     # the attempt and the gateway's one retry


def item(work_item_id: str, case_id: str, gate: GateAction, *, category: str = "system_pattern", direction: str = "adverse", rank: int | None = 5,
         orientation: str = "adverse") -> WorkItemRow:
    document = {"orientation": orientation, "supporting_findings": [{"category": category, "direction": direction, "rank": rank}]}
    return WorkItemRow(work_item_id, "run_" + "0" * 32, case_id, WorkKind.UPDATE_RESULT if gate == GateAction.UPDATED else WorkKind.NEW_RESULT, gate,
                       WorkStatus.PENDING, True, None, None, None, "ef1_" + "0" * 64, None, document)


class PriorityTests(unittest.TestCase):
    def test_tiers_and_tie_breaks_are_deterministic(self):
        rows = [item("wi_a", "rc1_c", GateAction.NEW, rank=3),
                item("wi_b", "rc1_b", GateAction.NEW, category="needs_attention", rank=9),
                item("wi_c", "rc1_a", GateAction.UPDATED, category="needs_attention", rank=12),
                item("wi_d", "rc1_d", GateAction.UPDATED, category="needs_attention", rank=4),
                item("wi_e", "rc1_e", GateAction.UPDATED, rank=1),
                item("wi_f", "rc1_f", GateAction.NEW, category="emerging_risk", rank=None),
                item("wi_g", "rc1_g", GateAction.NEW, category="needs_attention", direction="favourable", orientation="favourable", rank=2)]
        expected = ["wi_d", "wi_c", "wi_b", "wi_f", "wi_e", "wi_g", "wi_a"]
        for seed in range(20):
            shuffled = list(rows)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual([row.work_item_id for row in prioritize(shuffled)], expected)
        self.assertEqual([priority(row).tier for row in prioritize(rows)], [1, 1, 2, 2, 3, 3, 3])
        self.assertFalse(high_importance(None))

    def test_the_model_never_takes_part(self):
        import ast
        from pathlib import Path
        source = Path(__file__).resolve().parents[1] / "src" / "atlas_reasoning" / "work_priority.py"
        imported = {node.module for node in ast.walk(ast.parse(source.read_text())) if isinstance(node, ast.ImportFrom)}
        self.assertFalse({"atlas_reasoning.gateway", "atlas_reasoning.provider", "atlas_reasoning.analyst"} & imported)

    def test_policy(self):
        policy = OrchestrationPolicy()
        for code in ("provider:timeout", "provider:rate_limited", "work:INTERRUPTED", "work:BUDGET_EXHAUSTED", "store:OperationalError"):
            self.assertTrue(policy.is_retryable(code), code)
        for code in ("validation:HR_JUDGMENT", "provider:authentication", "provider:quota_exceeded", "contract:X", "internal:KeyError", None):
            self.assertFalse(policy.is_retryable(code), code)
        with self.assertRaises(ValueError):
            OrchestrationPolicy(max_attempts=0)
        with self.assertRaises(ValueError):
            OrchestrationPolicy(max_calls_per_pass=-1)


@requires_db
class RunControlTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.transport = ScriptedAnalyst()
        self.engine = ReasoningEngine(self.store, gateway(self.transport, recorder=StoreCallRecorder(self.store)), retries=1)
        self.t = times(12)
        self.runs = 0

    def gate(self, payload: Any = None) -> Any:
        report = run_gate(payload or snapshots.reasoning_input(), self.store, now=self.t[self.runs])
        self.runs += 1
        return report

    def orchestrator(self, budget: int | None = None, **kw: Any) -> RunOrchestrator:
        return RunOrchestrator(self.engine, policy=OrchestrationPolicy(max_calls_per_pass=budget, **kw))

    def calls(self) -> int:
        with self.store.transaction() as tx:
            return int(tx._one("SELECT count(*) AS n FROM llm_calls WHERE purpose IN ('analyst', 'update')")["n"])

    def run_row(self, run_id: str) -> dict[str, Any]:
        with self.store.transaction() as tx:
            return tx.get_run(run_id)

    def results(self) -> dict[str, tuple[str, int]]:
        with self.store.transaction() as tx:
            return {row["case_id"]: (row["result_id"], row["current_version"]) for row in tx._all("SELECT case_id, result_id, current_version FROM reasoning_results")}

    def assert_no_duplicates(self):
        with self.store.transaction() as tx:
            versions = tx._all("SELECT result_id, array_agg(version ORDER BY version) AS v FROM reasoning_result_versions GROUP BY result_id")
            for row in versions:
                self.assertEqual(row["v"], list(range(1, len(row["v"]) + 1)))
            self.assertEqual(tx._one("""SELECT count(*) AS n FROM (SELECT case_id FROM reasoning_results WHERE lifecycle_status IN ('new','active','updated','cooling')
                                         GROUP BY case_id HAVING count(*) > 1) d""")["n"], 0)
            self.assertEqual(tx._one("""SELECT count(*) AS n FROM (SELECT case_id, dedup_key FROM atlas_questions WHERE state = 'open'
                                         GROUP BY case_id, dedup_key HAVING count(*) > 1) d""")["n"], 0)
            self.assertEqual(tx._one("""SELECT count(*) AS n FROM (SELECT source_type, source_id, session_key, content_sha256 FROM memory_sync_log
                                         WHERE status = 'synced' GROUP BY 1, 2, 3, 4 HAVING count(*) > 1) d""")["n"], 0)
            self.assertEqual(tx._one("""SELECT count(*) AS n FROM (SELECT case_id FROM reasoning_work_items WHERE requires_llm AND status IN ('pending','in_progress')
                                         GROUP BY case_id HAVING count(*) > 1) d""")["n"], 0)

    # --- complete, zero-call, priority ----------------------------------------------------------------------------------------

    def test_a_full_pass_is_complete_and_an_unchanged_snapshot_costs_nothing(self):
        first = self.gate()
        report = self.orchestrator().run(first.run_id)
        self.assertEqual((report.status, report.reasons, report.executive_ready), ("complete", (), True))
        self.assertEqual(self.run_row(first.run_id)["status"], RunStatus.COMPLETE)
        self.assertEqual(report.calls_used, self.calls())
        before = self.calls()
        second = self.gate()                                   # same evidence
        again = self.orchestrator().run(second.run_id)
        self.assertEqual((again.status, again.calls_used, again.admitted), ("complete", 0, ()))
        self.assertEqual(self.calls(), before)
        with self.store.transaction() as tx:
            counts = sql.passes(tx, second.run_id)[-1]["counts"]
        self.assertGreater(counts["unchanged_cases"], 0)
        self.assert_no_duplicates()

    def test_admission_follows_the_deterministic_priority(self):
        first = self.gate()
        self.orchestrator().run(first.run_id)
        second = self.gate(payload_with(changed_rows()))       # editor-label-12's deadline case changes: an update
        pending = prioritize(self.engine.pending_work())
        report = self.orchestrator(budget=len(pending)).run(second.run_id)
        self.assertEqual(list(report.admitted), [row.work_item_id for row in pending])
        third = self.gate(payload_with(changed_rows(0.875)))
        pending = prioritize(self.engine.pending_work())
        tiers = [priority(row).tier for row in pending]
        self.assertEqual(tiers, sorted(tiers))
        self.assertEqual(self.orchestrator(budget=1).run(third.run_id).admitted, (pending[0].work_item_id,))

    def test_new_high_importance_cases_go_first_under_a_budget(self):
        first = self.gate()
        pending = self.engine.pending_work()
        important = {row.work_item_id for row in pending if priority(row).tier == 2}
        self.assertTrue(important)
        report = self.orchestrator(budget=len(important)).run(first.run_id)
        self.assertEqual(set(report.admitted), important)

    # --- budget, partial, resume ---------------------------------------------------------------------------------------------

    def test_budget_stops_new_work_and_leaves_it_resumable(self):
        first = self.gate()
        total = len(self.engine.pending_work())
        report = self.orchestrator(budget=3).run(first.run_id)
        self.assertEqual((report.status, report.calls_used, len(report.admitted), len(report.deferred)), ("partial", 3, 3, total - 3))
        self.assertIn("work_deferred", report.reasons)
        self.assertFalse(report.executive_ready)
        self.assertEqual(self.calls(), 3)
        with self.store.transaction() as tx:
            self.assertEqual({tx._one("SELECT status FROM reasoning_work_items WHERE work_item_id = %s", (wid,))["status"] for wid in report.deferred}, {"pending"})
        kept = self.results()
        self.assertEqual(self.orchestrator().incomplete_runs(), [first.run_id])
        resumed = self.orchestrator().resume(first.run_id)
        self.assertEqual((resumed.status, len(resumed.admitted)), ("complete", total - 3))
        self.assertEqual(self.calls(), total)
        for case_id, value in kept.items():
            self.assertEqual(self.results()[case_id], value)              # earlier results untouched
        idle = self.orchestrator().resume(first.run_id)
        self.assertEqual((idle.status, idle.calls_used, idle.admitted, idle.retries), ("complete", 0, (), ()))
        self.assertEqual(self.calls(), total)
        self.assert_no_duplicates()

    def test_a_call_the_budget_refuses_defers_the_item_without_spending_an_attempt(self):
        self.engine = ReasoningEngine(self.store, ReasoningGateway(self.transport, GatewaySettings(max_retries=1, backoff_seconds=0, max_backoff_seconds=0,
                                                                                                    concurrency=1),
                                                                   recorder=StoreCallRecorder(self.store), sleep=lambda seconds: None), retries=1)
        first = self.gate()
        case_id = next(d.case_id for d in first.decisions if d.identity_key == DEADLINE_12)
        def bad(payload):
            answer = analyst_answer(payload)
            answer["interpretation"]["statement"] = "The Editor is lazy and should be fired."
            return answer

        self.transport.script(case_id, bad)
        pending = [row for row in prioritize(self.engine.pending_work())]
        position = [row.case_id for row in pending].index(case_id)
        report = self.orchestrator(budget=position + 1).run(first.run_id)      # exactly enough for the first call of each admitted item
        outcome = next(o for o in report.outcomes if o.case_id == case_id)
        self.assertEqual((outcome.status, outcome.error), ("pending", "work:BUDGET_EXHAUSTED"))
        self.assertEqual(report.status, "partial")
        with self.store.transaction() as tx:
            self.assertEqual(tx._one("SELECT status FROM reasoning_work_items WHERE work_item_id = %s", (outcome.work_item_id,))["status"], "pending")
            self.assertEqual(sql.retries(tx, case_id=case_id), [])                # deferred, not failed: no attempt spent
        with self.store.transaction() as tx:
            row = tx._one("SELECT calls_used, call_budget FROM reasoning_run_passes WHERE pass_id = %s", (report.pass_id,))
        self.assertEqual(row["calls_used"], row["call_budget"])                # never overspent
        resumed = self.orchestrator().resume(first.run_id)
        self.assertIn(case_id, {o.case_id for o in resumed.outcomes if o.change_kind == "created"})
        self.assertEqual(resumed.status, "complete")

    def test_resume_after_process_interruption(self):
        first = self.gate()
        pending = self.engine.pending_work()
        with self.store.transaction() as tx:                                   # a worker claimed an item and died mid-call
            tx.set_work_item_status(pending[0].work_item_id, WorkStatus.IN_PROGRESS)
        live = self.orchestrator().resume(first.run_id)                        # a young claim may be live: never taken over
        self.assertEqual((live.recovered, live.status), ((), "partial"))
        self.assertNotIn(pending[0].work_item_id, live.admitted)
        with self.store.transaction() as tx:                                   # ... until it is older than the longest possible call
            tx._exec("UPDATE reasoning_work_items SET updated_at = now() - interval '1 day' WHERE work_item_id = %s", (pending[0].work_item_id,))
        resumed = self.orchestrator().resume(first.run_id)
        self.assertEqual(resumed.recovered, (pending[0].work_item_id,))
        self.assertEqual(len(resumed.retries), 1)
        with self.store.transaction() as tx:
            [retry] = sql.retries(tx, case_id=pending[0].case_id)
        self.assertEqual((retry["failed_work_item_id"], retry["attempt"], retry["failure"]), (pending[0].work_item_id, 2, "work:STALE_CLAIM"))
        self.assertEqual(resumed.status, "complete")
        self.assertIn(pending[0].case_id, self.results())
        self.assert_no_duplicates()

    def test_only_retryable_failures_are_retried_and_attempts_are_bounded(self):
        first = self.gate()
        ids = {d.identity_key: d.case_id for d in first.decisions}
        transient, permanent = ids[DEADLINE_12], next(c for k, c in ids.items() if k != DEADLINE_12)
        self.transport.script(transient, *OUTAGE, *OUTAGE)
        self.transport.script(permanent, ProviderAuthError("bad key"))
        report = self.orchestrator(max_attempts=2).run(first.run_id)
        self.assertEqual(report.status, "partial")
        self.assertEqual(report.reasons, ("resumable_failures",))
        resumed = self.orchestrator(max_attempts=2).resume(first.run_id)
        retried = {o.case_id for o in resumed.outcomes}
        self.assertEqual(retried, {transient})                                    # authentication is never retried
        self.assertEqual(resumed.status, "degraded")                              # out of attempts: failed for good
        self.assertEqual(resumed.reasons, ("unresolved_failures",))
        again = self.orchestrator(max_attempts=2).resume(first.run_id)
        self.assertEqual((again.retries, again.calls_used, again.status), ((), 0, "degraded"))     # bounded: no retry loop
        self.assertNotIn(transient, self.results())
        self.assertNotIn(permanent, self.results())
        self.assert_no_duplicates()

    def test_a_retried_failure_recovers_and_keeps_stable_ids(self):
        first = self.gate()
        self.orchestrator().run(first.run_id)
        kept = self.results()
        second = self.gate(payload_with(changed_rows()))
        case_id = next(d.case_id for d in second.decisions if d.identity_key == DEADLINE_12)
        self.transport.script(case_id, *OUTAGE)
        report = self.orchestrator().run(second.run_id)
        self.assertEqual(report.status, "partial")
        result_id, after_failure = self.results()[case_id]
        self.assertEqual(result_id, kept[case_id][0])                              # the previous valid result survives (same card)
        with self.store.transaction() as tx:
            kinds = [row["change_kind"] for row in tx.result_history(result_id)]
        self.assertNotIn("patched", kinds)                                         # the failure wrote nothing (the sweep may settle it)
        resumed = self.orchestrator().resume(second.run_id)
        self.assertEqual(resumed.status, "complete")
        self.assertEqual(self.results()[case_id], (result_id, after_failure + 1))  # same result, patched exactly once
        self.assert_no_duplicates()

    # --- isolation, outage, failure states ------------------------------------------------------------------------------------

    def test_one_case_failure_never_stops_the_others(self):
        first = self.gate()
        total = len(self.engine.pending_work())
        case_id = next(d.case_id for d in first.decisions if d.identity_key == DEADLINE_12)
        self.transport.script(case_id, ProviderAuthError("bad key"))
        report = self.orchestrator().run(first.run_id)
        self.assertEqual(sum(1 for o in report.outcomes if o.change_kind == "created"), total - 1)
        self.assertEqual((report.status, report.reasons, report.executive_ready), ("degraded", ("unresolved_failures",), True))

    def test_a_provider_outage_fails_the_run_and_resume_recovers_it(self):
        first = self.gate()
        for case_id in {d.case_id for d in first.decisions}:
            self.transport.script(case_id, *OUTAGE)
        report = self.orchestrator().run(first.run_id)
        self.assertEqual((report.status, report.reasons), ("failed", ("provider_outage",)))
        self.assertEqual(self.results(), {})
        resumed = self.orchestrator().resume(first.run_id)
        self.assertEqual(resumed.status, "complete")
        self.assert_no_duplicates()

    def test_a_run_that_was_never_gated_fails(self):
        with self.store.transaction() as tx:
            run_id = tx.create_run(source_snapshot_id="snapshot-x", release_id=None, upstream_contract_version="1.5.0", intelligence_version="v2",
                                   boundary_version="b", identity_version="i", fingerprint_version="f")
        report = self.orchestrator().run(run_id)
        self.assertEqual((report.status, report.reasons, report.calls_used), ("failed", ("not_gated",), 0))
        self.assertEqual(self.run_row(run_id)["status"], RunStatus.FAILED)

    def test_memory_degradation_marks_the_run_degraded(self):
        from atlas_reasoning.fake_honcho import FakeHoncho
        from atlas_reasoning.reasoning_context import HumanContext
        honcho = FakeHoncho()
        honcho.outage()
        self.engine.context = HumanContext(self.store, honcho, env={})
        first = self.gate()
        report = self.orchestrator().run(first.run_id)
        self.assertEqual(report.status, "degraded")
        self.assertIn("memory_degraded", report.reasons)

    # --- duplicate protection ------------------------------------------------------------------------------------------------

    def test_concurrent_orchestrators_never_process_the_same_work_twice(self):
        first = self.gate()
        total = len(self.engine.pending_work())
        reports: list[Any] = []

        def go():
            reports.append(self.orchestrator().run(first.run_id))

        threads = [threading.Thread(target=go) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        worked = [r for r in reports if r.skipped is None]
        self.assertGreaterEqual(len(worked), 1)
        self.assertEqual(self.calls(), total)                                      # every case reasoned exactly once
        self.assertEqual(sum(len(r.admitted) for r in worked), total)
        self.assert_no_duplicates()

    def test_the_database_refuses_a_second_open_pass_and_a_second_retry(self):
        first = self.gate()
        with self.store.transaction() as tx:
            sql.open_pass(tx, run_id=first.run_id, kind="initial", policy_version="p", call_budget=None)
        with self.assertRaises(psycopg.errors.UniqueViolation), self.store.transaction() as tx:
            sql.open_pass(tx, run_id=first.run_id, kind="resume", policy_version="p", call_budget=None)
        with self.store.session_lock(ENGINE_LOCK_KEY) as held:
            self.assertTrue(held)
            self.assertEqual(self.orchestrator().run(first.run_id).skipped, "engine_busy")      # another engine holds the lock
        report = self.orchestrator().resume(first.run_id)                          # the dead pass is closed as interrupted
        with self.store.transaction() as tx:
            outcomes = [row["outcome"] for row in sql.passes(tx, first.run_id)]
        self.assertEqual(outcomes, ["interrupted", "finished"])
        self.assertEqual(report.status, "complete")
        # A failed item is retried at most once, whatever races.
        second = self.gate(payload_with(changed_rows()))
        case_id = next(d.case_id for d in second.decisions if d.identity_key == DEADLINE_12)
        self.transport.script(case_id, *OUTAGE)
        self.orchestrator().run(second.run_id)
        with self.store.transaction() as tx:
            [candidate] = sql.retry_candidates(tx, second.run_id)
            pass_id = sql.open_pass(tx, run_id=second.run_id, kind="resume", policy_version="p", call_budget=1)
            retry_id = sql.create_retry(tx, second.run_id, candidate["work_item_id"], max_attempts=3, pass_id=pass_id)
        self.assertIsNotNone(retry_id)
        with self.store.transaction() as tx:                                   # close retry 1, so only the lineage key can stop a second one
            tx.set_work_item_status(retry_id, WorkStatus.FAILED, error="provider:timeout")
            self.assertIsNone(sql.create_retry(tx, second.run_id, candidate["work_item_id"], max_attempts=3, pass_id=pass_id))   # re-checked
        with self.assertRaises(psycopg.errors.UniqueViolation), self.store.transaction() as tx:
            other = tx.create_work_item(run_id=second.run_id, case_id=case_id, kind=WorkKind(candidate["kind"]), gate_action=GateAction(candidate["gate_action"]),
                                        result_id=candidate["result_id"], base_result_version=candidate["base_result_version"],
                                        fingerprint_before=candidate["fingerprint_before"], fingerprint_after=candidate["fingerprint_after"],
                                        material_delta=candidate["material_delta"], case_document=candidate["case_document"])
            tx._exec("""INSERT INTO reasoning_work_retries (retry_work_item_id, failed_work_item_id, case_id, evidence_fingerprint, attempt, failure, pass_id)
                        VALUES (%s, %s, %s, %s, 9, 'x', %s)""", (other, candidate["work_item_id"], case_id, candidate["fingerprint_after"], pass_id))
        with self.assertRaises(psycopg.errors.CheckViolation), self.store.transaction() as tx:
            tx._exec("UPDATE reasoning_run_passes SET calls_used = 5 WHERE pass_id = %s", (pass_id,))

    def test_a_failure_superseded_by_newer_work_is_neither_retried_nor_resumable(self):
        """Self-review H2: run A's failure, then run B's gate creates newer work for the case: A is not resumable for it (no endless partial)."""
        first = self.gate()
        self.orchestrator().run(first.run_id)
        second = self.gate(payload_with(changed_rows()))
        case_id = next(d.case_id for d in second.decisions if d.identity_key == DEADLINE_12)
        self.transport.script(case_id, *OUTAGE)
        self.assertEqual(self.orchestrator().run(second.run_id).status, "partial")
        third = self.gate(payload_with(changed_rows(0.875)))                    # newer evidence: the gate makes new work for the case
        self.assertNotIn(second.run_id, self.orchestrator(budget=0).incomplete_runs())
        resumed = self.orchestrator(budget=0).resume(second.run_id)
        self.assertEqual((resumed.retries, resumed.status), ((), "degraded"))
        self.assertEqual(resumed.reasons, ("unresolved_failures",))
        self.assertEqual(self.orchestrator().run(third.run_id).status, "complete")

    def test_an_outage_run_is_listed_for_resume(self):
        """Self-review H4."""
        first = self.gate()
        for case_id in {d.case_id for d in first.decisions}:
            self.transport.script(case_id, *OUTAGE)
        self.assertEqual(self.orchestrator().run(first.run_id).status, "failed")
        self.assertEqual(self.orchestrator().incomplete_runs(), [first.run_id])
        self.orchestrator().resume(first.run_id)
        self.assertEqual(self.orchestrator().incomplete_runs(), [])

    def test_degradation_survives_a_no_op_resume(self):
        """Self-review M1: a resume that repairs nothing never turns a degraded run complete."""
        from atlas_reasoning.fake_honcho import FakeHoncho
        from atlas_reasoning.reasoning_context import HumanContext
        honcho = FakeHoncho()
        honcho.outage()
        self.engine.context = HumanContext(self.store, honcho, env={})
        first = self.gate()
        self.assertEqual(self.orchestrator().run(first.run_id).status, "degraded")
        honcho.restore()
        again = self.orchestrator().resume(first.run_id)
        self.assertEqual((again.status, again.calls_used), ("degraded", 0))
        self.assertIn("memory_degraded", again.reasons)

    def test_a_never_gated_run_stays_failed_on_resume(self):
        """Self-review L1."""
        with self.store.transaction() as tx:
            run_id = tx.create_run(source_snapshot_id="snapshot-x", release_id=None, upstream_contract_version="1.5.0", intelligence_version="v2",
                                   boundary_version="b", identity_version="i", fingerprint_version="f")
        self.orchestrator().run(run_id)
        self.assertEqual(self.orchestrator().resume(run_id).reasons, ("not_gated",))

    def test_migration_is_clean_repeatable_and_healthy(self):
        db = fresh_database()
        self.assertEqual(apply_migrations(db), [])
        health = database_health(db)
        self.assertTrue(health["ok"], health)
        self.assertIn("0600_run_control.sql", health["applied"])


if __name__ == "__main__":
    unittest.main()
