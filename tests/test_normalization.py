import json
import unittest
from copy import deepcopy
from pathlib import Path

from atlas_commander.contracts import schema_errors
from atlas_commander.normalization import normalize_events

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
STATUSES = ["Backlog", "In Progress", "Ready For Approval", "Revision", "Approved", "Delivered"]
MAPPING = {"version": "status-v1", "statuses": {value: value for value in STATUSES}}


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class NormalizationTests(unittest.TestCase):
    def test_good_fixtures_preserve_contract_and_identity(self):
        events = [fixture("good/status-in-progress.json"), fixture("good/status-ready.json")]
        result = normalize_events(events, MAPPING)
        accepted, quarantined = result
        self.assertEqual(accepted, events)
        self.assertEqual(quarantined, [])
        for event in accepted:
            self.assertEqual(schema_errors(event, "normalized-status-event.schema.json"), [])
        self.assertEqual(result.status_mapping_version, "status-v1")

    def test_unknown_fixture_is_quarantined(self):
        result = normalize_events([fixture("bad/unknown-transition.json")], MAPPING)
        self.assertEqual(result.accepted, [])
        self.assertEqual(result.quarantined[0]["reason"], "UNKNOWN_STATUS")

    def test_conflicting_fixture_quarantines_every_copy_in_any_order(self):
        events = fixture("bad/duplicate-event.json")
        for records in (events, events[::-1], events + [events[0]]):
            result = normalize_events(records, MAPPING)
            self.assertEqual(result.accepted, [])
            self.assertEqual([q["reason"] for q in result.quarantined], ["CONFLICTING_DUPLICATE_ID"] * len(records))

    def test_identical_duplicates_keep_one_and_evidence_for_repeat(self):
        event = fixture("good/status-ready.json")
        result = normalize_events([event, dict(reversed(list(event.items())))], MAPPING)
        self.assertEqual(result.accepted, [event])
        self.assertEqual(result.quarantined[0]["reason"], "DUPLICATE_EVENT")
        self.assertEqual(result.quarantined[0]["source_index"], 1)

    def test_unresolved_fixture_remains_explicit(self):
        event = fixture("bad/unresolved-waset-co.json")
        self.assertEqual(normalize_events([event], MAPPING).accepted, [event])

    def activity(self):
        return {"id": "00023", "user_id": 42, "created_at": "2026-09-01T09:00:00.1234567+02:00",
                "event": "update_column_value", "data": json.dumps({"board_id": "00012", "pulse_id": 99,
                "column_id": "status_2", "previous_value": {"label": {"text": "Queued"}},
                "value": {"label": {"text": "Working"}}})}

    def test_activity_json_explicit_mapping_and_source_fidelity(self):
        raw = self.activity()
        mapping = {"version": "status-v2", "statuses": {"Queued": "Backlog", "Working": "In Progress"}}
        original = deepcopy(raw)
        result = normalize_events(json.dumps([raw]), mapping)
        event = result.accepted[0]
        self.assertEqual((event["event_id"], event["monday_board_id"], event["monday_item_id"], event["status_column_id"]),
                         ("00023", "00012", "99", "status_2"))
        self.assertEqual(event["occurred_at"], raw["created_at"])
        self.assertEqual(event["actor_monday_id"], "42")
        self.assertEqual(event["actor_resolution"], "unresolved_waset_co")
        self.assertIsNone(event["actor_id"])
        self.assertEqual(result.raw_sources, [original])
        self.assertEqual(raw, original)
        self.assertEqual(schema_errors(event, "normalized-status-event.schema.json"), [])

    def test_epoch_ticks_keep_seventh_fractional_digit(self):
        raw = self.activity()
        raw["created_at"] = "17882532001234567"
        mapping = {"version": "v1", "statuses": {"Queued": "Backlog", "Working": "In Progress"}}
        self.assertEqual(normalize_events([raw], mapping).accepted[0]["occurred_at"], "2026-09-01T09:00:00.1234567Z")

    def test_unknown_previous_status_is_not_guessed(self):
        event = fixture("good/status-ready.json")
        event["from_status"] = "Unknown"
        self.assertEqual(normalize_events([event], MAPPING).quarantined[0]["reason"], "UNKNOWN_STATUS")

    def test_malformed_records_do_not_stop_batch(self):
        good = fixture("good/status-ready.json")
        invalid_time = {**good, "event_id": "bad-time", "occurred_at": "2026-09-01"}
        invalid_id = {**good, "event_id": "bad-id", "monday_board_id": True}
        result = normalize_events([None, {"id": "bad-json", "data": "{"}, invalid_time, invalid_id, good], MAPPING)
        self.assertEqual(result.accepted, [good])
        self.assertEqual([q["reason"] for q in result.quarantined],
                         ["INVALID_RECORD", "INVALID_ACTIVITY_DATA", "SCHEMA_INVALID", "INVALID_ID"])

    def test_incomplete_actor_mapping_never_invents_identity(self):
        event = fixture("good/status-ready.json")
        del event["mapping_version"]
        accepted = normalize_events([event], MAPPING).accepted[0]
        self.assertEqual(accepted["actor_monday_id"], "person-42")
        self.assertIsNone(accepted["actor_id"])
        self.assertEqual(accepted["actor_resolution"], "unresolved_waset_co")

    def test_deterministic_detached_sources_and_outputs(self):
        events = [fixture("good/status-ready.json"), fixture("bad/unknown-transition.json")]
        result = normalize_events(events, MAPPING)
        self.assertEqual(result, normalize_events(events, MAPPING))
        result.accepted[0]["to_status"] = "Revision"
        result.quarantined[0]["raw_source"]["to_status"] = "Revision"
        self.assertEqual(result.raw_sources, events)
        result.raw_sources[0]["to_status"] = "Approved"
        self.assertEqual(events[0]["to_status"], "Ready For Approval")

    def test_null_origin_and_explicit_index_mapping(self):
        raw = self.activity()
        data = json.loads(raw["data"])
        data.pop("previous_value")
        data["value"] = {"label": {"index": 2}}
        raw["data"] = data
        result = normalize_events([raw], {"version": "v1", "statuses": {"2": "In Progress"}})
        self.assertIsNone(result.accepted[0]["from_status"])
        self.assertEqual(result.accepted[0]["to_status"], "In Progress")

    def test_unsupported_activity_is_quarantined(self):
        raw = self.activity()
        raw["event"] = "delete_pulse"
        self.assertEqual(normalize_events([raw], MAPPING).quarantined[0]["reason"], "UNSUPPORTED_EVENT")

    def test_invalid_conflicting_record_blocks_valid_copy(self):
        good = fixture("good/status-ready.json")
        bad = {**good, "to_status": "Unknown"}
        result = normalize_events([good, bad], MAPPING)
        self.assertEqual(result.accepted, [])
        self.assertEqual([q["reason"] for q in result.quarantined], ["CONFLICTING_DUPLICATE_ID"] * 2)

    def test_mapping_requires_version_and_canonical_targets(self):
        for mapping in ({}, {"statuses": {}}, {"version": "v1", "statuses": {"x": "Guess"}}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                normalize_events([], mapping)

    def test_canonical_labels_also_require_explicit_mapping(self):
        result = normalize_events([fixture("good/status-ready.json")],
                                  {"version": "v1", "statuses": {"Backlog": "Backlog"}})
        self.assertEqual(result.quarantined[0]["reason"], "UNKNOWN_STATUS")


if __name__ == "__main__":
    unittest.main()
