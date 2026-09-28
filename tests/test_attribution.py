import itertools
import json
import unittest

from atlas_commander.attribution import ActorMapping, ActorMappingEntry, resolve_transition_actor
from atlas_commander.contracts import ROOT, schema_errors, semantic_codes


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.mapping = ActorMapping("actor-v1", (
            ActorMappingEntry("person", "person-42", "editor-42"),
            ActorMappingEntry("team", "team-7", "editor-7"),
            ActorMappingEntry("person", "waset-id", shared=True),
        ))

    def test_canonical_person_matches_existing_fixture(self):
        event = json.loads((ROOT / "fixtures/good/status-in-progress.json").read_text())
        result = resolve_transition_actor("person", "person-42", self.mapping)
        self.assertEqual(result, {key: event[key] for key in result})
        self.assertEqual(schema_errors({**event, **result}, "normalized-status-event.schema.json"), [])

    def test_explicit_team_mapping_and_separate_namespaces(self):
        self.assertEqual(resolve_transition_actor("team", "team-7", self.mapping)["actor_id"], "editor-7")
        self.assertIsNone(resolve_transition_actor("person", "team-7", self.mapping)["actor_id"])
        collision = ActorMapping("v1", (ActorMappingEntry("person", "42", "editor-p"),
                                        ActorMappingEntry("team", "42", "editor-t")))
        self.assertEqual(resolve_transition_actor("team", "42", collision)["actor_id"], "editor-t")

    def test_missing_actor_fixture(self):
        event = json.loads((ROOT / "fixtures/bad/unresolved-waset-co.json").read_text())
        result = resolve_transition_actor(None, event["actor_monday_id"])
        self.assertEqual(result, {key: event[key] for key in result})
        self.assertEqual(schema_errors({**event, **result}, "normalized-status-event.schema.json"), [])
        self.assertTrue(semantic_codes({**event, **result}, "normalized-status-event.schema.json"))

    def test_unknown_missing_and_names_never_resolve(self):
        for kind, source_id, mapping in (
            ("person", "Waset Co", self.mapping), ("person", "Editor 42", self.mapping),
            ("person", "PERSON-42", self.mapping), ("person", " person-42 ", self.mapping),
            ("person", "unknown", self.mapping), (None, "person-42", self.mapping),
            ("person", None, self.mapping), ("person", "person-42", None),
        ):
            with self.subTest(kind=kind, source_id=source_id):
                result = resolve_transition_actor(kind, source_id, mapping)
                self.assertEqual(result["actor_resolution"], "unresolved_waset_co")
                self.assertIsNone(result["actor_id"])
                self.assertEqual(result["actor_monday_id"], source_id)

    def test_shared_actor_never_implies_editor_even_with_conflicting_mapping(self):
        for kind in ("person", "team"):
            entries = (ActorMappingEntry(kind, "waset-id", "editor-42", shared=True),
                       ActorMappingEntry(kind, "waset-id", "editor-42"))
            for order in itertools.permutations(entries):
                result = resolve_transition_actor(kind, "waset-id", ActorMapping("v1", order))
                self.assertIsNone(result["actor_id"])
                self.assertEqual(result["actor_monday_id"], "waset-id")

    def test_ambiguity_and_unassigned_entries_fail_closed_in_any_order(self):
        for target in ("editor-other", None):
            entries = (ActorMappingEntry("person", "42", "editor-42"), ActorMappingEntry("person", "42", target))
            for order in itertools.permutations(entries):
                self.assertIsNone(resolve_transition_actor("person", "42", ActorMapping("v1", order))["actor_id"])

    def test_duplicate_targets_version_and_repeatability(self):
        entry = ActorMappingEntry("person", "42", "editor-42")
        mapping = ActorMapping("v2", (entry, entry))
        result = resolve_transition_actor("person", "42", mapping)
        self.assertEqual(result["actor_id"], "editor-42")
        self.assertEqual(result["mapping_version"], "v2")
        self.assertEqual(result, resolve_transition_actor("person", "42", mapping))
        self.assertEqual(resolve_transition_actor("person", "unknown", mapping)["mapping_version"], "v2")

    def test_mapping_snapshots_input(self):
        entries = [ActorMappingEntry("person", "42", "editor-42")]
        mapping = ActorMapping("v1", entries)
        entries.clear()
        self.assertEqual(resolve_transition_actor("person", "42", mapping)["actor_id"], "editor-42")

    def test_invalid_configuration_and_source_ids_are_rejected(self):
        for version in (None, "", " "):
            with self.assertRaises(ValueError):
                ActorMapping(version, ())
        for source_id in (42, "", False):
            with self.assertRaises(ValueError):
                resolve_transition_actor("person", source_id, self.mapping)
        for args in (("name", "42"), ("person", ""), ("person", "42", "")):
            with self.assertRaises(ValueError):
                ActorMappingEntry(*args)


if __name__ == "__main__":
    unittest.main()
