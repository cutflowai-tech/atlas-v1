"""Unit tests for every Intelligence V2 detector (Task 60) and false-positive fixtures (Task 61).

Each detector is exercised on a synthetic fact base with: a clear positive case, a clear negative case, an insufficient
sample, missing data, contradicting evidence where the detector publishes it, a boundary at its threshold, deterministic
repeatability, and the ``approved_only`` path (``rule_not_approved`` unless every parameter is approved).
"""

import unittest

import investigation_factory as f

from atlas_commander.investigation import (
    concentration,
    editor,
    workload,
)
from atlas_commander.investigation.context import run_guarded
from atlas_commander.investigation.models import finding_errors

A, B, C, D = "editor-label-6", "editor-label-12", "editor-label-13", "editor-label-14"


def proj(item, editor_id=A, cohort="4", late=False, days=10, hours=10.0, **kw):
    """A completed project ``days`` before AS_OF; late when its ETA is one hour before Ready For Approval."""
    return f.fact(item, editor=editor_id, cohort=cohort, start=f.days_before(days), hours=hours, eta_hours=(hours - 1) if late else (hours + 1), **kw)


def run(detector_id, facts, mode="review", data=None, profiles=None):
    from atlas_commander.investigation.catalog import by_id
    result = run_guarded(by_id(detector_id), f.context(facts, mode, data, profiles))
    for item in result.findings:
        assert not finding_errors(item), finding_errors(item)
    return result


def reasons(result):
    return sorted({reason for row in result.not_evaluated for reason in row["reasons"]})


class ConcentrationTests(unittest.TestCase):
    def fixture(self, a_plus=10, a_plus_late=10, class_a=30, class_a_late=6):
        rows = [proj(f"p{i}", A if i % 2 else B, "8", late=i < a_plus_late, days=5 + i % 20) for i in range(a_plus)]
        rows += [proj(f"q{i}", [A, B, C][i % 3], "4", late=i < class_a_late, days=5 + i % 20) for i in range(class_a)]
        return f.base(rows)

    def test_positive_concentration_publishes_numerator_denominator_and_reference(self):
        result = run("concentration.negative", self.fixture())
        team = [x for x in result.findings if x.scope.kind == "video_type"]
        self.assertEqual(len(team), 1)
        params = team[0].statements[0].params
        self.assertEqual((params["group"], params["group_outcomes"], params["population_outcomes"], params["group_projects"], params["population_projects"]),
                         ("8", 10, 16, 10, 40))
        self.assertEqual((params["outcome_share"], params["population_share"]), (0.625, 0.25))
        self.assertEqual(team[0].sample_size, 10)
        self.assertIn("association_not_causation", team[0].limitations + ["association_not_causation"])

    def test_equal_rates_produce_no_finding(self):
        self.assertFalse([x for x in run("concentration.negative", self.fixture(10, 3, 30, 9)).findings if x.scope.kind == "video_type"])

    def test_tiny_group_is_not_reported(self):
        result = run("concentration.negative", self.fixture(a_plus=5, a_plus_late=5))
        self.assertFalse([x for x in result.findings if x.scope.kind == "video_type"])
        self.assertIn("insufficient_sample", reasons(result))

    def test_boundary_ratio_is_inclusive(self):
        data = f.config(concentration__minimum_share_ratio=2.5, concentration__minimum_share_difference=0.375)
        self.assertTrue([x for x in run("concentration.negative", self.fixture(), data=data).findings if x.scope.kind == "video_type"])
        data = f.config(concentration__minimum_share_ratio=2.51)
        self.assertFalse([x for x in run("concentration.negative", self.fixture(), data=data).findings if x.scope.kind == "video_type"])

    def test_editor_concentration_compares_editor_with_own_mix(self):
        rows = [proj(f"a{i}", A, "8", late=True, days=5 + i) for i in range(10)] + [proj(f"b{i}", A, "4", late=i < 1, days=5 + i) for i in range(20)]
        editor_findings = [x for x in run("concentration.negative", f.base(rows)).findings if x.scope.kind == "editor"]
        self.assertEqual(editor_findings[0].scope.editor_id, A)
        self.assertEqual(editor_findings[0].statements[0].code, "editor_outcome_concentrated")

    def test_positive_concentration_detector(self):
        rows = [proj(f"p{i}", A, "8", late=False, days=5 + i) for i in range(10)] + [proj(f"q{i}", B, "4", late=i > 2, days=5 + i) for i in range(30)]
        self.assertTrue([x for x in run("concentration.positive", f.base(rows)).findings if x.direction == "favourable"])

    def test_approved_only_is_rule_not_approved_and_deterministic(self):
        result = run("concentration.negative", self.fixture(), mode="approved_only", data=f.pre_d53())
        self.assertEqual((result.findings, reasons(result)), ([], ["rule_not_approved"]))
        first = [x.to_dict() for x in run("concentration.negative", self.fixture()).findings]
        self.assertEqual(first, [x.to_dict() for x in run("concentration.negative", self.fixture()).findings])

    def test_approving_the_parameters_allows_the_finding(self):
        data = f.config(unapprove=f.UNAPPROVED_D53, approve=concentration.PARAMS)
        result = run("concentration.negative", self.fixture(), mode="approved_only", data=data)
        self.assertTrue(result.findings)
        self.assertTrue(all(use.status == "approved" for use in result.findings[0].parameters))


def runway_fixture(short_late=18, short_total=20, adequate_late=4, adequate_total=16):
    """Three Editors with typical Class A execution of 10 h; runway below 10 h is short."""
    rows = []
    editors = [A, B, C]
    for i in range(short_total):
        late = i < short_late
        rows.append(f.fact(f"s{i}", editor=editors[i % 3], start=f.days_before(3 + i), hours=10 if late else 9, eta_hours=6 if late else 9.5))
    for i in range(adequate_total):
        late = i < adequate_late
        rows.append(f.fact(f"a{i}", editor=editors[i % 3], start=f.days_before(3 + i), hours=10 if not late else 13, eta_hours=12))
    return rows


class BottleneckTests(unittest.TestCase):
    def test_short_runway_association_with_contradicting_block(self):
        rows = runway_fixture()
        result = run("bottleneck.pre_editor_runway", f.base(rows))
        self.assertEqual(len(result.findings), 1, result.not_evaluated)
        found = result.findings[0]
        params = found.statements[0].params
        self.assertEqual((params["short_runway_late"], params["late"]), (18, 22))
        self.assertTrue(found.contradicting_evidence, "late projects with adequate runway are published as contradicting evidence")
        self.assertEqual({s.level for s in found.statements} >= {"fact", "association", "interpretation", "hypothesis"}, True)
        self.assertNotIn("editor", found.scope.kind)

    def test_no_difference_is_no_finding(self):
        self.assertIn("no_effect_at_approved_threshold", reasons(run("bottleneck.pre_editor_runway", f.base(runway_fixture(10, 20, 8, 16)))))

    def test_missing_eta_is_insufficient_not_guessed(self):
        rows = [f.fact(f"x{i}", editor=[A, B, C][i % 3], start=f.days_before(3 + i), eta_hours=None) for i in range(30)]
        self.assertIn("insufficient_sample", reasons(run("bottleneck.pre_editor_runway", f.base(rows))))

    def test_post_editor_delay_is_not_editor_time(self):
        rows = [f.fact(f"e{i}", editor=[A, B][i % 2], start=f.days_before(3 + i), hours=10, eta_hours=12, delivered_hours=5 if i < 6 else 1)
                for i in range(12)]
        result = run("bottleneck.post_editor", f.base(rows))
        self.assertEqual(result.findings[0].statements[0].params["delivered_after_eta"], 6)
        self.assertIn("delay_after_editor_interval_not_editor_execution", [s.code for s in result.findings[0].statements])
        self.assertIn("insufficient_outcome_events",
                      reasons(run("bottleneck.post_editor", f.base([f.fact(f"e{i}", start=f.days_before(3 + i), eta_hours=12, delivered_hours=5 if i < 2 else 1)
                                                                  for i in range(12)]))))

    def test_time_map_phases(self):
        rows = [f.fact(f"t{i}", start=f.days_before(3 + i), review_hours=1, delivered_hours=3) for i in range(12)]
        for row in rows:
            row.created_at = f.days_before(4 + int(row.monday_item_id[1:]))
        result = run("workflow.time_map", f.base(rows))
        phases = result.findings[0].statements[0].params["phases"]
        self.assertEqual((phases["editor_execution"]["median_hours"], phases["review_wait"]["median_hours"]), (10.0, 1.0))
        self.assertIn("insufficient_sample", reasons(run("workflow.time_map", f.base(rows[:5]))))


class ChangeTests(unittest.TestCase):
    def editor_rows(self, current_late=10, comparison_late=2, others_current_late=3, others_comparison_late=3):
        rows = [proj(f"c{i}", A, late=i < current_late, days=3 + i) for i in range(12)]
        rows += [proj(f"p{i}", A, late=i < comparison_late, days=33 + i) for i in range(12)]
        rows += [proj(f"oc{i}", B, late=i < others_current_late, days=3 + i) for i in range(12)]
        rows += [proj(f"op{i}", B, late=i < others_comparison_late, days=33 + i) for i in range(12)]
        return rows

    def test_editor_deterioration_specific_to_editor(self):
        result = run("change.editor", f.base(self.editor_rows()))
        late = [x for x in result.findings if x.key["measure"] == "late_rate" and x.key["against"] == "comparison" and x.scope.editor_id == A]
        self.assertEqual(len(late), 1)
        self.assertEqual((late[0].category, late[0].direction), ("needs_attention", "adverse"))
        self.assertFalse(late[0].contradicting_evidence)

    def test_change_that_mirrors_the_team_is_context_with_contradicting_evidence(self):
        result = run("change.editor", f.base(self.editor_rows(10, 2, 10, 2)))
        late = [x for x in result.findings if x.key["measure"] == "late_rate" and x.key["against"] == "comparison" and x.scope.editor_id == A]
        self.assertEqual(late[0].category, "hidden_context")
        self.assertTrue(late[0].contradicting_evidence)

    def test_small_recent_window_is_insufficient(self):
        rows = [proj(f"c{i}", A, late=True, days=3 + i) for i in range(5)] + [proj(f"p{i}", A, days=33 + i) for i in range(12)]
        self.assertIn("insufficient_recent_window", reasons(run("change.editor", f.base(rows))))

    def test_boundary_material_difference_is_inclusive(self):
        rows = self.editor_rows(current_late=8, comparison_late=2)       # 8/12 - 2/12 = 0.5 exactly
        data = f.config(evidence__material_rate_difference=0.5)
        found = [x for x in run("change.editor", f.base(rows), data=data).findings if x.key["measure"] == "late_rate" and x.key["against"] == "comparison"]
        self.assertTrue(found)
        data = f.config(evidence__material_rate_difference=0.51)
        found = [x for x in run("change.editor", f.base(rows), data=data).findings if x.key["measure"] == "late_rate" and x.key["against"] == "comparison"]
        self.assertFalse(found)

    def test_execution_change_stays_inside_one_video_type(self):
        # The Editor moved from Class B-heavy to Class A-heavy work: pooled medians would move, per-type medians do not.
        rows = [f.fact(f"h4{i}", editor=A, cohort="4", start=f.days_before(70 + i), hours=10) for i in range(6)]
        rows += [f.fact(f"h5{i}", editor=A, cohort="5", start=f.days_before(80 + i), hours=30) for i in range(12)]
        rows += [f.fact(f"c4{i}", editor=A, cohort="4", start=f.days_before(3 + i), hours=10) for i in range(12)]
        rows += [f.fact(f"c5{i}", editor=A, cohort="5", start=f.days_before(3 + i), hours=30) for i in range(6)]
        found = [x for x in run("change.editor", f.base(rows)).findings if x.key["measure"] == "median_execution"]
        self.assertEqual(found, [])

    def test_execution_deterioration_in_one_type(self):
        rows = [f.fact(f"h{i}", editor=A, start=f.days_before(70 + i), hours=10) for i in range(6)]
        rows += [f.fact(f"c{i}", editor=A, start=f.days_before(3 + i), hours=20) for i in range(6)]
        found = [x for x in run("change.editor", f.base(rows)).findings if x.key["measure"] == "median_execution"]
        self.assertEqual(found[0].statements[0].params["pct_change"], 100.0)

    def test_one_extreme_project_does_not_move_a_median(self):
        rows = [f.fact(f"h{i}", editor=[A, B][i % 2], start=f.days_before(70 + i), hours=10) for i in range(12)]
        rows += [f.fact(f"c{i}", editor=[A, B][i % 2], start=f.days_before(3 + i), hours=500 if i == 0 else 10) for i in range(12)]
        self.assertEqual(run("change.video_type", f.base(rows)).findings, [])

    def test_team_change_with_breadth(self):
        rows = [proj(f"c{i}", [A, B, C][i % 3], late=i < 14, days=3 + i) for i in range(15)]
        rows += [proj(f"p{i}", [A, B, C][i % 3], late=i < 2, days=33 + i % 25) for i in range(15)]
        found = [x for x in run("change.team", f.base(rows)).findings if x.key["against"] == "comparison" and x.key["measure"] == "late_rate"]
        params = found[0].statements[0].params
        self.assertEqual((params["editors_same_direction"], params["editors_with_both_periods"], params["shared_across_editors"]), (3, 3, True))
        self.assertEqual(found[0].statements[2].code, "change_is_group_wide")

    def test_team_change_with_editors_below_the_breadth_minimum_is_not_called_shared(self):
        rows = [proj(f"c{i}", [A, B, C][i % 3], late=i < 11, days=3 + i) for i in range(12)]      # 4 projects per Editor < 5
        rows += [proj(f"p{i}", [A, B, C][i % 3], late=i < 2, days=33 + i) for i in range(12)]
        found = [x for x in run("change.team", f.base(rows)).findings if x.key["against"] == "comparison" and x.key["measure"] == "late_rate"]
        params = found[0].statements[0].params
        self.assertEqual((params["editors_with_both_periods"], params["shared_across_editors"]), (0, False))
        self.assertEqual(found[0].statements[2].code, "change_breadth_not_established")

    def test_approved_only_without_d53_never_classifies_change(self):
        self.assertEqual(reasons(run("change.editor", f.base(self.editor_rows()), mode="approved_only", data=f.pre_d53())), ["rule_not_approved"])

    def test_approved_only_with_d53_classifies_change_on_approved_parameters(self):
        result = run("change.editor", f.base(self.editor_rows()), mode="approved_only")
        self.assertTrue(result.findings)
        self.assertTrue(all(use.status == "approved" and use.decision_id in ("D52", "D53") for x in result.findings for use in x.parameters))


def workload_rows(editor_id=A, high_hours=30.0, low_hours=10.0, blocks=12, cohort="4", late_high=False):
    """Blocks of three overlapping projects: concurrency 0, 1 and 2 at start; the Editor's own median is 1, so only the third is 'higher'."""
    rows = []
    for block in range(blocks):
        base_day = 100 - block * 7
        for position in range(3):
            high = position == 2
            hours = high_hours if high else low_hours
            start = f.stamp(f.at(f.days_before(base_day)) + f.timedelta(hours=position))
            rows.append(f.fact(f"{editor_id[-2:]}w{block}-{position}", editor=editor_id, cohort=cohort, start=start, hours=hours,
                               eta_hours=(hours - 1) if (late_high and high) else hours + 1))
    return rows


class WorkloadTests(unittest.TestCase):
    def test_team_association_is_worded_as_association(self):
        result = run("workload.association", f.base(workload_rows()))
        speed = [x for x in result.findings if x.key["code"] == "higher_workload_associated_with_execution_time"]
        self.assertEqual(len(speed), 1, result.not_evaluated)
        self.assertIn("association", [s.level for s in speed[0].statements])
        self.assertIn("association_not_causation", speed[0].limitations)

    def test_no_difference_no_finding(self):
        result = run("workload.association", f.base(workload_rows(high_hours=10.0)))
        self.assertFalse([x for x in result.findings if x.key["code"] == "higher_workload_associated_with_execution_time"])

    def test_insufficient_band(self):
        self.assertIn("insufficient_sample", reasons(run("workload.association", f.base(workload_rows(blocks=3)))))

    def test_overload_pattern_uses_editor_own_distribution(self):
        result = run("workload.overload_pattern", f.base(workload_rows(late_high=True)))
        self.assertTrue(result.findings)
        self.assertTrue(all(x.scope.editor_id == A and x.category == "hidden_context" for x in result.findings))

    def test_model_declares_no_capacity_rule(self):
        model = workload.workload_model(f.context(f.base(workload_rows())))
        self.assertEqual(model["capacity_classification"]["availability"], "rule_not_approved")
        self.assertEqual(model["editors"][0]["median"], 1)


class PatternTests(unittest.TestCase):
    def shared(self, elevated=(A, B, C)):
        rows = []
        for editor_id in (A, B, C):
            rows += [proj(f"{editor_id[-2:]}in{i}", editor_id, "8", late=i < (5 if editor_id in elevated else 1), days=5 + i) for i in range(6)]
            rows += [proj(f"{editor_id[-2:]}out{i}", editor_id, "4", late=i < 1, days=5 + i) for i in range(6)]
        return rows

    def test_shared_across_editors_is_a_system_pattern(self):
        found = [x for x in run("pattern.shared_across_editors", f.base(self.shared())).findings if x.key["measure"] == "late_delivery"]
        self.assertEqual((found[0].category, found[0].scope.cohort_key), ("system_pattern", "8"))
        self.assertIn("pattern_appears_process_wide", [s.code for s in found[0].statements])

    def test_confined_to_one_editor_is_editor_specific(self):
        found = [x for x in run("pattern.shared_across_editors", f.base(self.shared(elevated=(A,)))).findings if x.key["measure"] == "late_delivery"
                 and x.scope.cohort_key == "8"]
        self.assertEqual((found[0].category, found[0].scope.editor_id), ("editor_specific_pattern", A))

    def test_too_few_editors_is_insufficient(self):
        rows = [row for row in self.shared() if not row.monday_item_id.startswith(C[-2:])]
        self.assertIn("insufficient_qualifying_editors", reasons(run("pattern.shared_across_editors", f.base(rows))))

    def test_repeated_quality_across_editors(self):
        rows = [f.fact(f"l{i}", editor=[A, B, C][i % 3], cohort="6", start=f.days_before(5 + i), eta_hours=11,
                       labels=(f.label("Poor Communication", item=f"l{i}"),)) for i in range(6)]
        found = run("pattern.repeated_quality", f.base(rows)).findings
        self.assertEqual(found[0].statements[0].params["editors"], 3)
        two = [f.fact(f"m{i}", editor=[A, B][i % 2], cohort="6", start=f.days_before(5 + i), eta_hours=11,
                      labels=(f.label("Poor Communication", item=f"m{i}"),)) for i in range(8)]
        self.assertIn("insufficient_qualifying_editors", reasons(run("pattern.repeated_quality", f.base(two))))

    def test_repeated_delay_requires_both_halves_and_discloses_tests(self):
        rows = runway_fixture(18, 20, 4, 16)
        result = run("pattern.repeated_delay", f.base(rows))
        for item in result.findings:
            self.assertEqual(len(item.confidence["factors"][1]["slices"]), 2)
            self.assertIn("several_combinations_tested", item.limitations)
            self.assertIn("cells_tested", item.statements[0].params)

    def test_time_pattern_needs_repetition(self):
        rows = [proj(f"t{i}", [A, B][i % 2], late=i % 2 == 0, days=3 + i) for i in range(40)]
        self.assertEqual(run("pattern.time", f.base(rows)).findings, [])


class PersonSystemTests(unittest.TestCase):
    def peers(self):
        rows = [proj(f"p8{i}", [B, C][i % 2], "8", late=i < 9, days=5 + i) for i in range(10)]
        rows += [proj(f"p4{i}", [B, C][i % 2], "4", late=i < 1, days=5 + i) for i in range(10)]
        return rows

    def test_raw_gap_explained_by_mix_is_hidden_context(self):
        rows = self.peers() + [proj(f"a{i}", A, "8", late=i < 9, days=5 + i) for i in range(10)]
        found = run("person.mix_adjusted_deadline", f.base(rows)).findings
        mine = [x for x in found if x.scope.editor_id == A]
        self.assertEqual(mine[0].category, "hidden_context")
        self.assertIn("raw_gap_largely_reflects_work_mix", [s.code for s in mine[0].statements])
        self.assertTrue(mine[0].headline_contradiction)

    def test_difference_on_same_mix_is_editor_specific(self):
        rows = self.peers() + [proj(f"a{i}", A, "4", late=i < 9, days=5 + i) for i in range(10)]
        mine = [x for x in run("person.mix_adjusted_deadline", f.base(rows)).findings if x.scope.editor_id == A]
        self.assertEqual((mine[0].category, mine[0].direction), ("editor_specific_pattern", "adverse"))
        self.assertEqual(mine[0].statements[0].params["expected_late"], 1.0)

    def test_favourable_difference_points_to_recognition(self):
        rows = self.peers() + [proj(f"a{i}", A, "8", late=i < 2, days=5 + i) for i in range(10)]
        mine = [x for x in run("person.mix_adjusted_deadline", f.base(rows)).findings if x.scope.editor_id == A]
        self.assertEqual((mine[0].direction, mine[0].investigations[0].code), ("favourable", "recognise_evidence"))

    def test_below_approved_editor_minimum_is_insufficient(self):
        rows = self.peers() + [proj(f"a{i}", A, "4", late=True, days=5 + i) for i in range(9)]
        self.assertIn("insufficient_sample", reasons(run("person.mix_adjusted_deadline", f.base(rows))))


def profile(editor_id, speed_state="positive", deadline_state="negative", late=8, total=10, speed_rows=()):
    record = {"monday_item_id": f"{editor_id}-r", "cycle_id": "c", "event_ids": ["e"], "source_timestamps": ["2026-09-20T00:00:00Z"],
              "source_values": {"editor_id": editor_id}}
    window = {"window": "current", "start_date": "2026-08-30", "end_date_exclusive": "2026-09-29"}
    component = lambda state, facts: {"state": state, "reason": None, "facts": facts, "evidence": {"sample": {"n": 1}, "records": [record]}}
    return {"speed": {"component": component(speed_state, {"classifiable_projects": 10, "project_weights": {}}), "window": window, "cohorts": list(speed_rows)},
            "deadline": {"component": component(deadline_state, {"late": late, "deadline_classifiable_projects": total, "absolute_late_rate": late / total,
                                                                "comparator_late_rate": 0.5}), "window": window},
            "quality": {"component": {"state": "not_classifiable"}}, "overall": {"status": "Mixed", "status_label": "Mixed"}}


class ContradictionTests(unittest.TestCase):
    def test_metric_conflict_runs_in_approved_only(self):
        result = run("contradiction.metric_conflict", f.base([]), mode="approved_only", profiles={A: profile(A)})
        self.assertEqual(result.findings[0].statements[0].code, "conflict_fast_but_late")
        self.assertEqual(result.findings[0].to_dict()["parameter_status"], "approved")

    def test_no_conflict_no_finding(self):
        self.assertEqual(run("contradiction.metric_conflict", f.base([]), profiles={A: profile(A, "positive", "positive", 2)}).findings, [])

    def test_better_than_team_but_mostly_late_is_a_conflict(self):
        result = run("contradiction.metric_conflict", f.base([]), profiles={A: profile(A, "neutral", "positive", 7, 10)})
        self.assertEqual(result.findings[0].statements[0].code, "conflict_better_than_team_but_mostly_late")

    def bad_headline_rows(self):
        rows = []
        for i in range(15):                                     # typical Class A execution for others: 10 h
            rows.append(f.fact(f"b{i}", editor=[B, C][i % 2], start=f.days_before(5 + i), hours=10, eta_hours=11 if i % 2 else 9))
        for i in range(12):                                     # the Editor: normal 10 h execution, but most ETAs leave only 6 h
            rows.append(f.fact(f"a{i}", editor=A, start=f.days_before(5 + i), hours=10, eta_hours=6 if i < 10 else 11))
        return rows

    def test_bad_headline_surfaces_contradicting_evidence(self):
        result = run("contradiction.bad_headline", f.base(self.bad_headline_rows()))
        mine = [x for x in result.findings if x.scope.editor_id == A]
        self.assertEqual(len(mine), 1, result.not_evaluated)
        holding = mine[0].statements[0].params["holding_checks"]
        self.assertIn("late_despite_typical_execution", holding)
        self.assertIn("late_cluster_in_short_runway", holding)
        self.assertTrue(mine[0].contradicting_evidence)
        self.assertEqual(mine[0].direction, "mixed")
        self.assertIn("headline_may_overstate_execution_cause", [s.code for s in mine[0].statements])

    def test_no_adverse_headline_no_finding(self):
        rows = [row for row in self.bad_headline_rows() if row.editor_id != A]
        rows += [f.fact(f"a{i}", editor=A, start=f.days_before(5 + i), hours=10, eta_hours=11) for i in range(12)]
        self.assertFalse([x for x in run("contradiction.bad_headline", f.base(rows)).findings if x.scope.editor_id == A])

    def test_hidden_risk_behind_positive_speed(self):
        rows = [f.fact(f"h{i}", editor=A, start=f.days_before(3 + i), eta_hours=11,
                       labels=(f.label("Poor Communication", item=f"h{i}"),) if i < 6 else ()) for i in range(12)]
        result = run("contradiction.hidden_risk", f.base(rows), profiles={A: profile(A, "positive", "neutral", 2)})
        self.assertIn("negative_labels_behind_good_speed", result.findings[0].statements[0].params["holding_checks"])


class RiskTests(unittest.TestCase):
    def history(self):
        return [f.fact(f"h{i}", editor=[B, C, D][i % 3], start=f.days_before(40 + i), hours=10, eta_hours=6 if i < 12 else 12) for i in range(24)]

    def test_past_eta_is_a_fact_in_approved_only(self):
        item = f.open_work("o1", eta_in_hours=-3)
        result = run("risk.open_work", f.base(self.history(), [item]), mode="approved_only")
        found = [x for x in result.findings if x.key["signal"] == "past_eta"]
        self.assertEqual(found[0].statements[0].level, "fact")
        self.assertIn("risk_signal_not_prediction", [s.code for s in found[0].statements])

    def test_short_remaining_runway_signal(self):
        item = f.open_work("o2", started_hours_ago=2, eta_in_hours=3)          # 3 h left, typical 10 h - 2 h elapsed = 8 h still needed
        found = [x for x in run("risk.open_work", f.base(self.history(), [item])).findings if x.key["signal"] == "short_remaining_runway"]
        self.assertEqual(found[0].affected_projects, ["o2"])

    def test_no_open_work_no_signal(self):
        self.assertEqual(run("risk.open_work", f.base(self.history(), [])).findings, [])

    def test_similarity_only_when_similar_projects_did_worse_than_the_type(self):
        item = f.open_work("o3", started_hours_ago=1, eta_in_hours=5)          # 6 h runway < 10 h typical: short
        found = run("risk.historical_similarity", f.base(self.history(), [item])).findings
        self.assertEqual(found[0].statements[1].code, "resembles_historical_projects")
        adequate = f.open_work("o4", started_hours_ago=1, eta_in_hours=20)
        self.assertEqual(run("risk.historical_similarity", f.base(self.history(), [adequate])).findings, [])


class EditorTests(unittest.TestCase):
    def test_label_pattern_concentrated_in_deadline(self):
        rows = [f.fact(f"l{i}", editor=A, start=f.days_before(5 + i), eta_hours=11,
                       labels=(f.label("Late Delivery", scored=False, item=f"l{i}"),) if i < 6 else (f.label("Poor Communication", item=f"l{i}"),))
                for i in range(7)]
        found = [x for x in run("editor.label_pattern", f.base(rows)).findings if x.direction == "adverse"]
        self.assertEqual(found[0].statements[0].code, "negative_signals_concentrated_in_deadline")
        self.assertEqual((found[0].statements[0].params["top_count"], found[0].statements[0].params["occurrences"]), (6, 7))

    def test_label_pattern_insufficient(self):
        rows = [f.fact(f"l{i}", editor=A, start=f.days_before(5 + i), labels=(f.label("Late Delivery", item=f"l{i}"),)) for i in range(3)]
        self.assertIn("insufficient_outcome_events", reasons(run("editor.label_pattern", f.base(rows))))

    def test_speed_pattern_uses_approved_verdicts_only(self):
        row = {"verdict": "faster", "cohort_key": "4", "cohort_labels": ["Class A"], "editor_sample_size": 6, "editor_median_seconds": 36000,
               "team_sample_size": 12, "team_editor_count": 2, "team_median_seconds": 72000, "editor_vs_team_median_pct": -50.0,
               "evidence": {"records": [{"monday_item_id": "1", "cycle_id": "c", "event_ids": ["e"], "source_timestamps": ["t"], "source_values": {"editor_id": A}}]}}
        result = run("editor.speed_pattern", f.base([]), mode="approved_only", profiles={A: profile(A, speed_rows=[row])})
        self.assertEqual((result.findings[0].direction, result.findings[0].to_dict()["parameter_status"]), ("favourable", "approved"))
        self.assertEqual(run("editor.speed_pattern", f.base([]), profiles={A: profile(A, speed_rows=[{**row, "verdict": "not_classifiable"}])}).findings, [])

    def test_fairness_context_is_facts_only(self):
        rows = [proj(f"a{i}", A, "8", late=True, days=5 + i) for i in range(5)] + [proj(f"b{i}", B, "4", days=5 + i) for i in range(5)]
        context = editor.fairness_context(f.context(f.base(rows)), A)
        self.assertEqual(context["project_mix"][0]["share"], 1.0)
        self.assertIn("note", context)


class DataQualityTests(unittest.TestCase):
    def test_unclassifiable_deadline_names_the_exclusion(self):
        blocked = proj("x1", A)
        blocked.deadline_result, blocked.requested_eta_issue, blocked.exclusions = None, None, ("UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW",)
        found = [x for x in run("data.quality", f.base([blocked, proj("x2", A)])).findings if x.finding_type == "data.deadline_not_classifiable"]
        self.assertEqual(found[0].statements[0].params["reasons"], {"UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW": 1})

    def test_warnings_are_data_states(self):
        rows = [proj("u1", None, late=True), proj("a1", A, late=False, labels=(f.label("Late Delivery", scored=False, item="a1"),))]
        rows[0].exclusions = ("MISSING_EDITOR_EVENT",)
        result = run("data.quality", f.base(rows), mode="approved_only")
        types = {x.finding_type for x in result.findings}
        self.assertIn("data.unattributed_projects", types)
        self.assertIn("data.label_fact_disagreement", types)
        self.assertTrue(all(x.category == "data_warning" and x.direction == "neutral" for x in result.findings))


class FalsePositiveTests(unittest.TestCase):
    """Task 61: fixtures where a naive algorithm would produce a misleading finding."""

    def test_typical_execution_excludes_the_editor_being_evaluated(self):
        rows = [f.fact(f"a{i}", editor=A, start=f.days_before(5 + i), hours=50) for i in range(30)]
        rows += [f.fact(f"b{i}", editor=[B, C][i % 2], start=f.days_before(5 + i), hours=10) for i in range(12)]
        ctx = f.context(f.base(rows))
        self.assertEqual(ctx.baselines.typical("4", A).median_seconds, 36000)
        self.assertEqual(ctx.baselines.typical("4", None).median_seconds, 180000)

    def test_typical_execution_needs_approved_comparator_minimums(self):
        rows = [f.fact(f"b{i}", editor=B, start=f.days_before(5 + i), hours=10) for i in range(12)]
        self.assertFalse(f.context(f.base(rows)).baselines.typical("4", A).valid)          # one comparator Editor < D52 minimum of 2

    def test_video_types_are_never_pooled_for_speed(self):
        rows = [f.fact(f"a{i}", editor=A, cohort="5", start=f.days_before(5 + i), hours=30) for i in range(12)]
        rows += [f.fact(f"b{i}", editor=[B, C][i % 2], cohort="4", start=f.days_before(5 + i), hours=10) for i in range(12)]
        self.assertFalse(f.context(f.base(rows)).baselines.typical("5", A).valid)

    def test_revision_counts_never_enter_editor_findings(self):
        rows = [proj(f"r{i}", A, late=False, days=5 + i, client_revisions=5) for i in range(20)]
        rows += [proj(f"s{i}", B, late=False, days=5 + i) for i in range(20)]
        from atlas_commander.investigation.catalog import DETECTORS
        for detector in DETECTORS:
            for item in run_guarded(detector, f.context(f.base(rows))).findings:
                if item.scope.kind == "editor":
                    self.assertFalse(any("revision" in s.code for s in item.statements if s.level != "fact"), detector.detector_id)


if __name__ == "__main__":
    unittest.main()


class PrioritizationTests(unittest.TestCase):
    def test_historical_similarity_ranks_below_open_work_facts(self):
        from atlas_commander.investigation import prioritization
        history = [f.fact(f"h{i}", editor=[B, C, D][i % 3], start=f.days_before(40 + i), hours=10, eta_hours=6 if i < 12 else 12) for i in range(24)]
        facts = f.base(history, [f.open_work("o1", eta_in_hours=-3), f.open_work("o3", started_hours_ago=1, eta_in_hours=5)])
        findings = run("risk.open_work", facts).findings + run("risk.historical_similarity", facts).findings
        ranked = prioritization.rank(findings)
        self.assertEqual([x.finding_type for x in ranked][:1], ["risk.open_work"])
        self.assertEqual(prioritization.tier(ranked[-1]), 3)
        self.assertTrue(all(x.importance["method"].startswith("lexicographic") for x in ranked))
        self.assertEqual([x.importance["rank"] for x in ranked], list(range(1, len(ranked) + 1)))
