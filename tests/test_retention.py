"""Bounded retention: deterministic, transitive and fail closed."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from atlas_sync import __main__ as cli
from atlas_sync import lock, retention, status
from atlas_sync.config import DEFAULT_RETENTION_SECONDS, load_sync_config

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-retention-"))
        self.config = load_sync_config({"ATLAS_DATA_DIR": str(self.data)}, now=NOW)
        for root in (self.config.raw_dir, self.config.build_dir / "attempts",
                     self.config.publish_dir / "history", self.config.lock_dir / "scheduled-cycles"):
            root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    def age(self, path, hours=97):
        stamp = (NOW - timedelta(hours=hours)).timestamp()
        os.utime(path, (stamp, stamp), follow_symlinks=False)

    def artifact(self, attempt, source, *, status="complete", hours=97):
        raw = self.config.raw_dir / source
        raw.mkdir(); (raw / "evidence").write_text("raw")
        build = self.config.build_dir / attempt
        build.mkdir()
        (build / "build.json").write_text(json.dumps({"source": {"run_id": source, "raw_run_dir": str(raw.resolve())}}))
        (build / ("COMPLETE.json" if status == "complete" else "FAILED.json")).write_text("{}")
        record = self.config.build_dir / "attempts" / f"{attempt}.json"
        record.write_text(json.dumps({"attempt_id": attempt, "source_run_id": source,
                                      "status": "success" if status == "complete" else "failed"}))
        for path in (raw, build, record): self.age(path, hours)
        return raw, build, record

    def history(self, seq, publication, attempt, *, hours=97):
        path = self.config.publish_dir / "history" / f"{seq:06d}-{publication}.json"
        path.write_text(json.dumps({"publication_id": publication, "attempt_id": attempt,
                                    "switched": True, "status": "published"}))
        self.age(path, hours)
        return path

    def cleanup(self, dry_run=False):
        return retention._cleanup_locked(config=self.config, dry_run=dry_run, clock=lambda: NOW)

    def test_default_and_strict_age_boundary(self):
        self.assertEqual(self.config.retention_seconds, DEFAULT_RETENTION_SECONDS)
        old = "20260920T000000Z-aaaaaaaaaaaa"
        edge = "20260925T120000Z-bbbbbbbbbbbb"
        old_raw, old_build, _ = self.artifact(old, "20260920T000001Z-cccccccccccc")
        edge_raw, edge_build, _ = self.artifact(edge, "20260925T120001Z-dddddddddddd", hours=96)
        report = self.cleanup()
        self.assertFalse(old_build.exists()); self.assertFalse(old_raw.exists())
        self.assertTrue(edge_build.exists()); self.assertTrue(edge_raw.exists())
        self.assertGreater(report.deleted_bytes, 0)
        self.assertEqual(report.status, "complete")

    def test_current_and_real_default_rollback_target_are_transitively_retained(self):
        oldest = "20260901T000000Z-111111111111"
        prior = "20260902T000000Z-222222222222"
        current = "20260903T000000Z-333333333333"
        artifacts = {attempt: self.artifact(attempt, f"2026090{i}T010000Z-{str(i)*12}")
                     for i, attempt in enumerate((oldest, prior, current), 1)}
        h1 = self.history(1, "20260901T020000Z-aaaaaaaaaaaa", oldest)
        h2 = self.history(2, "20260902T020000Z-bbbbbbbbbbbb", prior)
        h3 = self.history(3, "20260903T020000Z-cccccccccccc", current)
        os.symlink(f"../builds/{current}/site", self.config.publish_dir / "current")
        (self.config.publish_dir / "CURRENT.json").write_text(json.dumps({"history_record": str(h3.resolve())}))
        report = self.cleanup()
        self.assertFalse(artifacts[oldest][1].exists()); self.assertFalse(h1.exists())
        for attempt in (prior, current):
            self.assertTrue(artifacts[attempt][0].exists()); self.assertTrue(artifacts[attempt][1].exists())
        self.assertTrue(h2.exists()); self.assertTrue(h3.exists())
        self.assertIn("publication_or_rollback_required", report.reasons)

    def test_failed_terminal_attempt_expires_but_incomplete_is_kept(self):
        failed = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, record = self.artifact(failed, "20260901T010000Z-bbbbbbbbbbbb", status="failed")
        self.cleanup()
        self.assertFalse(raw.exists()); self.assertFalse(build.exists()); self.assertFalse(record.exists())
        incomplete = self.config.build_dir / "20260901T020000Z-cccccccccccc"
        incomplete.mkdir(); self.age(incomplete)
        self.cleanup()
        self.assertTrue(incomplete.exists())

    def test_corrupt_reference_blocks_graph_and_unsafe_objects_are_never_followed(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, _ = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        corrupt = self.config.publish_dir / "history" / "000001-20260901T020000Z-cccccccccccc.json"
        corrupt.write_text("{"); self.age(corrupt)
        outside = self.data / "outside"; outside.write_text("keep")
        link = self.config.raw_dir / "20260901T030000Z-dddddddddddd"
        link.symlink_to(outside); self.age(link)
        report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue(raw.exists()); self.assertTrue(build.exists()); self.assertTrue(outside.exists()); self.assertTrue(link.is_symlink())
        self.assertIsNone(report.storage)

    def test_absolute_traversal_reference_fails_closed(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, _ = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        h = self.history(1, "20260901T020000Z-cccccccccccc", attempt)
        os.symlink(f"../builds/{attempt}/site", self.config.publish_dir / "current")
        (self.config.publish_dir / "CURRENT.json").write_text(json.dumps({"history_record": "/tmp/elsewhere.json"}))
        report = self.cleanup()
        self.assertEqual(report.status, "blocked"); self.assertTrue(raw.exists()); self.assertTrue(build.exists()); self.assertTrue(h.exists())

    def test_dry_run_is_read_only_and_reports_counts_bytes_reasons(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, _ = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        report = self.cleanup(dry_run=True)
        self.assertTrue(raw.exists()); self.assertTrue(build.exists())
        self.assertGreaterEqual(report.would_delete_count, 3); self.assertGreater(report.would_delete_bytes, 0)
        self.assertEqual(report.reasons["expired"], report.would_delete_count)
        self.assertFalse((self.config.lock_dir / "retention/latest.json").exists())

    def test_delete_failure_is_nonfatal_and_second_run_is_idempotent(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        real = retention._remove
        with mock.patch.object(retention, "_remove", side_effect=[OSError("disk"), *([real] * 10)]):
            report = self.cleanup()
        self.assertEqual(report.status, "partial")
        second = self.cleanup(); third = self.cleanup()
        self.assertEqual(second.status, "complete"); self.assertEqual(third.deleted_count, 0)

    def test_cycle_groups_expire_only_when_terminal_and_all_old(self):
        terminal = "20260901T000000Z-aaaaaaaaaaaa"
        active = "20260901T010000Z-bbbbbbbbbbbb"
        for suffix in ("started", "outcome", None):
            name = f"{terminal}.{suffix}.json" if suffix else f"{terminal}.json"
            path = self.config.lock_dir / "scheduled-cycles" / name
            path.write_text(json.dumps({"cycle_id": terminal})); self.age(path)
        started = self.config.lock_dir / "scheduled-cycles" / f"{active}.started.json"
        started.write_text(json.dumps({"cycle_id": active})); self.age(started)
        self.cleanup()
        self.assertFalse(any((self.config.lock_dir / "scheduled-cycles").glob(f"{terminal}*")))
        self.assertTrue(started.exists())

    def test_public_cleanup_uses_nonblocking_production_lock(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        _, build, _ = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        with lock.production_lock(self.config, "publish", clock=lambda: NOW):
            report = retention.cleanup(config=self.config, clock=lambda: NOW)
        self.assertEqual((report.status, report.failure_category), ("locked", "operation_locked"))
        self.assertTrue(build.exists())

    def test_status_exposes_storage_only_from_clean_report(self):
        attempt = "20260929T110000Z-aaaaaaaaaaaa"
        self.artifact(attempt, "20260929T110001Z-bbbbbbbbbbbb", hours=1)
        report = self.cleanup()
        self.assertEqual(report.status, "complete")
        snapshot = status.StatusSnapshot("now", "runtime", "healthy", "fresh", True, None, None, None, {})
        status._attach_retention(snapshot, self.config)
        self.assertIsNotNone(snapshot.retention)
        self.assertIn("build", snapshot.retention["storage"])
        latest = self.config.lock_dir / "retention/latest.json"
        document = json.loads(latest.read_text()); document["status"] = "partial"; latest.write_text(json.dumps(document))
        other = status.StatusSnapshot("now", "runtime", "healthy", "fresh", True, None, None, None, {})
        status._attach_retention(other, self.config)
        self.assertIsNone(other.retention)

    def test_cli_dry_run_json_is_structured(self):
        report = self.cleanup(dry_run=True)
        output = io.StringIO()
        with mock.patch.object(cli, "retention_cleanup", return_value=report), redirect_stdout(output):
            code = cli.main(["retention", "--dry-run", "--json"])
        document = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(document["dry_run"])
        self.assertIn("would_delete_bytes", document)


if __name__ == "__main__":
    unittest.main()
