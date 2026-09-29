"""Conservative deterministic bounded-retention behavior (filesystem only; no Monday access)."""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from atlas_sync import lock, retention, scheduled, status
from atlas_sync.config import load_sync_config

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
CURRENT = "20261001T120000Z-aaaaaaaaaaaa"
ROLLBACK = "20261002T120000Z-bbbbbbbbbbbb"
EXPIRED = "20261003T120000Z-cccccccccccc"
UNPUBLISHED = "20261004T120000Z-ffffffffffff"
BOUNDARY = "20261006T120000Z-dddddddddddd"
RECENT = "20261006T120001Z-eeeeeeeeeeee"


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-retention-"))
        self.config = load_sync_config({"ATLAS_DATA_DIR": str(self.data)}, now=NOW)

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    def add(self, attempt, source=None, *, state="complete", attempt_status="success", raw=True):
        source = source or attempt
        if raw:
            raw_dir = self.config.raw_dir / source
            raw_dir.mkdir(parents=True)
            (raw_dir / "manifest.json").write_text(json.dumps({"run": {"run_id": source}}))
            (raw_dir / "evidence.bin").write_bytes(b"evidence")
        attempts = self.config.build_dir / "attempts"
        attempts.mkdir(parents=True, exist_ok=True)
        record = {"attempt_id": attempt, "status": attempt_status, "source_run_id": source,
                  "raw_run_dir": str(self.config.raw_dir.resolve() / source)}
        (attempts / f"{attempt}.json").write_text(json.dumps(record))
        build = self.config.build_dir / attempt
        (build / "site").mkdir(parents=True)
        metadata = {"attempt": {"attempt_id": attempt},
                    "source": {"run_id": source, "raw_run_dir": str(self.config.raw_dir.resolve() / source)}}
        (build / "build.json").write_text(json.dumps(metadata))
        if state == "complete":
            (build / "COMPLETE.json").write_text("{}")
        elif state == "failed":
            (build / "FAILED.json").write_text("{}")
        return build

    def history(self, sequence, publication_id, attempt, *, switched=True):
        root = self.config.publish_dir / "history"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{sequence:06d}-{publication_id}.json"
        path.write_text(json.dumps({"publication_id": publication_id, "sequence": sequence,
                                    "attempt_id": attempt, "switched": switched}))
        return path

    def make_current(self, attempt, publication_id):
        self.config.publish_dir.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(self.config.build_dir / attempt / "site", self.config.publish_dir),
                   self.config.publish_dir / "current")
        (self.config.publish_dir / "CURRENT.json").write_text(json.dumps({
            "attempt_id": attempt, "publication_id": publication_id,
        }))

    def clean(self, *, dry_run=False):
        return retention.cleanup(config=self.config, dry_run=dry_run, clock=lambda: NOW)

    def test_current_default_rollback_and_transitive_raw_sources_are_kept(self):
        for attempt in (CURRENT, ROLLBACK, EXPIRED, UNPUBLISHED):
            self.add(attempt)
        current_pub = "20261001T130000Z-111111111111"
        rollback_pub = "20261002T130000Z-222222222222"
        expired_pub = "20261003T130000Z-333333333333"
        self.history(1, expired_pub, EXPIRED)
        self.history(2, rollback_pub, ROLLBACK)
        self.history(3, current_pub, CURRENT)
        self.make_current(CURRENT, current_pub)

        report = self.clean()
        self.assertEqual(report.status, "completed")
        for attempt in (CURRENT, ROLLBACK, EXPIRED):
            self.assertTrue((self.config.build_dir / attempt).exists())
            self.assertTrue((self.config.raw_dir / attempt).exists())
            self.assertTrue((self.config.build_dir / "attempts" / f"{attempt}.json").exists())
        for path in (self.config.build_dir / UNPUBLISHED, self.config.raw_dir / UNPUBLISHED,
                     self.config.build_dir / "attempts" / f"{UNPUBLISHED}.json"):
            self.assertFalse(path.exists(), path)
        self.assertEqual(report.deleted["raw_runs"]["count"], 1)
        self.assertEqual(report.protected_reasons["builds"]["current_publication"], 1)
        self.assertEqual(report.protected_reasons["builds"]["default_rollback_target"], 1)
        self.assertEqual(report.protected_reasons["builds"]["explicit_rollback_authorized"], 3)

    def test_age_boundary_failed_runs_dry_run_and_idempotence(self):
        self.add(BOUNDARY, state="failed", attempt_status="failed")
        self.add(RECENT, state="failed", attempt_status="failed")
        before = sum(path.stat().st_size for path in self.data.rglob("*") if path.is_file())
        preview = self.clean(dry_run=True)
        self.assertTrue((self.config.build_dir / BOUNDARY).exists())
        self.assertGreater(preview.eligible["builds"]["bytes"], 0)
        self.assertGreaterEqual(before, preview.eligible["builds"]["bytes"])

        first = self.clean()
        self.assertFalse((self.config.build_dir / BOUNDARY).exists())  # age == 96h is eligible
        self.assertTrue((self.config.build_dir / RECENT).exists())
        second = self.clean()
        self.assertEqual(sum(value["count"] for value in second.deleted.values()), 0)
        self.assertEqual(first.deleted["raw_runs"]["count"], 1)

    def test_incomplete_corrupt_traversal_absolute_symlink_and_unknown_objects_are_protected(self):
        incomplete = self.add(EXPIRED, state="incomplete", attempt_status="failed")
        (incomplete / "link").symlink_to("/tmp")
        record_path = self.config.build_dir / "attempts" / f"{EXPIRED}.json"
        record = json.loads(record_path.read_text())
        record["raw_run_dir"] = "/outside/raw"
        record_path.write_text(json.dumps(record))
        (self.config.raw_dir / "unknown.txt").write_text("leave me")
        (self.config.publish_dir / "history").mkdir(parents=True)
        (self.config.publish_dir / "history" / "garbage.json").write_text("not json")

        report = self.clean()
        self.assertTrue(incomplete.exists())
        self.assertTrue(record_path.exists())
        self.assertTrue((self.config.raw_dir / EXPIRED).exists())
        self.assertTrue((self.config.raw_dir / "unknown.txt").exists())
        self.assertIn("unknown_or_unsafe_raw_object", report.failures)
        self.assertIn("active_incomplete_or_corrupt", report.protected_reasons["builds"])
        self.assertIn("unsafe_source_reference", report.protected_reasons["attempt_records"])

    def test_active_and_corrupt_scheduled_cycles_are_kept_terminal_old_cycle_is_removed(self):
        root = self.config.lock_dir / "scheduled-cycles"
        root.mkdir(parents=True)
        old = EXPIRED
        active = ROLLBACK
        corrupt = CURRENT
        for suffix, phase in (("started", "started"), ("outcome", "outcome"), (None, "final")):
            name = f"{old}.{suffix}.json" if suffix else f"{old}.json"
            (root / name).write_text(json.dumps({"cycle_id": old, "record_phase": phase}))
        (root / f"{active}.started.json").write_text(json.dumps({"cycle_id": active, "record_phase": "started"}))
        (root / f"{corrupt}.outcome.json").write_text("bad")

        report = self.clean()
        self.assertFalse(any(root.glob(f"{old}*.json")))
        self.assertTrue((root / f"{active}.started.json").exists())
        self.assertTrue((root / f"{corrupt}.outcome.json").exists())
        self.assertEqual(report.deleted["scheduled_cycles"]["count"], 1)

    def test_public_entry_point_obeys_lock_and_cleanup_failure_never_changes_publication_result(self):
        with lock.production_lock(self.config, "publish", clock=lambda: NOW):
            blocked = self.clean(dry_run=True)
        self.assertEqual((blocked.status, retention.exit_code(blocked)), ("locked", 75))

        result = scheduled.ScheduledResult("20261010T120000Z-111111111111", "2026-10-10T12:00:00Z",
                                           status=scheduled.PUBLISHED)
        snapshot = status.StatusSnapshot("2026-10-10T12:00:00Z", "runtime", "healthy", "fresh", True,
                                         None, None, None, {})
        with mock.patch.object(scheduled, "_actual_live", return_value=CURRENT), \
             mock.patch.object(scheduled, "_evaluate_status", return_value=snapshot), \
             mock.patch.object(scheduled, "_record_outcome", return_value=Path("outcome")), \
             mock.patch.object(scheduled.alerts, "update_alert_state", side_effect=OSError()), \
             mock.patch.object(scheduled, "_record_final", return_value=Path("final")), \
             mock.patch.object(retention, "_cleanup_locked", side_effect=OSError("disk")):
            completed = scheduled._complete(result, self.config, lambda: NOW)
        # Alert persistence has its own existing semantics, but retention itself cannot overwrite publication outcome.
        self.assertTrue(completed.switched is False)
        self.assertEqual(completed.retention, {"status": "failed", "failures": ["retention_failed"]})
        self.assertEqual(completed.resulting_live_attempt, CURRENT)

        successful = scheduled.ScheduledResult("20261010T120000Z-222222222222", "2026-10-10T12:00:00Z",
                                               status=scheduled.PUBLISHED)
        alert_update = mock.Mock(consecutive_scheduled_failures=0, active_incidents=[])
        with mock.patch.object(scheduled, "_actual_live", return_value=CURRENT), \
             mock.patch.object(scheduled, "_evaluate_status", return_value=snapshot), \
             mock.patch.object(scheduled, "_record_outcome", return_value=Path("outcome")), \
             mock.patch.object(scheduled.alerts, "update_alert_state", return_value=alert_update), \
             mock.patch.object(scheduled, "_record_final", return_value=Path("final")), \
             mock.patch.object(retention, "_cleanup_locked", side_effect=OSError("disk")):
            retained_publication = scheduled._complete(successful, self.config, lambda: NOW)
        self.assertEqual((retained_publication.status, scheduled.exit_code(retained_publication)),
                         (scheduled.PUBLISHED, 0))
        self.assertEqual(retained_publication.retention, {"status": "failed", "failures": ["retention_failed"]})

        failed = scheduled.ScheduledResult("20261010T120000Z-333333333333", "2026-10-10T12:00:00Z",
                                           status=scheduled.SYNC_FAILED)
        with mock.patch.object(scheduled, "_actual_live", return_value=CURRENT), \
             mock.patch.object(scheduled, "_evaluate_status", return_value=snapshot), \
             mock.patch.object(scheduled, "_record_outcome", return_value=Path("outcome")), \
             mock.patch.object(scheduled.alerts, "update_alert_state", return_value=alert_update), \
             mock.patch.object(scheduled, "_record_final", return_value=Path("final")), \
             mock.patch.object(retention, "_cleanup_locked") as cleanup:
            scheduled._complete(failed, self.config, lambda: NOW)
        cleanup.assert_not_called()

    def test_status_exposes_counts_only_when_scan_is_clean(self):
        self.add(RECENT, state="failed", attempt_status="failed")
        clean = retention.storage_snapshot(self.config, clock=lambda: NOW)
        self.assertEqual(clean["status"], "clean")
        self.assertIn("scanned", clean)
        (self.config.raw_dir / "unknown").write_text("x")
        attention = retention.storage_snapshot(self.config, clock=lambda: NOW)
        self.assertEqual(attention, {"status": "attention_required", "retention_hours": 96})


if __name__ == "__main__":
    unittest.main()
