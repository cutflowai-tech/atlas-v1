"""Boundary tests for every rule approved by D53 (docs/DECISIONS.md, 2026-09-30), at the shipped approved values.

Each rule is tested just below, exactly at and (where meaningful) above its threshold, through the real detector that applies
it, in ``approved_only`` mode (the publishable mode). Fixtures are synthetic; no real names or IDs.
"""

import unittest
from types import SimpleNamespace

import investigation_factory as f

from atlas_commander.investigation import common as cm
from atlas_commander.investigation import narrative, prioritization
from atlas_commander.investigation.catalog import by_id
from atlas_commander.investigation.context import run_guarded
from atlas_commander.investigation.engine import publishable_finding
from atlas_commander.investigation.models import finding_errors
from atlas_commander.investigation.policy import IntelligencePolicy
from atlas_commander.investigation.workload import editor_high_workload

EDITORS = ["editor-label-6", "editor-label-12", "editor-label-13", "editor-label-14", "editor-label-15", "editor-label-16"]
A, B, C = EDITORS[:3]


def run(detector_id, facts, data=None):
    result = run_guarded(by_id(detector_id), f.context(facts, "approved_only", data))
    for finding in result.findings:
        assert not finding_errors(finding), finding_errors(finding)
        assert all(use.status == "approved" for use in finding.parameters), finding.finding_type
    return result


def reasons(result, **scope):
    return sorted({reason for row in result.not_evaluated for reason in row["reasons"]
                   if all(row["scope"].get(key) == value for key, value in scope.items())})


def proj(item, editor_id=A, cohort="4", late=False, days=10, hours=10.0):
    return f.fact(item, editor=editor_id, cohort=cohort, start=f.days_before(days), hours=hours, eta_hours=(hours - 1) if late else (hours + 1))


# --- D53.2 / D53.3 / D53.5: concentration ----------------------------------------------------------------------------------------

def concentration_rows(group, group_late, other, other_late):
    """``group`` Class A+ projects (``group_late`` late) beside ``other`` Class A projects (``other_late`` late), three Editors."""
    rows = [proj(f"g{i}", EDITORS[i % 3], "8", late=i < group_late, days=5 + i % 25) for i in range(group)]
    rows += [proj(f"o{i}", EDITORS[i % 3], "4", late=i < other_late, days=5 + i % 25) for i in range(other)]
    return f.base(rows)


def concentrated(result):
    return [x for x in result.findings if x.scope.kind == "video_type" and x.scope.cohort_key == "8"]


class ConcentrationBoundaryTests(unittest.TestCase):
    def test_group_sample_floor_is_ten_projects(self):
        below = run("concentration.negative", concentration_rows(9, 9, 30, 3))
        self.assertEqual(concentrated(below), [])
        self.assertIn("insufficient_sample", reasons(below, cohort_key="8"))
        for size in (10, 11):
            self.assertTrue(concentrated(run("concentration.negative", concentration_rows(size, size, 30, 3))), size)

    def test_outcome_event_floor_is_five_events(self):
        below = run("concentration.negative", concentration_rows(10, 4, 90, 1))       # 4 of 5 late projects sit in 10% of the work
        self.assertEqual(concentrated(below), [])
        self.assertIn("insufficient_outcome_events", reasons(below, cohort_key="8"))
        self.assertTrue(concentrated(run("concentration.negative", concentration_rows(10, 5, 90, 1))))

    def test_ratio_must_reach_1_25(self):
        # Base share 20/40 = 0.5. Outcome share 10/16 = 0.625: ratio exactly 1.25, difference 12.5 pp.
        at = concentrated(run("concentration.negative", concentration_rows(20, 10, 20, 6)))
        self.assertEqual(at[0].statements[0].params["share_ratio"], 1.25)
        # Outcome share 12/20 = 0.6: difference exactly 10 pp, but ratio 1.2 < 1.25.
        below = run("concentration.negative", concentration_rows(20, 12, 20, 8))
        self.assertEqual(concentrated(below), [])
        self.assertIn("no_effect_at_approved_threshold", reasons(below, cohort_key="8"))

    def test_absolute_share_difference_must_reach_10_points(self):
        # Base share 10/50 = 0.2. Outcome share 6/20 = 0.3: difference exactly 10 pp, ratio 1.5.
        self.assertTrue(concentrated(run("concentration.negative", concentration_rows(10, 6, 40, 14))))
        # Outcome share 7/25 = 0.28: ratio 1.4 passes but the difference is 8 pp.
        below = run("concentration.negative", concentration_rows(10, 7, 40, 18))
        self.assertEqual(concentrated(below), [])
        self.assertIn("no_effect_at_approved_threshold", reasons(below, cohort_key="8"))


# --- D53.4: shared / system pattern -----------------------------------------------------------------------------------------------

def breadth_rows(elevated, flat=0, short_editor=False):
    """Per Editor: 5 Class A+ and 5 Class A projects. Elevated Editors are late 4/5 inside Class A+ and 1/5 outside; flat Editors
    1/5 on both sides. ``short_editor`` adds an elevated Editor with only 4 projects inside (below the per-Editor minimum)."""
    rows = []
    for position, editor in enumerate(EDITORS[: elevated + flat]):
        inside_late = 4 if position < elevated else 1
        rows += [proj(f"{position}i{i}", editor, "8", late=i < inside_late, days=5 + i + position) for i in range(5)]
        rows += [proj(f"{position}o{i}", editor, "4", late=i < 1, days=5 + i + position) for i in range(5)]
    if short_editor:
        rows += [proj(f"si{i}", EDITORS[5], "8", late=True, days=5 + i) for i in range(4)]
        rows += [proj(f"so{i}", EDITORS[5], "4", days=5 + i) for i in range(5)]
    return f.base(rows)


def shared(result):
    return [x for x in result.findings if x.key == {"measure": "late_delivery", "cohort": "8"}]


class SharedPatternBoundaryTests(unittest.TestCase):
    def test_two_qualifying_editors_are_never_a_shared_pattern(self):
        result = run("pattern.shared_across_editors", breadth_rows(2))
        self.assertEqual(shared(result), [])
        self.assertIn("insufficient_qualifying_editors", reasons(result, cohort_key="8"))

    def test_three_affected_editors_are_a_shared_pattern(self):
        found = shared(run("pattern.shared_across_editors", breadth_rows(3)))
        self.assertEqual((found[0].category, found[0].statements[0].params["elevated_editors"]), ("system_pattern", 3))
        interpretation = next(s for s in found[0].statements if s.level == "interpretation")
        self.assertIn("more consistent with a shared workflow pattern than an isolated Editor pattern", narrative.T[interpretation.code](interpretation.params))

    def test_two_affected_of_three_qualifying_is_not_shared(self):
        # Two thirds of the qualifying Editors, but only 2 affected Editors (< 3): not shared, and not confined to one Editor.
        result = run("pattern.shared_across_editors", breadth_rows(2, flat=1))
        self.assertEqual(shared(result), [])
        self.assertIn("no_effect_at_approved_threshold", reasons(result, cohort_key="8"))

    def test_exactly_two_thirds_with_three_affected_is_shared(self):
        self.assertEqual(shared(run("pattern.shared_across_editors", breadth_rows(4, flat=2)))[0].category, "system_pattern")    # 4 of 6
        self.assertEqual(shared(run("pattern.shared_across_editors", breadth_rows(3, flat=1)))[0].category, "system_pattern")    # 3 of 4

    def test_below_two_thirds_is_not_shared(self):
        self.assertEqual(shared(run("pattern.shared_across_editors", breadth_rows(3, flat=2))), [])                          # 3 of 5

    def test_editor_below_five_comparable_projects_does_not_count(self):
        found = shared(run("pattern.shared_across_editors", breadth_rows(2, short_editor=True)))
        self.assertEqual(found, [])

    def test_breadth_rule_is_exact(self):
        self.assertTrue(cm.shared_across_editors(4, 6, 3, "2/3"))
        self.assertFalse(cm.shared_across_editors(2, 3, 3, "2/3"))
        self.assertFalse(cm.shared_across_editors(3, 5, 3, "2/3"))
        self.assertTrue(cm.shared_across_editors(3, 3, 3, "2/3"))
        self.assertFalse(cm.shared_across_editors(0, 0, 3, "2/3"))


# --- D53.6: materiality ---------------------------------------------------------------------------------------------------------

def team_rows(current_late, comparison_late, n=100):
    rows = [proj(f"c{i}", EDITORS[i % 3], late=i < current_late, days=3 + i % 25) for i in range(n)]
    rows += [proj(f"p{i}", EDITORS[i % 3], late=i < comparison_late, days=33 + i % 25) for i in range(n)]
    return f.base(rows)


def team_change(result):
    return [x for x in result.findings if x.key["measure"] == "late_rate" and x.key["against"] == "comparison"]


class MaterialityBoundaryTests(unittest.TestCase):
    def test_rate_difference_of_15_points_is_material_14_is_not(self):
        self.assertTrue(team_change(run("change.team", team_rows(35, 20))))       # 35% vs 20%
        below = run("change.team", team_rows(34, 20))                               # 34% vs 20%
        self.assertEqual(team_change(below), [])
        self.assertIn("no_effect_at_approved_threshold", reasons(below))

    def test_duration_difference_of_25_percent_is_material_24_is_not(self):
        def rows(current_hours):
            history = [f.fact(f"h{i}", editor=EDITORS[i % 3], start=f.days_before(70 + i), hours=10) for i in range(12)]
            return f.base(history + [f.fact(f"c{i}", editor=EDITORS[i % 3], start=f.days_before(3 + i), hours=current_hours) for i in range(12)])
        found = run("change.video_type", rows(12.5)).findings                      # +25%
        self.assertEqual(found[0].statements[0].params["pct_change"], 25.0)
        self.assertEqual(run("change.video_type", rows(12.4)).findings, [])         # +24%


# --- D53.7: short runway --------------------------------------------------------------------------------------------------------

class ShortRunwayBoundaryTests(unittest.TestCase):
    def setUp(self):
        # Typical Class A execution of the other Editors: 10 h (12 projects, 2 Editors: valid at the D52 comparator minimums).
        self.history = [f.fact(f"h{i}", editor=EDITORS[1 + i % 2], start=f.days_before(40 + i), hours=10, eta_hours=12) for i in range(12)]

    def short(self, runway_hours, cohort="4"):
        project = f.fact("x", editor=A, cohort=cohort, start=f.days_before(3), hours=8, eta_hours=runway_hours)
        facts = f.base([*self.history, project])
        return cm.short_runway(next(p for p in facts.projects if p.monday_item_id == "x"), f.context(facts, "approved_only").baselines)

    def test_runway_equal_to_typical_is_not_short(self):
        self.assertIs(self.short(10), False)

    def test_runway_below_typical_is_short(self):
        self.assertIs(self.short(9.99), True)

    def test_no_comparable_video_type_history_is_not_enough_evidence(self):
        self.assertIsNone(self.short(2, cohort="5"))


# --- D53.8: workload percentile -------------------------------------------------------------------------------------------------

def workload_history():
    """Editor A's own history: concurrency at start 0, 1, 2 repeated (blocks of three overlapping projects)."""
    rows = []
    for block in range(12):
        for position in range(3):
            start = f.stamp(f.at(f.days_before(100 - block * 7)) + f.timedelta(hours=position))
            rows.append(f.fact(f"w{block}-{position}", editor=A, start=start, hours=10, eta_hours=11))
    return rows


class WorkloadPercentileBoundaryTests(unittest.TestCase):
    def signal(self, open_items):
        items = [f.open_work(f"o{i}", editor=A, started_hours_ago=1, eta_in_hours=48) for i in range(open_items)]
        result = run("risk.open_work", f.base(workload_history(), items))
        return [x for x in result.findings if x.key["signal"] == "editor_workload_above_own_high_percentile"]

    def test_threshold_is_the_editors_own_75th_percentile(self):
        facts = f.base(workload_history())
        self.assertEqual(editor_high_workload(facts.attributed, 0.75), {A: 2})

    def test_other_active_projects_at_the_percentile_are_not_high(self):
        self.assertEqual(self.signal(3), [])                                        # 2 other active projects = the 75th percentile

    def test_other_active_projects_above_the_percentile_are_a_signal(self):
        found = self.signal(4)                                                       # 3 other active projects > 2
        params = found[0].statements[0].params["items"][0]
        self.assertEqual((params["editor_other_active_projects"], params["editor_high_percentile_concurrency"], params["percentile"]), (3, 2, 0.75))


# --- D53.11: confidence publication ---------------------------------------------------------------------------------------------

def stub(level, evidence_level="pattern", category="system_pattern"):
    return SimpleNamespace(confidence={"level": level}, evidence_level=evidence_level, category=category)


class ConfidencePublicationTests(unittest.TestCase):
    def test_strong_and_moderate_publish(self):
        self.assertTrue(publishable_finding(stub("strong")))
        self.assertTrue(publishable_finding(stub("moderate")))

    def test_weak_is_review_only(self):
        self.assertFalse(publishable_finding(stub("weak")))
        self.assertFalse(publishable_finding(stub("weak", "association", "hidden_context")))

    def test_weak_direct_fact_or_data_warning_publishes(self):
        self.assertTrue(publishable_finding(stub("weak", "fact", "emerging_risk")))
        self.assertTrue(publishable_finding(stub("weak", "metric", "data_warning")))


# --- D53.13 / D53.14: top 5 and duplicate clustering ----------------------------------------------------------------------------

def card(finding_id, projects, direction="adverse", types=("4",), category="system_pattern"):
    return SimpleNamespace(finding_id=finding_id, affected_projects=list(projects), direction=direction, affected_video_types=list(types), cluster=None,
                           category=category, investigations=[])


class TopFindingsAndClusteringTests(unittest.TestCase):
    policy = IntelligencePolicy.load(f.CONTRACT, "approved_only")

    def test_overlap_of_0_8_is_one_cluster_and_every_member_is_kept(self):
        first, second = card("a", range(10)), card("b", range(2, 10))               # Jaccard 8/10
        prioritization.cluster([first, second], self.policy)
        self.assertEqual(first.cluster["members"], ["a", "b"])
        self.assertTrue(second.cluster["suppressed_in_sections"])
        self.assertEqual(first.cluster["parameter_status"], "approved")

    def test_overlap_below_0_8_is_not_clustered(self):
        first, second = card("a", range(100)), card("b", range(21, 100))            # Jaccard 79/100
        prioritization.cluster([first, second], self.policy)
        self.assertIsNone(second.cluster)

    def test_opposite_direction_or_other_video_type_is_never_a_duplicate(self):
        for other in (card("b", range(10), direction="favourable"), card("b", range(10), types=("5",))):
            first = card("a", range(10))
            prioritization.cluster([first, other], self.policy)
            self.assertIsNone(other.cluster)

    def test_top_findings_are_the_first_five_primaries(self):
        cards = [card(f"f{i}", range(i * 10, i * 10 + 5)) for i in range(8)]
        cards.insert(1, card("dup", range(5)))                                    # a duplicate of f0: clustered, not in the top 5
        prioritization.cluster(cards, self.policy)
        top = prioritization.sections(cards, self.policy, [])["top_findings"]
        self.assertEqual(top["finding_ids"], ["f0", "f1", "f2", "f3", "f4"])
        self.assertEqual((top["limit"]["value"], top["limit"]["decision_id"]), (5, "D53"))

    def test_fewer_than_five_findings_are_all_shown(self):
        cards = [card(f"f{i}", range(i * 10, i * 10 + 5)) for i in range(3)]
        self.assertEqual(prioritization.sections(cards, self.policy, [])["top_findings"]["finding_ids"], ["f0", "f1", "f2"])


# --- Determinism ----------------------------------------------------------------------------------------------------------------

class DeterminismTests(unittest.TestCase):
    def test_every_d53_fixture_gives_identical_findings_twice(self):
        cases = [("concentration.negative", concentration_rows(10, 6, 40, 14)), ("pattern.shared_across_editors", breadth_rows(4, flat=2)),
                 ("change.team", team_rows(35, 20))]
        for detector, facts in cases:
            first = [x.to_dict() for x in run(detector, facts).findings]
            self.assertTrue(first, detector)
            self.assertEqual(first, [x.to_dict() for x in run(detector, facts).findings], detector)


# --- Fairness and conservatism guards added during the D53 production review ---------------------------------------------------

class FairnessGuardTests(unittest.TestCase):
    def test_repeated_delay_cell_is_compared_with_its_own_video_type(self):
        # Class A+ is late 90% of the time in every band; Class A 10%. Against the pooled rate every Class A+ cell would look elevated.
        rows = [proj(f"g{i}", EDITORS[i % 3], "8", late=i % 10 != 0, days=5 + i * 3) for i in range(30)]
        rows += [proj(f"o{i}", EDITORS[i % 3], "4", late=i % 10 == 0, days=5 + i * 3) for i in range(30)]
        result = run("pattern.repeated_delay", f.base(rows))
        self.assertEqual([x for x in result.findings if x.scope.cohort_key == "8"], [])
        examined = [row for row in result.not_evaluated if row["scope"].get("cohort_key") == "8" and "no_effect_at_approved_threshold" in row["reasons"]]
        self.assertTrue(examined)
        self.assertTrue(all(row["facts"]["overall_late_rate"] == 0.9 for row in examined))

    def test_timing_pattern_is_adjusted_for_the_video_type_mix(self):
        # Every Class A+ project (late) starts on the same weekday; Class A (on time) on the other days. The weekday is not late
        # more often than its Video Types predict, so there is no timing pattern.
        rows = [proj(f"w{k}", EDITORS[k % 3], "8", late=True, days=7 * k) for k in range(1, 21)]
        rows += [proj(f"d{k}", EDITORS[k % 3], "4", late=False, days=7 * (k // 6) + 1 + k % 6) for k in range(60)]
        result = run("pattern.time", f.base(rows))
        self.assertEqual([x for x in result.findings if x.key["dimension"] == "start_weekday"], [])
        weekday = [row for row in result.not_evaluated if row["facts"].get("dimension") == "start_weekday" and row["facts"].get("late_rate") == 1.0]
        self.assertEqual(weekday[0]["facts"]["overall_late_rate"], 1.0)

    def test_historical_similarity_needs_a_material_difference_from_the_video_type(self):
        history = []
        for i, (hours, eta) in enumerate([(10, 6)] * 6 + [(5, 6)] * 6 + [(20, 15)] * 5 + [(10, 15)] * 7):
            history.append(f.fact(f"h{i}", editor=EDITORS[1 + i % 4], start=f.days_before(40 + i), hours=hours, eta_hours=eta))
        item = f.open_work("o3", started_hours_ago=1, eta_in_hours=5)
        result = run("risk.historical_similarity", f.base(history, [item]))
        self.assertEqual(result.findings, [])
        facts = result.not_evaluated[0]["facts"]
        self.assertLess(facts["similar_late"] / facts["similar_projects"] - facts["video_type_late_rate"], 0.15)
        self.assertIn("no_effect_at_approved_threshold", result.not_evaluated[0]["reasons"])

    def test_editor_change_without_a_measurable_team_comparison_is_not_called_editor_specific(self):
        rows = [proj(f"c{i}", A, late=i < 10, days=3 + i) for i in range(12)] + [proj(f"p{i}", A, late=i < 2, days=33 + i) for i in range(12)]
        rows += [proj(f"bc{i}", B, days=3 + i) for i in range(3)] + [proj(f"bp{i}", B, days=33 + i) for i in range(3)]
        found = [x for x in run("change.editor", f.base(rows)).findings if x.key == {"measure": "late_rate", "against": "comparison", "cohort": None}]
        self.assertEqual(found[0].category, "hidden_context")
        self.assertIn("team_comparison_unavailable", [s.code for s in found[0].statements])
        self.assertNotIn("change_differs_from_team", [s.code for s in found[0].statements])

    def test_a_direct_fact_is_strong_with_one_explained_factor(self):
        item = f.open_work("o1", eta_in_hours=-3)
        found = [x for x in run("risk.open_work", f.base([], [item])).findings if x.key["signal"] == "past_eta"]
        self.assertEqual(found[0].confidence["level"], "strong")
        self.assertEqual([factor["factor"] for factor in found[0].confidence["factors"]], ["direct_observation"])


if __name__ == "__main__":
    unittest.main()
