"""Contract 1.3.0 (approved 2026-09-28) through the public pipeline path."""

import json
import unittest
from datetime import timedelta

import monday_factory as mf

from atlas_commander import cycles as c
from atlas_commander.identity import EDITOR_LABEL_NAME_MISMATCH
from atlas_commander.metrics import (
    COHORT_NOT_BENCHMARK_ELIGIBLE,
    COMPARABLE,
    FASTER,
    INSUFFICIENT_SAMPLE,
    INSUFFICIENT_SAMPLE_CONCLUSION,
    NO_OTHER_EDITORS,
    NOT_COMPARABLE_CONCLUSION,
    MetricPolicy,
    speed_benchmarks,
)
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION, load_contract, load_contract_version

NOW = "2026-09-28T00:00:00Z"
WILL, AHMED, MARIO = 6, 12, 4


def project(item_id, editor=WILL, video=(4,), hours=10, editor_names=None, extra=()):
    end = (c.parse_time("2026-09-01T10:00:00Z") + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [mf.editor(f"{item_id}-ed", item_id, "2026-09-01T09:00:00Z", [editor], editor_names),
            mf.video_type(f"{item_id}-vt", item_id, "2026-09-01T09:00:01Z", list(video)),
            mf.status(f"{item_id}-s1", item_id, "2026-09-01T10:00:00Z", "Create File", "In Progress"),
            mf.status(f"{item_id}-s2", item_id, end, "In Progress", "Ready For Approval"), *extra]


def many(editor, video, hours, first):
    return [log for offset, value in enumerate(hours) for log in project(str(first + offset), editor, video, value)]


class ContractV13Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.3.0")
        cls.v12 = load_contract_version("1.2.0")
        cls.policy = MetricPolicy.from_contract(cls.contract)

    def cycles(self, *logs, contract=None, **kwargs):
        return reconstruct_cycles(mf.payload(*logs), contract or self.contract, **kwargs).cycles

    def test_active_contract_is_13_and_12_is_unchanged(self):
        self.assertEqual((ACTIVE_CONTRACT_VERSION, load_contract()["contract_version"]), ("1.3.0", "1.3.0"))
        self.assertEqual(self.v12["video_type_cohorts"]["classification"]["confirmed_base_ids"], [])
        self.assertEqual(self.v12["editor_attribution"]["mapping_version"], "monday-editor-v1.0")

    def test_label_6_is_will_with_a_versioned_display_name(self):
        cycle = self.cycles(*project("1"))[0]
        self.assertEqual((cycle.editor_id, cycle.editor["display_name"], cycle.editor["mapping_version"]), ("editor-label-6", "Will", "monday-editor-v1.1"))
        old = self.cycles(*project("1"), contract=self.v12)[0]
        self.assertEqual((old.editor_id, old.editor["display_name"]), ("editor-label-6", "Synthetic Editor"))

    def test_reused_label_id_with_another_name_is_quarantined(self):
        cycle = self.cycles(*project("1", editor=AHMED, editor_names=["Anas"]))[0]
        self.assertIsNone(cycle.editor_id)
        self.assertIn(EDITOR_LABEL_NAME_MISMATCH, cycle.exclusions)
        self.assertEqual(self.cycles(*project("1", editor=AHMED, editor_names=["Anas"]), contract=self.v12)[0].editor_id, "editor-label-12")

    def test_unverified_editors_stay_quarantined(self):
        cycle = self.cycles(*project("1", editor=MARIO))[0]
        self.assertIsNone(cycle.editor_id)
        self.assertIn("UNMAPPED_EDITOR", cycle.exclusions)

    def test_current_editor_value_is_never_backfilled(self):
        logs = [log for log in project("1") if log["id"] != "1-ed"]
        items = {"items": [{"id": "1", "board": {"id": mf.BOARD}, "column_values": [{"id": mf.EDITOR, "type": "dropdown", "value": json.dumps({"ids": [6]}), "text": "Will"}]}]}
        cycle = self.cycles(*logs, items_payload=items)[0]
        self.assertIsNone(cycle.editor_id)
        self.assertIn(c.MISSING_EDITOR_EVENT, cycle.exclusions)

    def test_benchmark_eligibility_follows_the_approved_classification(self):
        cases = {(4,): True, (10, 4): True, (16, 4): True, (10, 16, 4): True, (5, 8): True, (16,): False, (10,): False, (22, 4): False, (1,): False}
        for video, expected in cases.items():
            with self.subTest(video=video):
                cycles = self.cycles(*project("1", video=video))
                cohort = speed_benchmarks("editor-label-6", cycles, self.policy, NOW)["cohorts"][0]
                self.assertEqual(cohort["benchmark_eligible"], expected)
                if not expected:
                    self.assertEqual(cohort["comparison_status"], COHORT_NOT_BENCHMARK_ELIGIBLE)

    def test_combinations_stay_distinct_cohorts(self):
        cycles = self.cycles(*many(WILL, (4,), (10, 11), 1), *many(WILL, (10, 4), (20,), 11), *many(WILL, (16, 4), (30,), 21))
        keys = {cohort["cohort_key"]: cohort["editor_sample_size"] for cohort in speed_benchmarks("editor-label-6", cycles, self.policy, NOW)["cohorts"]}
        self.assertEqual(keys, {"4": 2, "10:4": 1, "16:4": 1})

    def test_median_benchmark_with_sample_sizes_range_and_percentage(self):
        logs = [*many(WILL, (4,), (8, 9, 10, 11, 12), 1), *many(AHMED, (4,), (18, 19, 20, 21, 22), 11)]
        cohort = speed_benchmarks("editor-label-6", self.cycles(*logs), self.policy, NOW)["cohorts"][0]
        self.assertEqual((cohort["editor_sample_size"], cohort["team_sample_size"], cohort["team_includes_subject_editor"]), (5, 10, True))
        self.assertEqual((cohort["editor_median_seconds"], cohort["team_median_seconds"], cohort["benchmark_statistic"]), (10 * 3600, 15 * 3600, "median"))
        self.assertEqual((cohort["comparison_status"], cohort["conclusion"], cohort["editor_vs_team_median_pct"]), (COMPARABLE, FASTER, -33.3))
        self.assertEqual(cohort["team_typical_range_seconds"], {"p25": int(10.25 * 3600), "p75": int(19.75 * 3600)})
        self.assertEqual(cohort["editor_range_seconds"], {"min": 8 * 3600, "max": 12 * 3600})

    def test_no_conclusion_when_the_editor_is_the_whole_team(self):
        logs = many(WILL, (5,), (8, 9, 10, 11, 12), 1)
        cohort = speed_benchmarks("editor-label-6", self.cycles(*logs), self.policy, NOW)["cohorts"][0]
        self.assertEqual((cohort["comparison_status"], cohort["conclusion"]), (NO_OTHER_EDITORS, NOT_COMPARABLE_CONCLUSION))
        self.assertEqual((cohort["editor_sample_size"], cohort["team_editor_count"], cohort["team_median_seconds"]), (5, 1, 10 * 3600))
        v12 = MetricPolicy.from_contract(self.v12)
        self.assertFalse(v12.require_other_editor)

    def test_four_projects_show_data_but_no_conclusion(self):
        logs = [*many(WILL, (4,), (8, 9, 10, 11), 1), *many(AHMED, (4,), (18, 19, 20, 21, 22), 11)]
        cohort = speed_benchmarks("editor-label-6", self.cycles(*logs), self.policy, NOW)["cohorts"][0]
        self.assertEqual((cohort["comparison_status"], cohort["conclusion"], cohort["editor_sample_size"]), (INSUFFICIENT_SAMPLE, INSUFFICIENT_SAMPLE_CONCLUSION, 4))
        self.assertIsNotNone(cohort["team_median_seconds"])
        self.assertIsNotNone(cohort["editor_median_seconds"])


if __name__ == "__main__":
    unittest.main()
