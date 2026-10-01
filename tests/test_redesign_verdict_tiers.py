"""Redesign T2.5: every tier rule of spec §3 at, just below and just above its threshold (values from config/verdict-v1.json)."""

import unittest

from atlas_commander.verdict.config import load_config
from atlas_commander.verdict.tiers import BEST, LOW_ACTIVITY, STEADY, WATCH, WEAKEST, Standing, assign_tier

CONFIG = load_config()
TEAM = 0.59
TOP = Standing(in_top_share=True, worse_dimensions=())
MIDDLE = Standing(in_top_share=False, worse_dimensions=())


def m(completed=12, late_pp=0.0, speed=None, classified=True):
    return {"completed": completed, "late_rate": round(TEAM + late_pp / 100, 4), "team_late_rate": TEAM, "speed_delta_pct": speed,
            "speed_classified": classified and speed is not None}


class TierRuleTests(unittest.TestCase):
    def tier(self, metrics, overdue=0, standing=MIDDLE):
        return assign_tier(metrics, overdue, CONFIG, standing)

    def test_low_activity(self):
        self.assertEqual(self.tier(m(completed=0), overdue=2), LOW_ACTIVITY)          # zero projects always
        self.assertEqual(self.tier(m(completed=2)), LOW_ACTIVITY)                     # below 3 and nothing overdue
        self.assertEqual(self.tier(m(completed=2), overdue=1), WATCH)                 # below 3 but overdue work: judged
        self.assertEqual(self.tier(m(completed=3)), STEADY)                           # 3 is not "fewer than 3"

    def test_weakest_by_late_rate(self):
        self.assertEqual(self.tier(m(late_pp=20)), WEAKEST)                           # exactly +20 pp
        self.assertEqual(self.tier(m(late_pp=19.99)), WATCH)

    def test_weakest_by_speed_needs_later_than_team(self):
        self.assertEqual(self.tier(m(speed=30, late_pp=0.01)), WEAKEST)
        self.assertEqual(self.tier(m(speed=30, late_pp=0)), WATCH)                    # not later than the team: speed alone is Watch
        self.assertEqual(self.tier(m(speed=29.9, late_pp=1)), WATCH)                  # +25 % already Watch
        self.assertEqual(self.tier(m(speed=40, late_pp=1, classified=False)), STEADY) # an unclassified comparison never judges

    def test_watch(self):
        self.assertEqual(self.tier(m(late_pp=5)), STEADY)                              # "more than 5 pp"
        self.assertEqual(self.tier(m(late_pp=5.01)), WATCH)
        self.assertEqual(self.tier(m(speed=25)), WATCH)
        self.assertEqual(self.tier(m(speed=24.9)), STEADY)
        self.assertEqual(self.tier(m(), overdue=1, standing=TOP), WATCH)              # overdue work outranks Best

    def test_best_needs_top_share_and_no_worse_dimension(self):
        self.assertEqual(self.tier(m(late_pp=-5, speed=-10), standing=TOP), BEST)
        self.assertEqual(self.tier(m(late_pp=-5, speed=-10), standing=Standing(True, ("volume",))), STEADY)
        self.assertEqual(self.tier(m(late_pp=-5, speed=-10), standing=MIDDLE), STEADY)


if __name__ == "__main__":
    unittest.main()
