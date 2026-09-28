import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from atlas_commander.contracts import ROOT, schema_errors
from atlas_monday_probe.__main__ import main
from atlas_monday_probe.adapter import ActorMapping, AdapterError, StatusMapping, monday_log_timestamp, normalize, parse_status_changes
from atlas_monday_probe.client import MissingAccess, ReadOnlyMondayClient, ReadOnlyViolation, assert_read_only
from atlas_monday_probe.raw_store import RawStoreError, write_immutable
from atlas_monday_probe.report import build_drift_report, build_manifest

FIXTURES = ROOT / "fixtures/monday"
COLUMNS = {"status": "project_status", "editor": "dropdown_mm1emgt8", "video_type": "dropdown_mm062ga0", "eta": "date"}
STATUS = StatusMapping(version="status-test", board_id="900001", column_id="project_status", labels={9: "In Progress", 3: "Ready For Approval", 13: "Backlog"})
ACTORS = ActorMapping(version="actor-test", actors={"500002": "editor-synthetic"}, waset_co_accounts=frozenset({"500001"}))


def load(name):
    return json.loads((FIXTURES / name).read_text())


def outside_git_dir():
    directory = Path(tempfile.mkdtemp(prefix="atlas-raw-"))
    assert not any((parent / ".git").exists() for parent in [directory, *directory.parents])
    return directory


class TimestampTests(unittest.TestCase):
    def test_converts_100ns_ticks_without_losing_microseconds(self):
        self.assertEqual(monday_log_timestamp("17900106596002324"), "2026-09-21T17:10:59.600232Z")

    def test_rejects_non_tick_values_instead_of_guessing(self):
        for raw in ("2026-09-21T17:10:59Z", "1790010659", "", "1790010659600232x"):
            with self.subTest(raw=raw), self.assertRaises(AdapterError):
                monday_log_timestamp(raw)


class RawRetentionTests(unittest.TestCase):
    def test_raw_identifiers_and_timestamps_retained(self):
        payload = load("activity_logs.json")
        changes = parse_status_changes(payload, "project_status")
        raw_logs = {log["id"]: log for log in payload["boards"][0]["activity_logs"]}
        self.assertEqual([change.log_id for change in changes], ["log-1", "log-3", "log-2"])
        for change in changes:
            raw = raw_logs[change.log_id]
            data = json.loads(raw["data"])
            self.assertEqual(change.created_at_raw, raw["created_at"])
            self.assertEqual((change.user_id, change.account_id), (raw["user_id"], raw["account_id"]))
            self.assertEqual((change.board_id, change.item_id), (str(data["board_id"]), str(data["pulse_id"])))
            self.assertEqual(change.to_label_index, data["value"]["label"]["index"])

    def test_non_status_events_are_ignored(self):
        self.assertNotIn("log-4", [change.log_id for change in parse_status_changes(load("activity_logs.json"), "project_status")])

    def test_raw_store_is_write_once_read_only_and_outside_git(self):
        directory = outside_git_dir()
        record = write_immutable(directory, "payload.json", b'{"a":1}')
        self.assertFalse(record.path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        self.assertEqual(write_immutable(directory, "payload.json", b'{"a":1}').sha256, record.sha256)
        with self.assertRaises(RawStoreError):
            write_immutable(directory, "payload.json", b'{"a":2}')
        self.assertEqual(record.path.read_bytes(), b'{"a":1}')

    def test_raw_store_refuses_git_worktree(self):
        with self.assertRaises(RawStoreError):
            write_immutable(ROOT / ".atlas-raw-should-not-exist", "payload.json", b"{}")
        self.assertFalse((ROOT / ".atlas-raw-should-not-exist").exists())


class NoSourceMutationTests(unittest.TestCase):
    def test_write_operations_are_rejected_before_transport(self):
        sent = []
        client = ReadOnlyMondayClient(lambda query, variables: sent.append(query) or b'{"data":{}}')
        for query in ("mutation { delete_item(item_id: 1) { id } }", "query { a } mutation { change_column_value { id } }", "subscription { x }"):
            with self.subTest(query=query), self.assertRaises(ReadOnlyViolation):
                client.query(query, {})
        self.assertEqual(sent, [])

    def test_read_queries_with_mutation_text_in_strings_or_comments_are_allowed(self):
        assert_read_only('query { items(ids: [1]) { name } } # mutation is not an operation here')
        assert_read_only('query ($q: String = "mutation") { me { id } }')

    def test_capture_path_only_sends_read_only_queries(self):
        sent = []
        activity = json.dumps(load("activity_logs.json")).encode()

        def transport(query, variables):
            sent.append(query)
            return activity if "activity_logs" in query else b'{"data":{}}'
        client = ReadOnlyMondayClient(transport)
        client.status_activity("900001", ["100002"], "project_status", "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z")
        client.items(["100002"], list(COLUMNS.values()))
        client.users_and_columns("900001", ["500001"], list(COLUMNS.values()))
        self.assertEqual(len(sent), 3)
        for query in sent:
            assert_read_only(query)

    def test_missing_token_reports_exact_missing_access_and_never_prints_token(self):
        with self.assertRaisesRegex(MissingAccess, "MONDAY_API_TOKEN"):
            ReadOnlyMondayClient.from_env({})
        client = ReadOnlyMondayClient.from_env({"MONDAY_API_TOKEN": "secret-token-value"})
        self.assertNotIn("secret-token-value", repr(client))


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.changes = {change.log_id: change for change in parse_status_changes(load("activity_logs.json"), "project_status")}

    def test_no_mapping_means_no_event(self):
        event, reasons = normalize(self.changes["log-1"], None, None)
        self.assertIsNone(event)
        self.assertEqual(reasons, ["STATUS_MAPPING_MISSING", "ACTOR_MAPPING_MISSING"])

    def test_explicit_versioned_mappings_produce_contract_valid_event(self):
        event, reasons = normalize(self.changes["log-1"], STATUS, ACTORS)
        self.assertEqual(reasons, [])
        self.assertEqual(schema_errors(event, "normalized-status-event.schema.json"), [])
        self.assertEqual((event["event_id"], event["occurred_at"], event["actor_id"]), ("log-1", "2026-09-21T17:10:59.600232Z", "editor-synthetic"))
        self.assertEqual(event["mapping_version"], "status-test+actor-test")

    def test_waset_co_account_is_unresolved_not_attributed(self):
        event, _ = normalize(self.changes["log-3"], STATUS, ACTORS)
        self.assertEqual((event["actor_resolution"], event["actor_id"], event["actor_monday_id"]), ("unresolved_waset_co", None, "500001"))
        self.assertEqual(schema_errors(event, "normalized-status-event.schema.json"), [])

    def test_unmapped_labels_actors_and_undo_are_blocked(self):
        event, reasons = normalize(self.changes["log-2"], STATUS, ACTORS)
        self.assertIsNone(event)
        self.assertEqual(reasons, ["UNDO_ACTION", "UNMAPPED_TO_STATUS", "ACTOR_NOT_IN_MAPPING"])

    def test_mapping_for_another_board_is_not_reused(self):
        other = StatusMapping(version="x", board_id="1", column_id="project_status", labels=STATUS.labels)
        self.assertIn("STATUS_MAPPING_SCOPE_MISMATCH", normalize(self.changes["log-1"], other, ACTORS)[1])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.changes = parse_status_changes(load("activity_logs.json"), "project_status")

    def test_manifest_is_redacted(self):
        manifest = build_manifest(self.changes, [], {"access": "fixture", "scope": {}, "raw_store": {}})
        text = json.dumps(manifest["status_changes"])
        for secret in ("SYNTHETIC ITEM NAME", "pulse_name", "#000", "SYNTHETIC PERSON"):
            self.assertNotIn(secret, text)
        self.assertEqual(manifest["status_changes"][0]["created_at_raw"], "17900106596002324")
        self.assertFalse(manifest["mutation_performed"])

    def test_drift_report_flags_contract_gaps(self):
        report = build_drift_report(self.changes, load("items.json"), load("users_columns.json"), (FIXTURES / "baseline-snapshot.md").read_text(), COLUMNS)
        findings = {finding["code"]: finding for finding in report["findings"]}
        self.assertTrue(report["contract_change_required"])
        vocabulary = findings["STATUS_LABEL_VOCABULARY_DRIFT"]
        self.assertEqual(vocabulary["exact_text_matches"], {"3": "Ready For Approval", "9": "In Progress"})
        self.assertIn("Captions Revisions", vocabulary["monday_labels_without_contract_value"].values())
        self.assertEqual(findings["COLUMN_TYPE_ALIAS"]["log_column_types"], ["color"])
        self.assertEqual(findings["VIDEO_TYPE_MULTI_VALUE"]["items"], {"100002": [5, 16]})
        self.assertEqual(findings["REQUESTED_ETA_TIMEZONE"]["items"][0]["value_utc"], "2026-09-21T21:00:00Z")
        self.assertEqual(findings["ACTOR_IS_NOT_EDITOR"]["editor_column"]["type"], "dropdown")
        drift = findings["LABEL_DRIFT_SINCE_BASELINE"]
        self.assertEqual(drift["status_labels"]["added"], {"8": "Captions Revisions"})
        self.assertEqual(drift["editor_labels"]["added"], {"12": "Synthetic New"})
        self.assertEqual(drift["editor_deactivated"], {"baseline": [1], "live": [1, 8]})
        cross = findings["TIMESTAMP_CROSS_CHECK"]["items"][0]
        self.assertEqual((cross["item_id"], cross["latest_log_id"], cross["labels_agree"]), ("100002", "log-3", True))

    def test_cli_report_seals_raw_dir_and_writes_evidence(self):
        raw_dir = outside_git_dir()
        for name in ("activity_logs.json", "items.json", "users_columns.json"):
            write_immutable(raw_dir, name, (FIXTURES / name).read_bytes())
        out = outside_git_dir()
        code = main(["report", "--raw-dir", str(raw_dir), "--baseline-snapshot", str(FIXTURES / "baseline-snapshot.md"), "--access", "fixture",
                     "--scope", '{"board_id":"900001"}', "--manifest-out", str(out / "m.json"), "--drift-out", str(out / "d.json")])
        self.assertEqual(code, 0)
        manifest = json.loads((out / "m.json").read_text())
        self.assertEqual([payload["name"] for payload in manifest["raw_payloads"]], ["activity_logs.json", "items.json", "users_columns.json"])
        self.assertEqual(manifest["status_change_count"], 3)
        self.assertTrue(json.loads((out / "d.json").read_text())["contract_change_required"])

    def test_cli_capture_without_token_exits_with_missing_access(self):
        saved = os.environ.pop("MONDAY_API_TOKEN", None)
        try:
            code = main(["capture", "--board", "1", "--items", "2", "--since", "a", "--until", "b", "--raw-dir", str(outside_git_dir())])
        finally:
            if saved is not None:
                os.environ["MONDAY_API_TOKEN"] = saved
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
