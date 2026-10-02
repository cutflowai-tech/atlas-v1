"""Phase 17 executive core on PostgreSQL (``REV/17``): canonical input selection from the real pipeline (Change Gate → engine →
Phase 15 guardrails → canonical results), the preserve policy (zero model calls on unchanged input), versioned persistence by run,
failure preservation (provider failure, invalid structured output, validator rejection, version conflict), the migration and its
constraints. Offline model only (``ScriptedAnalyst`` for the engine, ``ScriptedExecutive`` for the brief). No network, ever."""

from __future__ import annotations

import dataclasses
import unittest

import psycopg
import reasoning_snapshots as snapshots
from reasoning_db import fresh_database, requires_db
from reasoning_engine_support import DEADLINE_12, changed_rows, payload_with, times, without_deadline_12
from reasoning_executive_support import ScriptedExecutive, generic_answer
from reasoning_fakes import ScriptedAnalyst, analyst_answer, gateway

from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.engine import ReasoningEngine
from atlas_reasoning.executive import EXECUTIVE_LOCK_KEY, BriefProvenance, Decision, ExecutiveSynthesizer, assemble_brief, executive_input
from atlas_reasoning.executive_contracts import SECTIONS, ExecutiveBrief
from atlas_reasoning.frozen import thaw
from atlas_reasoning.provider import ProviderUnavailable
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.executive import ExecutiveStore, ExecutiveTransaction
from atlas_reasoning.store.health import database_health
from atlas_reasoning.store.migrate import apply_migrations
from atlas_reasoning.store.repository import ReasoningStore, VersionConflict

RAW_DETECTOR = "deadline.editor_pattern:0123456789abcdef"


def citing(*refs):
    """An answer whose top concern cites ``refs`` (plus nothing else)."""
    def answer(payload):
        value = generic_answer(payload)
        value["sections"]["top_concerns"] = [{"text": "This open result deserves attention first.", "result_ids": list(refs)}]
        return value
    return answer


def refusing_analyst(payload):
    value = analyst_answer(payload)
    value["interpretation"]["statement"] = "Ahmed is lazy and should be fired."
    return value


@requires_db
class ExecutiveStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.executive_store = ExecutiveStore(self.store)
        self.analyst = ScriptedAnalyst()
        self.engine = ReasoningEngine(self.store, gateway(self.analyst, recorder=StoreCallRecorder(self.store)), retries=1)
        self.model = ScriptedExecutive()
        self.synthesizer = ExecutiveSynthesizer(self.executive_store, gateway(self.model, recorder=StoreCallRecorder(self.store)), retries=1)
        self.t = times(12)
        self.runs = 0

    # --- helpers ------------------------------------------------------------------------------------------------------------

    def run_snapshot(self, payload=None):
        report = run_gate(payload or snapshots.reasoning_input(), self.store, now=self.t[self.runs])
        self.runs += 1
        self.engine.process_run(report.run_id)
        return report

    def case_id(self, report, identity=DEADLINE_12):
        return next(d.case_id for d in report.decisions if d.identity_key == identity)

    def open_result_id(self, case_id):
        with self.store.transaction() as tx:
            return tx.open_result(case_id).result_id

    def current(self):
        return self.executive_store.current_brief()

    def inp(self, run_id):
        with self.executive_store.transaction() as tx:
            return executive_input(tx.canonical_results(run_id))

    def executive_calls(self, run_id):
        with self.store.transaction() as tx:
            return [row for row in tx.llm_calls(run_id=run_id) if row["purpose"] == "executive"]

    # --- input ----------------------------------------------------------------------------------------------------------------

    def test_input_is_exactly_the_canonical_eligible_results_and_never_a_failed_candidate(self):
        first = run_gate(snapshots.reasoning_input(), self.store, now=self.t[0])
        refused_case = self.case_id(first)
        self.analyst.script(refused_case, refusing_analyst, refusing_analyst)
        self.engine.process_run(first.run_id)
        failed = self.store.failed_candidates(case_id=refused_case)
        self.assertEqual(len(failed), 2)
        inp = self.inp(first.run_id)
        with self.store.transaction() as tx:
            canonical = {row["result_id"]: row for row in tx._all("SELECT result_id, current_version, lifecycle_status FROM reasoning_results")}
        self.assertEqual(inp.result_ids, frozenset(canonical))
        self.assertTrue(canonical)
        self.assertNotIn(failed[0]["result_id"], inp.result_ids)
        for result_id, version, status in inp.results:
            self.assertEqual((version, status.value), (canonical[result_id]["current_version"], canonical[result_id]["lifecycle_status"]))
        # A brief citing the refused candidate's result ID is refused with the precise code, and nothing is committed.
        self.model.script(citing(failed[0]["result_id"]), citing(failed[0]["candidate_id"]))
        outcome = self.synthesizer.synthesize(first.run_id)
        self.assertEqual((outcome.decision, outcome.failure), (Decision.FAILED, "validation:FAILED_CANDIDATE_REFERENCE"))
        self.assertIsNone(self.current())

    def test_cooling_is_excluded_and_resolved_appears_only_within_the_lookback(self):
        first = self.run_snapshot()
        result_id = self.open_result_id(self.case_id(first))
        statuses = []
        for _ in range(3):
            report = self.run_snapshot(payload_with(without_deadline_12()))
            status = self.store.get_result(result_id).lifecycle_status.value
            statuses.append(status)
            inp = self.inp(report.run_id)
            if status == "cooling":
                self.assertNotIn(result_id, inp.result_ids)
        self.assertEqual(statuses, ["cooling", "cooling", "resolved"])
        resolved_run = report.run_id
        row = self.inp(resolved_run).by_id()[result_id]
        self.assertEqual((row["lifecycle_status"], row["change"]["lifecycle_reason"]), ("resolved", "absent_for_configured_runs"))
        # A statement presenting it as a current concern is refused; as resolved it is accepted.
        self.model.script(citing(result_id), citing(result_id))
        refused = self.synthesizer.synthesize(resolved_run)
        self.assertEqual(refused.failure, "validation:LIFECYCLE_CONTRADICTION")
        outcome = self.synthesizer.synthesize(resolved_run)
        self.assertEqual(outcome.decision, Decision.SYNTHESIZED)
        brief = self.current()
        self.assertIn(result_id, {row.result_id for row in brief.input_results if row.lifecycle_status.value == "resolved"})
        # The resolution stays in the input for the run that resolved it and the next two, then drops out.
        later = [self.run_snapshot(payload_with(without_deadline_12())).run_id for _ in range(3)]
        self.assertIn(result_id, self.inp(later[0]).result_ids)
        self.assertIn(result_id, self.inp(later[1]).result_ids)
        self.assertNotIn(result_id, self.inp(later[2]).result_ids)

    # --- persistence and versions ---------------------------------------------------------------------------------------------

    def test_first_brief_is_persisted_with_its_inputs_and_references(self):
        first = self.run_snapshot()
        outcome = self.synthesizer.synthesize(first.run_id)
        self.assertEqual((outcome.decision, outcome.brief_version, outcome.llm_calls), (Decision.SYNTHESIZED, 1, 1))
        brief = self.current()
        self.assertEqual((brief.version, brief.run_id, brief.generator.kind, brief.prompt_version), (1, first.run_id, "model", "executive-v1"))
        self.assertEqual(brief.input_fingerprint, self.inp(first.run_id).fingerprint)
        with self.executive_store.transaction() as tx:
            inputs = tx.brief_inputs(brief.brief_id, 1)
            refs = tx.statement_refs(brief.brief_id, 1)
            runs = tx.synthesis_runs(first.run_id)
        self.assertEqual([(r["result_id"], r["result_version"], r["lifecycle_status"]) for r in inputs],
                         [(r.result_id, r.result_version, r.lifecycle_status.value) for r in brief.input_results])
        self.assertEqual(sorted({r["result_id"] for r in refs}), list(brief.referenced_result_ids))
        self.assertTrue(refs)
        self.assertEqual([(r["decision"], r["brief_version"], r["llm_calls"]) for r in runs], [("synthesized", 1, 1)])
        calls = self.executive_calls(first.run_id)
        self.assertEqual([(c["status"], c["prompt_version"], c["case_id"]) for c in calls], [("succeeded", "executive-v1", None)])
        self.assertEqual(brief.generator.request_ids, (calls[0]["request_id"],))

    def test_identical_input_makes_zero_model_calls_and_preserves_the_brief(self):
        first = self.run_snapshot()
        self.synthesizer.synthesize(first.run_id)
        before = self.current()
        requests = len(self.model.requests)
        again = self.synthesizer.synthesize(first.run_id)
        self.assertEqual((again.decision, again.llm_calls, again.brief_version), (Decision.UNCHANGED, 0, 1))
        self.assertEqual(len(self.model.requests), requests)
        self.assertEqual(self.current().to_dict(), before.to_dict())          # same wording, same version: no prose churn
        self.assertEqual(len(self.executive_store.brief_history()), 1)
        self.assertEqual([r["decision"] for r in self.executive_store.synthesis_runs(first.run_id)], ["synthesized", "unchanged"])

    def test_material_reasoning_change_makes_new_synthesis_work_and_keeps_history(self):
        first = self.run_snapshot()
        self.synthesizer.synthesize(first.run_id)
        second = self.run_snapshot()                       # same evidence: new -> active (a lifecycle change)
        self.assertEqual(self.synthesizer.synthesize(second.run_id).brief_version, 2)
        self.assertEqual(self.synthesizer.synthesize(second.run_id).decision, Decision.UNCHANGED)
        third = self.run_snapshot(payload_with(changed_rows()))   # changed evidence: one card patched (updated)
        result_id = self.open_result_id(self.case_id(third))
        self.assertEqual(self.store.get_result(result_id).lifecycle_status.value, "updated")
        outcome = self.synthesizer.synthesize(third.run_id)
        self.assertEqual((outcome.decision, outcome.brief_version, outcome.llm_calls), (Decision.SYNTHESIZED, 3, 1))
        history = self.executive_store.brief_history()
        self.assertEqual([(b.version, b.run_id) for b in history], [(1, first.run_id), (2, second.run_id), (3, third.run_id)])
        self.assertEqual(len({b.brief_id for b in history}), 1)
        self.assertEqual(len({b.input_fingerprint for b in history}), 3)
        updated = self.inp(third.run_id).by_id()[result_id]
        self.assertEqual(updated["lifecycle_status"], "updated")
        self.assertTrue(updated["change"]["patched_fields"])

    def test_no_eligible_result_gives_a_deterministic_empty_brief_without_a_model(self):
        run_id = self.run_snapshot(payload_with([])).run_id
        outcome = self.synthesizer.synthesize(run_id)
        self.assertEqual((outcome.decision, outcome.llm_calls), (Decision.SYNTHESIZED_EMPTY, 0))
        self.assertEqual(self.model.requests, [])
        brief = self.current()
        self.assertEqual((brief.generator.kind, brief.input_results, brief.referenced_result_ids), ("deterministic_empty", (), ()))
        self.assertEqual(self.synthesizer.synthesize(run_id).decision, Decision.UNCHANGED)

    # --- failure preservation -------------------------------------------------------------------------------------------------

    def assert_preserved(self, outcome, before, failure):
        self.assertEqual((outcome.decision, outcome.failure), (Decision.FAILED, failure))
        self.assertEqual((outcome.brief_id, outcome.brief_version), (before.brief_id, before.version))
        self.assertEqual(self.current().to_dict(), before.to_dict())
        self.assertEqual(len(self.executive_store.brief_history()), before.version)

    def prepared(self):
        """A valid brief (version 1), then a run whose input differs (new -> active), so synthesis must be attempted."""
        first = self.run_snapshot()
        self.synthesizer.synthesize(first.run_id)
        second = self.run_snapshot()
        return self.current(), second.run_id

    def test_provider_failure_preserves_the_previous_brief(self):
        before, run_id = self.prepared()
        self.model.script(ProviderUnavailable("down", status=503), ProviderUnavailable("down", status=503))
        self.assert_preserved(self.synthesizer.synthesize(run_id), before, "provider:provider_unavailable")
        row = self.executive_store.synthesis_runs(run_id)[-1]
        self.assertEqual((row["decision"], row["brief_version"], row["failure"]), ("failed", 1, "provider:provider_unavailable"))
        self.assertEqual([c["status"] for c in self.executive_calls(run_id)], ["failed"])
        # The input still differs from the current brief: the next attempt synthesizes (no work is lost to the failure).
        self.assertEqual(self.synthesizer.synthesize(run_id).brief_version, 2)

    def test_invalid_structured_output_preserves_the_previous_brief(self):
        before, run_id = self.prepared()
        self.model.script("not json at all", '{"sections": {"top_concerns": "oops"}}')
        self.assert_preserved(self.synthesizer.synthesize(run_id), before, "provider:invalid_structured_output")

    def test_validator_rejection_preserves_the_previous_brief_and_keeps_the_candidate_out_of_view(self):
        before, run_id = self.prepared()
        self.model.script(citing(RAW_DETECTOR), citing(RAW_DETECTOR))
        outcome = self.synthesizer.synthesize(run_id)
        self.assert_preserved(outcome, before, "validation:RAW_SOURCE_REFERENCE")
        self.assertEqual(outcome.llm_calls, 2)                        # one bounded corrective re-ask
        self.assertIn("RAW_SOURCE_REFERENCE at sections/top_concerns/0/result_ids/0", self.model.requests[-1].messages[-1].content)
        row = self.executive_store.synthesis_runs(run_id)[-1]
        self.assertEqual(row["error_codes"], ["RAW_SOURCE_REFERENCE"])
        self.assertEqual(row["rejected_candidate"]["sections"]["top_concerns"][0]["result_ids"], [RAW_DETECTOR])
        for brief in self.executive_store.brief_history():
            self.assertNotIn(RAW_DETECTOR, str(brief.to_dict()))

    def test_a_corrected_answer_after_a_refusal_is_accepted(self):
        before, run_id = self.prepared()
        self.model.script(citing(RAW_DETECTOR))
        outcome = self.synthesizer.synthesize(run_id)
        self.assertEqual((outcome.decision, outcome.brief_version, outcome.llm_calls), (Decision.SYNTHESIZED, before.version + 1, 2))

    def test_a_substituted_model_is_refused_without_a_retry(self):
        before, run_id = self.prepared()
        self.model.model = "openai/gpt-5.6-sol-pro"
        outcome = self.synthesizer.synthesize(run_id)
        self.assert_preserved(outcome, before, "validation:MODEL_SUBSTITUTED")
        self.assertEqual(outcome.llm_calls, 1)

    def test_a_concurrent_writer_wins_and_the_loser_preserves_its_brief(self):
        before, run_id = self.prepared()
        winner_holder = {}

        def race(payload):
            # Another writer commits version 2 while this synthesizer waits for its model answer.
            inp = self.inp(run_id)
            winner = ExecutiveBrief.from_dict(assemble_brief(generic_answer(payload), inp, BriefProvenance(
                before.brief_id, before.version + 1, run_id, "2026-10-02T00:00:00Z", provider="fake", model=self.model.model,
                request_ids=("req_" + "9" * 32,))))
            with self.executive_store.transaction() as tx:
                tx.append_brief(winner, expected_version=before.version)
            winner_holder["brief"] = winner
            return generic_answer(payload)

        self.model.script(race)
        outcome = self.synthesizer.synthesize(run_id)
        self.assertEqual((outcome.decision, outcome.failure, outcome.brief_version), (Decision.FAILED, "conflict:VersionConflict", before.version + 1))
        self.assertEqual(self.current().to_dict(), winner_holder["brief"].to_dict())
        self.assertEqual([b.version for b in self.executive_store.brief_history()], [1, 2])

    def test_version_conflicts_at_the_store(self):
        before, run_id = self.prepared()
        inp = self.inp(run_id)
        nxt = ExecutiveBrief.from_dict(assemble_brief(generic_answer(thaw(inp.payload)), inp, BriefProvenance(
            before.brief_id, 2, run_id, "2026-10-02T00:00:00Z", provider="fake", model=self.model.model, request_ids=("req_" + "8" * 32,))))
        with self.executive_store.transaction() as tx:
            tx.append_brief(nxt, expected_version=1)
        for expected in (1, None):
            with self.subTest(expected=expected), self.assertRaises(VersionConflict), self.executive_store.transaction() as tx:
                tx.append_brief(nxt if expected == 1 else dataclasses.replace(nxt, version=1, brief_id="eb1_" + "f" * 32), expected_version=expected)
        self.assertEqual(self.current().version, 2)

    def test_one_synthesizer_at_a_time(self):
        first = self.run_snapshot()
        with self.store.session_lock(EXECUTIVE_LOCK_KEY) as acquired:
            self.assertTrue(acquired)
            outcome = self.synthesizer.synthesize(first.run_id)
        self.assertEqual((outcome.decision, outcome.skipped), (None, "executive_busy"))
        self.assertEqual(self.model.requests, [])

    def test_a_candidate_the_database_cannot_store_never_loses_the_audit(self):
        before, run_id = self.prepared()
        nul = lambda payload: {**generic_answer(payload), "sections": {**generic_answer(payload)["sections"],
                                                                     "uncertainty": [{"text": "Weak\x00.", "result_ids": [payload["results"][0]["result_id"]]}]}}
        self.model.script(nul, nul)
        outcome = self.synthesizer.synthesize(run_id)
        self.assert_preserved(outcome, before, "validation:INVALID_TEXT")
        row = self.executive_store.synthesis_runs(run_id)[-1]
        self.assertEqual(row["error_codes"], ["INVALID_TEXT"])
        self.assertEqual(row["rejected_candidate"]["sections"]["uncertainty"][0]["text"], "Weak\ufffd.")

    def test_a_store_failure_on_commit_is_recorded_and_preserves_the_brief(self):
        before, run_id = self.prepared()
        original = ExecutiveTransaction.append_brief

        def broken(tx, brief, *, expected_version):
            raise RuntimeError("disk full")

        ExecutiveTransaction.append_brief = broken
        try:
            outcome = self.synthesizer.synthesize(run_id)
        finally:
            ExecutiveTransaction.append_brief = original
        self.assert_preserved(outcome, before, "store:RuntimeError")
        self.assertEqual(self.executive_store.synthesis_runs(run_id)[-1]["failure"], "store:RuntimeError")

    def test_the_input_is_read_from_one_snapshot(self):
        with self.executive_store.snapshot() as tx:
            self.assertEqual(tx._one("SHOW transaction_isolation")["transaction_isolation"], "repeatable read")
            self.assertEqual(tx._one("SHOW transaction_read_only")["transaction_read_only"], "on")

    # --- migration and constraints --------------------------------------------------------------------------------------------

    def test_migration_is_clean_repeatable_and_healthy(self):
        self.assertEqual(apply_migrations(self.store.db), [])
        report = database_health(self.store.db)
        self.assertTrue(report["ok"], report)
        self.assertIn("0500_executive_briefs.sql", report["applied"])

    def test_the_database_enforces_grounding_and_append_only_history(self):
        first = self.run_snapshot()
        self.synthesizer.synthesize(first.run_id)
        brief = self.current()
        outside = "rr1_" + "0" * 32
        statements = [
            # a statement reference to a result that is not in this version's input
            (("INSERT INTO executive_statement_refs (brief_id, version, section, statement_id, result_id) VALUES (%s, 1, 'top_concerns', "
              "'top_concerns-9', %s)"), (brief.brief_id, outside)),
            # an input row naming a result version that does not exist
            (("INSERT INTO executive_brief_inputs (brief_id, version, result_id, result_version, lifecycle_status, position) "
              "VALUES (%s, 1, %s, 99, 'active', 99)"), (brief.brief_id, brief.input_results[0].result_id)),
            ("UPDATE executive_brief_versions SET validator_version = 'x' WHERE brief_id = %s", (brief.brief_id,)),
            ("DELETE FROM executive_brief_runs", ()),
            ("DELETE FROM executive_briefs", ()),
            ("UPDATE executive_briefs SET scope = 'company', brief_id = %s", ("eb1_" + "1" * 32,)),
            ("INSERT INTO executive_brief_runs (synthesis_id, run_id, scope, decision, policy_version) VALUES (%s, %s, 'company', 'unchanged', 'p')",
             ("xs_" + "1" * 32, first.run_id)),
        ]
        for sql, params in statements:
            with self.subTest(sql=sql[:60]), self.assertRaises(psycopg.Error), self.store.db.transaction() as conn:
                conn.execute(sql, params or None)
        self.assertEqual(self.current().to_dict(), brief.to_dict())

    def test_empty_sections_are_still_versioned_by_run(self):
        first = self.run_snapshot()
        self.model.script(lambda payload: {"sections": {name: [] for name in SECTIONS}})
        outcome = self.synthesizer.synthesize(first.run_id)
        self.assertEqual(outcome.decision, Decision.SYNTHESIZED)
        self.assertEqual(self.current().referenced_result_ids, ())


if __name__ == "__main__":
    unittest.main()
