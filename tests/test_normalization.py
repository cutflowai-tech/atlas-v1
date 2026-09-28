import copy
import json
import unittest
from pathlib import Path

from atlas_commander.contracts import schema_errors
from atlas_commander.normalization import normalize_events

ROOT = Path(__file__).resolve().parents[1]
MAPPING = {"version": "status-v1", "statuses": {"Backlog": "Backlog", "In Progress": "In Progress", "Ready For Approval": "Ready For Approval"}}


class NormalizationTests(unittest.TestCase):
    def fixture(self, name):
        return json.loads((ROOT / "fixtures" / name).read_text())

    def test_canonical_fixtures_and_raw_evidence(self):
        events = [self.fixture("good/status-in-progress.json"), self.fixture("good/status-ready.json")]
        original = copy.deepcopy(events)
        result = normalize_events(events, MAPPING)
        accepted, quarantined = result
        self.assertEqual([event["event_id"] for event in accepted], [event["event_id"] for event in events])
        self.assertEqual(quarantined, [])
        self.assertEqual(result.status_mapping_version, "status-v1")
        for event in accepted:
            self.assertEqual(schema_errors(event, "normalized-status-event.schema.json"), [])
        accepted[0]["event_id"] = "changed"
        self.assertEqual(result.raw_sources, original)
        self.assertEqual(events, original)

    def activity(self):
        return {"id": "123", "board_id": 42, "created_at": "2026-09-01T09:00:00.123456+02:00", "user_id": 7,
                "event": "update_column_value", "data": json.dumps({"pulse_id": 99, "column_id": "status",
                "previous_value": {"label": {"text": "Backlog"}}, "value": {"label": {"text": "In Progress"}}})}

    def test_monday_json_preserves_ids_and_timestamp_without_guessing_actor(self):
        raw = self.activity()
        result = normalize_events(json.dumps([raw]), MAPPING)
        self.assertEqual(result.quarantined, [])
        event = result.accepted[0]
        self.assertEqual(event["monday_board_id"], "42")
        self.assertEqual(event["monday_item_id"], "99")
        self.assertEqual(event["status_column_id"], "status")
        self.assertEqual(event["occurred_at"], raw["created_at"])
        self.assertEqual(event["actor_monday_id"], "7")
        self.assertIsNone(event["actor_id"])
        self.assertEqual(event["actor_resolution"], "unresolved_waset_co")
        self.assertEqual(schema_errors(event, "normalized-status-event.schema.json"), [])

    def test_identical_duplicates_are_quarantined(self):
        raw = self.activity()
        result = normalize_events([raw, copy.deepcopy(raw), raw], MAPPING)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual([q["reason"] for q in result.quarantined], ["DUPLICATE_EVENT_ID"] * 2)

    def test_conflicts_quarantine_every_occurrence_regardless_of_order(self):
        events = self.fixture("bad/duplicate-event.json")
        for inputs in (events, events[::-1], events + events[:1]):
            result = normalize_events(inputs, MAPPING)
            self.assertEqual(result.accepted, [])
            self.assertEqual([q["reason"] for q in result.quarantined], ["CONFLICTING_EVENT_ID"] * len(inputs))

    def test_unknown_status_never_guessed(self):
        raw = self.fixture("bad/unknown-transition.json")
        result = normalize_events([raw], MAPPING)
        self.assertEqual(result.accepted, [])
        self.assertEqual(result.quarantined[0]["reason"], "UNKNOWN_STATUS")
        raw["to_status"] = "In Progress"
        raw["from_status"] = "Unmapped"
        self.assertEqual(normalize_events([raw], MAPPING).quarantined[0]["reason"], "UNKNOWN_STATUS")

    def test_unresolved_fixture_remains_explicit(self):
        raw = self.fixture("bad/unresolved-waset-co.json")
        accepted = normalize_events([raw], MAPPING).accepted
        self.assertEqual(accepted[0]["actor_resolution"], "unresolved_waset_co")
        self.assertEqual(accepted[0]["mapping_version"], "status-v1")

    def test_bad_records_do_not_discard_valid_neighbors(self):
        good = self.activity()
        for patch, reason in [({"data": "{"}, "INVALID_ACTIVITY_DATA"), ({"data": "[]"}, "INVALID_ACTIVITY_DATA"),
                              ({"created_at": "2026-09-01T09:00:00"}, "INVALID_TIMESTAMP"),
                              ({"created_at": "invalid"}, "INVALID_TIMESTAMP"), ({"board_id": True}, "INVALID_ID"),
                              ({"event": "delete_item"}, "UNSUPPORTED_EVENT")]:
            bad = dict(good, id="bad", **patch)
            with self.subTest(patch=patch):
                result = normalize_events([bad, good], MAPPING)
                self.assertEqual(len(result.accepted), 1)
                self.assertEqual(result.quarantined[0]["reason"], reason)
        self.assertEqual(normalize_events([None], MAPPING).quarantined[0]["reason"], "INVALID_EVENT")

    def test_explicit_alias_mapping_and_absent_previous_status(self):
        raw = self.activity()
        raw["data"] = {"pulse_id": 99, "column_id": "status", "value": "Working"}
        mapping = {"version": "v2", "statuses": {"Working": "In Progress"}}
        result = normalize_events([raw], mapping)
        self.assertEqual(result.accepted[0]["to_status"], "In Progress")
        self.assertIsNone(result.accepted[0]["from_status"])

    def test_mapping_must_be_versioned_and_canonical(self):
        for mapping in ({}, {"version": "v1", "statuses": {"x": "Invented"}}, {"statuses": MAPPING["statuses"]}):
            with self.assertRaises(ValueError):
                normalize_events([], mapping)

    def test_partial_canonical_identity_is_quarantined(self):
        raw = self.fixture("good/status-ready.json")
        del raw["mapping_version"]
        del raw["actor_mapping_version"]
        self.assertEqual(normalize_events([raw], MAPPING).quarantined[0]["reason"], "INVALID_ID")

    def test_malformed_previous_status_is_not_treated_as_missing(self):
        raw = self.activity()
        data = json.loads(raw["data"])
        data["previous_value"] = {"unexpected": "Backlog"}
        raw["data"] = data
        self.assertEqual(normalize_events([raw], MAPPING).quarantined[0]["reason"], "UNKNOWN_STATUS")

    def test_deterministic_results(self):
        raw = [self.activity(), None]
        self.assertEqual(normalize_events(raw, MAPPING), normalize_events(raw, MAPPING))


if __name__ == "__main__":
    unittest.main()
