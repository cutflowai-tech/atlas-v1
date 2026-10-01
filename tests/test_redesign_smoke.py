"""Redesign T0.4: snapshot-level smoke test. The supported site build runs end to end and publishes Editors.

Built from the synthetic contract 1.5 showcase extract through ``profile_cli.build_all`` (the same path as the CLI and, stage by
stage, the production cycle), so the redesign always has a working snapshot to render.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from atlas_commander import profile_cli, site_layout
from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.runtime import load_contract_version

CONTRACT = load_contract_version("1.5.0")


class SnapshotSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="atlas-redesign-smoke-"))
        result = profile_cli.reconstruct_extract(showcase_extract(), CONTRACT)
        cls.doc = profile_cli.build_all(result, CONTRACT, cls.out, GENERATED_AT)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_the_snapshot_builds_and_has_editors(self):
        dashboard = json.loads((self.out / site_layout.DASHBOARD_JSON).read_text())
        self.assertEqual(dashboard, self.doc)
        self.assertGreater(len(dashboard["editors"]), 0)
        for summary in dashboard["editors"]:
            self.assertTrue((self.out / site_layout.profile_json(summary["editor_id"])).is_file())

    def test_every_required_file_exists_in_both_languages(self):
        editor_ids = [s["editor_id"] for s in self.doc["editors"]]
        missing = [name for name in site_layout.required_files(editor_ids, CONTRACT["contract_version"]) if not (self.out / name).is_file()]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
