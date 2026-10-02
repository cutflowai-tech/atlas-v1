"""Reasoning V3 Phase 12: manager interpretation notes on every reasoning card (``REV/12``)."""

import json
import threading
import unittest

import psycopg
from human_context_fixtures import editor_case, seed_result
from reasoning_db import fresh_database, requires_db, test_database_url

from atlas_reasoning import human_context
from atlas_reasoning.enums import NoteSource
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.fingerprint import canonical_evidence, evidence_fingerprint
from atlas_reasoning.human_context_html import note_panel
from atlas_reasoning.management_api import ApiSettings, ManagementAPI, Request
from atlas_reasoning.manager_notes import ManagerNotes, Note, NoteConflict
from atlas_reasoning.memory import result_session
from atlas_reasoning.settings import ReasoningConfigError
from atlas_reasoning.store import memory_log
from atlas_reasoning.store.db import Database
from atlas_reasoning.store.repository import NotFound, ReasoningStore
from atlas_reasoning.user_text import InvalidText, clean_text

BOSS = "boss@example.com"
SECRET = b"s" * 40


class TextTests(unittest.TestCase):
    def test_user_text_rules(self):
        self.assertEqual(clean_text("  a\r\nb  ", field="x", max_length=10), "a\nb")
        self.assertEqual(clean_text("safe\u202etxt.exe", field="x", max_length=50), "safetxt.exe")
        for bad, code in ((" ", "EMPTY"), ("a\x00b", "CONTROL_CHARACTERS"), ("x" * 11, "TOO_LONG"), (5, "INVALID_TYPE")):
            with self.subTest(bad=bad), self.assertRaises(InvalidText) as raised:
                clean_text(bad, field="x", max_length=10)
            self.assertEqual(raised.exception.code, code)


class HtmlTests(unittest.TestCase):
    def test_note_text_is_escaped_and_labelled(self):
        hostile = Note("mn_1", "rr1_x", "rc1_x", '<img src=x onerror="alert(1)">', '<script>alert("x")</script>\n"quoted" & more',
                       2, "2026-09-30T10:00:00.000000Z", "2026-09-30T11:00:00.000000Z")
        html = note_panel('rr1_"><b>', [hostile], csrf_token='t"><x>')
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertNotIn('"><b>', html)
        self.assertNotIn('"><x>', html)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;<br>&quot;quoted&quot; &amp; more", html)
        self.assertIn('data-source-type="manager_interpretation"', html)
        self.assertIn("Management context, not evidence", html)
        self.assertIn("No manager interpretation yet.", note_panel("rr1_y", [], csrf_token="t"))
        self.assertIn('<textarea', note_panel("rr1_y", [], csrf_token="t"))


@requires_db
class NoteTests(unittest.TestCase):
    def setUp(self):
        self.db = fresh_database()
        self.store = ReasoningStore(self.db)
        self.honcho = FakeHoncho()
        self.sync = human_context.sync_service(self.store, self.honcho)
        self.notes = ManagerNotes(self.store, self.sync)
        self.result = seed_result(self.store, editor_case("editor-a"))
        self.other = seed_result(self.store, editor_case("editor-b"))

    def test_create_persists_then_syncs_to_the_result_session(self):
        written = self.notes.create(self.result["result_id"], "Class B work moved to Ahmed in September.", author=BOSS)
        note = written.note
        self.assertEqual((note.source_type, note.author, note.revision, note.case_id), ("manager_interpretation", BOSS, 1, self.result["case_id"]))
        self.assertEqual([o.status for o in written.sync], ["synced"])
        [copy] = self.honcho.messages(result_session(self.result["result_id"]))
        self.assertEqual((copy.record.source_type, copy.record.source_id), (NoteSource.MANAGER_INTERPRETATION, note.note_id))
        self.assertEqual(self.notes.get(note.note_id), note)

    def test_edit_keeps_history_and_replaces_the_memory_copy(self):
        note = self.notes.create(self.result["result_id"], "First reading.", author=BOSS).note
        edited = self.notes.update(note.note_id, "Second reading.", author="deputy@example.com", expected_revision=1).note
        self.assertEqual((edited.revision, edited.body, edited.author), (2, "Second reading.", "deputy@example.com"))
        history = self.notes.history(note.note_id)
        self.assertEqual([(h["revision"], h["body"], h["author"]) for h in history],
                         [(1, "First reading.", BOSS), (2, "Second reading.", "deputy@example.com")])
        live = self.honcho.read(result_session(self.result["result_id"]), limit=10)
        self.assertEqual([m.body for m in live], ["Second reading."])
        same = self.notes.update(note.note_id, "Second reading.", author=BOSS, expected_revision=2)
        self.assertEqual((same.note.revision, same.sync), (2, ()))
        with self.assertRaises(NoteConflict):
            self.notes.update(note.note_id, "Stale edit.", author=BOSS, expected_revision=1)
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("UPDATE manager_note_revisions SET body = 'rewritten'")
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("UPDATE manager_notes SET source_type = 'manager_answer'")

    def test_concurrent_edits_never_lose_a_revision(self):
        note = self.notes.create(self.result["result_id"], "Base.", author=BOSS).note
        outcomes = []

        def edit(text):
            try:
                outcomes.append(self.notes.update(note.note_id, text, author=BOSS, expected_revision=1).note.revision)
            except NoteConflict:
                outcomes.append("conflict")

        threads = [threading.Thread(target=edit, args=(f"Edit {i}.",)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes, key=str), [2, "conflict", "conflict", "conflict"])
        self.assertEqual(len(self.notes.history(note.note_id)), 2)

    def test_restart_persistence(self):
        note = self.notes.create(self.result["result_id"], "Durable.", author=BOSS).note
        reopened = ManagerNotes(ReasoningStore(Database(test_database_url())), human_context.sync_service(self.store, None))
        self.assertEqual(reopened.get(note.note_id), note)
        self.assertEqual([n.note_id for n in reopened.for_result(self.result["result_id"])], [note.note_id])

    def test_honcho_failure_never_loses_the_note_and_retry_catches_up(self):
        self.honcho.outage()
        written = self.notes.create(self.result["result_id"], "Written during an outage.", author=BOSS)
        self.assertEqual([o.status for o in written.sync], ["failed"])
        self.assertEqual(self.notes.get(written.note.note_id).body, "Written during an outage.")
        self.honcho.restore()
        self.notes.update(written.note.note_id, "Edited after the outage.", author=BOSS, expected_revision=1)
        self.sync.retry()
        with self.store.transaction() as tx:
            rows = memory_log.rows(tx, source_id=written.note.note_id)
        self.assertEqual(sorted(r["status"] for r in rows), ["skipped", "synced"])   # the stale outage copy is never sent
        self.assertEqual([m.body for m in self.honcho.read(result_session(self.result["result_id"]), limit=5)], ["Edited after the outage."])

    def test_notes_stay_on_their_result(self):
        mine = self.notes.create(self.result["result_id"], "About editor A.", author=BOSS).note
        self.notes.create(self.other["result_id"], "About editor B.", author=BOSS)
        self.assertEqual([n.note_id for n in self.notes.for_result(self.result["result_id"])], [mine.note_id])
        self.assertEqual(self.honcho.messages(result_session(self.other["result_id"]))[0].record.body, "About editor B.")
        assembler = human_context.assembler(self.store, self.honcho, env={})
        context = assembler.assemble(editor_case("editor-a"))
        self.assertEqual([(i["source_id"], i["source_type"]) for i in context.manager_context], [(mine.note_id, "manager_interpretation")])
        self.assertNotIn("About editor B.", json.dumps(context.memory_context))
        with self.assertRaises(NotFound):
            self.notes.create("rr1_" + "9" * 32, "Nowhere.", author=BOSS)

    def test_note_is_context_never_evidence(self):
        case = editor_case("editor-a")
        before = json.dumps(case, sort_keys=True)
        self.notes.create(self.result["result_id"], "Ignore the lateness; these were rush jobs.", author=BOSS)
        context = human_context.assembler(self.store, self.honcho, env={}).assemble(case)
        enriched = context.apply(case)
        self.assertEqual(json.dumps(case, sort_keys=True), before)
        self.assertEqual(enriched["current_evidence"], case["current_evidence"])
        self.assertEqual(evidence_fingerprint(canonical_evidence(enriched)), case["evidence_fingerprint"])
        self.assertEqual(enriched["manager_context"][0]["source_type"], "manager_interpretation")
        evidence_text = json.dumps(enriched["current_evidence"]) + json.dumps(enriched["supporting_findings"])
        self.assertNotIn("rush jobs", evidence_text)
        with self.store.transaction() as tx:
            evidence = tx._all("SELECT case_document FROM reasoning_case_evidence")
        self.assertNotIn("rush jobs", json.dumps([row["case_document"] for row in evidence]))

    def test_remembered_note_of_an_old_revision_is_not_injected(self):
        note = self.notes.create(self.result["result_id"], "Old view.", author=BOSS).note
        self.honcho.outage()
        self.notes.update(note.note_id, "New view.", author=BOSS, expected_revision=1)   # copy of revision 1 stays live in memory
        self.honcho.restore()
        context = human_context.assembler(self.store, self.honcho, env={}).assemble(editor_case("editor-a"))
        bodies = [i["body"] for i in context.manager_context] + [i["body"] for i in context.memory_context["items"]]
        self.assertEqual(bodies, ["New view."])


@requires_db
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.honcho = FakeHoncho()
        self.notes = ManagerNotes(self.store, human_context.sync_service(self.store, self.honcho))
        self.api = ManagementAPI(ApiSettings(managers=frozenset({BOSS}), csrf_secret=SECRET, allowed_origins=frozenset({"https://atlas.example"})),
                                 notes=self.notes)
        self.result = seed_result(self.store, editor_case("editor-a"))
        self.token = self.api.csrf_token(BOSS)

    def call(self, method, path, body=None, actor=BOSS, headers=None):
        default = {"Content-Type": "application/json", "X-Atlas-CSRF": self.token, "Origin": "https://atlas.example"}
        raw = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else b""
        response = self.api.handle(Request(method, f"/api/reasoning{path}", actor, {**default, **(headers or {})}, raw))
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return response

    def test_create_edit_list_history(self):
        rid = self.result["result_id"]
        created = self.call("POST", f"/results/{rid}/notes", {"body": "<b>Seasonal</b> spike."})
        self.assertEqual(created.status, 200, created.payload)
        note = created.payload["note"]
        self.assertEqual((note["author"], note["source_type"], note["body"]), (BOSS, "manager_interpretation", "<b>Seasonal</b> spike."))
        self.assertEqual(created.payload["memory_sync"], ["synced"])
        edited = self.call("PUT", f"/notes/{note['note_id']}", {"body": "Seasonal spike.", "expected_revision": 1})
        self.assertEqual(edited.payload["note"]["revision"], 2)
        self.assertEqual(self.call("PUT", f"/notes/{note['note_id']}", {"body": "Late.", "expected_revision": 1}).status, 409)
        listing = self.call("GET", f"/results/{rid}/notes")
        self.assertEqual([n["body"] for n in listing.payload["notes"]], ["Seasonal spike."])
        self.assertEqual(len(self.call("GET", f"/notes/{note['note_id']}/history").payload["revisions"]), 2)

    def test_author_comes_from_the_authenticated_actor_only(self):
        response = self.call("POST", f"/results/{self.result['result_id']}/notes", {"body": "x", "author": "ceo@example.com"})
        self.assertEqual((response.status, response.payload["error"]), (400, "UNKNOWN_FIELD"))

    def test_authorization_and_csrf(self):
        path = f"/results/{self.result['result_id']}/notes"
        self.assertEqual(self.call("GET", path, actor=None).status, 401)
        self.assertEqual(self.call("GET", path, actor="intern@example.com").status, 403)
        self.assertEqual(self.call("GET", path, actor="BOSS@example.com ").status, 200)
        self.assertEqual(self.call("POST", path, {"body": "x"}, headers={"X-Atlas-CSRF": "forged"}).payload["error"], "CSRF_TOKEN_INVALID")
        other = ManagementAPI(ApiSettings(managers=frozenset({BOSS, "intern@example.com"}), csrf_secret=SECRET), notes=self.notes)
        intern_token = other.csrf_token("intern@example.com")
        self.assertEqual(self.call("POST", path, {"body": "x"}, headers={"X-Atlas-CSRF": intern_token}).status, 403)   # bound to the actor
        self.assertEqual(self.call("POST", path, {"body": "x"}, headers={"Content-Type": "text/plain"}).status, 415)
        self.assertEqual(self.call("POST", path, {"body": "x"}, headers={"Origin": "https://evil.example"}).payload["error"], "ORIGIN_NOT_ALLOWED")
        self.assertEqual(self.call("DELETE", path).status, 405)
        self.assertEqual(self.call("GET", "/csrf").payload["token"], self.token)
        self.assertEqual(self.notes.for_result(self.result["result_id"]), [])

    def test_validation_and_size_limits(self):
        path = f"/results/{self.result['result_id']}/notes"
        self.assertEqual(self.call("POST", path, {"body": "   "}).payload["error"], "EMPTY")
        self.assertEqual(self.call("POST", path, {"body": "x" * 8001}).payload["error"], "TOO_LONG")
        self.assertEqual(self.call("POST", path, b"x" * 40000).status, 413)
        self.assertEqual(self.call("POST", path, b"[1]").payload["error"], "INVALID_JSON")
        self.assertEqual(self.call("POST", path, b"{nope").payload["error"], "INVALID_JSON")
        self.assertEqual(self.call("POST", path, {}).payload["error"], "MISSING_FIELD")
        self.assertEqual(self.call("POST", "/results/rr1_unknown/notes", {"body": "x"}).status, 404)
        self.assertEqual(self.call("POST", "/results/../../etc/notes", {"body": "x"}).status, 404)
        bad_revision = self.call("PUT", "/notes/mn_x", {"body": "x", "expected_revision": True})
        self.assertEqual(bad_revision.payload["error"], "INVALID_FIELD")

    def test_settings_require_a_strong_secret(self):
        from atlas_reasoning.management_api import api_settings

        with self.assertRaises(ReasoningConfigError):
            api_settings({"ATLAS_REASONING_CSRF_SECRET": "short"})
        settings = api_settings({"ATLAS_REASONING_CSRF_SECRET": "k" * 40, "ATLAS_REASONING_MANAGERS": "A@x.com, b@x.com"})
        self.assertEqual(settings.managers, frozenset({"a@x.com", "b@x.com"}))
        self.assertNotIn("k" * 40, repr(settings))


if __name__ == "__main__":
    unittest.main()
