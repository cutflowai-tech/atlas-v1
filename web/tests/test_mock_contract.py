"""Mock API fixtures served to the Editor Profile UI must satisfy the frozen contracts."""

import json
import unittest
from pathlib import Path

from atlas_commander.contracts import semantic_codes, validate

MOCK_DIR = Path(__file__).resolve().parents[1] / "mock" / "editors"
NESTED = {
    "speed": "speed-metric.schema.json",
    "deadline": "deadline-metric.schema.json",
    "quality": "quality-metric.schema.json",
}


class MockProfileContractTests(unittest.TestCase):
    def fixtures(self):
        paths = sorted(MOCK_DIR.glob("*.json"))
        self.assertTrue(paths, "no mock editor fixtures found")
        return [(path, json.loads(path.read_text())) for path in paths]

    def test_profiles_match_editor_profile_schema(self):
        for path, profile in self.fixtures():
            with self.subTest(fixture=path.name):
                self.assertEqual(validate(profile, "editor-profile.schema.json"), [])
                self.assertEqual(profile["editor"]["editor_id"], path.stem)

    def test_nested_records_pass_semantic_invariants(self):
        for path, profile in self.fixtures():
            for cycle in profile["work_cycles"]:
                with self.subTest(fixture=path.name, cycle=cycle["cycle_id"]):
                    codes = semantic_codes(cycle, "work-cycle.schema.json")
                    # A missing Requested ETA is a legitimate "not evaluated" case for the UI.
                    self.assertEqual([code for code in codes if code != "MISSING_REQUESTED_ETA"], [])
            for kind, schema in NESTED.items():
                for metric in profile["metrics"][kind]:
                    with self.subTest(fixture=path.name, metric=kind):
                        self.assertEqual(validate(metric, schema), [])
                        self.assertEqual(metric["editor_id"], profile["editor"]["editor_id"])

    def test_missing_eta_cycles_have_no_deadline_metric(self):
        for path, profile in self.fixtures():
            missing = {c["monday_item_id"] for c in profile["work_cycles"] if c["requested_eta"] is None}
            with self.subTest(fixture=path.name):
                evaluated = {m["evidence"]["monday_item_id"] for m in profile["metrics"]["deadline"]}
                self.assertFalse(missing & evaluated)


if __name__ == "__main__":
    unittest.main()
