"""Redesign T2.3: the September 2026 fixture of `02-VERDICT-ENGINE-SPEC.md` §9 and the tiers it must produce.

The expectations are the spec's; they fail until the engine implements them (T2.4, T2.5), each for the reason named in its message.
"""

import unittest

from verdict_fixture import editor, fixture, verdicts

from atlas_commander.contracts import schema_errors
from atlas_commander.verdict.engine import SCHEMA

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


if __name__ == "__main__":
    unittest.main()
