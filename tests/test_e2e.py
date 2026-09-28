import json
import subprocess
import unittest

from atlas_commander.contracts import ROOT, assert_valid


class ControlPlaneE2ETests(unittest.TestCase):
    def test_commander_can_plan_first_vertical_slice(self):
        output = subprocess.check_output([str(ROOT / "scripts/atlas"), "ready"], text=True)
        ready = {task["id"] for task in json.loads(output)}
        self.assertIn("DATA-001", ready)
        self.assertIn("METRICS-FIXTURE", ready)

    def test_mock_editor_profile_is_api_compatible(self):
        profile = json.loads((ROOT / "fixtures/good/editor-profile.json").read_text())
        assert_valid(profile, "editor-profile.schema.json")
        self.assertEqual(profile["subject_type"], "editor")


if __name__ == "__main__":
    unittest.main()
