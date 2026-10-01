"""Redesign T2.7: confidence (spec §5) starts High, loses one level per reason, never drops below Low, and never hides a verdict."""

import unittest

from verdict_fixture import editor, verdicts

from atlas_commander.verdict.confidence import confidence
from atlas_commander.verdict.config import load_config

CONFIG = load_config()
ALL = ["deadlines", "speed", "volume"]


class ConfidenceTests(unittest.TestCase):
    def test_sobhy_six_projects_is_low_because_of_few_projects(self):
        sobhy = editor(verdicts(), "Sobhy")
        self.assertEqual(sobhy["confidence"], "low")
        self.assertIn("few_projects", sobhy["confidence_reasons"])       # 6 < 10 completed projects: High -> Medium
        self.assertIn("missing_dimension", sobhy["confidence_reasons"])  # no speed comparison: Medium -> Low
        self.assertEqual(sobhy["tier"], "watch")                         # the verdict stays

    def test_will_twenty_two_projects_is_medium_and_says_why(self):
        will = editor(verdicts(), "Will")
        # 22 >= 10 projects and every key dimension present, so High would stand; the published Intelligence finding
        # "Will: the late-rate headline needs context" carries contradicting evidence on the deadline dimension his verdict
        # uses, so it steps down once, to Medium.
        self.assertEqual((will["confidence"], will["confidence_reasons"]), ("medium", ["mixed_evidence"]))

    def test_each_reason_lowers_one_level_with_a_floor(self):
        m = {"completed": 22}
        self.assertEqual(confidence(m, [], ALL, [], CONFIG), ("high", []))
        self.assertEqual(confidence({"completed": 9}, [], ALL, [], CONFIG)[0], "medium")
        self.assertEqual(confidence({"completed": 10}, [], ALL, [], CONFIG)[0], "high")
        self.assertEqual(confidence(m, ["speed"], ["deadlines", "volume"], [], CONFIG)[0], "medium")
        self.assertEqual(confidence(m, ["volume"], ["deadlines", "speed"], [], CONFIG)[0], "high")    # volume is not a key dimension
        self.assertEqual(confidence(m, [], ["speed", "volume"], ["finding"], CONFIG)[0], "high")    # the headline finding is about deadlines
        level, reasons = confidence({"completed": 2}, ["deadlines", "speed"], [], ["finding"], CONFIG)
        self.assertEqual(level, "low")                                                               # two or more reasons: the floor
        self.assertEqual(reasons[:2], ["few_projects", "missing_dimension"])

    def test_timeline_only_sets_low_directly(self):
        self.assertEqual(confidence({"completed": 30}, [], ALL, [], CONFIG, timeline_only=True), ("low", ["timeline_only"]))
        self.assertNotIn("timeline_only", {r for e in verdicts()["editors"] for r in e["confidence_reasons"]})


if __name__ == "__main__":
    unittest.main()
