import json
import unittest
from copy import deepcopy

from atlas_commander.contracts import ROOT, schema_errors
from atlas_commander.normalization import STATUSES, normalize_events


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.mapping = {status: status for status in STATUSES}
        self.event = self.fixture("good/status-in-progress.json")

    def fixture(self, path):
        return json.loads((ROOT / "fixtures" / path).read_text())

    def test_good_fixtures_preserve_contract_and_raw(self):
        events = [self.event, self.fixture("good/status-ready.json")]
        original = deepcopy(events)
        result = normalize_events(events, self.mapping)
        accepted, quarantined = result
        self.assertEqual(accepted, original)
        self.assertEqual(quarantined, [])
        self.assertEqual(result.raw_sources, original)
        self.assertEqual(events, original)
        accepted[0]["event_id"] = "changed"
        self.assertEqual(result.raw_sources, original)
        result.raw_sources[0]["event_id"] = "raw-changed"
        self.assertEqual(events, original)

    def test_identical_duplicates(self):
        result = normalize_events([self.event, dict(reversed(list(self.event.items())))], self.mapping)
        self.assertEqual(result.accepted, [self.event])
        self.assertEqual(result.quarantined[0]["reason"], "DUPLICATE_EVENT")
        self.assertEqual(result.quarantined[0]["input_index"], 1)

    def test_conflicts_quarantine_every_occurrence_in_any_order(self):
        events = self.fixture("bad/duplicate-event.json")
        for batch in (events, events[::-1], events + [events[0]]):
            result = normalize_events(batch, self.mapping)
            self.assertEqual(result.accepted, [])
            self.assertEqual([q["reason"] for q in result.quarantined], ["CONFLICTING_DUPLICATE_EVENT"] * len(batch))
            self.assertEqual([q["raw_source"] for q in result.quarantined], batch)

    def test_unknown_status_never_guessed(self):
        for event in (self.fixture("bad/unknown-transition.json"), dict(self.event, from_status="Unknown")):
            result = normalize_events([event], self.mapping)
            self.assertEqual(result.accepted, [])
            self.assertEqual(result.quarantined[0]["reason"], "UNKNOWN_STATUS")
        self.assertEqual(normalize_events([self.event], {}).accepted, [])

    def test_monday_json_and_explicit_mapping(self):
        raw = {"id": 100, "board_id": 7, "user_id": 42, "event": "update_column_value",
               "created_at": "2026-09-01T12:00:00.123456+03:00",
               "data": json.dumps({"pulse_id": 9, "column_id": "status_2", "previous_value": None,
                                   "value": {"label": {"text": "Working"}}})}
        result = normalize_events(json.dumps([raw]), {"Working": "In Progress"})
        event = result.accepted[0]
        self.assertEqual(schema_errors(event, "normalized-status-event.schema.json"), [])
        self.assertEqual((event["event_id"], event["monday_board_id"], event["monday_item_id"], event["status_column_id"]),
                         ("100", "7", "9", "status_2"))
        self.assertEqual(event["occurred_at"], raw["created_at"])
        self.assertEqual(event["actor_monday_id"], "42")
        self.assertEqual(event["actor_resolution"], "unresolved_waset_co")
        self.assertIsNone(event["actor_id"])
        self.assertIsNone(event["from_status"])
        self.assertEqual(result.raw_sources, [raw])
        self.assertEqual(result, normalize_events(json.dumps([raw]), {"Working": "In Progress"}))

    def test_unresolved_and_unversioned_actor_mapping(self):
        unresolved = self.fixture("bad/unresolved-waset-co.json")
        self.assertEqual(normalize_events([unresolved], self.mapping).accepted, [unresolved])
        event = dict(self.event, mapping_version=None)
        normalized = normalize_events([event], self.mapping).accepted[0]
        self.assertEqual(normalized["actor_monday_id"], "person-42")
        self.assertIsNone(normalized["actor_id"])
        self.assertEqual(normalized["actor_resolution"], "unresolved_waset_co")

    def test_invalid_records_are_isolated(self):
        invalid = [None, {}, dict(self.event, occurred_at="yesterday"), dict(self.event, occurred_at=123),
                   dict(self.event, monday_item_id=""), dict(self.event, data="{"), dict(self.event, data=[]),
                   dict(self.event, event="delete_pulse")]
        for raw in invalid:
            with self.subTest(raw=raw):
                result = normalize_events([raw, dict(self.event, event_id="valid")], self.mapping)
                self.assertEqual(len(result.accepted), 1)
                self.assertEqual(len(result.quarantined), 1)
                self.assertEqual(result.quarantined[0]["raw_source"], raw)

    def test_bad_configuration(self):
        for mapping in ({"Working": "Unknown"}, {"Working": []}, None):
            with self.assertRaises(ValueError):
                normalize_events([], mapping)
        with self.assertRaises(TypeError):
            normalize_events({}, self.mapping)
        self.assertEqual(normalize_events([], {}).accepted, [])


if __name__ == "__main__":
    unittest.main()
