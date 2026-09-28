import json
import unittest

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

    def test_contract_requires_requested_eta_for_deadline(self):
        schema = json.loads((ROOT / "contracts" / "work-cycle.schema.json").read_text())
        self.assertIn("requested_eta", schema["properties"])
        self.assertIn("in_progress_at", schema["required"])
        self.assertIn("ready_for_approval_at", schema["required"])

    def test_critical_routing_is_cross_family(self):
        assignments = assignments_for("critical")
        builder_families = {item["family"] for item in assignments if item["slot"].startswith("builder-")}
        validator_families = {item["family"] for item in assignments if item["slot"].startswith("validator-")}
        self.assertEqual(builder_families, {"codex", "claude"})
        self.assertEqual(validator_families, {"codex", "claude"})

    def test_all_routes_reference_registered_enabled_runtimes(self):
        registered = {
            item["name"]
            for item in json.loads((ROOT / "config" / "runtimes.json").read_text())["runtimes"]
            if item["enabled"]
        }
        for risk in ("simple", "normal", "critical"):
            for assignment in assignments_for(risk):
                self.assertIn(assignment["runtime"], registered)
                self.assertTrue(assignment["agent"])

    def test_five_subscription_profiles_are_distinct(self):
        runtimes = json.loads((ROOT / "config" / "runtimes.json").read_text())["runtimes"]
        self.assertEqual({item["id"] for item in runtimes}, {"codex-a", "codex-m", "codex-w", "claude-a", "claude-m"})
        self.assertEqual(len({item["multica_runtime_id"] for item in runtimes}), 5)
        self.assertEqual(len({item["multica_profile_id"] for item in runtimes}), 5)
        self.assertTrue(all(item["subscription_backed"] and item["enabled"] for item in runtimes))

    def test_policy_counts_match_requested_routes(self):
        policy = json.loads((ROOT / "config" / "risk-policy.json").read_text())
        self.assertEqual((policy["simple"]["builders"], policy["simple"]["reviewers"]), (1, 1))
        self.assertEqual((policy["normal"]["builders"], policy["normal"]["reviewers"]), (2, 1))
        self.assertEqual((policy["critical"]["builders"], policy["critical"]["validators"]), (3, 2))
        self.assertTrue(policy["critical"]["requires_arbiter"])
        self.assertTrue(policy["critical"]["requires_cross_family"])

    def test_event_evidence_cannot_be_empty(self):
        schema = json.loads((ROOT / "contracts" / "common.schema.json").read_text())
        event_ids = schema["$defs"]["evidence"]["properties"]["event_ids"]
        self.assertEqual(event_ids["minItems"], 1)

    def test_all_dag_entries_satisfy_task_contract(self):
        tasks = json.loads((ROOT / "tasks" / "dag.json").read_text())["tasks"]
        required = {"id", "title", "risk", "status", "depends_on", "acceptance_tests", "evidence_requirements", "affected_contracts", "contract_owner_gate"}
        for task in tasks:
            self.assertFalse(required - set(task), task["id"])

    def test_ready_queue_maximizes_fixture_parallelism(self):
        ready_ids = {task["id"] for task in ready_tasks()}
        # Every fixture task is done; the remaining tasks are blocked on the live token or on business decisions.
        self.assertEqual(ready_ids, set())
        tasks = {task["id"]: task for task in json.loads((ROOT / "tasks" / "dag.json").read_text())["tasks"]}
        self.assertTrue(all(tasks[task_id]["blocked_by"] for task_id in ("E2E-001", "ID-002")))

    def test_no_composite_scoring_task_exists(self):
        tasks = json.loads((ROOT / "tasks" / "dag.json").read_text())["tasks"]
        titles = " ".join(task["title"].lower() for task in tasks)
        self.assertNotIn("composite score", titles)


if __name__ == "__main__":
    unittest.main()
