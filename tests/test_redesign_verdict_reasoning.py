"""Redesign T2.8–T2.11: the combination rules of spec §6 connect findings instead of listing them."""

import dataclasses
import unittest

from verdict_fixture import editor, fixture, verdicts

from atlas_commander.verdict.config import load_config
from atlas_commander.verdict.inputs import normalize
from atlas_commander.verdict.reasoning import RUNWAY_EXPLAINS, RUNWAY_NOT_EXPLAINING, limit_tier, runway
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


if __name__ == "__main__":
    unittest.main()
