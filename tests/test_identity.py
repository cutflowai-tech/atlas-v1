import copy
import json
import unittest
from dataclasses import replace

from atlas_commander.contracts import ROOT, schema_errors
from atlas_commander.identity import EditorObservation, resolve_editor


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.identity = json.loads((ROOT / "fixtures/good/editor-identity.json").read_text())
        self.version = self.identity["mapping_version"]
        self.person = self.identity["monday_person_id"]
        self.mappings = {self.version: {self.person: [self.identity]}}
        self.observation = EditorObservation(
            monday_person_ids=(self.person,), monday_board_id="board-1",
            monday_item_id="item-1", editor_column_id="editor",
            source_timestamp="2026-01-01T12:00:00Z", event_id="editor-event-1",
            context="historical",
        )

    def resolve(self, observation=None, mappings=None, version=None, **kwargs):
        return resolve_editor(
            observation if observation is not None else self.observation,
            mappings if mappings is not None else self.mappings,
            mapping_version=self.version if version is None else version,
            **kwargs,
        )

    def assert_quarantined(self, result, code):
        self.assertIsNone(result["identity"])
        self.assertEqual(result["exception"], {"code": code})
        self.assertEqual(result["evidence"]["monday_item_id"], "item-1")

    def test_fixture_resolves_to_frozen_contract_with_evidence(self):
        result = self.resolve()
        self.assertEqual(result["identity"], self.identity)
        self.assertEqual(schema_errors(result["identity"], "editor-identity.schema.json"), [])
        self.assertIsNone(result["exception"])
        self.assertEqual(result["evidence"]["event_id"], "editor-event-1")
        self.assertEqual(result["evidence"]["monday_person_ids"], [self.person])
        self.assertEqual(result["evidence"]["mapping_candidates"], [self.identity])

    def test_missing_editor_is_quarantined(self):
        self.assert_quarantined(self.resolve(replace(self.observation, monday_person_ids=())), "MISSING_EDITOR")

    def test_multiple_editors_are_quarantined_even_when_one_is_unmapped(self):
        self.assert_quarantined(
            self.resolve(replace(self.observation, monday_person_ids=(self.person, "unknown"))), "AMBIGUOUS_EDITOR",
        )

    def test_mapping_conflicts_quarantined_independent_of_order(self):
        conflicting = {**self.identity, "editor_id": "editor-other"}
        self.mappings[self.version][self.person].append(conflicting)
        first = self.resolve()
        self.assert_quarantined(first, "AMBIGUOUS_EDITOR")
        self.mappings[self.version][self.person].reverse()
        self.assertEqual(first, self.resolve())
        self.assertEqual(len(first["evidence"]["mapping_candidates"]), 2)

    def test_missing_mapping_version_never_uses_latest(self):
        for version in ("", "identity-v999"):
            with self.subTest(version=version):
                self.assert_quarantined(self.resolve(version=version), "MISSING_MAPPING_VERSION")

    def test_versions_are_selected_exactly(self):
        newer = {**self.identity, "mapping_version": "identity-v2", "editor_id": "editor-new"}
        self.mappings["identity-v2"] = {self.person: [newer]}
        self.assertEqual(self.resolve()["identity"], self.identity)
        self.assertEqual(self.resolve(version="identity-v2")["identity"], newer)

    def test_names_and_normalized_ids_never_resolve(self):
        for person in (self.identity["display_name"], self.person.upper(), " " + self.person, "unknown"):
            with self.subTest(person=person):
                self.assert_quarantined(self.resolve(replace(self.observation, monday_person_ids=(person,))), "UNMAPPED_EDITOR")

    def test_invalid_person_ids_rejected_without_coercion(self):
        for person in (None, "", " ", 42, True):
            with self.subTest(person=person):
                self.assert_quarantined(self.resolve(replace(self.observation, monday_person_ids=(person,))), "INVALID_EDITOR_ID")

    def test_current_snapshot_cannot_establish_historical_editor(self):
        current = replace(self.observation, context="current")
        self.assert_quarantined(self.resolve(current), "MISSING_HISTORICAL_EDITOR_EVIDENCE")
        self.assertEqual(self.resolve(current, historical=False)["identity"], self.identity)

    def test_historical_editor_requires_event_evidence(self):
        for event_id in (None, "", " "):
            with self.subTest(event_id=event_id):
                self.assert_quarantined(
                    self.resolve(replace(self.observation, event_id=event_id)), "MISSING_HISTORICAL_EDITOR_EVIDENCE",
                )

    def test_non_monday_or_incomplete_evidence_rejected(self):
        for change in ({"source": "ai"}, {"context": "assignee"}, {"monday_item_id": ""}, {"source_timestamp": ""}):
            with self.subTest(change=change):
                result = self.resolve(replace(self.observation, **change))
                self.assertIsNone(result["identity"])
                self.assertEqual(result["exception"]["code"], "INVALID_EDITOR_EVIDENCE")

    def test_invalid_mapping_records_fail_closed(self):
        for change in (
            {"editor_id": ""}, {"monday_person_id": "another-person"}, {"mapping_version": "other-version"},
            {"resolution": "display_name"}, {"contract_version": "2.0.0"}, {"extra": "field"},
        ):
            with self.subTest(change=change):
                mappings = {self.version: {self.person: [{**self.identity, **change}]}}
                self.assert_quarantined(self.resolve(mappings=mappings), "INVALID_IDENTITY_MAPPING")

    def test_identical_duplicates_are_idempotent(self):
        self.mappings[self.version][self.person].append(dict(self.identity))
        observation = replace(self.observation, monday_person_ids=(self.person, self.person))
        self.assertEqual(self.resolve(observation)["identity"], self.identity)

    def test_empty_and_malformed_candidates_are_quarantined(self):
        for candidates, code in (
            ([], "UNMAPPED_EDITOR"), ([{}], "INVALID_IDENTITY_MAPPING"),
            (["editor-42"], "INVALID_IDENTITY_MAPPING"),
            (self.identity, "INVALID_IDENTITY_MAPPING"),
        ):
            with self.subTest(candidates=candidates):
                self.assert_quarantined(self.resolve(mappings={self.version: {self.person: candidates}}), code)

    def test_same_display_name_does_not_merge_people(self):
        other = {**self.identity, "editor_id": "editor-other", "monday_person_id": "person-other"}
        self.mappings[self.version]["person-other"] = [other]
        self.assertEqual(self.resolve()["identity"], self.identity)
        self.assertEqual(self.resolve(replace(self.observation, monday_person_ids=("person-other",)))["identity"], other)

    def test_resolution_is_deterministic_and_does_not_mutate_inputs(self):
        original = copy.deepcopy(self.mappings)
        result = self.resolve()
        self.assertEqual(result, self.resolve())
        result["identity"]["display_name"] = "changed"
        result["evidence"]["mapping_candidates"][0]["editor_id"] = "changed"
        self.assertEqual(self.mappings, original)
        self.assertEqual(self.resolve()["identity"], self.identity)


if __name__ == "__main__":
    unittest.main()
