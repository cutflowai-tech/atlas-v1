import copy
import json
import unittest
from itertools import permutations

from atlas_commander.attribution import ActorMapping, ActorMappingRule, resolve_transition_actor
from atlas_commander.contracts import ROOT, schema_errors, validate


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.event = json.loads((ROOT / "fixtures/good/status-in-progress.json").read_text())
        self.rule = ActorMappingRule("person", "person-42", "editor-42")
        self.mapping = ActorMapping("actor-v1", (self.rule,))

    def resolve(self, source_id, kind="person", mapping=None):
        event = dict(self.event, actor_monday_id=source_id)
        return resolve_transition_actor(event, actor_kind=kind, mapping=mapping or self.mapping)

    def assert_unresolved(self, result, source_id):
        self.assertEqual(result["actor_resolution"], "unresolved_waset_co")
        self.assertIsNone(result["actor_id"])
        self.assertEqual(result["actor_monday_id"], source_id)
        self.assertEqual(schema_errors(result, "normalized-status-event.schema.json"), [])
        self.assertEqual(validate(result, "normalized-status-event.schema.json"), ["UNRESOLVED_ACTOR"])

    def test_canonical_person_matches_fixture_and_contract(self):
        self.assertEqual(self.resolve("person-42"), self.event)
        self.assertEqual(validate(self.resolve("person-42"), "normalized-status-event.schema.json"), [])

    def test_team_requires_explicit_unique_mapping(self):
        mapping = ActorMapping("teams-v2", (ActorMappingRule("team", "team-9", "editor-42"),))
        result = self.resolve("team-9", "team", mapping)
        self.assertEqual(result["actor_id"], "editor-42")
        self.assertEqual(result["mapping_version"], "teams-v2")
        self.assertEqual(validate(result, "normalized-status-event.schema.json"), [])

    def test_shared_actor_name_and_source_id_cannot_imply_editor(self):
        for source_id in ("shared-7", "Waset Co", "waset co", "person-unknown", None):
            with self.subTest(source_id=source_id):
                self.assert_unresolved(self.resolve(source_id), source_id)

    def test_shared_actor_uses_only_exact_explicit_id_rule(self):
        mapping = ActorMapping("shared-v1", (ActorMappingRule("person", "shared-7", "editor-42"),))
        self.assertEqual(self.resolve("shared-7", mapping=mapping)["actor_id"], "editor-42")
        self.assert_unresolved(self.resolve("Waset Co", mapping=mapping), "Waset Co")

    def test_unknown_missing_and_wrong_kind_do_not_cross_namespaces(self):
        for kind in (None, "team", "unknown"):
            with self.subTest(kind=kind):
                self.assert_unresolved(self.resolve("person-42", kind), "person-42")

    def test_no_mapping_clears_existing_attribution(self):
        result = resolve_transition_actor(self.event, actor_kind="person")
        self.assert_unresolved(result, "person-42")
        self.assertIsNone(result["mapping_version"])

    def test_missing_source_id_does_not_reuse_existing_editor(self):
        event = dict(self.event)
        del event["actor_monday_id"]
        self.assert_unresolved(resolve_transition_actor(event, actor_kind="person", mapping=self.mapping), None)

    def test_unresolved_fixture_is_reproduced(self):
        fixture = json.loads((ROOT / "fixtures/bad/unresolved-waset-co.json").read_text())
        self.assertEqual(resolve_transition_actor(fixture, actor_kind="person"), fixture)
        self.assert_unresolved(fixture, None)

    def test_conflicting_rules_are_unresolved_in_every_order(self):
        rules = (self.rule, ActorMappingRule("person", "person-42", "editor-99"), self.rule)
        for ordering in permutations(rules):
            result = self.resolve("person-42", mapping=ActorMapping("conflict-v1", ordering))
            self.assert_unresolved(result, "person-42")
            self.assertEqual(result["mapping_version"], "conflict-v1")

    def test_duplicate_same_target_is_deterministic(self):
        mapping = ActorMapping("actor-v1", (self.rule, self.rule))
        self.assertEqual(self.resolve("person-42", mapping=mapping), self.event)

    def test_ids_are_not_trimmed_case_folded_or_coerced(self):
        for source_id in ("PERSON-42", " person-42", "person-42 "):
            self.assert_unresolved(self.resolve(source_id), source_id)
        result = self.resolve(42)
        self.assertEqual(result["actor_monday_id"], 42)
        self.assertIsNone(result["actor_id"])

    def test_event_evidence_preserved_and_input_not_mutated(self):
        original = copy.deepcopy(self.event)
        result = resolve_transition_actor(self.event, actor_kind="person", mapping=self.mapping)
        self.assertIsNot(result, self.event)
        self.assertEqual(self.event, original)
        for key in original.keys() - {"actor_id", "actor_resolution", "mapping_version"}:
            self.assertEqual(result[key], original[key])
        self.assertEqual(resolve_transition_actor(result, actor_kind="person", mapping=self.mapping), result)

    def test_versioned_snapshot_is_independent_of_mutable_rule_input(self):
        rules = [self.rule]
        mapping = ActorMapping("actor-v1", rules)
        rules.clear()
        self.assertEqual(self.resolve("person-42", mapping=mapping), self.event)

    def test_invalid_configuration_rejected(self):
        for value in (None, "", " ", 42, " v1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ActorMapping(value, ())
            with self.subTest(value=value), self.assertRaises(ValueError):
                ActorMappingRule("person", value, "editor-42")
            with self.subTest(value=value), self.assertRaises(ValueError):
                ActorMappingRule("person", "person-42", value)
        with self.assertRaises(ValueError):
            ActorMappingRule("name", "Waset Co", "editor-42")
        with self.assertRaises(ValueError):
            ActorMapping("v1", ({},))


if __name__ == "__main__":
    unittest.main()
