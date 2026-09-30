"""Redesign T2.14: the decisions of spec §7, with stable IDs, in priority order, capped on the overview."""

import copy
import unittest

from verdict_fixture import editor, fixture, verdicts

from atlas_commander.verdict.config import load_config
from atlas_commander.verdict.engine import build_verdicts

CONFIG = load_config()


def build(data):
    return build_verdicts(data["dashboard"], data["intelligence"], data["dashboard"]["generated_at"])


class DecisionsTests(unittest.TestCase):
    def test_the_fixture_decisions_in_spec_order(self):
        document = verdicts()
        names = {e["editor_id"]: e["display_name"] for e in document["editors"]}
        rows = [(d["horizon"], d["type"], [names[i] for i in d["owner_editor_ids"]], d["owner_role"]) for d in document["decisions"]]
        self.assertEqual(rows, [
            ("today", "overdue_open_work", ["Refaat", "Michael", "Mario"], None),          # the most overdue first
            ("this_week", "weakest_editor", ["Refaat"], "editors_manager"),
            ("this_week", "scheduling_runway", [], "scheduling_owner"),
            ("ask", "low_activity", ["Ahmed", "Michael", "Mohamed Mansour (Office)", "Samra"], None),
            ("management", "approve_rule", [], "ceo"),
        ])
        self.assertEqual([d["priority"] for d in document["decisions"]], [1, 2, 3, 4, 5])

    def test_today_lists_the_three_overdue_projects(self):
        today = verdicts()["decisions"][0]
        self.assertEqual(today["title"], {"key": "verdict.decision.overdue_open_work", "params": {"count": 3, "names": ["Refaat", "Michael", "Mario"]}})
        self.assertEqual([m["params"]["item_id"] for m in today["evidence"]], ["3202025538", "3109734616", "3248937694"])   # most overdue first
        self.assertEqual(today["confidence"], "high")

    def test_weakest_and_scheduling_carry_their_evidence(self):
        document = verdicts()
        refaat = editor(document, "Refaat")
        plan = document["decisions"][1]
        self.assertEqual((plan["evidence"], plan["confidence"], plan["target"]), (refaat["reasons"], refaat["confidence"], f"editor:{refaat['editor_id']}"))
        scheduling = document["decisions"][2]
        self.assertEqual(scheduling["title"]["params"], {"short_share_pct": 77.4})     # 328 of 424 >= 50%
        self.assertEqual(scheduling["evidence"][0]["params"]["short_runway_late"], 328)

    def test_ids_are_stable_and_follow_the_subject(self):
        first, second = verdicts()["decision_candidates"], verdicts()["decision_candidates"]
        self.assertEqual([d["id"] for d in first], [d["id"] for d in second])
        self.assertEqual(len({d["id"] for d in first}), len(first))
        data = copy.deepcopy(fixture())
        data["dashboard"]["generated_at"] = "2026-10-01T00:00:00Z"                     # a rebuild of the same facts
        self.assertEqual([d["id"] for d in build(data)["decision_candidates"]], [d["id"] for d in first])

    def test_the_overview_shows_at_most_the_cap_and_every_candidate_stays(self):
        data = copy.deepcopy(fixture())
        for e in data["dashboard"]["editors"]:                                       # make Will and Anas late too: three Weakest
            if e["display_name"] in ("Will", "Anas"):
                facts = e["interpretation"]["components"]["deadline"]["facts"]
                facts.update(late=facts["deadline_classifiable_projects"], absolute_late_rate=1.0)
        document = build(data)
        cap = int(CONFIG["decisions.overview_max"])
        self.assertEqual(len(document["decisions"]), cap)
        self.assertGreater(len(document["decision_candidates"]), cap)
        self.assertEqual(document["decisions"], document["decision_candidates"][:cap])
        weakest = [d for d in document["decision_candidates"] if d["type"] == "weakest_editor"]
        ranks = [editor(document, n)["rank"] for n in (d["title"]["params"]["name"] for d in weakest)]
        self.assertEqual(ranks, sorted(ranks, reverse=True))                           # the lowest-ranked Weakest first

    def test_nothing_to_decide_means_no_decision(self):
        data = copy.deepcopy(fixture())
        data["intelligence"] = None
        for e in data["dashboard"]["editors"]:
            e["interpretation"]["components"]["quality"]["rule_status"] = "approved"
            e["interpretation"]["components"]["quality"]["facts"]["negative_rate"] = 0.1
        types = {d["type"] for d in build(data)["decision_candidates"]}
        self.assertNotIn("overdue_open_work", types)                                   # no Intelligence: no overdue list, no runway split
        self.assertNotIn("scheduling_runway", types)
        self.assertNotIn("approve_rule", types)


if __name__ == "__main__":
    unittest.main()
