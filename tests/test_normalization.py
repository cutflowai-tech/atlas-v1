import copy
import json
import random
import unittest

from atlas_commander.contracts import ROOT, assert_valid, schema_errors, semantic_codes
from atlas_commander.normalization import normalize_events

FIXTURE = json.loads((ROOT / "fixtures/monday/activity-status-events.json").read_text())
SCHEMA = "normalized-status-event.schema.json"


def activity(event_id, text, previous=None, *, user_id="42", created_at="17889300000000000", column_id="status", event="update_column_value", **extra):
    data = {
        "board_id": 1,
        "pulse_id": 11,
        "column_id": column_id,
        "column_type": "color",
        "value": {"label": {"index": 0, "text": text}} if text is not None else {"label": None},
        "previous_value": {"label": {"index": 1, "text": previous}} if previous is not None else None,
    }
    data.update(extra)
    return {"id": event_id, "event": event, "user_id": user_id, "created_at": created_at, "entity": "pulse", "data": json.dumps(data)}


class NormalizeFixtureTests(unittest.TestCase):
    def setUp(self):
        self.raw = copy.deepcopy(FIXTURE["activity_logs"])
        self.result = normalize_events(self.raw, FIXTURE["status_mapping"], FIXTURE["actor_mapping"])

    def reasons(self):
        return {(record["event_id"], record["reason"]) for record in self.result.quarantined}

    def test_accepted_events_satisfy_contract(self):
        self.assertEqual([event["event_id"] for event in self.result.accepted], ["event-waset-co", "event-100", "event-101"])
        for event in self.result.accepted:
            with self.subTest(event=event["event_id"]):
                self.assertEqual(schema_errors(event, SCHEMA), [])
                expected = ["UNRESOLVED_ACTOR"] if event["actor_resolution"] == "unresolved_waset_co" else []
                self.assertEqual(semantic_codes(event, SCHEMA), expected)

    def test_duplicate_and_unknown_events_quarantined(self):
        self.assertEqual(
            self.reasons(),
            {
                ("event-dup", "DUPLICATE_EVENT_CONFLICT"),
                ("event-unknown", "UNKNOWN_STATUS"),
                ("event-eta", "NON_STATUS_EVENT"),
            },
        )
        self.assertEqual(sum(record["event_id"] == "event-dup" for record in self.result.quarantined), 2)
        accepted_ids = {event["event_id"] for event in self.result.accepted}
        self.assertTrue(accepted_ids.isdisjoint({"event-dup", "event-unknown", "event-eta"}))

    def test_identical_duplicate_is_deduplicated_not_quarantined(self):
        self.assertEqual([event["event_id"] for event in self.result.accepted].count("event-101"), 1)
        self.assertEqual(self.result.duplicate_event_ids, ["event-101"])

    def test_board_item_column_and_timestamp_fidelity(self):
        ready = next(event for event in self.result.accepted if event["event_id"] == "event-101")
        self.assertEqual((ready["monday_board_id"], ready["monday_item_id"], ready["status_column_id"]), ("1", "11", "status"))
        # Monday ticks are 100ns units: all seven sub-second digits are kept, not rounded.
        self.assertEqual(ready["occurred_at"], "2026-09-09T07:00:00.1234567Z")
        self.assertEqual((ready["from_status"], ready["to_status"]), ("In Progress", "Ready For Approval"))
        offset = next(event for event in self.result.accepted if event["event_id"] == "event-waset-co")
        self.assertEqual(offset["occurred_at"], "2026-09-01T08:30:00Z")

    def test_canonical_actor_preserved_and_unresolved_explicit(self):
        editor = next(event for event in self.result.accepted if event["event_id"] == "event-100")
        self.assertEqual(
            (editor["actor_resolution"], editor["actor_monday_id"], editor["actor_id"], editor["mapping_version"]),
            ("canonical_monday_id", "42", "editor-42", "actor-v1"),
        )
        unresolved = next(event for event in self.result.accepted if event["event_id"] == "event-waset-co")
        self.assertEqual(
            (unresolved["actor_resolution"], unresolved["actor_monday_id"], unresolved["actor_id"]),
            ("unresolved_waset_co", "77", None),
        )
        self.assertEqual(self.result.unresolved_actor_event_ids, ["event-waset-co"])

    def test_raw_source_preserved_separately_and_unmutated(self):
        self.assertEqual(self.raw, FIXTURE["activity_logs"])
        self.assertEqual(set(self.result.raw_sources), {event["event_id"] for event in self.result.accepted})
        self.assertEqual(self.result.raw_sources["event-100"], FIXTURE["activity_logs"][0])
        for event in self.result.accepted:
            self.assertNotIn("raw", event)
        unknown = next(record for record in self.result.quarantined if record["event_id"] == "event-unknown")
        self.assertEqual(unknown["raw"], FIXTURE["activity_logs"][5])
        self.assertEqual(self.result.status_mapping_version, "status-map-v1")
        self.assertEqual(self.result.actor_mapping_version, "actor-v1")

    def test_deterministic_under_input_reordering(self):
        shuffled = copy.deepcopy(FIXTURE["activity_logs"])
        random.Random(7).shuffle(shuffled)
        again = normalize_events(shuffled, FIXTURE["status_mapping"], FIXTURE["actor_mapping"])
        self.assertEqual(again.accepted, self.result.accepted)
        self.assertEqual({(r["event_id"], r["reason"]) for r in again.quarantined}, self.reasons())


class NormalizeEdgeCaseTests(unittest.TestCase):
    mapping = FIXTURE["status_mapping"]

    def normalize(self, *events, actor_mapping=None):
        return normalize_events(list(events), self.mapping, actor_mapping)

    def test_unknown_previous_status_is_not_guessed(self):
        result = self.normalize(activity("e1", "Working on it", previous="Stuck"))
        self.assertEqual(result.accepted, [])
        self.assertEqual(result.quarantined[0]["reason"], "UNKNOWN_STATUS")

    def test_label_match_is_exact(self):
        result = self.normalize(activity("e1", "working on it"))
        self.assertEqual(result.quarantined[0]["reason"], "UNKNOWN_STATUS")

    def test_cleared_status_is_quarantined(self):
        result = self.normalize(activity("e1", None, previous="Working on it"))
        self.assertEqual(result.quarantined[0]["reason"], "UNKNOWN_STATUS")

    def test_first_status_assignment_has_null_from_status(self):
        result = self.normalize(activity("e1", "Working on it"), actor_mapping=FIXTURE["actor_mapping"])
        self.assertIsNone(result.accepted[0]["from_status"])
        assert_valid(result.accepted[0], SCHEMA)

    def test_without_actor_mapping_actor_stays_unresolved(self):
        result = self.normalize(activity("e1", "Working on it"))
        event = result.accepted[0]
        self.assertEqual((event["actor_resolution"], event["actor_monday_id"], event["actor_id"], event["mapping_version"]), ("unresolved_waset_co", "42", None, None))
        self.assertEqual(schema_errors(event, SCHEMA), [])
        self.assertEqual(semantic_codes(event, SCHEMA), ["UNRESOLVED_ACTOR"])
        self.assertEqual(result.unresolved_actor_event_ids, ["e1"])

    def test_missing_id_and_malformed_data_quarantined(self):
        no_id = activity("e1", "Working on it")
        del no_id["id"]
        bad_json = activity("e2", "Working on it")
        bad_json["data"] = "{not json"
        no_item = activity("e3", "Working on it", pulse_id=None)
        result = self.normalize(no_id, bad_json, no_item, "not-an-object")
        self.assertEqual([record["reason"] for record in result.quarantined], ["MISSING_EVENT_ID", "MALFORMED_EVENT", "MALFORMED_EVENT", "MISSING_EVENT_ID"])

    def test_naive_or_invalid_timestamps_quarantined(self):
        result = self.normalize(activity("e1", "Working on it", created_at="2026-09-01T09:00:00"), activity("e2", "Working on it", created_at="yesterday"))
        self.assertEqual([record["reason"] for record in result.quarantined], ["INVALID_TIMESTAMP", "INVALID_TIMESTAMP"])

    def test_non_status_event_type_quarantined(self):
        result = self.normalize(activity("e1", "Working on it", event="create_pulse"))
        self.assertEqual(result.quarantined[0]["reason"], "NON_STATUS_EVENT")

    def test_duplicate_where_one_copy_is_malformed_is_conflict(self):
        good = activity("e1", "Working on it")
        broken = dict(good, data="{not json")
        result = self.normalize(good, broken)
        self.assertEqual(result.accepted, [])
        self.assertEqual([record["reason"] for record in result.quarantined], ["DUPLICATE_EVENT_CONFLICT"] * 2)

    def test_dict_and_string_data_forms_are_identical_duplicates(self):
        as_string = activity("e1", "Working on it")
        as_dict = dict(as_string, data=json.loads(as_string["data"]))
        result = self.normalize(as_string, as_dict)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.duplicate_event_ids, ["e1"])

    def test_ordering_uses_exact_instant_not_string(self):
        later = activity("a", "Working on it", created_at="2026-09-01T09:00:00.5Z")
        earlier = activity("b", "Working on it", created_at="2026-09-01T09:00:00Z")
        result = self.normalize(later, earlier)
        self.assertEqual([event["event_id"] for event in result.accepted], ["b", "a"])

    def test_out_of_range_timestamps_quarantine_without_aborting_batch(self):
        invalid = [10**5000, 10**100, "9" * 5000, "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"]
        for index, timestamp in enumerate(invalid):
            with self.subTest(case=index):
                result = self.normalize(activity("bad", "Working on it", created_at=timestamp), activity("good", "Working on it"))
                self.assertEqual([e["event_id"] for e in result.accepted], ["good"])
                self.assertEqual(result.quarantined[0]["reason"], "INVALID_TIMESTAMP")

    def test_strict_event_and_actor_ids(self):
        for value in [True, False, {}, {"id": 42}, [], [42], 42.0]:
            with self.subTest(value=value):
                result = self.normalize(activity(value, "Working on it"), activity("actor", "Working on it", user_id=value))
                self.assertEqual(result.accepted, [])
                self.assertEqual([q["reason"] for q in result.quarantined], ["MISSING_EVENT_ID", "MALFORMED_EVENT"])
        result = self.normalize(activity(123, "Working on it", user_id=42), actor_mapping=FIXTURE["actor_mapping"])
        self.assertEqual((result.accepted[0]["event_id"], result.accepted[0]["actor_monday_id"], result.accepted[0]["actor_id"]), ("123", "42", "editor-42"))

    def test_all_raw_occurrences_have_immutable_detached_snapshots(self):
        original = activity("e1", "Working on it")
        decoded = dict(original, data=json.loads(original["data"]))
        decoded["extra"] = [1, {"nested": [2]}]
        raw = [original, copy.deepcopy(original), decoded, activity(None, "Working on it")]
        result = self.normalize(*raw)
        self.assertEqual(len(result.raw_input_snapshots), 4)
        self.assertEqual(result.raw_input_snapshots[0], original)
        self.assertEqual(result.raw_input_snapshots[1], original)
        self.assertIsInstance(result.raw_input_snapshots[0]["data"], str)
        self.assertEqual(result.raw_input_snapshots[2]["data"], json.loads(original["data"]))
        with self.assertRaises(TypeError):
            result.raw_input_snapshots[2]["data"]["pulse_id"] = 99
        with self.assertRaises(TypeError):
            result.raw_input_snapshots[2]["extra"][1]["nested"][0] = 99
        decoded["data"]["pulse_id"] = 99
        decoded["extra"][1]["nested"][0] = 99
        self.assertEqual(result.raw_input_snapshots[2]["data"]["pulse_id"], 11)
        self.assertEqual(result.raw_input_snapshots[2]["extra"][1]["nested"], (2,))

    def test_identical_duplicates_keep_every_raw_copy(self):
        original = activity("e1", "Working on it")
        result = self.normalize(original, copy.deepcopy(original))
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.raw_sources, {"e1": original})
        self.assertEqual(result.raw_input_snapshots, (original, original))
        result.raw_sources["e1"]["id"] = "changed"
        self.assertEqual(result.raw_input_snapshots[0]["id"], "e1")

    def test_malformed_mapping_objects_raise_value_error(self):
        for mapping in [[], "v1", 42, True]:
            with self.subTest(mapping=mapping):
                with self.assertRaises(ValueError):
                    normalize_events([], mapping)
                with self.assertRaises(ValueError):
                    normalize_events([], self.mapping, mapping)
        for labels in [{"Done": []}, {"Done": {}}, {42: "Approved"}]:
            with self.assertRaises(ValueError):
                normalize_events([], dict(self.mapping, labels=labels))
        for actors in [{42: "editor-42"}, {"42": {}}, {"42": []}, {"42": True}, {"42": 42.0}, {"42": " "}]:
            with self.assertRaises(ValueError):
                normalize_events([], self.mapping, {"version": "v1", "actors": actors})

    def test_raw_actor_claims_cannot_override_versioned_mapping(self):
        raw = activity("e1", "Working on it", user_id=77)
        raw.update(actor_id="editor-42", actor_monday_id="42", mapping_version="forged", actor_resolution="canonical_monday_id")
        event = self.normalize(raw, actor_mapping=FIXTURE["actor_mapping"]).accepted[0]
        self.assertEqual((event["actor_resolution"], event["actor_monday_id"], event["actor_id"], event["mapping_version"]), ("unresolved_waset_co", "77", None, "actor-v1"))

    def test_other_color_column_is_not_status(self):
        result = self.normalize(activity("e1", "Working on it", column_id="priority"))
        self.assertEqual(result.quarantined[0]["reason"], "NON_STATUS_EVENT")

    def test_duplicate_fingerprints_preserve_json_types_in_both_orders(self):
        for location, field, valid_value, invalid_value in [
            ("entry", "user_id", 42, 42.0),
            ("data", "board_id", 1, True),
            ("data", "pulse_id", 11, 11.0),
        ]:
            valid = activity("same", "Working on it", user_id=42)
            valid["data"] = json.loads(valid["data"])
            target = valid if location == "entry" else valid["data"]
            target[field] = valid_value
            invalid = copy.deepcopy(valid)
            target = invalid if location == "entry" else invalid["data"]
            target[field] = invalid_value
            for records in [(valid, invalid), (invalid, valid)]:
                with self.subTest(field=field, first=records[0]):
                    result = self.normalize(*records)
                    self.assertEqual(result.accepted, [])
                    self.assertEqual(result.duplicate_event_ids, [])
                    self.assertEqual([q["reason"] for q in result.quarantined], ["DUPLICATE_EVENT_CONFLICT"] * 2)
                    self.assertEqual(len(result.raw_input_snapshots), 2)

    def test_board_and_item_ids_use_strict_id_validation(self):
        for field in ["board_id", "pulse_id"]:
            for value in [True, False, {}, [], 1.0, " "]:
                with self.subTest(field=field, value=value):
                    result = self.normalize(activity("e1", "Working on it", **{field: value}))
                    self.assertEqual(result.accepted, [])
                    self.assertEqual(result.quarantined[0]["reason"], "MALFORMED_EVENT")

    def test_invalid_mappings_rejected(self):
        with self.assertRaises(ValueError):
            normalize_events([], {"status_column_ids": ["status"], "labels": {"Done": "Approved"}})
        with self.assertRaises(ValueError):
            normalize_events([], {"version": "v1", "status_column_ids": ["status"], "labels": {"Done": "Finished"}})
        with self.assertRaises(ValueError):
            normalize_events([], {"version": "v1", "labels": {"Done": "Approved"}})
        with self.assertRaises(ValueError):
            normalize_events([], self.mapping, {"actors": {"42": "editor-42"}})


if __name__ == "__main__":
    unittest.main()
