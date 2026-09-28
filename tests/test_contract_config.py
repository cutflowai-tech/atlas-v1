import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MondayContractConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config/monday-contract-v1.0.json").read_text())

    def test_status_mapping_and_boundaries_are_explicit(self):
        mapping = self.config["status_mapping"]
        self.assertEqual(mapping["Create File"], "pre-cycle")
        self.assertEqual(mapping["In Progress"], "active-production")
        self.assertEqual(mapping["Internal Revisions"], "internal-rework")
        self.assertEqual(mapping["Revisions"], "external-client-rework")
        self.assertEqual(mapping["TOPAZ"], "delivery-preparation")
        self.assertEqual(mapping["Ready To Send"], "delivery-preparation")
        self.assertEqual(mapping["Sent"], "delivered")
        self.assertEqual(mapping["Ready For Approval"], "approval-terminal")
        boundaries = self.config["cycle_boundaries"]
        self.assertEqual(boundaries["start_label"], "In Progress")
        self.assertEqual(boundaries["end_label"], "Ready For Approval")
        self.assertEqual(boundaries["start_policy"], "first-transition-only")
        self.assertEqual(boundaries["end_policy"], "first-qualifying-transition-only")

    def test_quarantine_and_attribution_policies_are_non_inferential(self):
        self.assertFalse(self.config["quarantine_policy"]["silent_inference"])
        attribution = self.config["editor_attribution"]
        self.assertEqual(attribution["authoritative_field"], "Editor Name")
        self.assertEqual(attribution["activity_log_user_id"], "audit-metadata-only")
        self.assertIn("99154021", attribution["shared_accounts_never_infer_editor"])
        self.assertEqual(attribution["unresolved_policy"], "quarantine-from-per-editor-metrics")

    def test_video_type_cohorts_are_exact_and_isolated(self):
        cohorts = self.config["video_type_cohorts"]
        self.assertEqual(cohorts["multi_select_policy"], "exact-normalized-full-set")
        self.assertEqual(cohorts["cohort_key"], "sorted-canonical-video-type-ids")
        self.assertEqual(cohorts["comparison_policy"], "same-resolved-cohort-only-no-global-fallback")
        self.assertEqual(cohorts["unresolved_policy"], "quarantine-from-cohort-comparisons")

    def test_open_cycles_and_anomalies_are_retained(self):
        boundaries = self.config["cycle_boundaries"]
        self.assertEqual(boundaries["repeated_in_progress_create_file"], "same-cycle")
        self.assertEqual(boundaries["post_revision_transitions"], "same-cycle")
        self.assertEqual(boundaries["incomplete_cycles"], "retain-open-right-censored-exclude-from-completed-duration-aggregates")
        self.assertEqual(boundaries["duplicate_or_reversed_transitions"], "ignore-for-timing-and-flag-anomaly")


if __name__ == "__main__":
    unittest.main()
