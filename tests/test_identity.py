import json
import unittest

from atlas_commander.contracts import ROOT, validate
from atlas_commander.identity import (
    AMBIGUOUS_EDITOR,
    AMBIGUOUS_MAPPING,
    INVALID_OBSERVATION,
    MISSING_EDITOR,
    UNEVIDENCED_EDITOR,
    UNMAPPED_EDITOR,
    IdentityMapping,
    resolve_editor,
    resolve_editors,
)

MAPPING = {
    "mapping_version": "identity-v1",
    "entries": [
        {"monday_person_id": "person-42", "editor_id": "editor-42", "display_name": "Fixture Editor"},
        {"monday_person_id": 7001, "editor_id": "editor-7001", "display_name": "Sam Cutter"},
        {"monday_person_id": "person-dup", "editor_id": "editor-a", "display_name": "Dup A"},
        {"monday_person_id": "person-dup", "editor_id": "editor-b", "display_name": "Dup B"},
    ],
}


def observation(**overrides):
    base = {
        "monday_board_id": "board-1",
        "monday_item_id": "item-1",
        "column_id": "editor",
        "editor_person_ids": ["person-42"],
        "source": "historical_column_value",
        "event_ids": ["event-100"],
    }
    base.update(overrides)
    return base


class IdentityResolutionTests(unittest.TestCase):
    def setUp(self):
        self.mapping = IdentityMapping.from_dict(MAPPING)

    def test_resolves_to_good_fixture_by_monday_person_id(self):
        expected = json.loads((ROOT / "fixtures/good/editor-identity.json").read_text())
        result = resolve_editor(observation(), self.mapping)
        self.assertTrue(result.resolved)
        self.assertIsNone(result.exception)
        self.assertEqual(result.identity, expected)
        self.assertEqual(validate(result.identity, "editor-identity.schema.json"), [])

    def test_integer_monday_person_id_is_canonicalized(self):
        result = resolve_editor(observation(editor_person_ids=[7001]), self.mapping)
        self.assertEqual(result.identity["editor_id"], "editor-7001")
        self.assertEqual(result.identity["monday_person_id"], "7001")

    def test_missing_editor_is_quarantined(self):
        for ids in ([], None):
            with self.subTest(ids=ids):
                result = resolve_editor(observation(editor_person_ids=ids), self.mapping)
                self.assertIsNone(result.identity)
                self.assertEqual(result.exception["code"], MISSING_EDITOR)

    def test_multiple_editors_are_ambiguous_and_quarantined(self):
        result = resolve_editor(observation(editor_person_ids=["person-42", 7001]), self.mapping)
        self.assertIsNone(result.identity)
        self.assertEqual(result.exception["code"], AMBIGUOUS_EDITOR)
        self.assertEqual(result.exception["monday_person_ids"], ["7001", "person-42"])

    def test_duplicate_same_person_id_is_not_ambiguous(self):
        result = resolve_editor(observation(editor_person_ids=["person-42", "person-42"]), self.mapping)
        self.assertEqual(result.identity["editor_id"], "editor-42")

    def test_conflicting_mapping_is_quarantined_not_picked(self):
        mapping = IdentityMapping.from_dict(MAPPING)
        self.assertEqual(mapping.conflicts["person-dup"], ("editor-a", "editor-b"))
        result = resolve_editor(observation(editor_person_ids=["person-dup"]), mapping)
        self.assertIsNone(result.identity)
        self.assertEqual(result.exception["code"], AMBIGUOUS_MAPPING)

    def test_unmapped_person_id_is_quarantined(self):
        result = resolve_editor(observation(editor_person_ids=["person-unknown"]), self.mapping)
        self.assertEqual(result.exception["code"], UNMAPPED_EDITOR)
        self.assertEqual(result.exception["mapping_version"], "identity-v1")

    def test_display_name_never_resolves_identity(self):
        obs = observation(editor_person_ids=[], display_name="Fixture Editor")
        self.assertEqual(resolve_editor(obs, self.mapping).exception["code"], MISSING_EDITOR)
        # A display name passed where a person ID belongs is not fuzzily matched.
        obs = observation(editor_person_ids=["Fixture Editor"])
        self.assertEqual(resolve_editor(obs, self.mapping).exception["code"], UNMAPPED_EDITOR)
        obs = observation(editor_person_ids=["fixture editor "])
        self.assertEqual(resolve_editor(obs, self.mapping).exception["code"], INVALID_OBSERVATION)

    def test_observed_display_name_does_not_override_mapping(self):
        result = resolve_editor(observation(display_name="Someone Else"), self.mapping)
        self.assertEqual(result.identity["display_name"], "Fixture Editor")

    def test_current_assignee_without_evidence_is_rejected(self):
        for event_ids in (None, [], [""]):
            with self.subTest(event_ids=event_ids):
                result = resolve_editor(observation(source="current_assignee", event_ids=event_ids), self.mapping)
                self.assertIsNone(result.identity)
                self.assertEqual(result.exception["code"], UNEVIDENCED_EDITOR)
                self.assertIn("current assignee", result.exception["reason"])

    def test_current_assignee_with_event_evidence_resolves(self):
        result = resolve_editor(observation(source="current_assignee", event_ids=["event-assign-1"]), self.mapping)
        self.assertEqual(result.identity["editor_id"], "editor-42")

    def test_historical_value_without_evidence_is_rejected(self):
        result = resolve_editor(observation(event_ids=[]), self.mapping)
        self.assertEqual(result.exception["code"], UNEVIDENCED_EDITOR)

    def test_invalid_observations_are_quarantined(self):
        cases = [
            observation(monday_item_id=""),
            observation(column_id=None),
            observation(source="ai_guess"),
            observation(editor_person_ids="person-42"),
            observation(editor_person_ids=[True]),
        ]
        for obs in cases:
            with self.subTest(obs=obs):
                self.assertEqual(resolve_editor(obs, self.mapping).exception["code"], INVALID_OBSERVATION)

    def test_mapping_requires_version_and_complete_entries(self):
        with self.assertRaises(ValueError):
            IdentityMapping.from_dict({"entries": []})
        with self.assertRaises(ValueError):
            IdentityMapping.from_dict({"mapping_version": "v1", "entries": [{"monday_person_id": "p", "editor_id": "e"}]})
        with self.assertRaises(TypeError):
            IdentityMapping.from_dict({"mapping_version": "v1"})

    def test_mapping_version_is_carried_into_identity(self):
        mapping = IdentityMapping.from_dict({**MAPPING, "mapping_version": "identity-v2"})
        self.assertEqual(resolve_editor(observation(), mapping).identity["mapping_version"], "identity-v2")

    def test_batch_is_deterministic_and_partitions_exceptions(self):
        observations = [
            observation(monday_item_id="item-3", editor_person_ids=["person-42", 7001]),
            observation(monday_item_id="item-2", editor_person_ids=[]),
            observation(monday_item_id="item-1", event_ids=["event-2", "event-1"]),
            observation(monday_item_id="item-4", source="current_assignee", event_ids=None),
        ]
        resolved, exceptions = resolve_editors(observations, self.mapping)
        again = resolve_editors(list(reversed(observations)), self.mapping)
        self.assertEqual((resolved, exceptions), again)
        self.assertEqual([r["monday_item_id"] for r in resolved], ["item-1"])
        self.assertEqual(resolved[0]["event_ids"], ["event-1", "event-2"])
        self.assertEqual(
            [(e["monday_item_id"], e["code"]) for e in exceptions],
            [("item-2", MISSING_EDITOR), ("item-3", AMBIGUOUS_EDITOR), ("item-4", UNEVIDENCED_EDITOR)],
        )


if __name__ == "__main__":
    unittest.main()
