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
        self.assertTrue(snapshot.live_usable)
        self.assertIn("publication_metadata_inconsistent", snapshot.warnings)

    def test_future_retrieval_is_unknown_and_never_clamped(self):
        snapshot = self.evaluate(-1)
        self.assertEqual((snapshot.freshness_state, snapshot.freshness["age_seconds"]), ("unknown", -1.0))
        self.assertEqual((snapshot.system_state, snapshot.live_usable), ("failed", True))

    def test_unstable_pointer_is_bounded_concurrent_transition(self):
        live = ("ok", self.attempt.attempt_id)
        missing = ("ok", None)
        with mock.patch("atlas_sync.status._pointer_state", side_effect=[live, missing, live, missing]):
            snapshot = status.evaluate_status(config=self.config, clock=lambda: self.retrieved + timedelta(seconds=1))
        self.assertEqual((snapshot.system_state, snapshot.live_usable), ("unknown", False))
        self.assertEqual(snapshot.failure_categories, ["concurrent_transition"])

    def test_full_current_and_history_mismatch_is_degraded_but_usable(self):
        current_path = self.data / "published/CURRENT.json"
        current = json.loads(current_path.read_text())
        for key in ("source_run_id", "build_metadata_sha256", "contract_version", "board_id",
                    "publication_id", "published_at", "current_link", "current_target", "status"):
            current[key] = "wrong"
        current_path.write_text(json.dumps(current))
        history_path = next((self.data / "published/history").glob("*.json"))
        history_path.chmod(0o644)
        history = json.loads(history_path.read_text())
        history["source_run_id"] = "wrong"
        history_path.write_text(json.dumps(history))
        snapshot = self.evaluate()
        self.assertEqual((snapshot.system_state, snapshot.live_usable), ("degraded", True))
        checks = {check.name: check.status for check in snapshot.checks}
        self.assertEqual((checks["current_metadata"], checks["publication_history"]), ("warning", "warning"))

    def test_missing_incomplete_or_tampered_live_build_fails(self):
        (self.build / run.COMPLETE_NAME).unlink()
        incomplete = self.evaluate()
        self.assertEqual((incomplete.system_state, incomplete.failure_categories), ("failed", ["build_not_complete"]))

    def test_missing_current_build_fails(self):
        shutil.rmtree(self.build)
        snapshot = self.evaluate()
        self.assertEqual((snapshot.system_state, snapshot.live_usable), ("failed", False))
        self.assertIn("unknown_attempt", snapshot.failure_categories)

    def test_tampered_artifact_fails_deep_validation(self):
        (self.build / "site/en/dashboard.html").write_text("tampered")
        snapshot = self.evaluate()
        self.assertEqual(snapshot.system_state, "failed")
        self.assertIn("build_tampered", snapshot.failure_categories)

    def test_missing_or_invalid_raw_source_fails(self):
        shutil.rmtree(self.data / "raw/monday" / self.attempt.source_run_id)
        snapshot = self.evaluate()
        self.assertEqual((snapshot.system_state, snapshot.failure_categories), ("failed", ["missing_raw_evidence"]))

    def test_raw_source_failing_production_verification_fails(self):
        raw_run = self.data / "raw/monday" / self.attempt.source_run_id
        raw_file = raw_run / "columns.json"
        raw_file.chmod(0o644)
        raw_file.write_text("{}")
        snapshot = self.evaluate()
        self.assertEqual((snapshot.system_state, snapshot.live_usable), ("failed", False))
        self.assertIn("raw_evidence_invalid", snapshot.failure_categories)

    def test_wrong_contract_board_or_source_relationship_fails(self):
        metadata_path = self.build / run.BUILD_METADATA_NAME
        marker_path = self.build / run.COMPLETE_NAME
        original_metadata, original_marker = metadata_path.read_bytes(), marker_path.read_bytes()
        mutations = {
            "contract": lambda metadata: metadata.__setitem__("contract_version", "1.3.0"),
            "board": lambda metadata: metadata["monday"].__setitem__("board_id", "wrong"),
            "source": lambda metadata: metadata["source"].__setitem__("run_id", "20260101T000000Z-000000000000"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                metadata = json.loads(original_metadata)
                mutate(metadata)
                metadata_path.chmod(0o644)
                metadata_path.write_text(json.dumps(metadata))
                marker = json.loads(original_marker)
                marker["build_metadata_sha256"] = run._sha256(metadata_path.read_bytes())
                marker_path.chmod(0o644)
                marker_path.write_text(json.dumps(marker))
                self.assertEqual(self.evaluate().system_state, "failed")
                metadata_path.write_bytes(original_metadata)
                marker_path.write_bytes(original_marker)

    def test_missing_locale_and_wrong_lang_direction_fail(self):
        page = self.build / "site/ar/dashboard.html"
        original = page.read_text()
        page.unlink()
        self.assertEqual(self.evaluate().system_state, "failed")
        page.write_text(original.replace('dir="rtl"', 'dir="ltr"', 1))
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

    def test_consecutive_failure_threshold_and_success_reset(self):
        attempts = self.data / "builds/attempts"

        def record(number, state):
            attempt_id = f"2099010{number}T000000Z-00000000000{number}"
            (attempts / f"{attempt_id}.json").write_text(json.dumps({
                "attempt_id": attempt_id, "started_at": f"2099-01-0{number}T00:00:00Z",
                "finished_at": f"2099-01-0{number}T00:01:00Z", "status": state,
                "error_category": "timeout" if state == "failed" else None, "source_run_id": None,
            }))

        record(1, "failed")
        one = self.evaluate()
        self.assertEqual((one.system_state, one.live_usable, one.consecutive_failures), ("degraded", True, 1))
        record(2, "failed")
        record(3, "failed")
        threshold = self.evaluate()
        self.assertEqual((threshold.system_state, threshold.live_usable, threshold.consecutive_failures), ("failed", True, 3))
        self.assertIn("consecutive_sync_failures", threshold.failure_categories)
        record(4, "success")
        reset = self.evaluate()
        self.assertEqual((reset.system_state, reset.consecutive_failures), ("healthy", 0))

    def test_success_snapshot_has_all_named_health_checks(self):
        names = {check.name for check in self.evaluate().checks}
        self.assertTrue({"current_pointer", "current_metadata", "publication_history", "build_completion",
                         "build_metadata", "artifact_hashes", "locales", "raw_source", "raw_verification",
                         "provenance", "coverage_chronology"} <= names)

    def test_build_time_snapshot_is_pure_and_has_the_shared_shape(self):
        snapshot = status.build_time_snapshot(
            config=self.config, generated_at=self.meta["attempt"]["profiles_generated_at"],
            attempt_id=self.attempt.attempt_id, source_run_id=self.attempt.source_run_id,
            retrieved_at=self.meta["source"]["retrieved_at"], coverage=self.meta["source"]["coverage"], verified=True,
            started_at=self.attempt.started_at,
        )
        self.assertEqual((snapshot.snapshot_scope, snapshot.system_state, snapshot.live_usable), ("build_time", "unknown", False))
        self.assertEqual((snapshot.last_attempt["attempt_id"], snapshot.last_attempt["status"]),
                         (self.attempt.attempt_id, "running"))
        self.assertEqual(set(snapshot.as_dict()), set(self.evaluate().as_dict()))
        source = (Path(__file__).parents[1] / "src/atlas_sync/status.py").read_text()
        self.assertNotRegex(source, r"from \.run import|import atlas_sync\.run")

    def test_run_once_injects_one_build_time_snapshot_into_both_locales(self):
        site = self.build / run.SITE_DIR
        english = (site / "en/dashboard.html").read_text()
        arabic = (site / "ar/dashboard.html").read_text()
        for page in (english, arabic):
            self.assertIn(f'data-status-value="{self.attempt.attempt_id}"', page)
            self.assertIn(f'data-status-value="{self.attempt.source_run_id}"', page)
            self.assertIn('data-status-value="build_time"', page)
            self.assertIn('data-status-value="unknown"', page)
        self.assertIn("System status", english)
        self.assertIn("حالة النظام", arabic)

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
