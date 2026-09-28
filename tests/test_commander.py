import json
import unittest
from pathlib import Path

from atlas_commander.core import ROOT, classify, ready_tasks, slots_for


class CommanderTests(unittest.TestCase):
    def test_risk_classification(self):
        self.assertEqual(classify(set()), "simple")
        self.assertEqual(classify({"multi_component"}), "normal")
        self.assertEqual(classify({"business_rules"}), "critical")
        self.assertEqual(classify({"schema"}), "critical")

    def test_routing_shape(self):
        self.assertEqual(slots_for("simple"), ["builder-1", "reviewer-1", "integrator"])
        self.assertEqual(slots_for("normal"), ["builder-1", "builder-2", "reviewer-1", "arbiter", "integrator"])
        self.assertEqual(
            slots_for("critical"),
            ["builder-1", "builder-2", "builder-3", "validator-1", "validator-2", "arbiter", "integrator"],
        )

    def test_contract_keeps_deadline_and_eta_separate(self):
        schema = json.loads((ROOT / "contracts" / "atlas-v1.schema.json").read_text())
        self.assertIn("deadline", schema["properties"])
        self.assertIn("requested_eta", schema["properties"])
        self.assertEqual(schema["properties"]["evidence"]["properties"]["source"]["const"], "monday")

    def test_done_dependency_is_not_ready_itself(self):
        self.assertEqual(ready_tasks(), [])


if __name__ == "__main__":
    unittest.main()

