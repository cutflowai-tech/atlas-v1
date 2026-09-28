import json
import unittest
from pathlib import Path

from atlas_commander.core import ROOT, assignments_for, classify, ready_tasks, slots_for


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
        self.assertIn("monday_board_id", schema["required"])
        evidence_required = schema["properties"]["evidence"]["required"]
        for field in ("column_ids", "event_ids", "source_timestamps", "source_values"):
            self.assertIn(field, evidence_required)

    def test_critical_routing_is_cross_family(self):
        assignments = assignments_for("critical")
        builder_families = {item["family"] for item in assignments if item["slot"].startswith("builder-")}
        validator_families = {item["family"] for item in assignments if item["slot"].startswith("validator-")}
        self.assertEqual(builder_families, {"codex", "claude"})
        self.assertEqual(validator_families, {"codex", "claude"})

    def test_all_dag_entries_satisfy_task_contract(self):
        tasks = json.loads((ROOT / "tasks" / "dag.json").read_text())["tasks"]
        required = {"id", "title", "risk", "status", "depends_on", "acceptance_tests", "evidence_requirements", "affected_contracts", "contract_owner_gate"}
        for task in tasks:
            self.assertFalse(required - set(task), task["id"])

    def test_done_dependency_is_not_ready_itself(self):
        self.assertEqual(ready_tasks(), [])


if __name__ == "__main__":
    unittest.main()
