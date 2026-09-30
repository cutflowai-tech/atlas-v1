"""Redesign T2.8–T2.11: the combination rules of spec §6 connect findings instead of listing them."""

import dataclasses
import unittest

from verdict_fixture import editor, fixture, verdicts

from atlas_commander.verdict.config import load_config
from atlas_commander.verdict.inputs import normalize
from atlas_commander.verdict.reasoning import RUNWAY_EXPLAINS, RUNWAY_NOT_EXPLAINING, limit_tier, mirrored_changes, mirrors_team, runway
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


if __name__ == "__main__":
    unittest.main()
