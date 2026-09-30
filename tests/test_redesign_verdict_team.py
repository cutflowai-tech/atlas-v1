"""Redesign T2.15: the team verdict of spec §8 (state, trend, chain, KPIs)."""

import copy
import dataclasses
import unittest

from verdict_fixture import fixture, verdicts

from atlas_commander.contracts import schema_errors
from atlas_commander.verdict.config import load_config
from atlas_commander.verdict.engine import build_verdicts
from atlas_commander.verdict.inputs import normalize
from atlas_commander.verdict.team import state, team_verdict, trend

CONFIG = load_config()


def team_inputs():
    data = fixture()
    return normalize(data["dashboard"], data["intelligence"])[1]


class TeamVerdictTests(unittest.TestCase):
    def test_the_fixture_team_needs_intervention_and_is_improving(self):
        team = verdicts()["team"]
        self.assertEqual((team["state"], team["trend"]), ("needs_intervention", "improving"))   # 58.9% >= 40%, 3 overdue < 5; 75.2% -> 58.9%
        self.assertEqual(team["headline"]["key"], "verdict.team.headline.needs_intervention.improving")
        self.assertEqual(team["confidence"], "high")

    def test_three_kpis_59_was_75_three_overdue_77_short_runway(self):
        kpis = {k["key"]: k for k in verdicts()["team"]["kpis"]}
        self.assertEqual(list(kpis), ["late_rate", "overdue", "short_runway_share"])
        self.assertEqual((kpis["late_rate"]["value"], kpis["late_rate"]["label"]["params"], kpis["late_rate"]["tone"]),
                         ("58.9", {"previous_pct": 75.2}, "warn"))            # shown as 59% was 75%
        self.assertEqual((kpis["overdue"]["value"], kpis["overdue"]["tone"]), ("3", "warn"))
        self.assertEqual((kpis["short_runway_share"]["value"], kpis["short_runway_share"]["label"]["params"]),
                         ("77.4", {"short_runway_late": 328, "late": 424}))   # 77%, 328 of 424

    def test_the_chain_reads_fact_pattern_conclusion(self):
        chain = verdicts()["team"]["chain"]
        self.assertEqual(chain["fact"], {"key": "verdict.team.fact.late_rate_change",
                                         "params": {"late_pct": 58.9, "late": 76, "n": 129, "previous_pct": 75.2}})
        self.assertEqual(chain["pattern"]["params"], {"short_runway_late_pct": 73.2, "short_runway": 448, "adequate_runway_late_pct": 54.9,   # 50 of 91 (spec: "55%")
                                                      "adequate_runway": 91})
        self.assertEqual(chain["conclusion"]["key"], "verdict.team.conclusion.scheduling")   # 77.4% of late projects had short runway

    def test_state_thresholds(self):
        self.assertEqual(state(0.70, 0, CONFIG), "critical")
        self.assertEqual(state(0.6999, 5, CONFIG), "critical")                 # 5 overdue is critical on its own
        self.assertEqual(state(0.6999, 4, CONFIG), "needs_intervention")
        self.assertEqual(state(0.40, 0, CONFIG), "needs_intervention")
        self.assertEqual(state(0.3999, 4, CONFIG), "on_track")
        self.assertEqual(state(None, 0, CONFIG), "on_track")

    def test_trend_band(self):
        self.assertEqual(trend(0.55, 0.60, CONFIG), "flat")                    # exactly 5 points is still flat
        self.assertEqual(trend(0.5499, 0.60, CONFIG), "improving")
        self.assertEqual(trend(0.6501, 0.60, CONFIG), "declining")
        self.assertEqual(trend(0.60, None, CONFIG), "flat")

    def test_missing_inputs_lower_confidence_and_never_emit_null_params(self):
        no_intelligence = dataclasses.replace(team_inputs(), runway=None, runway_finding_id=None, intelligence_available=False, overdue=())
        team = team_verdict(dataclasses.replace(no_intelligence, previous_classifiable=0, previous_late=0), CONFIG)
        self.assertEqual(team["confidence"], "low")
        self.assertEqual(team["facts"]["confidence_reasons"], ["no_previous_window", "no_intelligence"])
        self.assertEqual([k["key"] for k in team["kpis"]], ["late_rate", "overdue"])
        self.assertEqual(team["chain"]["conclusion"]["key"], "verdict.team.conclusion.unknown")
        messages = [team["headline"], team["supporting"], *team["chain"].values(), *(k["label"] for k in team["kpis"])]
        self.assertFalse([m for m in messages if None in m["params"].values()])

    def test_the_whole_document_stays_schema_valid_without_intelligence(self):
        data = copy.deepcopy(fixture())
        document = build_verdicts(data["dashboard"], None, data["dashboard"]["generated_at"])
        self.assertEqual(document["team"]["state"], "needs_intervention")
        self.assertEqual(schema_errors(document, "verdict-v1.schema.json"), [])


if __name__ == "__main__":
    unittest.main()
