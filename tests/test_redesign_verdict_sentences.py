"""Redesign T2.12: every Editor's headline and 2–4 reasons are message keys chosen by tier and the strongest fact (spec §6).

The snapshot ``fixtures/verdict/september-2026.sentences.json`` pins the output for the §9 fixture. After an intended change, rewrite
it with ``PYTHONPATH=src:tests python3 tests/test_redesign_verdict_sentences.py --write`` and review the diff.
"""

import json
import sys
import unittest
from pathlib import Path

from verdict_fixture import editor, verdicts

from atlas_commander.verdict.config import load_config

CONFIG = load_config()
SNAPSHOT = Path(__file__).resolve().parents[1] / "fixtures" / "verdict" / "september-2026.sentences.json"


def sentences(document):
    return {e["display_name"]: {"tier": e["tier"], "headline": e["headline"], "reasons": e["reasons"]} for e in document["editors"]}


class HeadlineTests(unittest.TestCase):
    def test_every_editor_has_a_headline_key_and_two_to_four_reasons(self):
        for e in verdicts()["editors"]:
            self.assertTrue(e["headline"]["key"].startswith(f"verdict.headline.{e['tier']}."), e["display_name"])
            self.assertGreaterEqual(len(e["reasons"]), CONFIG["display.reasons_min"], e["display_name"])
            self.assertLessEqual(len(e["reasons"]), CONFIG["display.reasons_max"], e["display_name"])
            self.assertTrue(all(r["key"].startswith("verdict.reason.") for r in e["reasons"]), e["display_name"])
            self.assertEqual(len({json.dumps(r, sort_keys=True) for r in e["reasons"]}), len(e["reasons"]), e["display_name"])

    def test_the_spec_templates(self):
        document = verdicts()
        refaat = editor(document, "Refaat")                            # weakest + runway_not_explaining, slower than peers and himself
        self.assertEqual(refaat["headline"], {"key": "verdict.headline.weakest.not_scheduling_slower_self",
                                              "params": {"late_pct": 85.7, "speed_pct": 43.0, "own_pct": 26.3}})
        self.assertEqual(refaat["reasons"][0]["key"], "verdict.reason.runway_not_explaining")
        self.assertEqual(editor(document, "Anas")["headline"]["key"], "verdict.headline.steady.mirrors_team")   # "the improvement matches the whole team"
        self.assertEqual(editor(document, "Will")["headline"]["key"], "verdict.headline.best.faster")         # 24 > 22: Ibrahim has the highest load
        self.assertEqual(editor(document, "Samra")["headline"], {"key": "verdict.headline.low_activity.zero_activity", "params": {"lifetime_completed": 60}})
        self.assertEqual(editor(document, "Mario")["headline"], {"key": "verdict.headline.watch.overdue", "params": {"count": 1}})

    def test_the_strongest_fact_leads_the_reasons(self):
        document = verdicts()
        self.assertEqual(editor(document, "Anas")["reasons"][0]["key"], "verdict.reason.mirrors_team_late_rate")
        self.assertEqual(editor(document, "Sobhy")["reasons"][0]["key"], "verdict.reason.late_above_team")
        self.assertEqual(editor(document, "Mario")["reasons"][0]["key"], "verdict.reason.overdue_open")
        self.assertEqual(editor(document, "Will")["reasons"][0]["key"], "verdict.reason.volume_above_median")

    def test_a_mirrored_change_is_not_cited_as_the_editors_own(self):
        anas = editor(verdicts(), "Anas")
        keys = [r["key"] for r in anas["reasons"]]
        self.assertNotIn("verdict.reason.faster_than_own_history", keys)
        self.assertNotIn("verdict.reason.slower_than_own_history", keys)

    def test_output_matches_the_snapshot(self):
        self.assertEqual(sentences(verdicts()), json.loads(SNAPSHOT.read_text(encoding="utf-8")))


if __name__ == "__main__":
    if "--write" in sys.argv:
        SNAPSHOT.write_text(json.dumps(sentences(verdicts()), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {SNAPSHOT}")
    else:
        unittest.main()
