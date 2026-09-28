import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from atlas_commander import monday_probe as mp
from atlas_commander.contracts import ROOT, schema_errors

FIXTURE = ROOT / "fixtures/monday/activity-logs.synthetic.json"
MAPPING = {"mapping_version": "actor-v1", "actors": {"person-42": "editor-42"}}


def envelope():
    return json.loads(FIXTURE.read_text())


class RecordingTransport:
    def __init__(self, env):
        self.env, self.calls = env, []

    def __call__(self, query, variables, token):
        self.calls.append((query, variables))
        board = {"id": self.env["board_id"], "columns": self.env["columns"], "activity_logs": self.env["activity_logs"]}
        return {"data": {"boards": [board]}}


class MondayProbeTests(unittest.TestCase):
    def test_mutations_are_refused(self):
        client = mp.MondayReadOnlyClient(token="t", transport=RecordingTransport(envelope()))
        for query in ("mutation { delete_item(item_id: 1) { id } }", "  subscription { x }", "query { a } mutation { b }"):
            with self.subTest(query=query), self.assertRaises(mp.ReadOnlyViolation):
                client.query(query, {})

    def test_client_issues_only_queries(self):
        transport = RecordingTransport(envelope())
        client = mp.MondayReadOnlyClient(token="t", transport=transport)
        result = mp.probe(client, "900001", ["700001"], "status", None, None)
        self.assertEqual(len(result["activity_logs"]), 4)
        self.assertTrue(all(query.lstrip().startswith("query") for query, _ in transport.calls))
        self.assertEqual(transport.calls[-1][1]["columns"], ["status"])

    def test_missing_token_reports_exact_access(self):
        saved = os.environ.pop(mp.TOKEN_ENV, None)
        try:
            with self.assertRaisesRegex(mp.MissingAccess, mp.TOKEN_ENV):
                mp.MondayReadOnlyClient()
        finally:
            if saved is not None:
                os.environ[mp.TOKEN_ENV] = saved

    def test_api_errors_surface_as_missing_access(self):
        client = mp.MondayReadOnlyClient(token="t", transport=lambda q, v, t: {"errors": [{"message": "Not Authenticated"}]})
        with self.assertRaisesRegex(mp.MissingAccess, "Not Authenticated"):
            client.columns("1")

    def test_timestamp_conversion_keeps_microseconds(self):
        self.assertEqual(mp.monday_timestamp("17882532001234560"), "2026-09-01T09:00:00.123456Z")

    def test_raw_identifiers_and_timestamps_retained(self):
        env = envelope()
        event, issues = mp.normalize(env["activity_logs"][0], "status", MAPPING)
        self.assertEqual(issues, [])
        self.assertEqual(schema_errors(event, mp.STATUS_SCHEMA), [])
        self.assertEqual((event["event_id"], event["monday_board_id"], event["monday_item_id"]), ("synthetic-log-1", "900001", "700001"))
        self.assertEqual((event["from_status"], event["to_status"]), ("Backlog", "In Progress"))
        self.assertEqual((event["actor_monday_id"], event["actor_id"], event["mapping_version"]), ("person-42", "editor-42", "actor-v1"))
        sample = mp.build_outputs(env, None, MAPPING)["manifest"]["sample"][0]
        self.assertEqual((sample["id"], sample["created_at"]), ("synthetic-log-1", "17882532001234560"))

    def test_unmapped_actor_is_not_guessed(self):
        event, issues = mp.normalize(envelope()["activity_logs"][1], "status", MAPPING)
        self.assertEqual(issues, ["UNRESOLVED_ACTOR"])
        self.assertEqual((event["actor_resolution"], event["actor_id"], event["actor_monday_id"]), ("unresolved_waset_co", None, "person-99"))
        self.assertEqual(schema_errors(event, mp.STATUS_SCHEMA), [])

    def test_mapping_without_version_is_rejected(self):
        event, issues = mp.normalize(envelope()["activity_logs"][0], "status", {"actors": {"person-42": "editor-42"}})
        self.assertEqual(event["actor_resolution"], "unresolved_waset_co")
        self.assertIn("UNRESOLVED_ACTOR", issues)

    def test_unknown_status_label_is_not_mapped(self):
        event, issues = mp.normalize(envelope()["activity_logs"][2], "status", MAPPING)
        self.assertIsNone(event)
        self.assertEqual(issues, ["UNMAPPED_TO_STATUS"])

    def test_non_status_changes_are_ignored(self):
        self.assertEqual(mp.normalize(envelope()["activity_logs"][3], "status"), (None, ["NOT_STATUS_CHANGE"]))
        self.assertEqual(mp.normalize({"id": "x", "event": "update_column_value", "data": "{bad"}, "status"), (None, ["UNPARSEABLE_DATA"]))

    def test_manifest_redacts_people_and_free_text(self):
        manifest = mp.build_outputs(envelope(), None, MAPPING)["manifest"]
        text = json.dumps(manifest)
        for secret in ("person-42", "person-99", "Synthetic item title", "free text", "acct-1"):
            self.assertNotIn(secret, text)
        self.assertEqual(manifest["counts"], {"activity_logs": 4, "normalized_status_events": 2})
        self.assertEqual(manifest["mode"], "fixture")

    def test_drift_report(self):
        drift = mp.build_outputs(envelope(), None, MAPPING)["drift"]
        self.assertEqual(drift["observed_status_labels_not_in_contract"], ["Stuck"])
        self.assertEqual(drift["configured_status_labels_not_in_contract"], ["Stuck"])
        self.assertEqual(drift["contract_statuses_not_configured"], ["Approved", "Delivered", "Revision"])
        self.assertEqual(drift["log_keys"], {"missing": [], "unexpected": []})
        self.assertEqual(drift["issue_counts"], {"NOT_STATUS_CHANGE": 1, "UNMAPPED_TO_STATUS": 1, "UNRESOLVED_ACTOR": 1})
        self.assertTrue(drift["status_column_present"])

    def test_raw_store_is_immutable_and_outside_git(self):
        with self.assertRaises(ValueError):
            mp.store_raw(envelope(), ROOT / "tmp-raw")
        with tempfile.TemporaryDirectory() as tmp:
            path = mp.store_raw(envelope(), Path(tmp))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
            self.assertEqual(mp.store_raw(envelope(), Path(tmp)), path)
            self.assertEqual(json.loads(path.read_text())["activity_logs"], envelope()["activity_logs"])

    def test_outputs_are_deterministic(self):
        first = mp.build_outputs(envelope(), None, MAPPING)
        second = mp.build_outputs(envelope(), None, MAPPING)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_cli_without_token_exits_missing_access(self):
        saved = os.environ.pop(mp.TOKEN_ENV, None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                code = mp.main(["--board-id", "5091110326", "--item-id", "1", "--status-column-id", "status",
                                "--raw-dir", tmp, "--out-dir", tmp])
                self.assertEqual(code, 2)
                self.assertEqual(os.listdir(tmp), [])
        finally:
            if saved is not None:
                os.environ[mp.TOKEN_ENV] = saved


if __name__ == "__main__":
    unittest.main()
