"""Reasoning V3 07–14 integration gate: the engine (Phases 07–09) wired to the human-context and memory layer (Phases 10–14).

End to end on the real Change Gate, engine, validation, PostgreSQL store, context assembler, Atlas questions and memory sync, with an
offline model (``ScriptedAnalyst``) and an offline Honcho (``FakeHoncho``). No network, ever.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

import reasoning_snapshots as snapshots
from reasoning_db import fresh_database, requires_db
from reasoning_engine_support import DEADLINE_12, changed_rows, payload_with, times, without_deadline_12
from reasoning_fakes import ScriptedAnalyst, gateway, request_input, update_answer

from atlas_reasoning import analyst
from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.contracts import ContractViolation, result_case_errors
from atlas_reasoning.engine import ENGINE_LOCK_KEY, ReasoningEngine
from atlas_reasoning.enums import NoteSource, WorkStatus
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.manager_notes import ManagerNotes
from atlas_reasoning.memory import MemoryRecord, editor_session, result_session
from atlas_reasoning.output_checks import case_numbers
from atlas_reasoning.reasoning_context import HumanContext
from atlas_reasoning.settings import PINNED_MODEL, model_identity_matches
from atlas_reasoning.store import human_context as sql
from atlas_reasoning.store import memory_log
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.teach_atlas import TeachAtlas

BOSS = "boss@example.com"
SPEED_12 = "case-identity-v1|editor|editor-label-12|speed"
DEADLINE_15 = "case-identity-v1|editor|editor-label-15|deadline"
TEAM = "case-identity-v1|team|team|deadline"
ASSIGNMENT_QUESTION = "Did anything change in how this work was assigned?"


class CommittedFirstHoncho(FakeHoncho):
    """A FakeHoncho that proves PostgreSQL precedes memory: every copy it receives must name a canonical row that is already
    committed (read through a separate connection, which sees committed state only)."""

    store: ReasoningStore | None = None
    violations: list[str]

    def write(self, record: MemoryRecord) -> str:
        if self.store is not None:
            with self.store.transaction() as tx:
                try:
                    if record.source_type == NoteSource.PRIOR_REASONING_SUMMARY:
                        tx.get_result(record.source_id)
                    elif record.source_type == NoteSource.ATLAS_QUESTION:
                        sql.get_question(tx, record.source_id)
                except Exception:  # noqa: BLE001
                    self.violations.append(f"{record.source_type}:{record.source_id}")
        return super().write(record)


@requires_db
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.honcho = CommittedFirstHoncho()
        self.honcho.store, self.honcho.violations = self.store, []
        self.context = HumanContext(self.store, self.honcho, env={})
        self.transport = ScriptedAnalyst()
        self.engine = ReasoningEngine(self.store, gateway(self.transport, recorder=StoreCallRecorder(self.store)), context=self.context)
        self.notes = ManagerNotes(self.store, self.context.sync)
        self.teach = TeachAtlas(self.store, self.context.sync)
        self.t = times(10)
        self.runs = 0

    # --- helpers ------------------------------------------------------------------------------------------------------------

    def run_snapshot(self, payload=None):
        report = run_gate(payload or snapshots.reasoning_input(), self.store, now=self.t[self.runs])
        self.runs += 1
        return report, self.engine.process_run(report.run_id)

    def case_id(self, report, identity_key):
        return next(d.case_id for d in report.decisions if d.identity_key == identity_key)

    def result_id(self, case_id):
        with self.store.transaction() as tx:
            return tx.open_result(case_id).result_id

    def sent(self, case_id, purpose=None):
        """The request input of the latest call about ``case_id`` (optionally of one purpose)."""
        matching = [r for r in self.transport.requests if r.context.case_id == case_id and (purpose is None or r.context.purpose == purpose)]
        self.assertTrue(matching, f"no {purpose or ''} request for {case_id}")
        return matching[-1], request_input(matching[-1])

    def injections(self, case_id):
        with self.store.transaction() as tx:
            return tx._all("SELECT * FROM memory_injections WHERE case_id = %s ORDER BY created_at", (case_id,))

    def open_questions(self, case_id):
        with self.store.transaction() as tx:
            return sql.questions(tx, case_ids=[case_id], states=["open"])

    @staticmethod
    def evidence_text(payload):
        return json.dumps({key: payload[key] for key in ("statements", "evidence_blocks", "evidence_references", "supporting_findings",
                                                         "contradicting_findings")})

    # --- flows --------------------------------------------------------------------------------------------------------------

    def test_new_result_flow(self):
        """Change Gate new → scoped context → analyst request → structured result → committed → questions → memory sync."""
        report, engine_report = self.run_snapshot()
        case_id = self.case_id(report, DEADLINE_12)
        outcome = next(o for o in engine_report.outcomes if o.case_id == case_id)
        self.assertEqual((outcome.status, outcome.change_kind, outcome.version), ("done", "created", 1))
        request, payload = self.sent(case_id, "analyst")
        self.assertEqual(payload["manager_context"], [])
        # The injection audit carries the exact request ID, run and work item of the call, recorded before the call.
        [injection] = self.injections(case_id)
        self.assertEqual((injection["request_id"], injection["run_id"], injection["work_item_id"], injection["purpose"], injection["memory_status"]),
                         (request.context.request_id, report.run_id, outcome.work_item_id, "analyst", "available"))
        with self.store.transaction() as tx:
            call = tx._one("SELECT * FROM llm_calls WHERE request_id = %s", (request.context.request_id,))
        self.assertEqual((call["status"], call["work_item_id"]), ("succeeded", outcome.work_item_id))
        # The committed version's question became one canonical open question, attributed to that version.
        [question] = self.open_questions(case_id)
        self.assertEqual((question["question_text"], question["result_id"], question["result_version"]),
                         (ASSIGNMENT_QUESTION, outcome.result_id, 1))
        self.assertEqual(outcome.followup["questions"], {"created": 1})
        # Then the result summary went to memory: result and Editor sessions, after the canonical commit.
        self.assertEqual(outcome.followup["memory_sync"], {"synced": 2})
        sessions = {m.record.session_key for m in self.honcho.messages() if m.record.source_id == outcome.result_id}
        self.assertEqual(sessions, {result_session(outcome.result_id), editor_session("editor-label-12")})
        self.assertEqual(self.honcho.violations, [])

    def test_updated_result_flow(self):
        """Change Gate updated → scoped context → update request → deterministic patch → new version → questions → memory sync."""
        first, _ = self.run_snapshot()
        case_id = self.case_id(first, DEADLINE_12)
        result_id = self.result_id(case_id)
        note = self.notes.create(result_id, "Class B work moved to another Editor this month.", author=BOSS).note
        _, engine_report = self.run_snapshot(payload_with(changed_rows()))
        outcome = next(o for o in engine_report.outcomes if o.case_id == case_id)
        self.assertEqual((outcome.status, outcome.change_kind, outcome.result_id), ("done", "patched", result_id))
        request, payload = self.sent(case_id, "update")
        # The note reached the update request as attributed management context, never as evidence.
        self.assertEqual([(c["source_type"], c["author"]) for c in payload["manager_context"]], [("manager_interpretation", BOSS)])
        self.assertNotIn(note.body, self.evidence_text(payload))
        injection = self.injections(case_id)[-1]
        self.assertEqual((injection["request_id"], injection["purpose"], injection["result_id"], injection["work_item_id"]),
                         (request.context.request_id, "update", result_id, outcome.work_item_id))
        selected = [(row["source_type"], row["source_id"], row["session_key"]) for row in injection["selected"]]
        self.assertEqual(selected[0], ("manager_interpretation", note.note_id, result_session(result_id)))
        # Remembered prior reasoning: only this Editor's other cards and its Video Types' cards (this card itself reaches the model
        # as the previous result), never another Editor's.
        remembered = [row for row in injection["selected"] if row["source_type"] == "prior_reasoning_summary"]
        self.assertIn(editor_session("editor-label-12"), {row["session_key"] for row in remembered})
        self.assertTrue(all(row["session_key"] == editor_session("editor-label-12") or row["session_key"].startswith("video-type:")
                            for row in remembered))
        self.assertNotIn(result_id, {row["source_id"] for row in remembered})
        # Questions reconciled from the accepted current version: the same open question, now asked by version 3.
        [question] = self.open_questions(case_id)
        self.assertEqual((question["result_version"], question["ask_count"]), (outcome.version, 2))
        # The new version's summary replaced the old copy in memory.
        live = [m for m in self.honcho.messages(result_session(result_id)) if m.record.source_type == NoteSource.PRIOR_REASONING_SUMMARY and not m.retired]
        self.assertEqual([m.record.metadata["result_version"] for m in live], [outcome.version])
        self.assertEqual(self.honcho.violations, [])

    def test_honcho_unavailable(self):
        """Memory retrieval degraded → reasoning still runs on canonical context → result committed → failed sync recorded."""
        self.honcho.outage()
        report, engine_report = self.run_snapshot()
        self.assertEqual(engine_report.failed, ())
        case_id = self.case_id(report, DEADLINE_12)
        result_id = self.result_id(case_id)
        [injection] = self.injections(case_id)
        self.assertEqual((injection["memory_status"], injection["degraded_reason"]), ("degraded", "memory_unavailable"))
        _, payload = self.sent(case_id, "analyst")
        self.assertEqual(payload["memory_context"], [])
        with self.store.transaction() as tx:
            rows = memory_log.rows(tx, source_type="prior_reasoning_summary", source_id=result_id)
        self.assertEqual({row["status"] for row in rows}, {"failed"})
        self.assertEqual(self.store.get_result(result_id).version, 1)            # canonical result untouched
        self.honcho.restore()
        retried = self.context.sync.retry(limit=500)
        self.assertTrue(retried and {o.status for o in retried} <= {"synced", "duplicate"})
        with self.store.transaction() as tx:
            self.assertEqual({row["status"] for row in memory_log.rows(tx, source_type="prior_reasoning_summary", source_id=result_id)}, {"synced"})

    def test_answered_question_is_attributed_context_not_evidence(self):
        first, _ = self.run_snapshot()
        case_id = self.case_id(first, DEADLINE_12)
        [question] = self.open_questions(case_id)
        answer, _, _ = self.context.questions.answer(question["question_id"], "Yes, Class B work went to another Editor.", author=BOSS)
        _, engine_report = self.run_snapshot(payload_with(changed_rows()))
        _, payload = self.sent(case_id, "update")
        [context] = [c for c in payload["manager_context"] if c["source_type"] == "manager_answer"]
        self.assertIn(answer.body, context["body"])
        self.assertEqual(context["author"], BOSS)
        self.assertNotIn(answer.body, self.evidence_text(payload))
        self.assertNotIn(answer.answer_id, {ref["ref_id"] for ref in payload["evidence_references"]})
        # The answered question is not asked again by the new version.
        self.assertEqual(self.open_questions(case_id), [])
        outcome = next(o for o in engine_report.outcomes if o.case_id == case_id)
        self.assertEqual(outcome.error, None)
        self.assertEqual(outcome.followup["questions"], {"suppressed_answered": 1})

    def test_teachings_reach_only_matching_cases_and_expire(self):
        self.teach.create(body="Editor 12 covers urgent Class B work.", scope_type="editor", scope_id="editor-label-12", teaching_type="context",
                          validity_mode="until_changed", author=BOSS)
        self.teach.create(body="Editor 15 is part-time this quarter.", scope_type="editor", scope_id="editor-label-15", teaching_type="context",
                          validity_mode="until_changed", author=BOSS)
        self.teach.create(body="Editor 12 was on leave in January.", scope_type="editor", scope_id="editor-label-12",
                          teaching_type="temporary_situation", validity_mode="date_range", valid_from="2026-01-01", valid_until="2026-01-31",
                          author=BOSS)
        report, _ = self.run_snapshot()

        def teachings(identity):
            _, payload = self.sent(self.case_id(report, identity), "analyst")
            return [c["body"] for c in payload["manager_context"] if c["source_type"] == "management_teaching"]

        for identity in (DEADLINE_12, SPEED_12):
            body = " | ".join(teachings(identity))
            self.assertIn("Editor 12 covers urgent Class B work.", body)
            self.assertNotIn("Editor 15", body)
            self.assertNotIn("on leave in January", body)          # expired: never injected
        self.assertEqual([b for b in teachings(DEADLINE_15) if "Editor 12" in b], [])
        self.assertIn("Editor 15 is part-time this quarter.", " | ".join(teachings(DEADLINE_15)))
        self.assertEqual(teachings(TEAM), [])                      # a team case gets no Editor's teaching

    def test_editor_a_memory_never_reaches_editor_b(self):
        first, _ = self.run_snapshot()
        a_result = self.result_id(self.case_id(first, DEADLINE_12))
        self.notes.create(a_result, "Editor 12 had a family emergency.", author=BOSS)
        changed = changed_rows()
        for row in changed:     # make Editor 15's deadline case change too, so it is reasoned again with memory present
            if row["scope"].get("editor_id") == "editor-label-15" and row["statements"][0]["params"].get("current") is not None:
                row["statements"][0]["params"]["current"] = 0.99
                break
        report, _ = self.run_snapshot(payload_with(changed))
        b_case = self.case_id(report, DEADLINE_15)
        self.sent(b_case, "update")      # Editor 15's card was reasoned again while Editor 12's note and memory existed
        for request in [r for r in self.transport.requests if r.context.case_id == b_case]:
            payload = request_input(request)
            text = json.dumps([payload["manager_context"], payload["memory_context"]])
            self.assertNotIn("Editor 12", text)
            self.assertNotIn(a_result, text)
        for injection in self.injections(b_case):
            self.assertNotIn(editor_session("editor-label-12"), injection["sessions"])
            self.assertNotIn(result_session(a_result), injection["sessions"])
        self.assertTrue(any(editor_session("editor-label-12") in i["sessions"] for i in self.injections(self.case_id(report, DEADLINE_12))))

    def test_same_evidence_still_creates_zero_model_work(self):
        """New human context never defeats the Change Gate: same case and evidence → zero model work."""
        first, _ = self.run_snapshot()
        case_id = self.case_id(first, DEADLINE_12)
        result_id = self.result_id(case_id)
        self.notes.create(result_id, "Seasonal spike.", author=BOSS)
        self.teach.create(body="Deadlines in October are client-driven.", scope_type="company", scope_id=None, teaching_type="context",
                          validity_mode="until_changed", author=BOSS)
        [question] = self.open_questions(case_id)
        self.context.questions.answer(question["question_id"], "No change in assignments.", author=BOSS)
        calls, injections = len(self.transport.requests), len(self.injections(case_id))
        again, engine_report = self.run_snapshot()
        self.assertEqual(again.counts["llm_work_items"], 0)
        self.assertEqual([o for o in engine_report.outcomes if o.status != WorkStatus.DONE], [])
        self.assertEqual(len(self.transport.requests), calls)
        self.assertEqual(len(self.injections(case_id)), injections)

    def test_no_change_review_asks_nothing_and_writes_no_memory(self):
        first, _ = self.run_snapshot()
        case_id = self.case_id(first, DEADLINE_12)
        result_id = self.result_id(case_id)
        self.transport.script(case_id, lambda payload: update_answer(payload, change={}, rationale="The card still holds."))
        writes = len([c for c in self.honcho.calls if c[0] == "write"])
        with self.store.transaction() as tx:
            asks = len(sql.asks(tx, case_id))
        _, engine_report = self.run_snapshot(payload_with(changed_rows()))
        outcome = next(o for o in engine_report.outcomes if o.case_id == case_id)
        self.assertEqual(outcome.change_kind, "no_change_review")
        self.assertEqual(outcome.followup["skipped"], "no_change_review: no visible change")
        self.assertEqual(len([c for c in self.honcho.calls if c[0] == "write"]), writes)
        with self.store.transaction() as tx:
            self.assertEqual(len(sql.asks(tx, case_id)), asks)
        # The remembered summary still says what the current version says, so it stays usable context.
        source = self.context.assembler.sources[NoteSource.PRIOR_REASONING_SUMMARY]
        [copy] = [m for m in self.honcho.read(editor_session("editor-label-12"), limit=50) if m.source_id == result_id]
        scope = type("Scope", (), {"previous_result_id": None})()
        with self.store.transaction() as tx:
            self.assertTrue(source.is_current(tx, copy, scope, datetime.now(UTC)))

    def test_pending_work_for_a_disappeared_case_is_closed_without_a_model_call(self):
        first = run_gate(snapshots.reasoning_input(), self.store, now=self.t[0])
        case_id = self.case_id(first, DEADLINE_12)
        run_gate(payload_with(without_deadline_12()), self.store, now=self.t[1])     # the case disappears before the engine runs
        outcomes = self.engine.process_work(self.engine.pending_work())
        outcome = next(o for o in outcomes if o.case_id == case_id)
        self.assertEqual((outcome.status, outcome.result_id), ("done", None))
        self.assertNotIn(case_id, {r.context.case_id for r in self.transport.requests})

    def test_one_engine_at_a_time(self):
        report = run_gate(snapshots.reasoning_input(), self.store, now=self.t[0])
        with self.store.session_lock(ENGINE_LOCK_KEY) as held:
            self.assertTrue(held)
            busy = self.engine.process_run(report.run_id)
        self.assertEqual((busy.skipped, busy.outcomes), ("engine_busy", ()))
        self.assertEqual(self.transport.requests, [])
        self.assertEqual(self.engine.process_run(report.run_id).skipped, None)

    def test_model_identity(self):
        report = run_gate(snapshots.reasoning_input(), self.store, now=self.t[0])
        self.transport.model = PINNED_MODEL + "-20260709"         # OpenRouter's dated canonical slug of the pinned model
        outcomes = self.engine.process_run(report.run_id).outcomes
        self.assertEqual({o.status for o in outcomes}, {"done"})

    def test_a_substituted_model_is_refused(self):
        report = run_gate(snapshots.reasoning_input(), self.store, now=self.t[0])
        self.transport.model = "openai/gpt-5.6-sol-pro"
        outcomes = self.engine.process_run(report.run_id).outcomes
        self.assertEqual({o.error for o in outcomes}, {"validation:MODEL_SUBSTITUTED"})


class ReviewFixTests(unittest.TestCase):
    """Independent review of PR #34: model identity, evidence roles and invented numbers."""

    def test_model_identity_accepts_only_the_pinned_slug_or_its_dated_canonical_slug(self):
        self.assertTrue(model_identity_matches(PINNED_MODEL, PINNED_MODEL))
        self.assertTrue(model_identity_matches(PINNED_MODEL, PINNED_MODEL + "-20260709"))
        for other in ("openai/gpt-5.6-sol-pro", "openai/gpt-5.6-sol-pro-20260709", "openai/gpt-5.6-sol:batch", "openai/gpt-5.6-sol-2026-07-09",
                      "openai/gpt-5.6-sol-202607091", "openai/gpt-5.6-luna", "gpt-5.6-sol", ""):
            with self.subTest(other=other):
                self.assertFalse(model_identity_matches(PINNED_MODEL, other))

    def _case_and_result(self):
        import reasoning_factory as factory

        case = factory.case_dict()
        result = factory.result_dict(case)
        return case, result

    def test_counter_evidence_must_cite_contradicting_evidence(self):
        case, result = self._case_and_result()
        self.assertEqual(result_case_errors(result, case), [])
        references = case["current_evidence"]["references"]
        contradicting_members = {row["member_key"] for row in case["contradicting_findings"]}
        counter = {ref["ref_id"] for ref in references if ref["role"] == "contradicting" or ref["member_key"] in contradicting_members}
        supporting = [ref["ref_id"] for ref in references if ref["ref_id"] not in counter]
        self.assertTrue(counter and supporting)
        wrong = json.loads(json.dumps(result))
        wrong["counter_evidence"] = [{"statement": "Something else.", "evidence_refs": supporting[:1]}]
        self.assertIn("COUNTER_EVIDENCE_MISSING", " ".join(result_case_errors(wrong, case)))
        misused = json.loads(json.dumps(result))
        misused_case = json.loads(json.dumps(case))
        misused_case["current_evidence"]["references"] = [dict(ref, role="contradicting") if ref["ref_id"] == min(counter) else ref
                                                          for ref in misused_case["current_evidence"]["references"]]
        misused["supporting_evidence"][0]["evidence_refs"] = [*supporting[:1], min(counter)]
        self.assertIn("EVIDENCE_ROLE_MISMATCH", " ".join(result_case_errors(misused, misused_case)))

    def test_counts_and_dates_are_not_scaled_into_percentages(self):
        case, _ = self._case_and_result()
        allowed = case_numbers(case)
        self.assertIn(68.75, allowed)                               # the rate 0.6875 written as a percentage
        sample = case["supporting_findings"][0]["sample_size"]
        self.assertNotIn(sample * 100.0, allowed)                   # a count is never scaled
        self.assertNotIn(2026 * 100.0, allowed)                     # nor a date part

    def test_numbers_in_human_context_are_never_admitted(self):
        import reasoning_factory as factory

        case = factory.case_dict()
        case["manager_context"] = [{"source_type": "manager_answer", "source_id": "aa_1", "body": "It took 37 days.", "author": BOSS,
                                    "recorded_at": "2026-09-30T00:00:00Z"}]
        self.assertNotIn(37.0, case_numbers(case))

    def test_invalid_model_output_still_raises_a_contract_violation(self):
        from reasoning_engine_support import new_case

        from atlas_reasoning.provider import ProviderResponse

        case = new_case()
        response = ProviderResponse(request_id="req_" + "1" * 32, model=PINNED_MODEL, content="", parsed={"title": "only a title"})
        with self.assertRaises(ContractViolation):
            analyst.result_from_response(case, response, provider="fake", result_id="rr1_" + "c" * 32, now="2026-09-28T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
