"""Redesign T2.6: score and rank (spec §4): a normal case, a missing speed dimension, a tie, and an Editor below the minimum."""

import unittest

from verdict_fixture import editor, verdicts

from atlas_commander.verdict.config import load_config
from atlas_commander.verdict.tiers import Scored, dimension_points, rank, score, weights

CONFIG = load_config()


def metrics(completed, late_rate, speed, classified=True, team=0.59):
    return {"completed": completed, "late_rate": late_rate, "team_late_rate": team, "speed_delta_pct": speed, "speed_classified": classified}


class ScoreTests(unittest.TestCase):
    def test_normal_case_follows_the_formula(self):
        # Will in the fixture: 12 of 22 late (team 76 of 129), 23.3% faster, 22 projects against a ranked median of 15.
        points = dimension_points(metrics(22, 0.5455, -23.3, team=0.5891), 15, CONFIG)
        self.assertAlmostEqual(points["deadlines"], 50 + (58.91 - 54.55) * 2, places=6)
        self.assertAlmostEqual(points["speed"], 50 + 23.3 * 1.25, places=6)
        self.assertAlmostEqual(points["volume"], 50 + (22 / 15 - 1) * 50, places=6)
        value, missing = score(points, CONFIG, quality_approved=False)
        self.assertEqual(missing, [])
        self.assertEqual(value, round(0.40 * points["deadlines"] + 0.35 * points["speed"] + 0.25 * points["volume"], 1))
        self.assertEqual(editor(verdicts(), "Will")["score"], 69.5)

    def test_a_missing_speed_dimension_redistributes_its_weight(self):
        points = dimension_points(metrics(15, 0.4667, None, classified=False, team=0.5891), 15, CONFIG)
        self.assertIsNone(points["speed"])
        value, missing = score(points, CONFIG, quality_approved=False)
        self.assertEqual(missing, ["speed"])
        self.assertEqual(value, round(points["deadlines"] * 0.40 / 0.65 + points["volume"] * 0.25 / 0.65, 1))
        mario = editor(verdicts(), "Mario")
        self.assertIn("missing_speed", mario["confidence_reasons"])
        self.assertEqual(mario["based_on"], ["deadlines", "volume"])

    def test_points_are_clamped(self):
        points = dimension_points(metrics(60, 1.0, 90, team=0.2), 15, CONFIG)
        self.assertEqual((points["deadlines"], points["speed"], points["volume"]), (0, 0, 100))

    def test_quality_takes_its_weight_once_approved(self):
        shared = weights(CONFIG, quality_approved=True)
        self.assertAlmostEqual(shared["quality"], 0.25)
        self.assertAlmostEqual(shared["deadlines"] + shared["speed"] + shared["volume"], 0.75)
        self.assertAlmostEqual(shared["deadlines"] / shared["speed"], 0.40 / 0.35)

    def test_a_tie_goes_to_the_lower_late_rate_then_more_projects(self):
        order = rank([Scored("a", 60.0, 0.60, 20), Scored("b", 60.0, 0.50, 10), Scored("c", 60.0, 0.50, 12), Scored("d", 70.0, 0.9, 5)])
        self.assertEqual(order, {"d": 1, "c": 2, "b": 3, "a": 4})

    def test_an_editor_below_the_minimum_is_not_ranked(self):
        document = verdicts()
        ranked = [e for e in document["editors"] if e["rank"] is not None]
        self.assertEqual(sorted(e["rank"] for e in ranked), list(range(1, len(ranked) + 1)))
        for name in ("Mohamed Mansour (Office)", "Samra"):
            verdict = editor(document, name)
            self.assertEqual((verdict["rank"], verdict["score"]), (None, None))
            self.assertEqual(verdict["ranked_of"], len(ranked))
        self.assertTrue(all(e["metrics"]["completed"] >= 5 for e in ranked))


if __name__ == "__main__":
    unittest.main()
