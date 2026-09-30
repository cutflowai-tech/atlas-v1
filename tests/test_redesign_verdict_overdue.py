"""Redesign T2.13: every Editor's open projects past Requested ETA, named for people (Video Type and Monday item ID), never by UUID."""

import copy
import dataclasses
import json
import re
import unittest

from verdict_fixture import editor, fixture, verdicts

from atlas_commander.verdict.engine import build_verdicts, overdue
from atlas_commander.verdict.inputs import Overdue, normalize

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class OverdueListTests(unittest.TestCase):
    def test_michael_refaat_and_mario_have_one_overdue_project_each(self):
        document = verdicts()
        counts = {e["display_name"]: len(e["overdue"]) for e in document["editors"] if e["overdue"]}
        self.assertEqual(counts, {"Michael": 1, "Refaat": 1, "Mario": 1})

    def test_each_project_is_human_readable_with_status_and_source(self):
        (project,) = editor(verdicts(), "Refaat")["overdue"]
        self.assertEqual(project, {"project_id": "3202025538", "status": "Revisions", "source_url": None,
                                   "project_name": {"key": "verdict.project.reference", "params": {"video_type": "Simple Short", "item_id": "3202025538"}},
                                   "requested_eta": "2026-09-25T14:19:56Z", "hours_past_eta": 118.8})
        self.assertIsNone(UUID.search(json.dumps([e["overdue"] for e in verdicts()["editors"]])))

    def test_the_source_link_uses_the_sites_monday_template(self):
        data = fixture()
        document = build_verdicts(data["dashboard"], data["intelligence"], data["dashboard"]["generated_at"],
                                  monday_item_url="https://example.monday.com/boards/1/pulses/{item_id}")
        self.assertEqual(editor(document, "Mario")["overdue"][0]["source_url"], "https://example.monday.com/boards/1/pulses/3248937694")

    def test_without_evidence_records_the_editor_name_still_attributes_and_the_item_id_names_it(self):
        data = copy.deepcopy(fixture())
        for f in data["intelligence"]["findings"]:
            f.pop("supporting_evidence", None)
        document = build_verdicts(data["dashboard"], data["intelligence"], data["dashboard"]["generated_at"])
        (project,) = editor(document, "Michael")["overdue"]
        self.assertEqual(project["project_name"], {"key": "verdict.project.item", "params": {"item_id": "3109734616"}})

    def test_most_overdue_first_and_counted_in_the_tier(self):
        data = fixture()
        refaat = next(e for e in normalize(data["dashboard"], data["intelligence"])[0] if e.display_name == "Refaat")
        two = dataclasses.replace(refaat, overdue=(*refaat.overdue, Overdue("3300000000", "In Progress", "2026-09-29T09:00:00Z", 300.0, "Simple Short")))
        self.assertEqual([p["project_id"] for p in overdue(two, None)], ["3300000000", "3202025538"])
        self.assertEqual(editor(verdicts(), "Mario")["tier"], "watch")          # overdue open work places Mario in Watch (§3)


if __name__ == "__main__":
    unittest.main()
