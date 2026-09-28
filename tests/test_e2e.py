import json
import subprocess
import unittest

from atlas_commander.contracts import ROOT, assert_valid


class ControlPlaneE2ETests(unittest.TestCase):
    def test_commander_can_plan_first_vertical_slice(self):
        output = subprocess.check_output([str(ROOT / "scripts/atlas"), "ready"], text=True)
        ready = {task["id"] for task in json.loads(output)}
        dag = {task["id"]: task for task in json.loads((ROOT / "tasks" / "dag.json").read_text())["tasks"]}
        # The first vertical slice's fixture tasks are done; blocked tasks never enter the ready queue.
        self.assertEqual({"DATA-001", "METRICS-FIXTURE"} & ready, set())
        self.assertTrue(all(dag[task_id]["status"] in {"todo", "ready"} for task_id in ready))
        self.assertEqual(dag["E2E-001"]["status"], "blocked")

    def test_mock_editor_profile_is_api_compatible(self):
        profile = json.loads((ROOT / "fixtures/good/editor-profile.json").read_text())
        assert_valid(profile, "editor-profile.schema.json")
        self.assertEqual(profile["subject_type"], "editor")


if __name__ == "__main__":
    unittest.main()
