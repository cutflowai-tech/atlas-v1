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
    def test_only_in_progress_work_counts_as_overdue(self):
        # D55: Michael's and Refaat's items are in Revisions, past the ETA the shared account reset on entry (D19): revision
        # context, never overdue work held against the Editor (D31). Mario's item is In Progress.
        document = verdicts()
        counts = {e["display_name"]: len(e["overdue"]) for e in document["editors"] if e["overdue"]}
        self.assertEqual(counts, {"Mario": 1})
        self.assertEqual(editor(document, "Refaat")["tier"], "weakest")   # still Weakest, on its late rate alone

    def test_each_project_is_human_readable_with_status_and_source(self):
        (project,) = editor(verdicts(), "Mario")["overdue"]
        self.assertEqual(project, {"project_id": "3248937694", "status": "In Progress", "source_url": None,
                                   "project_name": {"key": "verdict.project.reference", "params": {"video_type": "Premium Short", "item_id": "3248937694"}},
                                   "requested_eta": "2026-09-30T09:00:00Z", "hours_past_eta": 4.2})
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
        (project,) = editor(document, "Mario")["overdue"]
        self.assertEqual(project["project_name"], {"key": "verdict.project.item", "params": {"item_id": "3248937694"}})

    def test_most_overdue_first_and_counted_in_the_tier(self):
        data = fixture()
        refaat = next(e for e in normalize(data["dashboard"], data["intelligence"])[0] if e.display_name == "Refaat")
        two = dataclasses.replace(refaat, overdue=(Overdue("3300000001", "In Progress", "2026-09-30T09:00:00Z", 20.0, "Simple Short"),
                                                   Overdue("3300000000", "In Progress", "2026-09-29T09:00:00Z", 300.0, "Simple Short")))
        self.assertEqual([p["project_id"] for p in overdue(two, None)], ["3300000000", "3300000001"])
        self.assertEqual(editor(verdicts(), "Mario")["tier"], "watch")          # overdue open work places Mario in Watch (§3)


if __name__ == "__main__":
    unittest.main()
