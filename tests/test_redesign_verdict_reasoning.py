"""Redesign T2.8–T2.11: the combination rules of spec §6 connect findings instead of listing them."""

import copy
import dataclasses
import unittest

from verdict_fixture import editor, fixture, verdicts

from atlas_commander.verdict.config import load_config
from atlas_commander.verdict.decisions import APPROVE_RULE, LOW_ACTIVITY, decision_id
from atlas_commander.verdict.engine import build_verdicts
from atlas_commander.verdict.inputs import normalize
from atlas_commander.verdict.reasoning import (
    RUNWAY_EXPLAINS,
    RUNWAY_NOT_EXPLAINING,
    duplicates,
    limit_tier,
    mirrored_changes,
    mirrors_team,
    runway,
    silent_measurement,
    zero_activity,
)
from atlas_commander.verdict.tiers import LOW_ACTIVITY as LOW_ACTIVITY_TIER
from atlas_commander.verdict.tiers import STEADY, WATCH, WEAKEST

CONFIG = load_config()


def inputs():
    data = fixture()
    editors, team = normalize(data["dashboard"], data["intelligence"])
    return {e.display_name: e for e in editors}, team


class RunwayRuleTests(unittest.TestCase):
    """T2.8, §6 rows 1-2."""

    def test_refaat_lateness_is_not_explained_by_scheduling(self):
        editors, team = inputs()
        result = runway(editors["Refaat"], team, CONFIG)
        self.assertEqual(result.code, RUNWAY_NOT_EXPLAINING)          # 85.7% > 73.2% (the team's late rate on short-runway projects)
        self.assertEqual(result.reason["params"], {"late_pct": 85.7, "short_runway_late_pct": 73.2})
        refaat = editor(verdicts(), "Refaat")
        self.assertIn(result.reason, refaat["reasons"])
        self.assertEqual(refaat["tier"], WEAKEST)                     # "not explaining" allows Weakest

    def test_scheduling_explains_lateness_when_rate_and_share_say_so(self):
        editors, team = inputs()
        mostly_short = dataclasses.replace(editors["Anas"], runway_late=20, runway_late_short=17)   # 85% >= team share 77.4%
        result = runway(mostly_short, team, CONFIG)
        self.assertEqual(result.code, RUNWAY_EXPLAINS)
        self.assertEqual(result.reason["params"]["short_share_pct"], 85.0)
        self.assertIsNone(runway(editors["Anas"], team, CONFIG))       # 13 of 20 = 65% < 77.4%: no claim either way

    def test_a_softened_editor_is_never_worse_than_watch(self):
        editors, team = inputs()
        explained = runway(dataclasses.replace(editors["Anas"], runway_late=20, runway_late_short=17), team, CONFIG)
        self.assertEqual(limit_tier(WEAKEST, explained), WATCH)
        self.assertEqual(limit_tier(STEADY, explained), STEADY)
        self.assertEqual(limit_tier(WEAKEST, runway(editors["Refaat"], team, CONFIG)), WEAKEST)

    def test_no_runway_split_means_no_claim(self):
        editors, team = inputs()
        self.assertIsNone(runway(editors["Refaat"], dataclasses.replace(team, runway=None), CONFIG))


class MirrorsTeamTests(unittest.TestCase):
    """T2.9, §6 row 3."""

    def test_anas_improvement_mirrors_the_team(self):
        anas = editor(verdicts(), "Anas")
        self.assertIn({"key": "verdict.reason.mirrors_team_late_rate",
                       "params": {"before_pct": 69.2, "now_pct": 53.8, "team_before_pct": 75.6, "team_now_pct": 59.0}}, anas["reasons"])
        self.assertEqual(anas["tier"], STEADY)                        # neither credited nor blamed

    def test_his_standalone_late_rate_finding_is_hidden_from_the_overview(self):
        document = verdicts()
        hidden = {(h["finding_id"], h["reason"]) for h in document["findings"]["hide_from_overview"]}
        self.assertIn(("change.editor:anas-history", "mirrors_team"), hidden)
        self.assertIn("change.editor:anas-history", editor(document, "Anas")["hidden_finding_ids"])

    def test_a_change_the_team_did_not_share_is_the_editors_own(self):
        editors, _ = inputs()
        refaat_speed = next(c for c in editors["Refaat"].changes if c.measure == "median_execution")
        self.assertFalse(mirrors_team(refaat_speed, CONFIG))           # +26.3% against the team's -4.1%: 30.4 >= 25
        self.assertEqual(mirrored_changes(editors["Refaat"], CONFIG), [])

    def test_the_material_difference_is_the_boundary(self):
        editors, _ = inputs()
        change = next(c for c in editors["Anas"].changes if c.against == "history")
        self.assertTrue(mirrors_team(dataclasses.replace(change, difference=-0.1662 + 0.1499), CONFIG))
        self.assertFalse(mirrors_team(dataclasses.replace(change, difference=-0.1662 + 0.15), CONFIG))
        self.assertFalse(mirrors_team(dataclasses.replace(change, team_difference=None), CONFIG))


def finding(finding_id, editors, measure, sample, *, finding_type="change.editor", cohort=None, window=None):
    params = {"measure": measure, **({"cohort_key": cohort} if cohort else {})}
    return {"finding_id": finding_id, "finding_type": finding_type, "affected_editors": editors, "sample_size": sample,
            "time_window": window, "statements": [{"code": "late_rate_changed", "params": params}]}


class DuplicateFindingTests(unittest.TestCase):
    """T2.10, §6 row 4."""

    def test_anas_two_late_rate_findings_collapse_into_the_larger_one(self):
        document = verdicts()
        self.assertEqual(document["findings"]["duplicates"], [{"kept": "change.editor:anas-history", "hidden": ["change.editor:anas-comparison"],
                                                              "editor_id": "editor-label-5", "measure": "late_rate"}])   # 39 > 29 projects

    def test_the_other_one_is_kept_under_more_details(self):
        document = verdicts()
        anas = editor(document, "Anas")
        self.assertIn(("change.editor:anas-comparison", "duplicate"),
                      {(h["finding_id"], h["reason"]) for h in document["findings"]["hide_from_overview"]})
        self.assertIn("change.editor:anas-comparison", anas["hidden_finding_ids"])   # off the overview ...
        self.assertIn("change.editor:anas-comparison", anas["finding_ids"])          # ... still linked for More details
        self.assertIn("change.editor:anas-comparison", {f["finding_id"] for f in fixture()["intelligence"]["findings"]})

    def test_every_hidden_finding_is_listed_once(self):
        ids = [h["finding_id"] for h in verdicts()["findings"]["hide_from_overview"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_same_editor_same_measure_overlapping_windows_only(self):
        september = {"start_date": "2026-08-31", "end_date_exclusive": "2026-09-30"}
        august = {"start_date": "2026-08-01", "end_date_exclusive": "2026-08-31"}
        base = finding("a", ["e1"], "late_rate", 30, window=september)
        self.assertEqual(duplicates([base, finding("b", ["e1"], "late_rate", 20, window=august)]), [])        # windows only touch
        self.assertEqual(duplicates([base, finding("b", ["e2"], "late_rate", 20, window=september)]), [])     # another Editor
        self.assertEqual(duplicates([base, finding("b", ["e1"], "median_execution", 20, window=september)]), [])   # another metric
        self.assertEqual(duplicates([finding("a", ["e1"], "median_execution", 30, cohort="6"),
                                     finding("b", ["e1"], "median_execution", 20, cohort="7")]), [])          # another Video Type
        self.assertEqual(duplicates([base, finding("b", ["e1", "e2"], "late_rate", 20, window=september)]), [])   # not one Editor's
        self.assertEqual(duplicates([base, finding("b", ["e1"], "late_rate", 40, window={"start_date": "2026-09-15",
                                                                                         "end_date_exclusive": "2026-10-15"})]),
                         [{"kept": "b", "hidden": ["a"], "editor_id": "e1", "measure": "late_rate"}])

    def test_equal_samples_keep_a_stable_choice(self):
        pair = [finding("z", ["e1"], "late_rate", 30), finding("a", ["e1"], "late_rate", 30)]
        self.assertEqual(duplicates(pair), duplicates(list(reversed(pair))))
        self.assertEqual(duplicates(pair)[0]["kept"], "a")

    def test_a_hidden_duplicate_cannot_make_the_editor_mirror_the_team(self):
        data = copy.deepcopy(fixture())
        history = next(f for f in data["intelligence"]["findings"] if f["finding_id"] == "change.editor:anas-history")
        history["statements"][0]["params"]["team_difference"] = 0.10     # the kept change now differs from the team's (gap 25 pp)
        document = build_verdicts(data["dashboard"], data["intelligence"], data["dashboard"]["generated_at"])
        anas = editor(document, "Anas")
        self.assertEqual([r for r in anas["reasons"] if r["key"].startswith("verdict.reason.mirrors_team")], [])
        self.assertEqual({(h["finding_id"], h["reason"]) for h in document["findings"]["hide_from_overview"] if h["editor_id"] == "editor-label-5"},
                         {("change.editor:anas-comparison", "duplicate")})


def candidates(document, decision_type):
    return [d for d in document["decision_candidates"] if d["type"] == decision_type]


class SilentMeasurementTests(unittest.TestCase):
    """T2.11, §6 row 5."""

    def test_quality_at_zero_for_everyone_is_a_management_decision(self):
        editors, _ = inputs()
        self.assertEqual({e.quality_negative_rate for e in editors.values() if e.quality_negative_rate is not None}, {0.0})
        (rule,) = candidates(verdicts(), APPROVE_RULE)
        self.assertEqual((rule["horizon"], rule["owner_role"], rule["owner_editor_ids"], rule["target"]), ("management", "ceo", [], "rule:quality"))
        self.assertEqual(rule["title"], {"key": "verdict.decision.approve_rule", "params": {"dimension": "quality"}})
        self.assertEqual([m["key"] for m in rule["evidence"]], ["verdict.evidence.rule_not_approved", "verdict.evidence.zero_for_everyone"])
        self.assertEqual(rule["evidence"][1]["params"], {"dimension": "quality", "editors": 9})   # every Editor with a value
        self.assertEqual(rule["id"], decision_id(APPROVE_RULE, "quality"))

    def test_zero_is_read_as_not_measured_never_as_good(self):
        document = verdicts()
        for e in document["editors"]:
            self.assertNotIn("quality", e["based_on"], e["display_name"])
            self.assertNotIn("quality.state", (e["metrics"]["quality"] or {}).get("key", ""), e["display_name"])

    def test_an_approved_rule_that_reads_zero_for_everyone_is_reviewed_and_not_scored(self):
        data = copy.deepcopy(fixture())
        for e in data["dashboard"]["editors"]:
            e["interpretation"]["components"]["quality"].update(rule_status="approved", state="good")
        document = build_verdicts(data["dashboard"], data["intelligence"], data["dashboard"]["generated_at"])
        (rule,) = candidates(document, APPROVE_RULE)
        self.assertEqual(rule["title"]["key"], "verdict.decision.review_rule")
        self.assertEqual([m["key"] for m in rule["evidence"]], ["verdict.evidence.zero_for_everyone"])
        for e in document["editors"]:                                  # "good" from a measure that is 0% for everyone is not shown
            self.assertNotIn("quality", e["based_on"], e["display_name"])
            self.assertNotEqual((e["metrics"]["quality"] or {}).get("key"), "verdict.quality.state.good", e["display_name"])

    def test_a_measure_that_varies_is_not_silent(self):
        data = copy.deepcopy(fixture())
        for e in data["dashboard"]["editors"]:
            e["interpretation"]["components"]["quality"]["rule_status"] = "approved"
        mario = next(e for e in data["dashboard"]["editors"] if e["display_name"] == "Mario")
        mario["interpretation"]["components"]["quality"]["facts"]["negative_rate"] = 0.2667     # as on the real build
        document = build_verdicts(data["dashboard"], data["intelligence"], data["dashboard"]["generated_at"])
        self.assertEqual(candidates(document, APPROVE_RULE), [])
        editors = normalize(data["dashboard"], data["intelligence"])[0]
        self.assertEqual(silent_measurement(editors), [])
        self.assertEqual(silent_measurement([e for e in editors if e.display_name == "Will"]), [])   # one Editor at 0% is not "everyone"
        self.assertEqual(silent_measurement([]), [])


class ZeroActivityTests(unittest.TestCase):
    """T2.11, §6 row 6."""

    def test_samra_produces_an_ask_candidate(self):
        document = verdicts()
        (ask,) = candidates(document, LOW_ACTIVITY)
        samra = editor(document, "Samra")
        self.assertEqual(samra["tier"], LOW_ACTIVITY_TIER)
        self.assertEqual((ask["horizon"], ask["owner_role"]), ("ask", None))
        self.assertIn(samra["editor_id"], ask["owner_editor_ids"])
        self.assertIn({"key": "verdict.evidence.zero_activity", "params": {"name": "Samra", "lifetime_completed": 60}}, ask["evidence"])
        self.assertEqual(ask["title"]["key"], "verdict.decision.zero_activity")

    def test_only_editors_with_nothing_completed_and_nothing_in_progress(self):
        editors, _ = inputs()
        self.assertEqual(sorted(name for name, e in editors.items() if zero_activity(e)), ["Ahmed", "Samra"])
        self.assertFalse(zero_activity(editors["Michael"]))            # 0 completed but 1 in progress (and overdue)
        self.assertFalse(zero_activity(editors["Mohamed Mansour (Office)"]))
        (ask,) = candidates(verdicts(), LOW_ACTIVITY)
        owners = sorted([editors["Ahmed"], editors["Samra"]], key=lambda e: e.editor_id)
        self.assertEqual(ask["owner_editor_ids"], [e.editor_id for e in owners])
        self.assertEqual(ask["title"]["params"], {"names": [e.display_name for e in owners]})   # names in the owners' order

    def test_candidates_are_stable_and_in_priority_order(self):
        first, second = verdicts()["decision_candidates"], verdicts()["decision_candidates"]
        self.assertEqual(first, second)
        self.assertEqual([d["type"] for d in first], [LOW_ACTIVITY, APPROVE_RULE])          # §7: ask (4) before management (5)
        self.assertEqual([d["priority"] for d in first], [4, 5])
        self.assertEqual(verdicts()["decisions"], [])                                      # the overview list is T2.14


if __name__ == "__main__":
    unittest.main()
