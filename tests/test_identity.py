import json
import unittest
from dataclasses import replace

from atlas_commander.contracts import ROOT, validate
from atlas_commander.identity import (
    AMBIGUOUS_EDITOR,
    MISSING_EDITOR,
    MISSING_EVIDENCE,
    UNMAPPED_EDITOR,
    EditorObservation,
    IdentityMapping,
    MappingError,
    resolve_all,
    resolve_editor,
)

MAPPING = {
    "mapping_version": "identity-v1",
    "entries": [
        {"monday_person_id": "person-42", "editor_id": "editor-42", "display_name": "Fixture Editor"},
        {"monday_person_id": "person-7", "editor_id": "editor-7", "display_name": "Other Editor"},
        {"monday_person_id": "person-dup", "editor_id": "editor-a", "display_name": "Dup A"},
        {"monday_person_id": "person-dup", "editor_id": "editor-b", "display_name": "Dup B"},
    ],
}


def observation(person_ids, **overrides):
    base = EditorObservation(
        monday_board_id="board-1",
        monday_item_id="item-1",
        column_id="editor",
        person_ids=tuple(person_ids),
        source="editor_column_event",
        event_id="event-100",
        observed_at="2026-09-01T09:00:00Z",
    )
    return replace(base, **overrides)


class IdentityResolutionTests(unittest.TestCase):
    def setUp(self):
        self.mapping = IdentityMapping.from_dict(MAPPING)

    def assertQuarantined(self, result, code):
        self.assertIsNone(result.identity)
        self.assertIsNotNone(result.exception)
        self.assertEqual(result.exception.code, code)
        self.assertEqual(result.exception.mapping_version, "identity-v1")

    def test_resolves_to_good_fixture(self):
        expected = json.loads((ROOT / "fixtures/good/editor-identity.json").read_text())
        result = resolve_editor(observation(["person-42"]), self.mapping)
        self.assertTrue(result.resolved)
        self.assertIsNone(result.exception)
        self.assertEqual(result.identity, expected)
        self.assertEqual(validate(result.identity, "editor-identity.schema.json"), [])

    def test_numeric_monday_person_id_is_canonicalised(self):
        mapping = IdentityMapping.from_dict({"mapping_version": "v2", "entries": [{"monday_person_id": "4242", "editor_id": "e", "display_name": "E"}]})
        self.assertEqual(resolve_editor(observation([4242]), mapping).identity["editor_id"], "e")

    def test_missing_editor_quarantined(self):
        for person_ids in ([], [""]):
            with self.subTest(person_ids=person_ids):
                self.assertQuarantined(resolve_editor(observation(person_ids), self.mapping), MISSING_EDITOR)

    def test_multiple_people_in_editor_column_quarantined(self):
        result = resolve_editor(observation(["person-42", "person-7"]), self.mapping)
        self.assertQuarantined(result, AMBIGUOUS_EDITOR)
        self.assertEqual(result.exception.person_ids, ("person-42", "person-7"))

    def test_repeated_same_person_is_not_ambiguous(self):
        self.assertTrue(resolve_editor(observation(["person-42", "person-42"]), self.mapping).resolved)

    def test_conflicting_mapping_quarantined(self):
        result = resolve_editor(observation(["person-dup"]), self.mapping)
        self.assertQuarantined(result, AMBIGUOUS_EDITOR)
        self.assertEqual(result.exception.candidate_editor_ids, ("editor-a", "editor-b"))

    def test_unmapped_person_quarantined(self):
        self.assertQuarantined(resolve_editor(observation(["person-999"]), self.mapping), UNMAPPED_EDITOR)

    def test_display_name_is_never_used_for_resolution(self):
        for value in ("Fixture Editor", "fixture editor", "editor-42"):
            with self.subTest(value=value):
                self.assertQuarantined(resolve_editor(observation([value]), self.mapping), UNMAPPED_EDITOR)

    def test_current_assignee_without_evidence_quarantined(self):
        obs = observation(["person-42"], source="current_assignee", event_id=None, observed_at=None)
        result = resolve_editor(obs, self.mapping)
        self.assertQuarantined(result, MISSING_EVIDENCE)
        self.assertIn("current assignee", result.exception.reason)

    def test_current_assignee_is_not_a_historical_source_even_with_event(self):
        self.assertQuarantined(resolve_editor(observation(["person-42"], source="current_assignee"), self.mapping), MISSING_EVIDENCE)

    def test_historical_observation_requires_event_and_timestamp(self):
        for overrides in ({"event_id": None}, {"observed_at": None}, {"source": "unknown"}):
            with self.subTest(overrides=overrides):
                self.assertQuarantined(resolve_editor(observation(["person-42"], **overrides), self.mapping), MISSING_EVIDENCE)

    def test_identity_carries_mapping_version(self):
        v2 = IdentityMapping.from_dict({**MAPPING, "mapping_version": "identity-v2"})
        self.assertEqual(resolve_editor(observation(["person-42"]), v2).identity["mapping_version"], "identity-v2")

    def test_resolve_all_splits_identities_and_exceptions_deterministically(self):
        observations = [
            observation(["person-42"]),
            observation([], monday_item_id="item-2"),
            observation(["person-dup"], monday_item_id="item-3"),
        ]
        first = resolve_all(observations, self.mapping)
        self.assertEqual(first, resolve_all(observations, self.mapping))
        identities, exceptions = first
        self.assertEqual([identity["editor_id"] for identity in identities], ["editor-42"])
        self.assertEqual([(item["monday_item_id"], item["code"]) for item in exceptions], [("item-2", MISSING_EDITOR), ("item-3", AMBIGUOUS_EDITOR)])
        self.assertTrue(all(item["mapping_version"] == "identity-v1" for item in exceptions))


class IdentityMappingTests(unittest.TestCase):
    def test_mapping_requires_version(self):
        for data in ({"entries": []}, {"mapping_version": "", "entries": []}, None):
            with self.subTest(data=data), self.assertRaises(MappingError):
                IdentityMapping.from_dict(data)

    def test_mapping_entries_require_all_fields(self):
        with self.assertRaises(MappingError):
            IdentityMapping.from_dict({"mapping_version": "v1", "entries": [{"monday_person_id": "p", "editor_id": "e"}]})

    def test_identical_duplicate_entries_are_not_ambiguous(self):
        entry = {"monday_person_id": "p", "editor_id": "e", "display_name": "E"}
        mapping = IdentityMapping.from_dict({"mapping_version": "v1", "entries": [entry, dict(entry)]})
        self.assertTrue(resolve_editor(observation(["p"]), mapping).resolved)


if __name__ == "__main__":
    unittest.main()
