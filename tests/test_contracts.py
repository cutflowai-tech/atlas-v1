import json
import unittest

from atlas_commander.contracts import ROOT, schema_errors, semantic_codes, validate


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = ROOT / "fixtures"
        self.manifest = json.loads((self.fixtures / "manifest.json").read_text())

    def test_every_good_fixture_is_valid(self):
        for relative, schema in self.manifest["good"].items():
            with self.subTest(fixture=relative):
                instance = json.loads((self.fixtures / relative).read_text())
                self.assertEqual(validate(instance, schema), [])

    def test_every_bad_fixture_has_expected_failure(self):
        for relative, expectation in self.manifest["bad"].items():
            with self.subTest(fixture=relative):
                instance = json.loads((self.fixtures / relative).read_text())
                self.assertIn(expectation["code"], validate(instance, expectation["schema"]))

    def test_speed_cohort_cannot_cross_video_type(self):
        instance = json.loads((self.fixtures / "good/speed-metric.json").read_text())
        instance["cohort_video_type"] = "long-form"
        self.assertEqual(semantic_codes(instance, "speed-metric.schema.json"), ["CROSS_VIDEO_TYPE_COHORT"])

    def test_deadline_is_ready_for_approval_vs_requested_eta(self):
        instance = json.loads((self.fixtures / "good/deadline-metric.json").read_text())
        instance["result"] = "late"
        self.assertEqual(semantic_codes(instance, "deadline-metric.schema.json"), ["DEADLINE_RESULT_MISMATCH"])

    def test_revision_context_does_not_feed_quality_value(self):
        schema = json.loads((ROOT / "contracts/quality-metric.schema.json").read_text())
        self.assertNotIn("score", schema["properties"])
        self.assertIn("Display-only", schema["properties"]["revision_context"]["description"])

    def test_evidence_source_is_monday(self):
        instance = json.loads((self.fixtures / "good/quality-metric.json").read_text())
        instance["evidence"]["source"] = "ai"
        self.assertTrue(schema_errors(instance, "quality-metric.schema.json"))


if __name__ == "__main__":
    unittest.main()
