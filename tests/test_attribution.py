import json
import unittest

from atlas_commander.attribution import (
    CONTRACT_UNRESOLVED,
    REASON_AMBIGUOUS_MAPPING,
    REASON_MISSING_ACTOR,
    REASON_UNKNOWN_ACTOR,
    REASON_WASET_CO_SHARED_ACTOR,
    ActorMapping,
    TransitionActor,
    resolve_actor,
)
from atlas_commander.contracts import ROOT, schema_errors, semantic_codes

FIXTURES = ROOT / "fixtures"
EVENT_SCHEMA = "normalized-status-event.schema.json"


def load_json(relative):
    return json.loads((FIXTURES / relative).read_text())


class AttributionFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = load_json("attribution/unresolved-actors.json")
        self.mapping_config = load_json(self.fixture["mapping"])
        self.mapping = ActorMapping.from_config(self.mapping_config)

    def event_for(self, case):
        resolution = resolve_actor(TransitionActor.from_source(case["actor"]), self.mapping)
        return resolution, {**self.fixture["base_event"], "event_id": case["event_id"], **resolution.event_fields()}

    def test_fixture_cases_resolve_as_expected(self):
        for case in self.fixture["cases"]:
            with self.subTest(event_id=case["event_id"]):
                resolution, event = self.event_for(case)
                expected = case["expected"]
                self.assertEqual(resolution.status, expected["status"])
                self.assertEqual(resolution.reason, expected["reason"])
                self.assertEqual(resolution.actor_id, expected["actor_id"])
                self.assertEqual(event["actor_resolution"], expected["actor_resolution"])

    def test_every_fixture_event_satisfies_contract(self):
        for case in self.fixture["cases"]:
            with self.subTest(event_id=case["event_id"]):
                resolution, event = self.event_for(case)
                self.assertEqual(schema_errors(event, EVENT_SCHEMA), [])
                expected_codes = [] if resolution.resolved else ["UNRESOLVED_ACTOR"]
                self.assertEqual(semantic_codes(event, EVENT_SCHEMA), expected_codes)

    def test_unresolved_fixture_is_present_for_evidence(self):
        unresolved = [case for case in self.fixture["cases"] if case["expected"]["status"] == "unresolved"]
        reasons = {case["expected"]["reason"] for case in unresolved}
        self.assertEqual(reasons, {REASON_MISSING_ACTOR, REASON_UNKNOWN_ACTOR, REASON_AMBIGUOUS_MAPPING, REASON_WASET_CO_SHARED_ACTOR})


class WasetCoMappingTests(unittest.TestCase):
    """Acceptance: Waset Co mapping uses canonical IDs only."""

    def setUp(self):
        self.mapping = ActorMapping.from_config(load_json("attribution/actor-mapping-v1.json"))

    def test_waset_co_shared_actor_never_implies_editor_even_if_mapped(self):
        # person-waset-shared also has an explicit entry to editor-42; shared status wins.
        resolution = resolve_actor(TransitionActor("person-waset-shared", "person", "Waset Co"), self.mapping)
        self.assertFalse(resolution.resolved)
        self.assertEqual(resolution.reason, REASON_WASET_CO_SHARED_ACTOR)
        self.assertIsNone(resolution.actor_id)
        self.assertEqual(resolution.candidate_actor_ids, ("editor-42",))
        self.assertIsNone(resolution.event_fields()["actor_id"])

    def test_display_name_is_never_consulted(self):
        # Same canonical ID with differing names resolves identically.
        first = resolve_actor(TransitionActor("person-42", "person", "Fixture Editor"), self.mapping)
        second = resolve_actor(TransitionActor("person-42", "person", "Waset Co"), self.mapping)
        self.assertEqual(first.actor_id, "editor-42")
        self.assertEqual(second.actor_id, "editor-42")
        # A name matching a known editor does not rescue an unknown ID, and name case/spacing is irrelevant.
        for name in ("Fixture Editor", "fixture editor", " Fixture  Editor ", "editor-42", "person-42"):
            with self.subTest(name=name):
                resolution = resolve_actor(TransitionActor("person-999", "person", name), self.mapping)
                self.assertEqual(resolution.reason, REASON_UNKNOWN_ACTOR)
                self.assertIsNone(resolution.actor_id)

    def test_ids_are_matched_exactly_without_normalisation(self):
        for monday_id in ("PERSON-42", " person-42", "person-42 ", "person-042", "42"):
            with self.subTest(monday_id=monday_id):
                resolution = resolve_actor(TransitionActor(monday_id, "person"), self.mapping)
                self.assertEqual(resolution.reason, REASON_UNKNOWN_ACTOR)
                self.assertEqual(resolution.source_monday_id, monday_id)

    def test_person_and_team_id_namespaces_are_distinct(self):
        self.assertEqual(resolve_actor(TransitionActor("team-edit-7", "team"), self.mapping).actor_id, "editor-team-7")
        self.assertEqual(resolve_actor(TransitionActor("team-edit-7", "person"), self.mapping).reason, REASON_UNKNOWN_ACTOR)

    def test_ambiguous_mapping_stays_unresolved_with_candidates(self):
        resolution = resolve_actor(TransitionActor("person-77", "person"), self.mapping)
        self.assertEqual(resolution.reason, REASON_AMBIGUOUS_MAPPING)
        self.assertEqual(resolution.candidate_actor_ids, ("editor-77", "editor-78"))
        self.assertIsNone(resolution.actor_id)

    def test_missing_or_malformed_actor_is_unresolved(self):
        sources = [None, {}, {"display_name": "Fixture Editor"}, {"monday_id": "", "kind": "person"}, {"monday_id": 42, "kind": "person"},
                   {"monday_id": "person-42"}, {"monday_id": "person-42", "kind": "group"}]
        for source in sources:
            with self.subTest(source=source):
                resolution = resolve_actor(TransitionActor.from_source(source), self.mapping)
                self.assertEqual(resolution.reason, REASON_MISSING_ACTOR)
                self.assertEqual(resolution.event_fields()["actor_resolution"], CONTRACT_UNRESOLVED)

    def test_source_ids_and_mapping_version_are_preserved(self):
        resolution = resolve_actor(TransitionActor("team-waset-co", "team", "Waset Co"), self.mapping)
        self.assertEqual(
            resolution.evidence(),
            {
                "status": "unresolved",
                "reason": REASON_WASET_CO_SHARED_ACTOR,
                "source_monday_id": "team-waset-co",
                "source_kind": "team",
                "source_display_name": "Waset Co",
                "actor_id": None,
                "mapping_version": "actor-v1",
                "candidate_actor_ids": [],
            },
        )
        self.assertEqual(resolution.event_fields()["actor_monday_id"], "team-waset-co")
        self.assertEqual(resolution.event_fields()["mapping_version"], "actor-v1")


class ActorMappingConfigTests(unittest.TestCase):
    def config(self):
        return load_json("attribution/actor-mapping-v1.json")

    def test_mapping_is_order_independent(self):
        config = self.config()
        reversed_config = {**config, "entries": list(reversed(config["entries"])),
                           "waset_co_shared_actors": list(reversed(config["waset_co_shared_actors"]))}
        self.assertEqual(ActorMapping.from_config(config), ActorMapping.from_config(reversed_config))

    def test_duplicate_identical_entries_are_not_ambiguous(self):
        config = self.config()
        config["entries"].append({"monday_kind": "person", "monday_id": "person-42", "actor_id": "editor-42"})
        resolution = resolve_actor(TransitionActor("person-42", "person"), ActorMapping.from_config(config))
        self.assertEqual(resolution.actor_id, "editor-42")

    def test_mapping_version_is_required(self):
        for version in (None, "", 1):
            with self.subTest(version=version):
                config = self.config()
                config["mapping_version"] = version
                with self.assertRaises(ValueError):
                    ActorMapping.from_config(config)

    def test_malformed_entries_are_rejected(self):
        bad_entries = [
            {"monday_kind": "person", "monday_id": "person-1"},
            {"monday_kind": "person", "actor_id": "editor-1"},
            {"monday_kind": "user", "monday_id": "person-1", "actor_id": "editor-1"},
            {"monday_kind": "person", "monday_id": 1, "actor_id": "editor-1"},
            {"display_name": "Fixture Editor", "actor_id": "editor-1"},
        ]
        for entry in bad_entries:
            with self.subTest(entry=entry):
                config = self.config()
                config["entries"].append(entry)
                with self.assertRaises(ValueError):
                    ActorMapping.from_config(config)
        for field, value in (("entries", {"person-1": "editor-1"}), ("waset_co_shared_actors", ["team-waset-co"])):
            with self.subTest(field=field):
                config = self.config()
                config[field] = value
                with self.assertRaises(ValueError):
                    ActorMapping.from_config(config)

    def test_different_mapping_versions_are_recorded(self):
        config = self.config()
        config["mapping_version"] = "actor-v2"
        resolution = resolve_actor(TransitionActor("person-42", "person"), ActorMapping.from_config(config))
        self.assertEqual(resolution.event_fields()["mapping_version"], "actor-v2")


if __name__ == "__main__":
    unittest.main()
