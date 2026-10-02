"""Reasoning V3 Phase 13: Atlas questions and management answers (``REV/13``)."""

import json
import threading
import unittest

import psycopg
from human_context_fixtures import editor_case, patch_result, question, seed_result
from reasoning_db import fresh_database, requires_db

from atlas_reasoning import human_context
from atlas_reasoning.atlas_questions import AtlasQuestions, Question, QuestionClosed, dedup_key, evidence_answerable
from atlas_reasoning.enums import NoteSource
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.human_context_html import question_panel
from atlas_reasoning.management_api import ApiSettings, ManagementAPI, Request
from atlas_reasoning.manager_notes import ManagerNotes
from atlas_reasoning.memory import editor_session, result_session
from atlas_reasoning.store import human_context as sql
from atlas_reasoning.store import memory_log
from atlas_reasoning.store.repository import ReasoningStore

BOSS = "boss@example.com"
Q1 = "Did Class B assignments change in September?"


class RuleTests(unittest.TestCase):
    def test_dedup_key_ignores_case_spacing_and_end_punctuation(self):
        self.assertEqual(dedup_key(Q1), dedup_key("  did class b   ASSIGNMENTS change in september "))
        self.assertNotEqual(dedup_key(Q1), dedup_key("Did Class A assignments change in September?"))

    def test_questions_answerable_from_evidence_are_recognised(self):
        for text in ("How many projects were late in September?", "What was the late rate last month?", "Which projects were late?",
                     "When was item 1101 delivered?", "What percentage of Class B work was on time?", "How late were the deliveries?"):
            with self.subTest(text=text):
                self.assertTrue(evidence_answerable(text))
        for text in (Q1, "Was Ahmed covering for another Editor?", "Is a client deadline policy in effect?"):
            with self.subTest(text=text):
                self.assertFalse(evidence_answerable(text))


@requires_db
class QuestionTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.honcho = FakeHoncho()
        self.sync = human_context.sync_service(self.store, self.honcho)
        self.qa = AtlasQuestions(self.store, self.sync)
        self.case = editor_case("editor-a")
        self.result = seed_result(self.store, self.case, questions=[question(Q1), question("How many projects were late?")])

    def open_questions(self):
        with self.store.transaction() as tx:
            return sql.questions(tx, case_ids=[self.case["case_id"]], states=["open"])

    def test_questions_are_stored_with_their_context_and_synced(self):
        report = self.qa.record_result_questions(self.result["result_id"], run_id=self.result["_run_id"])
        self.assertEqual([outcome for _, outcome, _ in report.outcomes], ["created", "suppressed_evidence"])
        [row] = self.open_questions()
        self.assertEqual((row["question_text"], row["reason"], row["expected_context_type"], row["state"], row["result_id"], row["result_version"]),
                         (Q1, "Assignment context is not in Monday.", "assignment_context", "open", self.result["result_id"], 1))
        self.assertTrue(row["created_at"] and row["updated_at"] and row["resolved_at"] is None)
        [copy] = self.honcho.messages(result_session(self.result["result_id"]))
        self.assertEqual((copy.record.source_type, copy.record.peer_id), (NoteSource.ATLAS_QUESTION, "atlas"))
        with self.store.transaction() as tx:
            asks = sql.asks(tx, self.case["case_id"])
        self.assertEqual(sorted(a["outcome"] for a in asks), ["created", "suppressed_evidence"])

    def test_no_duplicate_open_question_across_repeated_runs(self):
        self.qa.record_result_questions(self.result["result_id"])
        self.assertEqual(self.qa.record_result_questions(self.result["result_id"]).outcomes, ())    # same version again: no-op
        v2 = patch_result(self.store, self.result, self.case, questions_for_management=[question("did class b assignments change in September")])
        report = self.qa.record_result_questions(self.result["result_id"])
        self.assertEqual([outcome for _, outcome, _ in report.outcomes], ["repeated"])
        [row] = self.open_questions()
        self.assertEqual((row["ask_count"], row["result_version"]), (2, v2["version"]))
        self.assertEqual(len(self.honcho.messages(result_session(self.result["result_id"]))), 1)

    def test_concurrent_runs_create_one_question(self):
        errors = []

        def record():
            try:
                self.qa.record_result_questions(self.result["result_id"])
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        threads = [threading.Thread(target=record) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.open_questions()), 1)

    def test_dismissal(self):
        self.qa.record_result_questions(self.result["result_id"])
        [row] = self.open_questions()
        dismissed = self.qa.dismiss(row["question_id"], author=BOSS, reason="Not relevant this quarter.")
        self.assertEqual((dismissed.state, dismissed.resolved_by, dismissed.dismiss_reason), ("dismissed", BOSS, "Not relevant this quarter."))
        self.assertEqual(self.honcho.read(result_session(self.result["result_id"]), limit=5), [])   # the question's copy is retired
        self.assertEqual(self.qa.dismiss(row["question_id"], author=BOSS).state, "dismissed")       # idempotent
        with self.assertRaises(QuestionClosed):
            self.qa.answer(row["question_id"], "Too late.", author=BOSS)
        patch_result(self.store, self.result, self.case, questions_for_management=[question(Q1)])
        report = self.qa.record_result_questions(self.result["result_id"])
        self.assertEqual([outcome for _, outcome, _ in report.outcomes], ["suppressed_dismissed"])
        self.assertEqual(self.open_questions(), [])

    def test_questions_no_longer_asked_are_superseded(self):
        self.qa.record_result_questions(self.result["result_id"])
        patch_result(self.store, self.result, self.case, questions_for_management=[])
        report = self.qa.record_result_questions(self.result["result_id"])
        self.assertEqual(len(report.superseded), 1)
        self.assertEqual(self.qa.get(report.superseded[0]).state, "superseded")

    def test_answer_persistence_attribution_and_sync(self):
        self.qa.record_result_questions(self.result["result_id"])
        [row] = self.open_questions()
        answer, created, sync = self.qa.answer(row["question_id"], "Yes: Class B moved to Ahmed on 1 September.", author=BOSS)
        self.assertTrue(created)
        self.assertEqual((answer.source_type, answer.author, answer.conflicts_with_answer_id), ("manager_answer", BOSS, None))
        question_state = self.qa.get(row["question_id"])
        self.assertEqual((question_state.state, question_state.resolved_by), ("answered", BOSS))
        self.assertEqual({o.session_key for o in sync}, {result_session(self.result["result_id"]), editor_session("editor-a")})
        self.assertEqual({o.status for o in sync}, {"synced"})
        again = self.qa.answer(row["question_id"], "  yes: class b moved to Ahmed on 1 September. ", author=BOSS)
        self.assertEqual((again[0].answer_id, again[1]), (answer.answer_id, False))
        patch_result(self.store, self.result, self.case, questions_for_management=[question(Q1)])
        self.assertEqual([o for _, o, _ in self.qa.record_result_questions(self.result["result_id"]).outcomes], ["suppressed_answered"])
        with self.assertRaises(QuestionClosed):
            self.qa.dismiss(row["question_id"], author=BOSS)
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("UPDATE atlas_questions SET state = 'open', resolved_at = NULL")
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("UPDATE atlas_answers SET body = 'rewritten'")

    def test_conflicting_answers_are_preserved_and_flagged(self):
        self.qa.record_result_questions(self.result["result_id"])
        [row] = self.open_questions()
        first, _, _ = self.qa.answer(row["question_id"], "Yes, Class B moved to Ahmed.", author=BOSS)
        second, created, _ = self.qa.answer(row["question_id"], "No, assignments did not change.", author="deputy@example.com")
        self.assertTrue(created)
        self.assertEqual(second.conflicts_with_answer_id, first.answer_id)
        loaded = self.qa.get(row["question_id"])
        self.assertTrue(loaded.has_conflict)
        self.assertEqual([a.body for a in loaded.answers], ["Yes, Class B moved to Ahmed.", "No, assignments did not change."])
        context = human_context.assembler(self.store, self.honcho, env={}).assemble(self.case)
        [item] = [i for i in context.manager_context if i["source_type"] == "manager_answer"]
        self.assertEqual(item["source_id"], second.answer_id)
        self.assertIn("No, assignments did not change.", item["body"])
        self.assertIn("Conflict: management answered differently earlier", item["body"])
        self.assertIn("Yes, Class B moved to Ahmed.", item["body"])
        live = [m.source_id for m in self.honcho.read(result_session(self.result["result_id"]), limit=10)]
        self.assertIn(second.answer_id, live)

    def test_answers_are_reused_for_the_same_editor_only(self):
        self.qa.record_result_questions(self.result["result_id"])
        [row] = self.open_questions()
        answer, _, _ = self.qa.answer(row["question_id"], "Class B moved to Ahmed.", author=BOSS)
        assembler = human_context.assembler(self.store, self.honcho, env={})
        same_editor = editor_case("editor-a", topic="speed")
        seed_result(self.store, same_editor)
        reused = assembler.assemble(same_editor)
        self.assertEqual([i["memory_ref"] is not None and i["source_type"] for i in reused.memory_context["items"]
                          if "Class B moved" in i["body"]], ["manager_answer"])
        other = editor_case("editor-b")
        seed_result(self.store, other)
        self.assertNotIn("Class B moved", json.dumps(assembler.assemble(other).memory_context))
        self.assertEqual(answer.question_id, row["question_id"])

    def test_answer_survives_honcho_outage(self):
        self.qa.record_result_questions(self.result["result_id"])
        [row] = self.open_questions()
        self.honcho.outage()
        answer, created, sync = self.qa.answer(row["question_id"], "Rush season.", author=BOSS)
        self.assertTrue(created)
        self.assertEqual({o.status for o in sync}, {"failed"})
        self.assertEqual(self.qa.get(row["question_id"]).answers[0].body, "Rush season.")
        self.honcho.restore()
        self.sync.retry()
        with self.store.transaction() as tx:
            self.assertEqual({r["status"] for r in memory_log.rows(tx, source_id=answer.answer_id)}, {"synced"})


class HtmlTests(unittest.TestCase):
    def test_question_panel_escapes_and_labels(self):
        from atlas_reasoning.atlas_questions import Answer

        q = Question("aq_1", "rc1_x", "rr1_x", 1, "<b>Did</b> it change?", 'Because "context" & <i>stuff</i>', "assignment_context", "answered",
                     1, "t", "t", "t", BOSS, None,
                     (Answer("aa_1", "aq_1", "<script>x</script>", BOSS, "t", None), Answer("aa_2", "aq_1", "No.", BOSS, "t", "aa_1")))
        html = question_panel("rr1_x", [q], csrf_token="tok")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>Did", html)
        self.assertIn("&lt;b&gt;Did&lt;/b&gt;", html)
        self.assertIn("Differs from an earlier answer", html)
        self.assertIn('data-source-type="manager_answer"', html)
        self.assertNotIn("Dismiss", html)          # answered questions cannot be dismissed
        self.assertEqual(question_panel("rr1_x", [], csrf_token="tok"), "")


@requires_db
class ApiTests(unittest.TestCase):
    def test_answer_and_dismiss_routes(self):
        store = ReasoningStore(fresh_database())
        sync = human_context.sync_service(store, FakeHoncho())
        qa = AtlasQuestions(store, sync)
        api = ManagementAPI(ApiSettings(managers=frozenset({BOSS}), csrf_secret=b"s" * 40), notes=ManagerNotes(store, sync), questions=qa)
        case = editor_case("editor-a")
        result = seed_result(store, case, questions=[question(Q1), question("Was a client deadline policy in effect?", kind="client_context")])
        qa.record_result_questions(result["result_id"])
        headers = {"Content-Type": "application/json", "X-Atlas-CSRF": api.csrf_token(BOSS)}

        def call(method, path, body=None):
            return api.handle(Request(method, f"/api/reasoning{path}", BOSS, headers, json.dumps(body).encode() if body is not None else b""))

        listed = call("GET", f"/results/{result['result_id']}/questions").payload["questions"]
        self.assertEqual([q["state"] for q in listed], ["open", "open"])
        first, second = (q["question_id"] for q in listed)
        answered = call("POST", f"/questions/{first}/answers", {"body": "Yes."})
        self.assertEqual((answered.status, answered.payload["question"]["state"], answered.payload["answer"]["author"]), (200, "answered", BOSS))
        self.assertEqual(call("POST", f"/questions/{second}/dismiss", {"reason": "Not needed."}).payload["question"]["state"], "dismissed")
        self.assertEqual(call("POST", f"/questions/{second}/answers", {"body": "x"}).status, 409)
        self.assertEqual(call("POST", f"/questions/{first}/dismiss", {}).payload["error"], "QUESTION_CLOSED")
        self.assertEqual(call("POST", f"/questions/{first}/answers", {"body": "x", "author": "ceo"}).payload["error"], "UNKNOWN_FIELD")
        self.assertEqual(call("GET", "/questions/aq_missing").status, 404)


if __name__ == "__main__":
    unittest.main()
