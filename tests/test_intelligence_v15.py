"""Deterministic contract-1.5 interpretation tests (D23--D47).

Every approved rule below is an in-memory test fixture built from the real 1.5 contract; none of these numbers is a
threshold proposal, and the shipped contract keeps every threshold null / rule_not_approved.
"""

import copy
import unittest
from datetime import timedelta

import monday_factory as mf

from atlas_commander import cycles as c
from atlas_commander.intelligence import (
    FASTER,
    INSUFFICIENT_COMPARATOR_EDITORS,
    INSUFFICIENT_SAMPLE,
    NO_OTHER_EDITORS,
    SIMILAR,
    EvidenceScope,
    completed_day_windows,
    deadline_component,
    evaluation_cohort,
    overall_status,
    quality_component,
    quality_rates,
    recent_change,
    speed_benchmarks,
    speed_component,
)
from atlas_commander.interpretation_policy import (
    NEGATIVE,
    NEUTRAL,
    NOT_CLASSIFIABLE,
    NOT_ENOUGH_APPROVED_LOGIC,
    NOT_ENOUGH_EVIDENCE,
    POSITIVE,
    RULE_NOT_APPROVED,
    InterpretationPolicy,
    lookup_keys,
    policy_errors,
)
from atlas_commander.metrics import MetricPolicy, deadline_result
from atlas_commander.pipeline import reconstruct_cycles, reconstruct_quality
from atlas_commander.runtime import load_contract_version

NOW = "2026-09-29T12:00:00Z"
WILL, AHMED, MICHAEL = (6, "Will"), (12, "Ahmed"), (13, "Michael")
RATE_KEYS = ("positive_quality_rate", "negative_quality_rate", "late_rate", "median_speed_seconds")


def project(item_id, editor=WILL, hours=4, end="2026-09-28T00:30:00Z", video=(8,), eta=None, extra=()):
    finish = c.parse_time(end)
    start = finish - timedelta(hours=hours)
    stamp = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    logs = [
        mf.editor(f"{item_id}-ed", item_id, stamp(start - timedelta(hours=1)), [editor[0]], [editor[1]]),
        mf.video_type(f"{item_id}-vt", item_id, stamp(start - timedelta(minutes=59)), list(video)),
        mf.status(f"{item_id}-s1", item_id, stamp(start), "Create File", "In Progress"),
        mf.status(f"{item_id}-s2", item_id, stamp(finish), "In Progress", "Ready For Approval"),
        *extra,
    ]
    if eta is not None:
        logs.insert(0, mf.eta(f"{item_id}-eta", item_id, stamp(start - timedelta(hours=2)), eta[:10], eta[11:19]))
    return logs


def approved(contract, **sections):
    """A copy of the contract with test-only approved rules (each marked approved with its decision ID)."""
    contract = copy.deepcopy(contract)
    interpretation = contract["interpretation"]
    if "quality" in sections:
        interpretation["quality_component"].update({**sections["quality"], "minimum_project_sample_size_status": "approved",
                                                    "threshold_status": "approved", "decision_id": "D39"})
    if "speed" in sections:
        values = sections["speed"]
        for key in ("minimum_editor_sample_size", "minimum_comparator_sample_size", "minimum_comparator_editor_count"):
            contract["speed_benchmark"][key] = values[key]
            contract["speed_benchmark"][f"{key}_status"] = "approved"
        contract["speed_benchmark"]["component"].update({"faster_band": values["faster_band"], "slower_band": values["slower_band"],
                                                         "band_status": "approved", "decision_id": "D38"})
    if "deadline" in sections:
        contract["deadline"]["component"].update({**sections["deadline"], "threshold_status": "approved", "decision_id": "D45"})
    if "overall" in sections:
        interpretation["overall_status"].update({"lookup_table": sections["overall"], "threshold_status": "approved", "decision_id": "D37"})
    if "trend" in sections:
        values = sections["trend"]
        interpretation["trend"].update({"minimum_sample_size": values["minimum_sample_size"],
                                        "material_change_thresholds": values["material_change_thresholds"],
                                        "minimum_sample_size_status": "approved", "threshold_status": "approved", "decision_id": "D23"})
    return contract


def unapproved(contract):
    """A copy of the contract with every interpretation rule back at null / rule_not_approved (the pre-D52 state)."""
    contract = copy.deepcopy(contract)
    interpretation = contract["interpretation"]
    interpretation["quality_component"].update({"minimum_project_sample_size": None, "minimum_project_sample_size_status": "rule_not_approved",
                                                "threshold_status": "rule_not_approved"})
    for key in ("minimum_editor_sample_size", "minimum_comparator_sample_size", "minimum_comparator_editor_count"):
        contract["speed_benchmark"].update({key: None, f"{key}_status": "rule_not_approved"})
    contract["speed_benchmark"]["component"].update({"faster_band": None, "slower_band": None, "band_status": "rule_not_approved"})
    contract["deadline"]["component"].update({"minimum_editor_sample_size": None, "minimum_comparator_sample_size": None,
                                              "better_band": None, "worse_band": None, "threshold_status": "rule_not_approved"})
    interpretation["overall_status"].update({"lookup_table": None, "threshold_status": "rule_not_approved"})
    interpretation["trend"].update({"minimum_sample_size": None, "minimum_sample_size_status": "rule_not_approved", "threshold_status": "rule_not_approved"})
    return contract


def test_lookup():
    """A complete test-only lookup: count Negative / Positive components the way the round-4 shadow proposal describes."""
    table = {}
    for key in lookup_keys():
        states = key.split("|")
        negatives, positives = states.count(NEGATIVE), states.count(POSITIVE)
        classified = sum(state != NOT_CLASSIFIABLE for state in states)
        table[key] = (NOT_ENOUGH_EVIDENCE if classified < 2 else "Below Expectations" if negatives >= 2 else "Mixed" if negatives == 1
                      else "Strong" if positives >= 2 else "Good")
    return table


class IntelligenceV15Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.5.0")
        cls.policy = InterpretationPolicy.from_contract(cls.contract)
        cls.unapproved = InterpretationPolicy.from_contract(unapproved(cls.contract))
        cls.mapping = MetricPolicy.from_contract(cls.contract).video_types
        cls.scope = EvidenceScope.from_contract(cls.contract, NOW)

    def reconstruct(self, *logs, contract=None):
        return reconstruct_cycles(mf.payload(*logs), contract or self.contract, ingestion={"retrieved_at": NOW})

    # --- windows (D24, D42)
    def test_cairo_completed_day_assignment_uses_first_ready_for_approval(self):
        # 21:30Z is 00:30 on Sep 29 in Cairo and is today's incomplete day; 20:30Z is Sep 28.
        result = self.reconstruct(*project("101", end="2026-09-28T20:30:00Z"), *project("102", end="2026-09-28T21:30:00Z"),
                                  *project("103", end="2026-08-29T20:30:00Z"))
        cohort = evaluation_cohort(result.cycles, completed_day_windows(NOW, 30, 30), "cairo-completed-days-v1.0")
        self.assertEqual([cycle.monday_item_id for cycle in cohort["current"]], ["101"])
        self.assertEqual([cycle.monday_item_id for cycle in cohort["comparison"]], ["103"])
        self.assertEqual(cohort["coverage"]["outside_window_projects"], 1)
        self.assertEqual((cohort["windows"]["timezone"], cohort["coverage"]["scope"]), ("Africa/Cairo", "team"))

    # --- quality (D26--D30, D39): registry is the only source of what is scored
    def test_for_bonus_is_parsed_per_label_and_only_scored_quality_labels_count(self):
        logs = project("1", extra=[
            mf.dropdown("issue", "1", mf.ISSUES, "2026-09-28T02:00:00Z", [1, 2], ["Late Delivery", "Poor Communication"]),
            mf.dropdown("bonus", "1", "dropdown_mm3tyvvc", "2026-09-28T03:00:00Z", [1, 5, 3, 6],
                        ["1- Exceptional Quality", "On Time Delivery", "Saved Rush Project", "High Workload"]),
        ])
        result = self.reconstruct(*logs)
        quality = reconstruct_quality(result, self.contract, NOW)
        observed = {(m["performance_label"], m["evidence"]["source_values"]["label_class"], m["evidence"]["source_values"]["scoring_eligible"])
                    for m in quality.occurrences}
        self.assertEqual(observed, {("Late Delivery", "Negative", False), ("Poor Communication", "Negative", True),
                                    ("1- Exceptional Quality", "Positive", True), ("On Time Delivery", "Positive", False),
                                    ("Saved Rush Project", "Positive", True), ("High Workload", "Context", False)})
        facts = quality_rates("editor-label-6", quality.occurrences, result.cycles, self.scope, None, "quality-component-v1.0")
        self.assertEqual((facts["positive_count"], facts["negative_count"], facts["eligible_completed_projects"]), (2, 1, 1))
        self.assertEqual({(row["label"], row["reason"]) for row in facts["scoring_exclusions"]},
                         {("Late Delivery", "not_scored_quality"), ("On Time Delivery", "not_scored_quality"), ("High Workload", "context_label")})

    def test_changing_scored_quality_in_the_contract_changes_scoring_without_code(self):
        contract = copy.deepcopy(self.contract)
        praise = next(entry for entry in contract["quality_labels"]["registries"]["positive"] if entry["label"] == "Client Praise")
        praise["scored_quality"] = False
        late = next(entry for entry in contract["quality_labels"]["registries"]["negative"] if entry["label"] == "Late Delivery")
        late["scored_quality"] = True
        logs = project("1", extra=[
            mf.dropdown("issue", "1", mf.ISSUES, "2026-09-28T02:00:00Z", [1], ["Late Delivery"]),
            mf.dropdown("bonus", "1", "dropdown_mm3tyvvc", "2026-09-28T03:00:00Z", [4], ["Client Praise"]),
        ])
        for config, expected in ((self.contract, (1, 0)), (contract, (0, 1))):
            result = self.reconstruct(*logs, contract=config)
            facts = quality_rates("editor-label-6", reconstruct_quality(result, config, NOW).occurrences, result.cycles, self.scope, None, None)
            self.assertEqual((facts["positive_count"], facts["negative_count"]), expected)

    def test_context_labels_can_never_be_scored_and_every_label_needs_an_explicit_flag(self):
        from atlas_commander.quality import QualityPolicy
        contract = copy.deepcopy(self.contract)
        contract["quality_labels"]["registries"]["context"][0]["scored_quality"] = True
        with self.assertRaisesRegex(ValueError, "cannot be scored"):
            QualityPolicy.from_contract(contract)
        contract = copy.deepcopy(self.contract)
        del contract["quality_labels"]["registries"]["positive"][0]["scored_quality"]
        with self.assertRaisesRegex(ValueError, "explicitly"):
            QualityPolicy.from_contract(contract)

    def test_quality_component_classifies_only_under_an_approved_rule(self):
        facts = {"eligible_completed_projects": 4, "positive_count": 2, "negative_count": 0, "positive_rate": 0.5, "negative_rate": 0.0,
                 "evidence": {"records": []}}
        self.assertEqual(quality_component(facts, self.policy.quality)["reason"], RULE_NOT_APPROVED)  # D52: N/P still unapproved
        rule = InterpretationPolicy.from_contract(approved(self.contract, quality={
            "minimum_project_sample_size": 2, "negative_rate_threshold": 0.5, "positive_rate_threshold": 0.25})).quality
        self.assertEqual(quality_component(facts, rule)["state"], POSITIVE)
        self.assertEqual(quality_component({**facts, "eligible_completed_projects": 1}, rule)["reason"], INSUFFICIENT_SAMPLE)

    # --- speed (D32, D35, D36, D38)
    def speed_rule(self, **overrides):
        values = {"minimum_editor_sample_size": 1, "minimum_comparator_sample_size": 1, "minimum_comparator_editor_count": 1,
                  "faster_band": -25, "slower_band": 25, **overrides}
        return InterpretationPolicy.from_contract(approved(self.contract, speed=values)).speed

    def test_speed_is_first_pass_leave_one_out_and_requires_another_editor(self):
        rework = [mf.status("r1", "201", "2026-09-28T04:00:00Z", "Ready For Approval", "Revisions"),
                  mf.status("r2", "201", "2026-09-28T20:00:00Z", "Revisions", "Ready For Approval")]
        result = self.reconstruct(*project("201", WILL, 2, extra=rework), *project("202", AHMED, 10))
        row = speed_benchmarks("editor-label-6", result.cycles, self.mapping, self.speed_rule(), self.scope, None)["cohorts"][0]
        self.assertEqual((row["editor_median_seconds"], row["comparator_median_seconds"], row["verdict"]), (2 * 3600, 10 * 3600, FASTER))
        self.assertTrue(row["benchmark_excludes_subject_editor"])
        self.assertEqual({record["source_values"]["editor_id"] for record in row["evidence"]["records"]}, {"editor-label-6", "editor-label-12"})
        alone = self.reconstruct(*project("201", WILL, 2))
        row = speed_benchmarks("editor-label-6", alone.cycles, self.mapping, self.speed_rule(), self.scope, None)["cohorts"][0]
        self.assertEqual((row["verdict"], row["reason"]), (NOT_CLASSIFIABLE, NO_OTHER_EDITORS))

    def test_speed_enforces_subject_comparator_project_and_comparator_editor_minimums(self):
        result = self.reconstruct(*project("1", WILL, 2), *project("2", AHMED, 10), *project("3", AHMED, 10))
        cases = [({"minimum_editor_sample_size": 2}, INSUFFICIENT_SAMPLE),
                 ({"minimum_comparator_sample_size": 3}, INSUFFICIENT_SAMPLE),
                 ({"minimum_comparator_editor_count": 2}, INSUFFICIENT_COMPARATOR_EDITORS),
                 ({}, None)]
        for overrides, reason in cases:
            with self.subTest(overrides=overrides):
                row = speed_benchmarks("editor-label-6", result.cycles, self.mapping, self.speed_rule(**overrides), self.scope, None)["cohorts"][0]
                self.assertEqual(row["reason"], reason)
                self.assertEqual(row["comparator_editor_count"], 1)
        unapproved = speed_benchmarks("editor-label-6", result.cycles, self.mapping, self.unapproved.speed, self.scope, None)["cohorts"][0]
        self.assertEqual((unapproved["verdict"], unapproved["reason"]), (NOT_CLASSIFIABLE, RULE_NOT_APPROVED))

    def test_speed_bands_are_compared_unrounded_and_boundaries_are_similar(self):
        # 125.04 / 100 hours is +25.04%: displayed as 25.0 but still slower than a +25% band.
        result = self.reconstruct(*project("1", WILL, 125.04), *project("2", AHMED, 100))
        row = speed_benchmarks("editor-label-6", result.cycles, self.mapping, self.speed_rule(), self.scope, None)["cohorts"][0]
        self.assertEqual((row["editor_vs_comparator_pct"], row["verdict"]), (25.0, "slower"))
        result = self.reconstruct(*project("1", WILL, 125), *project("2", AHMED, 100))
        row = speed_benchmarks("editor-label-6", result.cycles, self.mapping, self.speed_rule(), self.scope, None)["cohorts"][0]
        self.assertEqual(row["verdict"], SIMILAR, "the band boundary itself is similar (inclusive)")

    def test_speed_component_is_a_project_weighted_majority(self):
        rule = self.speed_rule()
        rows = [{"cohort_key": key, "verdict": verdict, "reason": None, "editor_sample_size": n, "evidence": {"records": []}}
                for key, verdict, n in (("a", "faster", 10), ("b", "similar", 6), ("c", "slower", 5))]
        component = speed_component("e1", {"cohorts": rows, "excluded_editor_projects": []}, rule, self.scope, None)
        self.assertEqual(component["state"], NEUTRAL)  # 10/21 is not a majority (D38).

    # --- deadline (D45)
    def deadline_rows(self, *specs):
        rows = []
        for item, editor, late in specs:
            finish = "2026-09-28T00:30:00Z"
            eta = "2026-09-27T20:30:00Z" if late else "2026-09-28T04:30:00Z"
            result = self.reconstruct(*project(item, editor, 4, end=finish, eta=eta))
            policy = MetricPolicy.from_contract(self.contract)
            rows += [row for row in (deadline_result(cycle, policy, NOW) for cycle in result.cycles) if row is not None]
        return rows

    def test_deadline_component_is_relative_leave_one_out_and_keeps_absolute_facts(self):
        rows = self.deadline_rows(("1", WILL, False), ("2", AHMED, True))
        unapproved = deadline_component("editor-label-6", rows, self.unapproved.deadline, self.scope, None)
        self.assertEqual((unapproved["state"], unapproved["reason"]), (NOT_CLASSIFIABLE, RULE_NOT_APPROVED))
        self.assertEqual((unapproved["facts"]["absolute_late_rate"], unapproved["facts"]["comparator_late_rate"]), (0.0, 1.0))
        rule = InterpretationPolicy.from_contract(approved(self.contract, deadline={
            "minimum_editor_sample_size": 1, "minimum_comparator_sample_size": 1, "better_band": -0.15, "worse_band": 0.15})).deadline
        self.assertEqual(deadline_component("editor-label-6", rows, rule, self.scope, None)["state"], POSITIVE)
        alone = self.deadline_rows(("1", WILL, True))
        self.assertEqual(deadline_component("editor-label-6", alone, rule, self.scope, None)["reason"], NO_OTHER_EDITORS)

    # --- overall (D25, D37, D41, D47)
    def components(self, quality, speed, deadline):
        return {name: {"state": state, "reason": None if state != NOT_CLASSIFIABLE else reason, "evidence": {}}
                for name, (state, reason) in (("quality", quality), ("speed", speed), ("deadline", deadline))}

    def test_overall_is_a_lookup_and_never_classifies_without_approval(self):
        classified = self.components((POSITIVE, None), (NEUTRAL, None), (NOT_CLASSIFIABLE, INSUFFICIENT_SAMPLE))
        unapproved = overall_status(classified, self.unapproved, None, NOW)
        self.assertEqual((unapproved["status"], unapproved["status_label"], unapproved["reason"]), (None, NOT_ENOUGH_APPROVED_LOGIC, RULE_NOT_APPROVED))
        policy = InterpretationPolicy.from_contract(approved(self.contract, overall=test_lookup()))
        result = overall_status(classified, policy, None, NOW)
        self.assertEqual((result["status"], result["lookup_key"] if "lookup_key" in result else result["evidence"]["lookup_key"]),
                         ("Good", "positive|neutral|not_classifiable"))
        self.assertEqual(overall_status(self.components((NEGATIVE, None), (NEGATIVE, None), (POSITIVE, None)), policy, None, NOW)["status"],
                         "Below Expectations")

    def test_too_few_components_is_a_data_state_distinct_from_unapproved_logic(self):
        policy = InterpretationPolicy.from_contract(approved(self.contract, overall=test_lookup()))
        thin = self.components((POSITIVE, None), (NOT_CLASSIFIABLE, INSUFFICIENT_SAMPLE), (NOT_CLASSIFIABLE, NO_OTHER_EDITORS))
        result = overall_status(thin, policy, None, NOW)
        self.assertEqual((result["status"], result["status_label"], result["reason"]), (None, NOT_ENOUGH_EVIDENCE, "not_enough_classifiable_components"))
        unapproved = self.components((POSITIVE, None), (NOT_CLASSIFIABLE, RULE_NOT_APPROVED), (NOT_CLASSIFIABLE, RULE_NOT_APPROVED))
        self.assertEqual(overall_status(unapproved, self.unapproved, None, NOW)["status_label"], NOT_ENOUGH_APPROVED_LOGIC)
        # Once the lookup is approved (D52), fewer than two classifiable components is a data state whatever the reason;
        # the unapproved component rule stays visible in "Why this status".
        gap = overall_status(unapproved, policy, None, NOW)
        self.assertEqual(gap["status_label"], NOT_ENOUGH_EVIDENCE)
        self.assertEqual(gap["why"][1]["reason"], RULE_NOT_APPROVED)
        why = {row["component"]: row["reason"] for row in result["why"]}
        self.assertEqual(why, {"quality": None, "speed": INSUFFICIENT_SAMPLE, "deadline": NO_OTHER_EDITORS, "overall_lookup": None})

    def test_overall_ignores_revisions_current_work_and_context(self):
        components = self.components((POSITIVE, None), (NEUTRAL, None), (NEUTRAL, None))
        components.update({"revisions": {"state": NEGATIVE, "reason": None}, "current_work": {"state": NEGATIVE, "reason": None}})
        policy = InterpretationPolicy.from_contract(approved(self.contract, overall=test_lookup()))
        result = overall_status(components, policy, None, NOW)
        self.assertEqual(set(result["component_states"]), {"quality", "speed", "deadline"})
        self.assertEqual(result["status"], "Good")

    # --- recent change / trend (D23): direction per measurement, metric-specific materiality
    def trend_policy(self, **thresholds):
        values = {"minimum_sample_size": 1, "material_change_thresholds": {key: thresholds.get(key, 0.05) for key in RATE_KEYS}}
        return InterpretationPolicy.from_contract(approved(self.contract, trend=values))

    def side(self, value, sample=10):
        return {"value": value, "sample": sample, "evidence": {"records": []}}

    def test_worsening_lateness_and_negative_quality_are_declining(self):
        policy = self.trend_policy(median_speed_seconds=3600)
        cases = {("late_rate", 0.5, 0.2): "Declining", ("late_rate", 0.2, 0.5): "Improving",
                 ("negative_quality_rate", 0.4, 0.1): "Declining", ("negative_quality_rate", 0.1, 0.4): "Improving",
                 ("positive_quality_rate", 0.4, 0.1): "Improving", ("positive_quality_rate", 0.1, 0.4): "Declining",
                 ("median_speed_seconds", 20000, 10000): "Declining", ("median_speed_seconds", 10000, 20000): "Improving"}
        for (measurement, current, comparison), expected in cases.items():
            with self.subTest(measurement=measurement, current=current, comparison=comparison):
                self.assertEqual(recent_change(measurement, self.side(current), self.side(comparison), policy)["trend"], expected)

    def test_materiality_is_metric_specific(self):
        # A 1,000-second speed change is below its 3,600-second threshold; a 0.1 late-rate change is above its 0.05 threshold.
        policy = self.trend_policy(median_speed_seconds=3600, late_rate=0.05)
        self.assertEqual(recent_change("median_speed_seconds", self.side(11000), self.side(10000), policy)["trend"], "Stable")
        self.assertEqual(recent_change("late_rate", self.side(0.3), self.side(0.2), policy)["trend"], "Declining")

    def test_recent_change_is_a_fact_without_an_approved_trend_rule(self):
        change = recent_change("late_rate", self.side(0.2), self.side(0.4), self.unapproved)
        self.assertEqual((change["difference"], change["trend"], change["trend_reason"]), (-0.2, None, RULE_NOT_APPROVED))
        self.assertEqual(recent_change("late_rate", self.side(0.2, 3), self.side(0.4), self.trend_policy())["trend"], "Improving")
        small = InterpretationPolicy.from_contract(approved(self.contract, trend={
            "minimum_sample_size": 5, "material_change_thresholds": dict.fromkeys(RATE_KEYS, 0.05)}))
        self.assertEqual(recent_change("late_rate", self.side(0.2, 3), self.side(0.4), small)["trend_reason"], INSUFFICIENT_SAMPLE)

    # --- configuration errors: a half-approved rule never silently classifies or silently stays quiet (D25)
    def test_half_configured_or_mis_decided_rules_are_contract_errors(self):
        contract = approved(self.contract, quality={"minimum_project_sample_size": 10, "negative_rate_threshold": None, "positive_rate_threshold": 0.2})
        self.assertTrue(any("quality.negative_rate_threshold" in error for error in policy_errors(contract)))
        contract = approved(self.contract, overall={"positive|neutral|neutral": "Good"})
        self.assertTrue(any("every quality|speed|deadline" in error for error in policy_errors(contract)))
        contract = copy.deepcopy(self.contract)
        contract["interpretation"]["trend"]["directions"]["late_rate"] = "higher_is_better"
        self.assertTrue(policy_errors(contract))
        contract = copy.deepcopy(self.contract)
        contract["interpretation"]["quality_component"]["negative_rate_threshold"] = 0.3
        self.assertTrue(any("not approved" in error for error in policy_errors(contract)))
        contract = approved(self.contract, quality={"minimum_project_sample_size": 10, "negative_rate_threshold": 0.3, "positive_rate_threshold": 0.2})
        contract["interpretation"]["quality_component"]["decision_id"] = "D38"
        self.assertTrue(any("without its decision" in error for error in policy_errors(contract)))
        contract = copy.deepcopy(self.contract)
        contract["interpretation"]["overall_status"]["minimum_classifiable_components"] = 1
        self.assertTrue(any("D41" in error for error in policy_errors(contract)))
        self.assertEqual(policy_errors(self.contract), [])
        self.assertEqual(policy_errors(unapproved(self.contract)), [])

    def test_malformed_quality_registry_is_a_config_error_not_a_crash(self):
        from atlas_commander.runtime import contract_config_errors
        contract = copy.deepcopy(self.contract)
        contract["quality_labels"]["registries"]["positive"].append("oops")
        self.assertTrue(contract_config_errors(contract))

    def test_insufficient_data_with_approved_components_is_a_data_state_even_before_lookup_approval(self):
        rules = approved(unapproved(self.contract), quality={"minimum_project_sample_size": 1, "negative_rate_threshold": 0.5, "positive_rate_threshold": 0.5},
                         speed={"minimum_editor_sample_size": 1, "minimum_comparator_sample_size": 1, "minimum_comparator_editor_count": 1,
                                "faster_band": -25, "slower_band": 25},
                         deadline={"minimum_editor_sample_size": 1, "minimum_comparator_sample_size": 1, "better_band": -0.15, "worse_band": 0.15})
        thin = self.components((POSITIVE, None), (NOT_CLASSIFIABLE, NO_OTHER_EDITORS), (NOT_CLASSIFIABLE, INSUFFICIENT_SAMPLE))
        result = overall_status(thin, InterpretationPolicy.from_contract(rules), None, NOW)
        self.assertEqual(result["status_label"], NOT_ENOUGH_EVIDENCE)

    # --- D52: the approved production values
    def test_d52_approved_values_are_exactly_the_management_decision(self):
        state = lambda rule: (rule.approved, rule.state()["values"])
        self.assertEqual(state(self.policy.speed), (True, {"minimum_editor_sample_size": 5, "minimum_comparator_sample_size": 10,
                                                           "minimum_comparator_editor_count": 2, "faster_band": -25, "slower_band": 25}))
        self.assertEqual(state(self.policy.deadline), (True, {"minimum_editor_sample_size": 10, "minimum_comparator_sample_size": 60,
                                                              "better_band": -0.15, "worse_band": 0.15}))
        self.assertEqual(state(self.policy.quality), (False, {"minimum_project_sample_size": 10, "negative_rate_threshold": None,
                                                              "positive_rate_threshold": None}))
        self.assertEqual(state(self.policy.trend), (False, {"minimum_sample_size": 10, "material_change_thresholds": None}))
        self.assertEqual(self.contract["interpretation"]["trend"]["material_change_thresholds"], dict.fromkeys(RATE_KEYS))
        self.assertTrue(self.policy.overall.approved)
        self.assertEqual(self.policy.overall.values["lookup_table"], test_lookup(), "the configured table is the D52 counting rule")

    def test_d52_quality_unapproved_does_not_block_overall_when_speed_and_deadline_are_valid(self):
        quality_held = (NOT_CLASSIFIABLE, RULE_NOT_APPROVED)
        cases = {((POSITIVE, None), (POSITIVE, None)): "Strong", ((POSITIVE, None), (NEUTRAL, None)): "Good",
                 ((NEGATIVE, None), (POSITIVE, None)): "Mixed", ((NEGATIVE, None), (NEGATIVE, None)): "Below Expectations"}
        for (speed, deadline), expected in cases.items():
            with self.subTest(speed=speed, deadline=deadline):
                self.assertEqual(overall_status(self.components(quality_held, speed, deadline), self.policy, None, NOW)["status"], expected)
        thin = overall_status(self.components(quality_held, (NOT_CLASSIFIABLE, INSUFFICIENT_SAMPLE), (POSITIVE, None)), self.policy, None, NOW)
        self.assertEqual((thin["status"], thin["status_label"]), (None, NOT_ENOUGH_EVIDENCE))

    def test_d52_deadline_band_edges_are_exact(self):
        # 3 of 10 late (30%) against 27 of 60 late (45%): exactly -15 pp is inside the neutral band.
        rows = self.deadline_rows(*((str(n), WILL, n < 3) for n in range(10)), *((str(100 + n), AHMED, n < 27) for n in range(60)))
        component = deadline_component("editor-label-6", rows, self.policy.deadline, self.scope, None)
        self.assertEqual((component["state"], component["facts"]["late_rate_difference"]), (NEUTRAL, -0.15))
        rows = self.deadline_rows(*((str(n), WILL, n < 3) for n in range(10)), *((str(100 + n), AHMED, n < 28) for n in range(60)))
        self.assertEqual(deadline_component("editor-label-6", rows, self.policy.deadline, self.scope, None)["state"], POSITIVE)
        few = self.deadline_rows(*((str(n), WILL, False) for n in range(9)), *((str(100 + n), AHMED, True) for n in range(60)))
        self.assertEqual(deadline_component("editor-label-6", few, self.policy.deadline, self.scope, None)["reason"], INSUFFICIENT_SAMPLE)

    def test_d52_trend_stays_unclassified_while_recent_change_is_shown(self):
        change = recent_change("late_rate", self.side(0.2, 20), self.side(0.6, 20), self.policy)
        self.assertEqual((change["difference"], change["trend"], change["trend_reason"]), (-0.4, None, RULE_NOT_APPROVED))


if __name__ == "__main__":
    unittest.main()
