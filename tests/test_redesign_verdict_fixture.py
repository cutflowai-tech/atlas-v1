"""Redesign T2.3: the September 2026 fixture of `02-VERDICT-ENGINE-SPEC.md` §9 and the tiers it must produce.

The expectations are the spec's; they fail until the engine implements them (T2.4, T2.5), each for the reason named in its message.
"""

import unittest

from verdict_fixture import editor, fixture, verdicts

from atlas_commander.contracts import schema_errors
from atlas_commander.verdict.config import load_config
from atlas_commander.verdict.engine import SCHEMA
from atlas_commander.verdict.inputs import metrics, normalize

EXPECTED_TIERS = {"Will": "best", "Anas": "steady", "Refaat": "weakest", "Sobhy": "watch",
                  "Mohamed Mansour (Office)": "low_activity", "Samra": "low_activity"}


class FixtureTests(unittest.TestCase):
    def test_the_fixture_loads_and_reproduces_the_team_totals(self):
        data = fixture()
        editors = data["dashboard"]["editors"]
        facts = [e["interpretation"]["components"]["deadline"]["facts"] for e in editors]
        self.assertEqual(round(sum(f["late"] for f in facts) / sum(f["deadline_classifiable_projects"] for f in facts), 2), 0.59)
        self.assertEqual(len(data["intelligence"]["findings"][0]["statements"][0]["params"]["items"]), 3)
        self.assertEqual(schema_errors(verdicts(), SCHEMA), [])

    @unittest.expectedFailure   # T2.5 not implemented yet: the engine writes no Editor verdicts
    def test_spec_tiers(self):
        document = verdicts()
        for name, tier in EXPECTED_TIERS.items():
            self.assertEqual(editor(document, name)["tier"], tier, name)


def fixture_metrics() -> dict[str, dict]:
    data = fixture()
    editors, team = normalize(data["dashboard"], data["intelligence"])
    return {e.display_name: metrics(e, team, load_config()) for e in editors}


SPEC = {   # completed, late count, late rate (1 decimal %), speed vs peers (whole %), own speed change (whole %)
    "Will": (22, 12, 54.5, -23, None),
    "Anas": (13, 7, 53.8, 23, None),
    "Refaat": (14, 12, 85.7, 43, 26),
    "Sobhy": (6, 4, 66.7, None, None),
    "Mohamed Mansour (Office)": (2, 1, 50.0, 3, None),
    "Samra": (0, None, None, None, None),
}


class MetricsTests(unittest.TestCase):
    """T2.4: the existing metrics mapped into EditorVerdict.metrics match spec §9 exactly."""

    def test_late_counts_rates_and_speed_deltas_match_the_spec(self):
        got = fixture_metrics()
        for name, (completed, late, rate, speed, own) in SPEC.items():
            m = got[name]
            self.assertEqual(m["completed"], completed, name)
            self.assertEqual(m["late_count"], late, name)
            self.assertEqual(None if m["late_rate"] is None else round(m["late_rate"] * 100, 1), rate, name)
            self.assertEqual(None if m["speed_delta_pct"] is None else round(m["speed_delta_pct"]), speed, name)
            self.assertEqual(None if m["own_speed_delta_pct"] is None else round(m["own_speed_delta_pct"]), own, name)

    def test_speed_labels_and_team_rate(self):
        got = fixture_metrics()
        self.assertEqual(got["Refaat"]["speed_label"], {"key": "verdict.speed.label", "params": {"labels": ["Simple Short"], "editor_hours": 41.6,
                                                                                                 "peer_hours": 29.1, "n": 11}})
        self.assertEqual(got["Will"]["speed_label"]["params"]["labels"], ["Class A"])
        self.assertIsNone(got["Sobhy"]["speed_label"])                       # no comparable peers: "n/a"
        self.assertFalse(got["Mohamed Mansour (Office)"]["speed_classified"])   # one project: shown, never used for a verdict
        self.assertTrue(got["Refaat"]["speed_classified"])
        self.assertEqual({round(m["team_late_rate"] * 100) for m in got.values()}, {59})

    def test_quality_is_not_measured_unless_there_is_something_to_show(self):
        got = fixture_metrics()
        self.assertEqual(got["Will"]["quality"], {"key": "verdict.quality.positive_notes", "params": {"positive_pct": 18.2}})
        self.assertIsNone(got["Refaat"]["quality"])   # 0% issues under an unapproved rule is "not measured", never "good"


if __name__ == "__main__":
    unittest.main()
