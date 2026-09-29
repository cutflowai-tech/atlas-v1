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
        raw_marker = ({"ingest_version": "atlas-ingest-v2", "status": "complete", "run": {"run_id": source}}
                      if status == "complete" else
                      {"ingest_version": "atlas-ingest-v2", "status": "failed", "run": {"run_id": source}})
        (raw / ("manifest.json" if status == "complete" else "FAILED.json")).write_text(json.dumps(raw_marker))
        build = self.config.build_dir / attempt
        build.mkdir()
        (build / "build.json").write_text(json.dumps({"attempt": {"attempt_id": attempt},
                                                       "source": {"run_id": source, "raw_run_dir": str(raw.resolve())}}))
        marker = ({"status": "complete", "attempt_id": attempt, "source_run_id": source}
                  if status == "complete" else {"status": "failed", "attempt_id": attempt})
        (build / ("COMPLETE.json" if status == "complete" else "FAILED.json")).write_text(json.dumps(marker))
        record = self.config.build_dir / "attempts" / f"{attempt}.json"
        record.write_text(json.dumps({"attempt_id": attempt, "source_run_id": source,
                                      "raw_run_dir": str(raw.resolve()),
                                      "status": "success" if status == "complete" else "failed"}))
        for path in (raw, build, record): self.age(path, hours)
        return raw, build, record

    def history(self, seq, publication, attempt, *, hours=97):
        path = self.config.publish_dir / "history" / f"{seq:06d}-{publication}.json"
        path.write_text(json.dumps({"publication_version": "atlas-publication-v1", "sequence": seq,
                                    "publication_id": publication, "attempt_id": attempt,
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
        (self.config.publish_dir / "CURRENT.json").write_text(json.dumps({"history_record": str(h3.resolve()),
                                                                           "publication_id": "20260903T020000Z-cccccccccccc",
                                                                           "attempt_id": current}))
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
            phase = suffix or "final"
            path.write_text(json.dumps({"scheduled_cycle_version": "atlas-scheduled-cycle-v1",
                                        "record_phase": phase, "cycle_id": terminal})); self.age(path)
        started = self.config.lock_dir / "scheduled-cycles" / f"{active}.started.json"
        started.write_text(json.dumps({"scheduled_cycle_version": "atlas-scheduled-cycle-v1",
                                       "record_phase": "started", "cycle_id": active})); self.age(started)
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
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        _, build, _ = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        output = io.StringIO()
        with mock.patch.object(cli, "retention_cleanup", wraps=lambda **kwargs: retention.cleanup(
                config=self.config, clock=lambda: NOW, **kwargs)), redirect_stdout(output):
            code = cli.main(["retention", "--json"])
        document = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(document["dry_run"])
        self.assertIn("would_delete_bytes", document)
        self.assertTrue(build.exists())

    def test_nested_root_symlink_never_traverses_or_deletes_external_data(self):
        shutil.rmtree(self.config.build_dir / "attempts")
        outside = self.data / "outside-attempts"
        outside.mkdir()
        old = "20260901T000000Z-aaaaaaaaaaaa"
        external = outside / f"{old}.json"
        external.write_text(json.dumps({"attempt_id": old, "status": "failed"}))
        (self.config.build_dir / "attempts").symlink_to(outside, target_is_directory=True)
        report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue(external.exists())

    def test_retained_build_transitively_keeps_older_source(self):
        source = "20260901T000000Z-aaaaaaaaaaaa"
        recent = "20260929T110000Z-bbbbbbbbbbbb"
        raw, build, _ = self.artifact(recent, source)
        report = self.cleanup()
        self.assertTrue(build.exists())
        self.assertTrue(raw.exists())
        self.assertIn("source_evidence_required", report.reasons)

    def test_corrupt_markers_and_unknown_history_fail_closed(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, _ = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        (build / "COMPLETE.json").write_text("{")
        (raw / "manifest.json").write_text("{")
        legacy = self.config.publish_dir / "history" / "legacy.json"
        legacy.write_text(json.dumps({"attempt_id": attempt, "switched": True}))
        report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue(build.exists())
        self.assertTrue(raw.exists())
        self.assertTrue(legacy.exists())
        self.assertIn("corrupt_reference", report.reasons)

    def test_real_failed_raw_and_early_failed_build_can_expire(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        source = "20260901T010000Z-bbbbbbbbbbbb"
        raw, build, record = self.artifact(attempt, source, status="failed")
        (build / "build.json").unlink()
        report = self.cleanup()
        self.assertEqual(report.status, "complete")
        self.assertFalse(raw.exists())
        self.assertFalse(build.exists())
        self.assertFalse(record.exists())

    def test_expired_explicit_rollback_history_is_bounded_but_default_is_kept(self):
        oldest, previous, current = (
            "20260901T000000Z-111111111111", "20260902T000000Z-222222222222", "20260903T000000Z-333333333333")
        for index, attempt in enumerate((oldest, previous, current), 1):
            self.artifact(attempt, f"2026090{index}T010000Z-{str(index) * 12}")
        old_history = self.history(1, "20260901T020000Z-aaaaaaaaaaaa", oldest)
        previous_history = self.history(2, "20260902T020000Z-bbbbbbbbbbbb", previous)
        current_history = self.history(3, "20260903T020000Z-cccccccccccc", current)
        (self.config.build_dir / current / "site").mkdir()
        (self.config.publish_dir / "current").symlink_to(f"../builds/{current}/site")
        (self.config.publish_dir / "CURRENT.json").write_text(json.dumps({
            "attempt_id": current, "publication_id": "20260903T020000Z-cccccccccccc",
            "history_record": str(current_history),
        }))
        first = self.cleanup()
        self.assertFalse(old_history.exists())
        self.assertFalse((self.config.build_dir / oldest).exists())
        self.assertTrue(previous_history.exists())
        self.assertTrue((self.config.build_dir / previous).exists())
        self.assertTrue(current_history.exists())
        self.assertEqual(first.status, "complete")

    def test_retention_report_symlink_never_writes_or_supplies_status_outside_lock_root(self):
        outside = self.data / "outside-report"
        outside.mkdir()
        (self.config.lock_dir / "retention").symlink_to(outside, target_is_directory=True)
        report = self.cleanup()
        self.assertEqual((report.status, report.failure_category), ("partial", "report_write_failed"))
        self.assertFalse((outside / "latest.json").exists())
        (outside / "latest.json").write_text(json.dumps({
            "report_version": "atlas-retention-v1", "status": "complete", "storage": {},
        }))
        snapshot = status.StatusSnapshot("now", "runtime", "healthy", "fresh", True, None, None, None, {})
        status._attach_retention(snapshot, self.config)
        self.assertIsNone(snapshot.retention)

    def test_running_attempt_protects_paired_build_and_source(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, record = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb", status="failed")
        document = json.loads(record.read_text())
        document["status"] = "running"
        record.write_text(json.dumps(document))
        report = self.cleanup()
        self.assertTrue(record.exists())
        self.assertTrue(build.exists())
        self.assertTrue(raw.exists())
        self.assertIn("active_or_incomplete", report.reasons)

    def test_incomplete_build_without_attempt_record_keeps_its_source(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        source = "20260901T010000Z-bbbbbbbbbbbb"
        raw, build, record = self.artifact(attempt, source)
        (build / "COMPLETE.json").unlink()
        record.unlink()
        report = self.cleanup()
        self.assertEqual(report.status, "complete")
        self.assertTrue(build.exists())
        self.assertTrue(raw.exists())
        self.assertIn("source_evidence_required", report.reasons)

    def test_unknown_build_directory_keeps_valid_referenced_source(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        source = "20260901T010000Z-bbbbbbbbbbbb"
        raw, build, record = self.artifact(attempt, source)
        unknown = self.config.build_dir / "legacy-build"
        build.rename(unknown)
        record.unlink()
        report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue(unknown.exists())
        self.assertTrue(raw.exists())

    def test_corrupt_raw_blocks_deletion_of_referencing_build_and_attempt(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, record = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        (raw / "manifest.json").write_text("{")
        report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue(raw.exists())
        self.assertTrue(build.exists())
        self.assertTrue(record.exists())

    def test_current_metadata_symlink_blocks_cleanup(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, record = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        (build / "site").mkdir()
        history = self.history(1, "20260901T020000Z-cccccccccccc", attempt)
        (self.config.publish_dir / "current").symlink_to(f"../builds/{attempt}/site")
        outside = self.data / "outside-current.json"
        outside.write_text(json.dumps({
            "attempt_id": attempt,
            "publication_id": "20260901T020000Z-cccccccccccc",
            "history_record": str(history),
        }))
        (self.config.publish_dir / "CURRENT.json").symlink_to(outside)
        report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue(raw.exists())
        self.assertTrue(build.exists())
        self.assertTrue(record.exists())
        self.assertTrue(history.exists())

    def test_corrupt_raw_without_build_keeps_attempt_record(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, record = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        shutil.rmtree(build)
        (raw / "manifest.json").write_text("{")
        report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue(raw.exists())
        self.assertTrue(record.exists())

    def test_incomplete_build_with_unknown_source_keeps_raw_graph(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, record = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        (build / "COMPLETE.json").unlink()
        (build / "build.json").unlink()
        record.unlink()
        report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue(build.exists())
        self.assertTrue(raw.exists())

    def test_invalid_current_metadata_blocks_cleanup_without_live_pointer(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, record = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        (self.config.publish_dir / "CURRENT.json").write_text("{")
        report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue(raw.exists())
        self.assertTrue(build.exists())
        self.assertTrue(record.exists())

    def test_delete_swap_never_removes_replacement_object(self):
        root = self.data / "delete-race"
        root.mkdir()
        target = root / "target"
        target.mkdir()
        (target / "original").write_text("keep")
        moved = root / "moved-original"
        real_rename = os.rename
        swapped = False

        def swap_then_rename(src, dst, *args, **kwargs):
            nonlocal swapped
            if src == target.name and not swapped:
                swapped = True
                real_rename(src, moved.name, src_dir_fd=kwargs["src_dir_fd"],
                            dst_dir_fd=kwargs["dst_dir_fd"])
                target.mkdir()
                (target / "replacement").write_text("must survive")
            return real_rename(src, dst, *args, **kwargs)

        with (mock.patch.object(retention.os, "rename", side_effect=swap_then_rename),
              self.assertRaisesRegex(OSError, "changed during deletion")):
            retention._remove(root, target, retention._identity(target))
        self.assertTrue((target / "replacement").exists())
        self.assertTrue((moved / "original").exists())

    def test_delete_swap_before_open_never_removes_replacement_object(self):
        root = self.data / "delete-early-race"
        root.mkdir()
        target = root / "target"
        target.mkdir()
        (target / "original").write_text("keep")
        expected = retention._identity(target)
        moved = root / "moved-original"
        real_safe_child = retention._safe_child
        swapped = False

        def validate_then_swap(parent, candidate):
            nonlocal swapped
            valid = real_safe_child(parent, candidate)
            if valid and not swapped:
                swapped = True
                target.rename(moved)
                target.mkdir()
                (target / "replacement").write_text("must survive")
            return valid

        with (mock.patch.object(retention, "_safe_child", side_effect=validate_then_swap),
              self.assertRaisesRegex(OSError, "changed since validation")):
            retention._remove(root, target, expected)
        self.assertTrue((target / "replacement").exists())
        self.assertTrue((moved / "original").exists())

    def test_unknown_build_with_invalid_source_blocks_raw_deletion(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, record = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        unknown = self.config.build_dir / "legacy-build"
        build.rename(unknown)
        record.unlink()
        (unknown / "build.json").write_text(json.dumps({
            "source": {"run_id": raw.name, "raw_run_dir": "/outside/raw"},
        }))
        report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue(unknown.exists())
        self.assertTrue(raw.exists())

    def test_raw_swap_during_validation_never_deletes_replacement(self):
        attempt = "20260901T000000Z-aaaaaaaaaaaa"
        raw, build, record = self.artifact(attempt, "20260901T010000Z-bbbbbbbbbbbb")
        shutil.rmtree(build)
        record.unlink()
        moved = self.data / "moved-validated-raw"
        real_validate = retention._valid_raw_run
        swapped = False

        def validate_then_swap(path):
            nonlocal swapped
            result = real_validate(path)
            if path.name == raw.name and not swapped:
                swapped = True
                raw.rename(moved)
                raw.mkdir()
                (raw / "replacement").write_text("must survive")
            return result

        with mock.patch.object(retention, "_valid_raw_run", side_effect=validate_then_swap):
            report = self.cleanup()
        self.assertEqual(report.status, "blocked")
        self.assertTrue((raw / "replacement").exists())
        self.assertTrue((moved / "manifest.json").exists())

    def test_report_parent_swap_cannot_write_outside_opened_directory(self):
        directory = self.config.lock_dir / "retention"
        directory.mkdir()
        saved = self.config.lock_dir / "retention-opened"
        outside = self.data / "outside-race"
        outside.mkdir()
        real_open = os.open
        swapped = False

        def swap_parent(path, *args, **kwargs):
            nonlocal swapped
            if isinstance(path, str) and path.startswith(".latest.json") and not swapped:
                swapped = True
                directory.rename(saved)
                directory.symlink_to(outside, target_is_directory=True)
            return real_open(path, *args, **kwargs)

        report = retention.RetentionReport("now", "cutoff", 345600, False)
        with mock.patch.object(retention.os, "open", side_effect=swap_parent):
            retention._write_report(self.config, report)
        self.assertFalse((outside / "latest.json").exists())
        self.assertTrue((saved / "latest.json").exists())

    def test_status_parent_swap_never_reads_external_report(self):
        directory = self.config.lock_dir / "retention"
        directory.mkdir()
        (directory / "latest.json").write_text(json.dumps({
            "report_version": "atlas-retention-v1", "status": "partial", "storage": {},
        }))
        saved = self.config.lock_dir / "retention-opened"
        outside = self.data / "outside-status-race"
        outside.mkdir()
        (outside / "latest.json").write_text(json.dumps({
            "report_version": "atlas-retention-v1", "status": "complete",
            "storage": {"raw_run": {"count": 1, "bytes": 1}},
        }))
        real_open = os.open
        swapped = False

        def swap_parent(path, *args, **kwargs):
            nonlocal swapped
            if path == "latest.json" and not swapped:
                swapped = True
                directory.rename(saved)
                directory.symlink_to(outside, target_is_directory=True)
            return real_open(path, *args, **kwargs)

        snapshot = status.StatusSnapshot("now", "runtime", "healthy", "fresh", True, None, None, None, {})
        with mock.patch.object(status.os, "open", side_effect=swap_parent):
            status._attach_retention(snapshot, self.config)
        self.assertIsNone(snapshot.retention)


if __name__ == "__main__":
    unittest.main()
