"""Reasoning V3 Phase 14: the Teach Atlas knowledge interface (``REV/14``)."""

import hashlib
import json
import re
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from human_context_fixtures import editor_case, seed_result, team_case
from reasoning_db import fresh_database, requires_db

from atlas_reasoning import human_context
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.fingerprint import canonical_evidence, evidence_fingerprint
from atlas_reasoning.human_context_html import teach_atlas_page
from atlas_reasoning.management_api import ApiSettings, ManagementAPI, Request
from atlas_reasoning.manager_notes import ManagerNotes
from atlas_reasoning.memory import GLOBAL_TEACHINGS, editor_session, session_key
from atlas_reasoning.store import human_context as sql
from atlas_reasoning.store import memory_log
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.teach_atlas import (
    DATA_ISSUE_NOTE,
    TeachAtlas,
    Teaching,
    TeachingConflict,
    current_period,
    teaching_session,
    validity_window,
)
from atlas_reasoning.user_text import InvalidText

BOSS = "boss@example.com"
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
EVIDENCE_TABLES = ("reasoning_cases", "reasoning_case_evidence", "reasoning_case_observations", "reasoning_results", "reasoning_result_versions",
                   "reasoning_evidence_links", "reasoning_work_items")


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class ValidityTests(unittest.TestCase):
    def test_validity_modes(self):
        self.assertEqual(validity_window("until_changed", None, None, NOW), (NOW, None))
        self.assertEqual(validity_window("current_period", None, None, NOW),
                         (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)))
        self.assertEqual(current_period(datetime(2026, 12, 31, tzinfo=UTC))[1], datetime(2027, 1, 1, tzinfo=UTC))
        start, end = validity_window("date_range", "2026-10-01", "2026-10-31", NOW)
        self.assertEqual((start, end), (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)))   # date-only end is inclusive
        self.assertEqual(validity_window("date_range", "2026-10-01T08:00:00Z", "2026-10-01T18:00:00+02:00", NOW)[1],
                         datetime(2026, 10, 1, 16, tzinfo=UTC))
        for args in (("date_range", "2026-10-02", "2026-10-01"), ("date_range", None, "2026-10-01"), ("until_changed", None, "2026-11-01"),
                     ("current_period", "2026-10-01", None), ("date_range", "2026-10-01T00:00:00", "2026-11-01"), ("date_range", "soon", "later")):
            with self.subTest(args=args), self.assertRaises(InvalidText):
                validity_window(*args, NOW)

    def test_scope_sessions(self):
        self.assertEqual(teaching_session("company", None), GLOBAL_TEACHINGS)
        self.assertEqual(teaching_session("editor", "e1"), editor_session("e1"))
        self.assertEqual(teaching_session("video_type", "4"), "video-type:4")
        self.assertEqual(teaching_session("workflow", "pre_editor"), "workflow:pre_editor")
        self.assertEqual(teaching_session("client", "acme"), session_key("client", "acme"))
        self.assertEqual(teaching_session("specific_result", "rr1_x"), "result:rr1_x")


class HtmlTests(unittest.TestCase):
    def test_teach_atlas_page_shows_scope_type_validity_and_escapes(self):
        teaching = Teaching("tch_1", "<script>x</script> rule", "editor", '"><img>', "correction", "date_range", "2026-10-01T00:00:00.000000Z",
                            "2026-11-01T00:00:00.000000Z", "active", BOSS, 2, True, True, "t", "t")
        html = teach_atlas_page([teaching], csrf_token="tok")
        self.assertNotIn("<script>", html)
        self.assertNotIn('"><img>', html)
        for text in ("Management teaching", "Editor: &quot;&gt;&lt;img&gt;", "Correction", "Date range: 2026-10-01", "under engineering review",
                     "never change Monday data", 'name="affects_source_data"', "Current period only"):
            self.assertIn(text, html)
        self.assertNotIn("/enable", html)          # already active
        archived = Teaching("tch_2", "Old", "company", None, "context", "until_changed", None, None, "archived", None, 3, False, False, "t", "t")
        self.assertNotIn("/archive", teach_atlas_page([archived], csrf_token="tok"))


def table_digest(store):
    """A digest of every evidence/result table: proves teachings never change them."""
    digest = hashlib.sha256()
    with store.transaction() as tx:
        for table in EVIDENCE_TABLES:
            for row in tx._all(f"SELECT to_jsonb(t) AS row FROM {table} t ORDER BY to_jsonb(t)::text"):
                digest.update(json.dumps(row["row"], sort_keys=True, default=str).encode())
    return digest.hexdigest()


@requires_db
class TeachingTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.honcho = FakeHoncho()
        self.clock = Clock(NOW)
        self.sync = human_context.sync_service(self.store, self.honcho, clock=self.clock)
        self.teach = TeachAtlas(self.store, self.sync, clock=self.clock)
        self.case_a = editor_case("editor-a")
        self.case_b = editor_case("editor-b")
        self.result_a = seed_result(self.store, self.case_a)
        self.result_b = seed_result(self.store, self.case_b)
        self.assembler = human_context.assembler(self.store, self.honcho, env={})

    def teach_one(self, body, scope_type="company", scope_id=None, teaching_type="business_rule", validity_mode="until_changed", **kw):
        return self.teach.create(body=body, scope_type=scope_type, scope_id=scope_id, teaching_type=teaching_type, validity_mode=validity_mode,
                                 author=BOSS, **kw)

    def injected(self, case, now=NOW, **kw):
        context = self.assembler.assemble(case, now=now, **kw)
        return [i["body"] for i in context.manager_context] + [i["body"] for i in context.memory_context["items"]]

    def test_create_persists_then_syncs_to_the_scope_session(self):
        written = self.teach_one("Class A deadlines are contractual.", scope_type="video_type", scope_id="4")
        t = written.teaching
        self.assertEqual((t.source_type, t.scope_type, t.scope_id, t.status, t.revision, t.effective, t.author),
                         ("management_teaching", "video_type", "4", "active", 1, True, BOSS))
        self.assertEqual([o.status for o in written.sync], ["synced"])
        [copy] = self.honcho.messages("video-type:4")
        self.assertIn("Class A deadlines are contractual.", copy.record.body)
        self.assertEqual(copy.record.metadata["teaching_type"], "business_rule")

    def test_scope_isolation(self):
        self.teach_one("Company rule.")
        self.teach_one("Editor A is part-time.", scope_type="editor", scope_id="editor-a")
        self.teach_one("Editor B is on leave.", scope_type="editor", scope_id="editor-b")
        self.teach_one("Type 4 rule.", scope_type="video_type", scope_id="4")
        self.teach_one("Type 9 rule.", scope_type="video_type", scope_id="9")
        self.teach_one("Result A only.", scope_type="specific_result", scope_id=self.result_a["result_id"])
        self.teach_one("Client rule.", scope_type="client", scope_id="acme")
        a = " | ".join(self.injected(self.case_a))
        for text in ("Company rule.", "Editor A is part-time.", "Type 4 rule.", "Result A only."):
            self.assertIn(text, a)
        for text in ("Editor B is on leave.", "Type 9 rule.", "Client rule."):
            self.assertNotIn(text, a)
        b = " | ".join(self.injected(self.case_b))
        self.assertIn("Editor B is on leave.", b)
        self.assertNotIn("Editor A is part-time.", b)
        self.assertNotIn("Result A only.", b)
        team = team_case(["editor-a", "editor-b"])
        seed_result(self.store, team)
        team_text = " | ".join(self.injected(team))
        self.assertIn("Company rule.", team_text)
        self.assertNotIn("Editor A is part-time.", team_text)
        self.assertIn("Editor A is part-time.", " | ".join(self.injected(team, explicit_editor_ids=["editor-a"])))
        with self.assertRaises(InvalidText):
            self.teach_one("x", scope_type="company", scope_id="editor-a")
        with self.assertRaises(InvalidText):
            self.teach_one("x", scope_type="editor", scope_id=None)
        with self.assertRaises(InvalidText):
            self.teach_one("x", scope_type="planet", scope_id="mars")

    def test_expiration_and_temporary_validity(self):
        ranged = self.teach_one("Holiday cover until 20 October.", teaching_type="temporary_situation", validity_mode="date_range",
                                valid_from="2026-10-10", valid_until="2026-10-20").teaching
        period = self.teach_one("October rush.", teaching_type="temporary_situation", validity_mode="current_period").teaching
        future = self.teach_one("Starts in December.", validity_mode="date_range", valid_from="2026-12-01", valid_until="2026-12-31").teaching
        self.assertTrue(ranged.effective and period.effective)
        self.assertFalse(future.effective)
        self.assertEqual(self.honcho.messages(GLOBAL_TEACHINGS).__len__(), 2)     # a teaching not yet in effect is not synced
        now_text = " | ".join(self.injected(self.case_a))
        self.assertIn("Holiday cover", now_text)
        self.assertIn("October rush.", now_text)
        self.assertNotIn("Starts in December.", now_text)
        later = NOW + timedelta(days=10)                          # 25 October: the range ended, the month did not
        later_context = self.assembler.assemble(self.case_a, now=later)
        later_text = json.dumps([later_context.manager_context, later_context.memory_context])
        self.assertNotIn("Holiday cover", later_text)            # neither canonical nor its still-live memory copy
        self.assertIn("October rush.", later_text)
        self.assertGreaterEqual(later_context.dropped.get("memory_not_current", 0) + later_context.dropped.get("duplicate", 0), 1)
        self.assertNotIn("October rush.", " | ".join(self.injected(self.case_a, now=datetime(2026, 11, 2, tzinfo=UTC))))
        self.clock.now = later
        self.assertEqual(self.teach.retire_expired(), 1)
        self.assertEqual([m.record.source_id for m in self.honcho.messages(GLOBAL_TEACHINGS) if not m.retired], [period.teaching_id])
        self.assertEqual(self.teach.get(ranged.teaching_id).status, "active")    # expiry never rewrites the canonical row

    def test_future_teaching_is_synced_when_it_comes_into_effect(self):
        # Review of PR #33: a teaching not in effect when written was never copied to memory afterwards.
        future = self.teach_one("Starts in December.", validity_mode="date_range", valid_from="2026-12-01", valid_until="2026-12-31").teaching
        self.assertEqual(self.honcho.messages(GLOBAL_TEACHINGS), [])
        self.assertEqual(self.teach.sync_effective(), [])
        self.clock.now = datetime(2026, 12, 2, tzinfo=UTC)
        [outcome] = self.teach.sync_effective()
        self.assertEqual((outcome.source_id, outcome.status), (future.teaching_id, "synced"))
        self.assertEqual([o.status for o in self.teach.sync_effective()], ["duplicate"])      # sent once
        self.assertEqual([m.record.source_id for m in self.honcho.messages(GLOBAL_TEACHINGS)], [future.teaching_id])

    def test_disable_enable_archive(self):
        t = self.teach_one("Use the client calendar.").teaching
        disabled = self.teach.disable(t.teaching_id, author=BOSS)
        self.assertEqual((disabled.teaching.status, disabled.retired), ("disabled", 1))
        self.assertNotIn("Use the client calendar.", " | ".join(self.injected(self.case_a)))
        enabled = self.teach.enable(t.teaching_id, author=BOSS)
        self.assertEqual([o.status for o in enabled.sync], ["synced"])
        self.assertIn("Use the client calendar.", " | ".join(self.injected(self.case_a)))
        archived = self.teach.archive(t.teaching_id, author=BOSS).teaching
        self.assertEqual(archived.status, "archived")
        self.assertNotIn("Use the client calendar.", " | ".join(self.injected(self.case_a)))
        self.assertEqual(self.teach.get(t.teaching_id).body, "Use the client calendar.")   # archived stays auditable
        self.assertEqual([h["snapshot"]["status"] for h in self.teach.history(t.teaching_id)], ["active", "disabled", "active", "archived"])
        self.assertEqual([x.teaching_id for x in self.teach.list_teachings(statuses=["archived"])], [t.teaching_id])
        for action in (lambda: self.teach.enable(t.teaching_id, author=BOSS),
                       lambda: self.teach.update(t.teaching_id, expected_revision=archived.revision, author=BOSS, body="Changed.")):
            with self.assertRaises(TeachingConflict):
                action()
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("UPDATE teachings SET status = 'active', revision = revision + 1 WHERE teaching_id = %s", (t.teaching_id,))
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("DELETE FROM teachings")

    def test_edit_history_and_conflicts(self):
        t = self.teach_one("Draft rule.", scope_type="editor", scope_id="editor-a").teaching
        edited = self.teach.update(t.teaching_id, expected_revision=1, author="deputy@example.com", body="Final rule.",
                                   validity_mode="date_range", valid_from="2026-10-01", valid_until="2026-12-31").teaching
        self.assertEqual((edited.revision, edited.body, edited.validity_mode, edited.author), (2, "Final rule.", "date_range", "deputy@example.com"))
        live = [m.body for m in self.honcho.read(editor_session("editor-a"), limit=5)]
        self.assertEqual(len(live), 1)
        self.assertIn("Final rule.", live[0])
        with self.assertRaises(TeachingConflict):
            self.teach.update(t.teaching_id, expected_revision=1, author=BOSS, body="Stale.")
        self.assertEqual(self.teach.update(t.teaching_id, expected_revision=2, author=BOSS, body="Final rule.").teaching.revision, 2)
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("UPDATE teachings SET scope_id = 'editor-b', revision = revision + 1")
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("UPDATE teaching_revisions SET author = 'x'")

    def test_corrections_flag_bad_upstream_data_and_never_change_evidence(self):
        before = table_digest(self.store)
        with self.assertRaisesRegex(InvalidText, "upstream"):
            self.teach_one("Item 1101 was not late.", teaching_type="correction")
        with self.assertRaises(InvalidText):
            self.teach_one("Rule.", affects_source_data=True)
        plain = self.teach_one("Read 'late' as 'late against the client ETA'.", teaching_type="correction", affects_source_data=False)
        self.assertIsNone(plain.review_flag)
        flagged = self.teach_one("Item 1101's Ready For Approval date in Monday is wrong; it was delivered on time.",
                                 scope_type="editor", scope_id="editor-a", teaching_type="correction", affects_source_data=True)
        self.assertIsNotNone(flagged.review_flag)
        [flag] = self.teach.review_flags()
        self.assertEqual((flag["source_id"], flag["status"], flag["raised_by"]), (flagged.teaching.teaching_id, "open", BOSS))
        self.teach.update(flagged.teaching.teaching_id, expected_revision=1, author=BOSS, body="Item 1101 RFA date is wrong in Monday.")
        self.assertEqual(len(self.teach.review_flags()), 1)          # one open flag per teaching
        context = self.assembler.assemble(self.case_a, now=NOW)
        [item] = [i for i in context.manager_context if i["source_id"] == flagged.teaching.teaching_id]
        self.assertIn(DATA_ISSUE_NOTE, item["body"])
        enriched = context.apply(self.case_a)
        self.assertEqual(enriched["current_evidence"], self.case_a["current_evidence"])
        self.assertEqual(evidence_fingerprint(canonical_evidence(enriched)), self.case_a["evidence_fingerprint"])
        self.assertEqual(table_digest(self.store), before)            # no evidence, result or case row changed

    def test_teaching_survives_honcho_outage(self):
        self.honcho.outage()
        written = self.teach_one("Written while Honcho is down.")
        self.assertEqual([o.status for o in written.sync], ["failed"])
        self.assertIn("Written while Honcho is down.", " | ".join(self.injected(self.case_a)))
        self.honcho.restore()
        self.sync.retry()
        with self.store.transaction() as tx:
            self.assertEqual({r["status"] for r in memory_log.rows(tx, source_id=written.teaching.teaching_id)}, {"synced"})


class EvidenceImmutabilityTests(unittest.TestCase):
    def test_human_context_code_never_writes_evidence_tables(self):
        package = Path(__file__).resolve().parents[1] / "src" / "atlas_reasoning"
        modules = ["memory.py", "memory_sync.py", "memory_context.py", "honcho_client.py", "fake_honcho.py", "manager_notes.py", "atlas_questions.py",
                   "teach_atlas.py", "human_context.py", "human_context_html.py", "management_api.py", "user_text.py", "store/human_context.py",
                   "store/memory_log.py"]
        write = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(reasoning_\w+)", re.IGNORECASE)
        for name in modules:
            with self.subTest(module=name):
                self.assertEqual(write.findall((package / name).read_text()), [])
                self.assertNotIn("atlas_commander", (package / name).read_text())
        for name in ("0200_memory_sync.sql", "0201_memory_injections.sql", "0202_atlas_questions.sql", "0203_teach_atlas.sql"):
            text = (package / "store" / "migrations" / name).read_text()
            self.assertIsNone(re.search(r"ALTER TABLE reasoning_|UPDATE reasoning_|INSERT INTO reasoning_", text), name)


@requires_db
class ApiTests(unittest.TestCase):
    def test_teach_atlas_routes(self):
        store = ReasoningStore(fresh_database())
        sync = human_context.sync_service(store, FakeHoncho())
        teach = TeachAtlas(store, sync)
        api = ManagementAPI(ApiSettings(managers=frozenset({BOSS}), csrf_secret=b"s" * 40), notes=ManagerNotes(store, sync), teachings=teach)
        headers = {"Content-Type": "application/json", "X-Atlas-CSRF": api.csrf_token(BOSS)}

        def call(method, path, body=None):
            return api.handle(Request(method, f"/api/reasoning{path}", BOSS, headers, json.dumps(body).encode() if body is not None else b""))

        created = call("POST", "/teachings", {"body": "Fridays are half days.", "scope_type": "company", "teaching_type": "context",
                                              "validity_mode": "until_changed"})
        self.assertEqual(created.status, 200, created.payload)
        tid = created.payload["teaching"]["teaching_id"]
        self.assertEqual((created.payload["teaching"]["author"], created.payload["memory_sync"]), (BOSS, ["synced"]))
        flagged = call("POST", "/teachings", {"body": "Monday shows the wrong ETA for item 7.", "scope_type": "company",
                                              "teaching_type": "correction", "validity_mode": "until_changed", "affects_source_data": True})
        self.assertTrue(flagged.payload["engineering_review_flag"])
        self.assertEqual(len(call("GET", "/review-flags").payload["flags"]), 1)
        self.assertEqual(call("POST", "/teachings", {"body": "x", "scope_type": "company", "teaching_type": "context",
                                                     "validity_mode": "forever"}).payload["error"], "INVALID_VALIDITY")
        self.assertEqual(call("POST", "/teachings", {"body": "x", "scope_type": "company", "teaching_type": "context", "validity_mode": "until_changed",
                                                     "status": "archived"}).payload["error"], "UNKNOWN_FIELD")
        edited = call("PUT", f"/teachings/{tid}", {"expected_revision": 1, "body": "Fridays end at 14:00."})
        self.assertEqual(edited.payload["teaching"]["revision"], 2)
        self.assertEqual(call("POST", f"/teachings/{tid}/disable", {}).payload["teaching"]["status"], "disabled")
        self.assertEqual(call("POST", f"/teachings/{tid}/archive", {}).payload["teaching"]["status"], "archived")
        self.assertEqual(call("POST", f"/teachings/{tid}/enable", {}).status, 409)
        self.assertEqual([t["teaching_id"] for t in call("GET", "/teachings?status=archived").payload["teachings"]], [tid])
        self.assertEqual(len(call("GET", f"/teachings/{tid}/history").payload["revisions"]), 4)
        with store.transaction() as tx:
            self.assertEqual(len(sql.teachings(tx)), 2)


if __name__ == "__main__":
    unittest.main()
