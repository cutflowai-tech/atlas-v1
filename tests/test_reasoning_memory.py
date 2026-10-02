"""Reasoning V3 Phase 10: Honcho as contextual memory, never the canonical store (``REV/10``)."""

import json
import re
import unittest
import urllib.error

from human_context_fixtures import seed_result
from reasoning_db import fresh_database, requires_db

from atlas_reasoning import settings
from atlas_reasoning.enums import MemorySyncStatus, NoteSource
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.honcho_client import HonchoClient, HttpResult
from atlas_reasoning.memory import (
    ATLAS_PEER,
    GLOBAL_TEACHINGS,
    MemoryPolicyError,
    MemoryRecord,
    MemoryRejected,
    MemoryUnavailable,
    check_record,
    editor_session,
    honcho_session_id,
    manager_peer,
    parse_session,
    result_session,
    session_key,
    summary_record,
    video_type_session,
)
from atlas_reasoning.memory_sync import MemorySyncService
from atlas_reasoning.store import memory_log
from atlas_reasoning.store.repository import ReasoningStore

KEY = "hk-test-not-a-real-key-0123456789"


def note(body="Class B work moved to Ahmed in September.", session=None, source_id="note_1", **kw):
    return MemoryRecord(kw.pop("source_type", NoteSource.MANAGER_INTERPRETATION), source_id, session or result_session("rr1_" + "a" * 32), body,
                        author=kw.pop("author", "boss@example.com"), recorded_at="2026-09-30T10:00:00Z", metadata=kw.pop("metadata", {}))


class SessionPolicyTests(unittest.TestCase):
    def test_session_naming_convention(self):
        self.assertEqual(editor_session("editor-7"), "editor:editor-7")
        self.assertEqual(video_type_session("4"), "video-type:4")
        self.assertEqual(result_session("rr1_x"), "result:rr1_x")
        self.assertEqual(session_key(GLOBAL_TEACHINGS), "global:teachings")
        self.assertEqual(session_key("team:editors"), "team:editors")
        self.assertEqual(parse_session("editor:a:b"), ("editor", "a:b"))
        for bad in ("editor:", "nobody:1", "editor: x ", "global:other", "editor:a\nb"):
            with self.subTest(bad=bad), self.assertRaises(MemoryPolicyError):
                parse_session(bad)

    def test_honcho_ids_are_safe_distinct_and_not_atlas_ids(self):
        keys = [editor_session("a"), editor_session("A"), editor_session("a b"), video_type_session("a"), result_session("rr1_" + "b" * 32),
                GLOBAL_TEACHINGS, "team:editors"]
        ids = [honcho_session_id(key) for key in keys]
        self.assertEqual(len(set(ids)), len(ids))
        for key, sid in zip(keys, ids, strict=True):
            self.assertRegex(sid, r"^[a-zA-Z0-9_-]{1,512}$")
            self.assertNotIn(key.split(":")[-1], sid.split("-", 2)[-1] if key.startswith("result:") else "")
        self.assertTrue(honcho_session_id(GLOBAL_TEACHINGS).startswith("atlas-global-teachings-"))

    def test_manager_peers_are_pseudonymous(self):
        peer = manager_peer("Boss@Example.com ")
        self.assertEqual(peer, manager_peer("boss@example.com"))
        self.assertNotIn("example", peer)
        self.assertRegex(peer, r"^manager-[0-9a-f]{16}$")
        self.assertEqual(manager_peer(None), "management")
        self.assertEqual(note(source_type=NoteSource.ATLAS_QUESTION).peer_id, ATLAS_PEER)

    def test_wrong_session_is_refused(self):
        with self.assertRaisesRegex(MemoryPolicyError, "may not be written"):
            check_record(note(session=editor_session("editor-7")))          # a manager note belongs to its result only
        with self.assertRaisesRegex(MemoryPolicyError, "may not be written"):
            check_record(note(source_type=NoteSource.ATLAS_QUESTION, session=GLOBAL_TEACHINGS))
        check_record(note(source_type=NoteSource.MANAGEMENT_TEACHING, session=GLOBAL_TEACHINGS))
        check_record(note(source_type=NoteSource.MANAGER_ANSWER, session=editor_session("editor-7")))

    def test_raw_data_leakage_is_refused(self):
        raw = json.dumps([{"monday_item_id": "1101", "event_ids": ["e1"], "values": {"late": True}}])
        with self.assertRaisesRegex(MemoryPolicyError, "not a JSON document"):
            check_record(note(body=raw))
        with self.assertRaisesRegex(MemoryPolicyError, "not allowed"):
            check_record(note(metadata={"event_ids": "e1,e2"}))
        with self.assertRaisesRegex(MemoryPolicyError, "scalar"):
            check_record(note(metadata={"case_id": {"values": [1]}}))
        with self.assertRaisesRegex(MemoryPolicyError, "8000"):
            check_record(note(body="x" * 8001))
        with self.assertRaises(MemoryPolicyError):
            check_record(note(body="   "))
        with self.assertRaises(MemoryPolicyError):
            check_record(note(source_type="monday_event"))

    def test_prior_reasoning_summary_carries_no_evidence(self):
        import reasoning_factory as factory

        result = factory.result_dict()
        record = check_record(summary_record(result, result_session(result["result_id"])))
        self.assertEqual(record.source_type, NoteSource.PRIOR_REASONING_SUMMARY)
        self.assertIn(result["reasoning_summary"], record.body)
        dumped = record.body + json.dumps(record.provenance())
        for ref in result["observation"]["evidence_refs"]:
            self.assertNotIn(ref, dumped)
        self.assertNotRegex(dumped, r"\b11\d\d\b")   # no Monday item IDs (1101, 1102, ...)

    def test_provenance_preserves_source(self):
        record = check_record(note(metadata={"case_id": "rc1_x", "revision": 2}))
        provenance = record.provenance()
        self.assertEqual((provenance["source_type"], provenance["source_id"], provenance["session_key"]),
                         ("manager_interpretation", "note_1", record.session_key))
        self.assertEqual(provenance["content_sha256"], record.content_sha256)
        self.assertNotIn("boss@example.com", json.dumps(provenance))
        self.assertNotEqual(record.content_sha256, check_record(note(body="Other text.")).content_sha256)


class FakeHttp:
    def __init__(self, replies=None, error=None):
        self.requests = []
        self.replies = replies or {}
        self.error = error

    def __call__(self, method, url, headers, body, timeout):
        self.requests.append((method, url, dict(headers), json.loads(body) if body else None))
        if self.error is not None:
            raise self.error
        for (m, pattern), reply in self.replies.items():
            if m == method and re.search(pattern, url):
                return reply
        if url.endswith("/messages") and method == "POST":
            return HttpResult(200, json.dumps([{"id": "msg-1", "content": "x", "peer_id": "atlas"}]).encode())
        return HttpResult(200, b"{}")


def client(http, environment="test"):
    return HonchoClient(settings.HonchoSettings(api_key=KEY, environment=environment), http=http)


class HonchoClientTests(unittest.TestCase):
    def test_write_creates_workspace_peer_session_then_message(self):
        http = FakeHttp()
        ref = client(http).write(note())
        self.assertEqual(ref, "msg-1")
        paths = [(m, url.split("api.honcho.dev")[1]) for m, url, _, _ in http.requests]
        sid = honcho_session_id(note().session_key)
        peer = manager_peer("boss@example.com")
        self.assertEqual(paths, [("POST", "/v3/workspaces"), ("POST", "/v3/workspaces/waset-atlas-test/peers"),
                                 ("POST", "/v3/workspaces/waset-atlas-test/sessions"),
                                 ("POST", f"/v3/workspaces/waset-atlas-test/sessions/{sid}/peers"),
                                 ("POST", f"/v3/workspaces/waset-atlas-test/sessions/{sid}/messages")])
        self.assertEqual(http.requests[0][3]["id"], "waset-atlas-test")
        message = http.requests[-1][3]["messages"][0]
        self.assertEqual(message["peer_id"], peer)
        self.assertEqual(message["metadata"]["source_type"], "manager_interpretation")
        self.assertEqual(http.requests[-1][2]["Authorization"], f"Bearer {KEY}")

    def test_get_or_create_calls_are_cached(self):
        http = FakeHttp()
        honcho = client(http)
        honcho.write(note())
        honcho.write(note(body="Second note.", source_id="note_2"))
        self.assertEqual(sum(1 for _, url, _, _ in http.requests if url.endswith("/messages")), 2)
        self.assertEqual(len(http.requests), 6)

    def test_one_workspace_per_environment(self):
        self.assertEqual(client(FakeHttp(), "production").workspace_id, "waset-atlas-production")
        self.assertNotEqual(client(FakeHttp(), "staging").workspace_id, client(FakeHttp(), "production").workspace_id)

    def test_errors_map_to_retryable_or_rejected_and_never_leak_the_key(self):
        cases = [(HttpResult(503, b"down"), MemoryUnavailable), (HttpResult(429, b""), MemoryUnavailable), (HttpResult(401, KEY.encode()), MemoryRejected),
                 (HttpResult(422, b"bad"), MemoryRejected), (HttpResult(200, b"not json"), MemoryUnavailable)]
        for reply, error in cases:
            with self.subTest(status=reply.status):
                http = FakeHttp({("POST", r"/v3/workspaces$"): reply})
                with self.assertRaises(error) as raised:
                    client(http).write(note())
                self.assertNotIn(KEY, str(raised.exception))
        for exc in (TimeoutError(), urllib.error.URLError(f"refused {KEY}"), OSError("reset")):
            with self.subTest(exc=type(exc).__name__), self.assertRaises(MemoryUnavailable) as raised:
                client(FakeHttp(error=exc)).write(note())
            self.assertNotIn(KEY, str(raised.exception))
        self.assertNotIn(KEY, repr(client(FakeHttp())))
        self.assertNotIn(KEY, repr(settings.HonchoSettings(api_key=KEY)))

    def test_read_returns_live_messages_with_metadata(self):
        page = {"items": [{"id": "m2", "content": "new", "metadata": {"source_type": "manager_interpretation", "source_id": "n2"}, "created_at": "t"},
                          {"id": "m1", "content": "old", "metadata": {"source_type": "manager_interpretation", "atlas_retired": True}},
                          {"id": "m0", "metadata": {}}], "total": 3, "page": 1, "size": 10, "pages": 1}
        http = FakeHttp({("POST", r"/messages/list"): HttpResult(200, json.dumps(page).encode())})
        found = client(http).read(editor_session("e1"), limit=10)
        self.assertEqual([(m.memory_ref, m.source_type, m.source_id) for m in found], [("m2", "manager_interpretation", "n2")])
        self.assertIn("reverse=true", http.requests[-1][1])

    def test_retire_keeps_the_copy_provenance_and_marks_it_retired(self):
        sid = honcho_session_id(editor_session("e1"))
        current = {"id": "m1", "content": "x", "metadata": {"source_type": "manager_answer", "source_id": "aa_1"}}
        http = FakeHttp({("GET", r"/messages/m1$"): HttpResult(200, json.dumps(current).encode())})
        client(http).retire(editor_session("e1"), "m1")
        method, url, _, body = http.requests[-1]
        self.assertEqual((method, url.split("api.honcho.dev")[1]), ("PUT", f"/v3/workspaces/waset-atlas-test/sessions/{sid}/messages/m1"))
        self.assertEqual(body, {"metadata": {"source_type": "manager_answer", "source_id": "aa_1", "atlas_retired": True}})
        other = FakeHttp({("GET", r"/messages/m1$"): HttpResult(200, json.dumps({**current, "id": "m9"}).encode())})
        with self.assertRaises(MemoryUnavailable):
            client(other).retire(editor_session("e1"), "m1")
        self.assertNotIn("PUT", [m for m, _, _, _ in other.requests])

    def test_a_session_never_written_is_empty_not_an_outage(self):
        http = FakeHttp({("POST", r"/messages/list"): HttpResult(404, b"{}"), ("GET", r"/messages/m1$"): HttpResult(404, b"{}")})
        self.assertEqual(client(http).read(editor_session("new-editor"), limit=5), [])
        client(http).retire(editor_session("new-editor"), "m1")
        self.assertNotIn("PUT", [m for m, _, _, _ in http.requests])

    def test_policy_is_enforced_before_any_request(self):
        http = FakeHttp()
        with self.assertRaises(MemoryPolicyError):
            client(http).write(note(session=GLOBAL_TEACHINGS))
        self.assertEqual(http.requests, [])

    def test_redirects_are_refused_never_followed(self):
        # Review of PR #33: urllib would resend the Authorization header to a redirect target.
        from atlas_reasoning import honcho_client

        handler = honcho_client._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "http://elsewhere.example/steal"))
        for status in (301, 302, 307, 308):
            with self.subTest(status=status), self.assertRaises(MemoryRejected) as raised:
                client(FakeHttp({("POST", r"/v3/workspaces$"): HttpResult(status, b"")})).write(note())
            self.assertNotIn(KEY, str(raised.exception))

    def test_read_pages_past_retired_copies(self):
        # Review of PR #33: retired copies (every edit leaves one) must not hide older live copies.
        def message(i, retired):
            return {"id": f"m{i}", "content": f"body {i}", "metadata": {"source_type": "manager_answer", "source_id": f"a{i}",
                                                                         **({"atlas_retired": True} if retired else {})}}
        first = {"items": [message(i, True) for i in range(100)]}
        second = {"items": [message(100, False), message(101, False)]}
        http = FakeHttp({("POST", r"/messages/list\?.*page=1&"): HttpResult(200, json.dumps(first).encode()),
                         ("POST", r"/messages/list\?.*page=2&"): HttpResult(200, json.dumps(second).encode())})
        found = client(http).read(editor_session("e1"), limit=5)
        self.assertEqual([m.memory_ref for m in found], ["m100", "m101"])



class SettingsTests(unittest.TestCase):
    def test_memory_is_off_by_default_and_needs_environment_and_key(self):
        self.assertFalse(settings.memory_enabled({}))
        self.assertTrue(settings.memory_enabled({"ATLAS_REASONING_MEMORY": "on"}))
        with self.assertRaisesRegex(settings.ReasoningConfigError, "ATLAS_REASONING_ENVIRONMENT"):
            settings.honcho_settings({"HONCHO_API_KEY": KEY})
        with self.assertRaisesRegex(settings.ReasoningConfigError, "HONCHO_API_KEY"):
            settings.honcho_settings({"ATLAS_REASONING_ENVIRONMENT": "test"})
        with self.assertRaisesRegex(settings.ReasoningConfigError, "one of"):
            settings.honcho_settings({"ATLAS_REASONING_ENVIRONMENT": "prod", "HONCHO_API_KEY": KEY})
        with self.assertRaisesRegex(settings.ReasoningConfigError, "https"):
            settings.honcho_settings({"ATLAS_REASONING_ENVIRONMENT": "test", "HONCHO_API_KEY": KEY, "ATLAS_HONCHO_BASE_URL": "http://evil.example"})
        ok = settings.honcho_settings({"ATLAS_REASONING_ENVIRONMENT": "staging", "HONCHO_API_KEY": KEY})
        self.assertEqual((ok.workspace_id, ok.base_url), ("waset-atlas-staging", "https://api.honcho.dev"))


class IsolationTests(unittest.TestCase):
    def test_only_the_honcho_client_knows_honcho_and_no_memory_module_reads_atlas(self):
        from pathlib import Path

        package = Path(__file__).resolve().parents[1] / "src" / "atlas_reasoning"
        for path in sorted(package.rglob("*.py")):
            text = path.read_text()
            if path.name not in ("honcho_client.py", "settings.py", "__main__.py"):
                self.assertNotIn("api.honcho.dev", text, path.name)
                self.assertNotIn("/v3/workspaces", text, path.name)
        for name in ("memory.py", "honcho_client.py", "fake_honcho.py", "memory_sync.py", "store/memory_log.py"):
            text = (package / name).read_text()
            for upstream in ("atlas_commander", "atlas_monday_probe", "atlas_sync", "reasoning_input_boundary"):
                self.assertNotIn(upstream, text, name)


@requires_db
class SyncTests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.honcho = FakeHoncho()
        self.sync = MemorySyncService(self.store, self.honcho)

    def log(self, **kw):
        with self.store.transaction() as tx:
            return memory_log.rows(tx, **kw)

    def test_mock_write_and_read(self):
        [outcome] = self.sync.sync([note()])
        self.assertEqual(outcome.status, "synced")
        [memory] = self.honcho.read(note().session_key, limit=5)
        self.assertEqual((memory.memory_ref, memory.source_type, memory.source_id), (outcome.external_ref, "manager_interpretation", "note_1"))
        [row] = self.log()
        self.assertEqual((row["status"], row["external_ref"], row["backend"], row["attempts"]), ("synced", outcome.external_ref, "fake-honcho", 1))
        self.assertEqual(row["peer_id"], manager_peer("boss@example.com"))

    def test_duplicate_sync_is_not_sent_twice(self):
        first = self.sync.sync([note()])
        second = self.sync.sync([note()])
        self.assertEqual([o.status for o in first + second], ["synced", "duplicate"])
        self.assertEqual(len(self.honcho.messages()), 1)
        self.assertEqual(len(self.log()), 1)

    def test_changed_content_replaces_the_previous_copy(self):
        self.sync.sync([note()])
        self.sync.sync([note(body="Edited: Class B work moved in October.")])
        stored = self.honcho.messages(note().session_key)
        self.assertEqual([m.retired for m in stored], [True, False])
        rows = self.log()
        self.assertEqual([r["retired_at"] is not None for r in rows], [True, False])
        self.assertEqual([m.body for m in self.honcho.read(note().session_key, limit=5)], ["Edited: Class B work moved in October."])

    def test_outage_logs_failure_and_retry_sends_current_content(self):
        result = seed_result(self.store)
        self.honcho.outage()
        outcomes = self.sync.sync_result(result["result_id"])
        self.assertEqual({o.status for o in outcomes}, {"failed"})
        self.assertEqual({o.error_class for o in outcomes}, {"memory_unavailable"})
        self.assertEqual(self.store.get_result(result["result_id"]).to_dict()["version"], 1)   # canonical state intact
        self.assertEqual({r["status"] for r in self.log()}, {"failed"})
        self.honcho.restore()
        retried = self.sync.retry()
        self.assertEqual({o.status for o in retried}, {"synced"})
        self.assertEqual({r["status"] for r in self.log()}, {"synced"})
        sessions = {r["session_key"] for r in self.log()}
        self.assertEqual(sessions, {result_session(result["result_id"]), editor_session("editor-label-12")})

    def test_retry_never_resends_stale_content(self):
        self.honcho.outage()
        self.sync.sync([note(source_type=NoteSource.PRIOR_REASONING_SUMMARY, source_id="rr1_" + "f" * 32, author=None)])
        self.honcho.restore()
        self.assertEqual(self.sync.retry(), [])   # the result does not exist canonically: nothing to send
        self.assertEqual([r["status"] for r in self.log()], [MemorySyncStatus.SKIPPED.value])
        self.assertEqual(self.honcho.messages(), [])

    def test_backend_bug_never_breaks_the_caller(self):
        class Broken(FakeHoncho):
            def write(self, record):
                raise KeyError("boom")

        [outcome] = MemorySyncService(self.store, Broken()).sync([note()])
        self.assertEqual((outcome.status, outcome.error_class), ("failed", "internal_error"))

    def test_memory_off_logs_skipped_and_sends_nothing(self):
        [outcome] = MemorySyncService(self.store, None).sync([note()])
        self.assertEqual(outcome.status, "skipped")
        self.assertEqual([r["status"] for r in self.log()], ["skipped"])

    def test_wrong_session_is_refused_before_logging(self):
        # Refused, never sent or logged; and never raised, because the caller's canonical row is already committed.
        [outcome] = self.sync.sync([note(session=editor_session("editor-7"))])
        self.assertEqual((outcome.status, outcome.error_class), ("refused", "memory_policy"))
        self.assertEqual(self.log(), [])
        self.assertEqual(self.honcho.calls, [])

    def test_json_body_is_refused_without_raising(self):
        [outcome] = self.sync.sync([note(body='["see", "item 12"]')])
        self.assertEqual(outcome.status, "refused")
        self.assertEqual(self.log(), [])
        self.assertEqual(self.honcho.calls, [])

    def test_retire_source(self):
        self.sync.sync([note(source_type=NoteSource.MANAGEMENT_TEACHING, session=GLOBAL_TEACHINGS, source_id="t1")])
        self.assertEqual(self.sync.retire_source(NoteSource.MANAGEMENT_TEACHING, "t1"), 1)
        self.assertEqual(self.honcho.read(GLOBAL_TEACHINGS, limit=5), [])

    def test_sync_log_identity_is_immutable(self):
        import psycopg

        self.sync.sync([note()])
        with self.assertRaises(psycopg.errors.IntegrityConstraintViolation), self.store.transaction() as tx:
            tx._exec("UPDATE memory_sync_log SET content_sha256 = %s", ("0" * 64,))


if __name__ == "__main__":
    unittest.main()
