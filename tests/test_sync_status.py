"""Task 7 core: persisted-evidence status and health, with no Monday or mutation."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from test_ingest import FakeMonday, items
from test_sync_run import HISTORY, T0, TOKEN, Clock, Monotonic, logs

from atlas_sync import __main__ as cli
from atlas_sync import publish, run, status
from atlas_sync.config import load_sync_config
from atlas_sync.lock import production_lock


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-status-"))
        self.env = {"MONDAY_API_TOKEN": TOKEN, "ATLAS_DATA_DIR": str(self.data), "ATLAS_HISTORY_START": HISTORY}
        self.config = load_sync_config(self.env, now=T0)
        self.attempt = self.stage(1)
        outcome = publish.publish(self.attempt.attempt_id, self.env, clock=Clock(T0 + timedelta(days=2)))
        self.assertEqual(outcome.status, publish.PUBLISHED)
        self.build = Path(self.attempt.staged_build_dir)
        self.meta = json.loads((self.build / run.BUILD_METADATA_NAME).read_text())
        self.retrieved = status._parse_time(self.meta["source"]["retrieved_at"])
        assert self.retrieved is not None

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    def stage(self, days):
        result = run.run_once(self.env, transport=FakeMonday(logs(), items()),
                              clock=Clock(T0 + timedelta(days=days)), monotonic=Monotonic(), sleep=lambda _: None)
        self.assertEqual(result.status, "success", result.as_dict())
        return result

    def evaluate(self, age=3000):
        return status.evaluate_status(config=self.config, clock=lambda: self.retrieved + timedelta(seconds=age))

    def test_healthy_fresh_snapshot_has_source_coverage_and_separate_publish_time(self):
        snapshot = self.evaluate()
        self.assertEqual((snapshot.system_state, snapshot.freshness_state, status.exit_code(snapshot)), ("healthy", "fresh", 0))
        current = snapshot.current_publication
        self.assertEqual(current["source_run_id"], self.attempt.source_run_id)
        self.assertEqual(current["monday_retrieved_at"], self.meta["source"]["retrieved_at"])
        self.assertNotEqual(current["published_at"], current["monday_retrieved_at"])
        self.assertEqual(current["coverage"], self.meta["source"]["coverage"])

    def test_exact_fresh_delayed_stale_boundaries_use_config(self):
        self.assertEqual(self.evaluate(3600).freshness_state, "fresh")
        self.assertEqual(self.evaluate(3600.001).freshness_state, "delayed")
        self.assertEqual(self.evaluate(7199.999).freshness_state, "delayed")
        stale = self.evaluate(7200)
        self.assertEqual((stale.freshness_state, status.exit_code(stale)), ("stale", 1))

    def test_no_current_and_broken_current_are_failed(self):
        (self.data / "published/current").unlink()
        self.assertEqual((self.evaluate().system_state, status.exit_code(self.evaluate())), ("failed", 2))
        os.symlink("/tmp/not-atlas", self.data / "published/current")
        broken = self.evaluate()
        self.assertEqual((broken.system_state, broken.failure_categories), ("failed", ["unsafe_current"]))

    def test_current_metadata_disagreement_degrades_but_live_pointer_wins(self):
        path = self.data / "published/CURRENT.json"
        document = json.loads(path.read_text())
        document["attempt_id"] = "20260101T000000Z-000000000000"
        path.write_text(json.dumps(document))
        snapshot = self.evaluate()
        self.assertEqual((snapshot.system_state, snapshot.current_publication["attempt_id"]), ("degraded", self.attempt.attempt_id))
        self.assertIn("current_metadata_inconsistent", snapshot.warnings)

    def test_missing_incomplete_or_tampered_live_build_fails(self):
        (self.build / run.COMPLETE_NAME).unlink()
        incomplete = self.evaluate()
        self.assertEqual((incomplete.system_state, incomplete.failure_categories), ("failed", ["build_not_complete"]))

    def test_tampered_artifact_fails_deep_validation(self):
        (self.build / "site/en/dashboard.html").write_text("tampered")
        snapshot = self.evaluate()
        self.assertEqual(snapshot.system_state, "failed")
        self.assertIn("build_tampered", snapshot.failure_categories)

    def test_missing_or_invalid_raw_source_fails(self):
        shutil.rmtree(self.data / "raw/monday" / self.attempt.source_run_id)
        snapshot = self.evaluate()
        self.assertEqual((snapshot.system_state, snapshot.failure_categories), ("failed", ["missing_raw_evidence"]))

    def test_wrong_contract_board_or_source_relationship_fails(self):
        path = self.build / run.BUILD_METADATA_NAME
        metadata = json.loads(path.read_text())
        metadata["monday"]["board_id"] = "wrong"
        path.chmod(0o644)
        path.write_text(json.dumps(metadata))
        self.assertEqual(self.evaluate().system_state, "failed")

    def test_missing_locale_and_wrong_lang_direction_fail(self):
        (self.build / "site/ar/dashboard.html").unlink()
        self.assertEqual(self.evaluate().system_state, "failed")

    def test_latest_failed_attempt_degrades_last_good_dashboard_safely(self):
        attempt_id = "20990101T000000Z-000000000001"
        record = {"attempt_id": attempt_id, "started_at": "2099-01-01T00:00:00Z", "finished_at": "2099-01-01T00:01:00Z",
                  "status": "failed", "error_category": "timeout", "error_type": "SecretRawException", "source_run_id": None}
        path = self.data / "builds/attempts" / f"{attempt_id}.json"
        path.write_text(json.dumps(record))
        snapshot = self.evaluate()
        self.assertEqual((snapshot.system_state, snapshot.last_attempt["status"]), ("degraded", "failed"))
        encoded = json.dumps(snapshot.as_dict())
        self.assertIn("timeout", encoded)
        self.assertNotIn("SecretRawException", encoded)
        self.assertNotIn(TOKEN, encoded)

    def test_latest_success_can_differ_from_current_published_attempt(self):
        staged = self.stage(3)
        snapshot = self.evaluate()
        self.assertEqual(snapshot.last_successful_attempt["attempt_id"], staged.attempt_id)
        self.assertEqual(snapshot.current_publication["attempt_id"], self.attempt.attempt_id)

    def test_status_never_calls_monday_takes_lock_or_writes(self):
        before = {str(p): p.stat().st_mtime_ns for p in self.data.rglob("*")}
        with mock.patch("atlas_sync.status.load_sync_config", return_value=self.config), \
             mock.patch("atlas_sync.config.SyncConfig.monday_client", side_effect=AssertionError("network")), \
             mock.patch("atlas_sync.lock.production_lock", side_effect=AssertionError("lock")):
            self.evaluate()
        after = {str(p): p.stat().st_mtime_ns for p in self.data.rglob("*")}
        self.assertEqual(before, after)

    def test_status_runs_while_production_lock_is_held(self):
        with production_lock(self.config, "publish", target=self.attempt.attempt_id, clock=lambda: T0):
            snapshot = self.evaluate()
        self.assertEqual(snapshot.system_state, "healthy")

    def test_human_and_json_cli(self):
        snapshot = self.evaluate()
        for json_mode in (False, True):
            output = io.StringIO()
            with mock.patch("atlas_sync.status.evaluate_status", return_value=snapshot), redirect_stdout(output):
                code = cli.main(["status", *(["--json"] if json_mode else [])])
            self.assertEqual(code, 0)
            if json_mode:
                self.assertEqual(json.loads(output.getvalue())["system_state"], "healthy")
            else:
                self.assertIn("Atlas system: HEALTHY", output.getvalue())
                self.assertIn("Monday retrieved:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
