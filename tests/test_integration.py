import json
import unittest

from atlas_commander.contracts import ROOT, assert_valid


class FixturePipelineIntegrationTests(unittest.TestCase):
    def test_fixture_events_form_declared_cycle(self):
        fixture = ROOT / "fixtures/good"
        start = json.loads((fixture / "status-in-progress.json").read_text())
        end = json.loads((fixture / "status-ready.json").read_text())
        cycle = json.loads((fixture / "work-cycle.json").read_text())
        assert_valid(start, "normalized-status-event.schema.json")
        assert_valid(end, "normalized-status-event.schema.json")
        assert_valid(cycle, "work-cycle.schema.json")
        self.assertEqual((start["event_id"], end["event_id"]), (cycle["in_progress_event_id"], cycle["ready_for_approval_event_id"]))
        self.assertEqual((start["to_status"], end["to_status"]), ("In Progress", "Ready For Approval"))

    def test_metric_evidence_resolves_to_cycle_events(self):
        fixture = ROOT / "fixtures/good"
        cycle = json.loads((fixture / "work-cycle.json").read_text())
        speed = json.loads((fixture / "speed-metric.json").read_text())
        assert_valid(speed, "speed-metric.schema.json")
        self.assertEqual(set(speed["evidence"]["event_ids"]), {cycle["in_progress_event_id"], cycle["ready_for_approval_event_id"]})
        self.assertEqual(speed["evidence"]["monday_item_id"], cycle["monday_item_id"])


if __name__ == "__main__":
    unittest.main()
