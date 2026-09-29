"""Deterministic contract-1.5 metric framework tests (D23--D45, D47)."""

import copy
import unittest
from datetime import timedelta

import monday_factory as mf

from atlas_commander import cycles as c
from atlas_commander.intelligence import (
    FASTER,
    NEUTRAL,
    NOT_CLASSIFIABLE,
    NOT_ENOUGH_EVIDENCE,
    POSITIVE,
    RULE_NOT_APPROVED,
    IntelligencePolicy,
    data_coverage,
    deadline_component,
    evaluation_cohort,
    overall_status,
    quality_component,
    quality_rates,
    recent_change,
    revision_context,
    speed_benchmarks_v15,
    speed_component,
)
from atlas_commander.metrics import MetricPolicy
from atlas_commander.pipeline import reconstruct_cycles, reconstruct_quality
from atlas_commander.runtime import load_contract_version

NOW = "2026-09-29T12:00:00Z"
AHMED, MICHAEL = 12, 13


def project(item_id, editor=AHMED, hours=4, end="2026-09-28T00:30:00Z", video=(8,), extra=()):
    finish = c.parse_time(end)
    start = finish - timedelta(hours=hours)
    return [
        mf.editor(f"{item_id}-ed", item_id, (start - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), [editor]),
        mf.video_type(f"{item_id}-vt", item_id, (start - timedelta(minutes=59)).strftime("%Y-%m-%dT%H:%M:%SZ"), list(video)),
        mf.status(f"{item_id}-s1", item_id, start.strftime("%Y-%m-%dT%H:%M:%SZ"), "Create File", "In Progress"),
        mf.status(f"{item_id}-s2", item_id, finish.strftime("%Y-%m-%dT%H:%M:%SZ"), "In Progress", "Ready For Approval"),
        *extra,
    ]


def label(log_id, item_id, column_id, moment, ids, names):
    return mf.dropdown(log_id, item_id, column_id, moment, ids, names)


class IntelligenceV15Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = copy.deepcopy(load_contract_version("1.4.0"))
        cls.contract["contract_version"] = "1.5.0"
        cls.contract["quality_labels"]["for_bonus"].update({
            "mapping_version": "monday-for-bonus-v1.0",
            "id_to_label": {"1": "1- Exceptional Quality", "2": "Client Praise", "3": "On Time Delivery",
                            "4": "Saved Rush Project", "5": "High Workload", "6": "Additional Revisions"},
            "class_by_id": {"1": "Positive", "2": "Positive", "3": "Positive", "4": "Positive", "5": "Context", "6": "Context"},
        })
        cls.mapping = MetricPolicy.from_contract(cls.contract).video_types

    def reconstruct(self, *logs):
        return reconstruct_cycles(mf.payload(*logs), self.contract, ingestion={"retrieved_at": NOW})

    def test_for_bonus_is_parsed_per_label_and_scoring_excludes_deadline_and_context_labels(self):
        logs = project("1", extra=[
            label("issue", "1", mf.ISSUES, "2026-09-28T02:00:00Z", [1, 2], ["Late Delivery", "Poor Communication"]),
            label("bonus", "1", "dropdown_mm3tyvvc", "2026-09-28T03:00:00Z", [1, 3, 4, 5],
                  ["1- Exceptional Quality", "On Time Delivery", "Saved Rush Project", "High Workload"]),
        ])
        result = self.reconstruct(*logs)
        quality = reconstruct_quality(result, self.contract, NOW)
        observed = {(metric["performance_label"], metric["evidence"]["source_values"]["label_class"])
                    for metric in quality.occurrences}
        self.assertEqual(observed, {("Late Delivery", "Negative"), ("Poor Communication", "Negative"),
                                    ("1- Exceptional Quality", "Positive"), ("On Time Delivery", "Positive"),
                                    ("Saved Rush Project", "Positive"), ("High Workload", "Context")})
        facts = quality_rates("editor-label-12", quality.occurrences, result.cycles)
        self.assertEqual((facts["positive_count"], facts["negative_count"], facts["positive_rate"], facts["negative_rate"]), (2, 1, 2.0, 1.0))
        self.assertEqual({entry["label"] for entry in facts["scoring_exclusions"]}, {"Late Delivery", "On Time Delivery", "High Workload"})
        self.assertTrue(facts["evidence"]["occurrence_event_ids"])

    def test_cairo_completed_day_assignment_uses_first_ready_for_approval(self):
        # 21:30Z is 00:30 on Sep 29 in Cairo and is today's incomplete day; 20:30Z is Sep 28.
        result = self.reconstruct(*project("101", end="2026-09-28T20:30:00Z"),
                                  *project("102", end="2026-09-28T21:30:00Z"),
                                  *project("103", end="2026-08-29T20:30:00Z"))
        cohort = evaluation_cohort(result.cycles, NOW)
        self.assertEqual([cycle.monday_item_id for cycle in cohort["current"]], ["101"])
        self.assertEqual([cycle.monday_item_id for cycle in cohort["comparison"]], ["103"])
        self.assertEqual(cohort["coverage"]["outside_window_projects"], 1)
        self.assertEqual(cohort["windows"]["timezone"], "Africa/Cairo")

    def test_speed_is_first_pass_leave_one_out_and_requires_other_editor(self):
        rework = [mf.status("r1", "201", "2026-09-28T04:00:00Z", "Ready For Approval", "Revisions"),
                  mf.status("r2", "201", "2026-09-28T20:00:00Z", "Revisions", "Ready For Approval")]
        result = self.reconstruct(*project("201", AHMED, 2, extra=rework), *project("202", MICHAEL, 10))
        approved = {"approved": True, "decision_id": "D38", "rule_version": "speed-component-v1.5",
                    "minimum_editor_sample": 1, "minimum_comparator_sample": 1, "similar_band_pct": 10}
        row = speed_benchmarks_v15("editor-label-12", result.cycles, self.mapping, approved, NOW)["cohorts"][0]
        self.assertEqual((row["editor_median_seconds"], row["comparator_median_seconds"], row["verdict"]), (2 * 3600, 10 * 3600, FASTER))
        self.assertTrue(row["benchmark_excludes_subject_editor"])
        alone = self.reconstruct(*project("201", AHMED, 2))
        row = speed_benchmarks_v15("editor-label-12", alone.cycles, self.mapping, approved, NOW)["cohorts"][0]
        self.assertEqual((row["verdict"], row["reason"]), (NOT_CLASSIFIABLE, "no_other_editors_in_cohort"))

    def test_unapproved_rules_keep_facts_but_classify_nothing(self):
        facts = {"eligible_completed_projects": 20, "negative_rate": 0.0, "positive_rate": 1.0, "evidence": {"cycle_ids": ["c1"]}}
        quality = quality_component(facts, {"negative_rate_at_least": 0.2, "positive_rate_at_least": 0.5, "minimum_project_sample": 5})
        self.assertEqual((quality["state"], quality["reason"], quality["facts"]["positive_rate"]), (NOT_CLASSIFIABLE, RULE_NOT_APPROVED, 1.0))
        change = recent_change(0.2, 0.4, "late_rate")
        self.assertEqual((change["difference"], change["trend"], change["trend_reason"]), (-0.2, None, RULE_NOT_APPROVED))
        overall = overall_status({"quality": {"state": POSITIVE, "evidence": {}}, "speed": {"state": NEUTRAL, "evidence": {}},
                                  "deadline": {"state": NOT_CLASSIFIABLE, "evidence": {}}}, None)
        self.assertEqual((overall["status"], overall["reason"]), (NOT_ENOUGH_EVIDENCE, RULE_NOT_APPROVED))
        policy = IntelligencePolicy.from_contract({"editor_intelligence": {"evaluation_window": {"days": 30, "timezone": "Africa/Cairo"},
                                                                            "components": {"quality": {"rule_version": "q-v1"}}}})
        self.assertEqual((policy.window_days, policy.quality["rule_version"]), (30, "q-v1"))

    def test_project_weighted_speed_and_relative_deadline_components(self):
        speed_rule = {"approved": True, "decision_id": "D38", "rule_version": "speed-component-v1.5"}
        cohorts = [{"verdict": FASTER, "editor_sample_size": 10, "evidence": {"editor_cycle_ids": ["a"]}},
                   {"verdict": "Similar", "editor_sample_size": 6, "evidence": {"editor_cycle_ids": ["b"]}},
                   {"verdict": "Slower", "editor_sample_size": 5, "evidence": {"editor_cycle_ids": ["c"]}}]
        speed = speed_component(cohorts, speed_rule)
        self.assertEqual(speed["state"], NEUTRAL)  # 10/21 is not a majority.
        deadline_rule = {"approved": True, "decision_id": "D45", "rule_version": "deadline-component-v1.5",
                         "minimum_editor_sample": 1, "minimum_comparator_sample": 1, "similar_band": 0.05}
        deadline = deadline_component("e1", [{"editor_id": "e1", "cycle_id": "a", "result": "early"},
                                                    {"editor_id": "e2", "cycle_id": "b", "result": "late"}], deadline_rule)
        self.assertEqual((deadline["state"], deadline["facts"]["absolute_late_rate"], deadline["facts"]["comparator_late_rate"]), (POSITIVE, 0.0, 1.0))

    def test_overall_lookup_needs_two_components_and_revision_context_never_scores(self):
        lookup = {"approved": True, "decision_id": "D37", "rule_version": "overall-v1.5",
                  "lookup": {"Positive|Neutral|Not classifiable": "Good"}}
        components = {"quality": {"state": POSITIVE, "evidence": {}}, "speed": {"state": NEUTRAL, "evidence": {}},
                      "deadline": {"state": NOT_CLASSIFIABLE, "evidence": {}}}
        self.assertEqual(overall_status(components, lookup)["status"], "Good")
        components["speed"] = {"state": NOT_CLASSIFIABLE, "evidence": {}}
        self.assertEqual(overall_status(components, lookup)["reason"], "not_enough_classifiable_components")
        revisions = [mf.status("cr", "1", "2026-09-28T04:00:00Z", "Ready For Approval", "Revisions"),
                     mf.status("ir", "1", "2026-09-28T05:00:00Z", "Revisions", "Internal Revisions")]
        result = self.reconstruct(*project("1", extra=revisions))
        context = revision_context("editor-label-12", result.cycles)
        self.assertFalse(context["affects_scoring"])
        self.assertEqual((context["client_revision"]["events"], context["internal_revision"]["events"]), (1, 1))
        self.assertNotIn("revisions", overall_status(components, lookup)["component_states"])

    def test_coverage_retains_data_quality_exclusions(self):
        good = self.reconstruct(*project("1"))
        bad = copy.deepcopy(good.cycles[0])
        bad.monday_item_id = "bad"
        bad.cycle_id = "cycle:bad"
        bad.exclusions = ["UNMAPPED_VIDEO_TYPE", "MISSING_REQUESTED_ETA"]
        coverage = data_coverage([good.cycles[0], bad], quarantined=[{"reason": "UNMAPPED_QUALITY_LABEL"}])
        self.assertEqual(coverage["exclusions_by_reason"], {"UNMAPPED_VIDEO_TYPE": 1, "MISSING_REQUESTED_ETA": 1})
        self.assertEqual(coverage["excluded_projects"][0]["monday_item_id"], "bad")
        self.assertEqual(coverage["quarantined_quality_labels"][0]["reason"], "UNMAPPED_QUALITY_LABEL")


if __name__ == "__main__":
    unittest.main()
