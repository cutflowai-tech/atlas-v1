"""Deterministic, fail-closed retention tests; no Monday or production access."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION, load_contract_version
from atlas_sync import __main__ as cli
from atlas_sync import retention
from atlas_sync.config import SyncConfig

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, value=NOW):
        self.value = value

    def __call__(self):
        return self.value


def rid(moment: datetime, char: str) -> str:
    return moment.strftime("%Y%m%dT%H%M%SZ-") + char * 12


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="atlas-retention-"))
        board = str(load_contract_version(ACTIVE_CONTRACT_VERSION)["source_board"]["board_id"])
        self.config = SyncConfig(None, None, "2025-04", ACTIVE_CONTRACT_VERSION, board,
                                 self.root / "raw", self.root / "builds", self.root / "published",
                                 "2026-02-01T00:00:00Z", 3600, 7200, 3,
                                 lock_dir=self.root / "locks", retention_hours=96)
        for path in (self.config.raw_dir, self.config.build_dir / "attempts",
                     self.config.publish_dir / "history", self.config.lock_dir / "scheduled-cycles"):
            path.mkdir(parents=True)

    def raw(self, run_id, failed=False):
        path = self.config.raw_dir / run_id
        path.mkdir()
        (path / ("FAILED.json" if failed else "manifest.json")).write_text("{}")
        return path

    def build(self, attempt_id, run_id, failed=False, source_path=None):
        path = self.config.build_dir / attempt_id
        path.mkdir()
        (path / ("FAILED.json" if failed else "COMPLETE.json")).write_text("{}")
        source = source_path if source_path is not None else str(self.config.raw_dir.resolve() / run_id)
        (path / "build.json").write_text(json.dumps({"source": {"run_id": run_id, "raw_run_dir": source}}))
        record = {"attempt_id": attempt_id, "status": "failed" if failed else "success"}
        (self.config.build_dir / "attempts" / f"{attempt_id}.json").write_text(json.dumps(record))
        return path

    def history(self, sequence, publication_id, attempt_id, switched=True, status="published"):
        path = self.config.publish_dir / "history" / f"{sequence:06d}-{publication_id}.json"
        path.write_text(json.dumps({"publication_id": publication_id, "attempt_id": attempt_id,
                                    "switched": switched, "status": status}))
        return path

    def current(self, attempt_id):
        (self.config.build_dir / attempt_id / "site").mkdir(exist_ok=True)
        (self.config.publish_dir / "current").symlink_to(Path("../builds") / attempt_id / "site")

    def test_exact_boundary_is_retained_and_one_second_older_is_deleted(self):
        boundary = rid(NOW - timedelta(hours=96), "a")
        older = rid(NOW - timedelta(hours=96, seconds=1), "b")
        for value in (boundary, older):
            self.raw(value, failed=True)
            self.build(value, value, failed=True)
        report = retention._cleanup_locked(self.config, clock=Clock())
        self.assertTrue((self.config.build_dir / boundary).exists())
        self.assertFalse((self.config.build_dir / older).exists())
        self.assertIn("within_retention", report.reasons)
        self.assertGreater(report.bytes["deleted"], 0)

    def test_current_and_actual_default_rollback_target_keep_transitive_sources(self):
        old = NOW - timedelta(days=10)
        attempts = [rid(old + timedelta(seconds=i), c) for i, c in enumerate("abc")]
        sources = [rid(old + timedelta(minutes=1, seconds=i), c) for i, c in enumerate("def")]
        publications = [rid(old + timedelta(minutes=2, seconds=i), c) for i, c in enumerate("789")]
        for attempt, source in zip(attempts, sources):
            self.raw(source)
            self.build(attempt, source)
        for sequence, (publication, attempt) in enumerate(zip(publications, attempts), 1):
            self.history(sequence, publication, attempt)
        self.current(attempts[-1])

        report = retention._cleanup_locked(self.config, clock=Clock())
        # All still-advertised explicit rollback targets survive this pass; old history for a expires.
        for value in attempts:
            self.assertTrue((self.config.build_dir / value).exists())
        for value in sources:
            self.assertTrue((self.config.raw_dir / value).exists())
        self.assertFalse((self.config.publish_dir / "history" / f"000001-{publications[0]}.json").exists())
        self.assertGreaterEqual(report.reasons["publication_or_rollback"], 8)

        # Once no history advertises a as explicitly rollbackable, the next pass retires it and its source.
        retention._cleanup_locked(self.config, clock=Clock())
        self.assertFalse((self.config.build_dir / attempts[0]).exists())
        self.assertFalse((self.config.raw_dir / sources[0]).exists())

    def test_failed_terminal_runs_expire_but_incomplete_artifacts_do_not(self):
        old = rid(NOW - timedelta(days=8), "a")
        incomplete = rid(NOW - timedelta(days=8, seconds=1), "b")
        self.raw(old, failed=True)
        self.build(old, old, failed=True)
        (self.config.raw_dir / incomplete).mkdir()
        (self.config.build_dir / incomplete).mkdir()
        (self.config.build_dir / "attempts" / f"{incomplete}.json").write_text(
            json.dumps({"attempt_id": incomplete, "status": "running"}))
        report = retention._cleanup_locked(self.config, clock=Clock())
        self.assertFalse((self.config.raw_dir / old).exists())
        self.assertTrue((self.config.raw_dir / incomplete).exists())
        self.assertTrue((self.config.build_dir / incomplete).exists())
        self.assertIn("active_or_incomplete", report.reasons)

    def test_corrupt_traversing_or_absolute_reference_fails_closed(self):
        old = rid(NOW - timedelta(days=8), "a")
        source = rid(NOW - timedelta(days=8, minutes=1), "b")
        self.raw(source)
        self.build(old, source, source_path="/outside/raw")
        self.history(1, rid(NOW - timedelta(days=8, minutes=2), "c"), old)
        self.current(old)
        report = retention._cleanup_locked(self.config, clock=Clock())
        self.assertTrue((self.config.build_dir / old).exists())
        self.assertTrue((self.config.raw_dir / source).exists())
        self.assertIn("ambiguous_reference", report.reasons)

    def test_unknown_objects_and_symlinks_are_never_followed_or_deleted(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "valuable").write_text("keep")
        (self.config.raw_dir / "mystery").write_text("unknown")
        link_id = rid(NOW - timedelta(days=8), "a")
        (self.config.raw_dir / link_id).symlink_to(outside, target_is_directory=True)
        report = retention._cleanup_locked(self.config, clock=Clock())
        self.assertTrue((outside / "valuable").exists())
        self.assertTrue((self.config.raw_dir / link_id).is_symlink())
        self.assertIn("unknown_object", report.reasons)
        self.assertIn("unsafe_filesystem_object", report.reasons)

    def test_scheduled_cycle_group_dry_run_then_delete_is_idempotent(self):
        old = rid(NOW - timedelta(days=8), "a")
        root = self.config.lock_dir / "scheduled-cycles"
        for suffix in (".started.json", ".outcome.json", ".json"):
            phase = "started" if suffix.startswith(".started") else ("outcome" if suffix.startswith(".outcome") else "final")
            (root / f"{old}{suffix}").write_text(json.dumps({
                "scheduled_cycle_version": "atlas-scheduled-cycle-v1", "record_phase": phase, "cycle_id": old,
            }))
        dry = retention.cleanup(config=self.config, dry_run=True, clock=Clock())
        self.assertEqual(dry.counts["would_delete"], 3)
        self.assertEqual(len(list(root.iterdir())), 3)
        applied = retention.cleanup(config=self.config, clock=Clock())
        again = retention.cleanup(config=self.config, clock=Clock())
        self.assertEqual(applied.counts["deleted"], 3)
        self.assertEqual(again.counts.get("deleted", 0), 0)
        self.assertIsNotNone(retention.latest_summary(self.config))

    def test_delete_failure_is_reported_without_raising(self):
        old = rid(NOW - timedelta(days=8), "a")
        self.raw(old, failed=True)
        with mock.patch.object(retention, "_remove", side_effect=OSError("disk")):
            report = retention._cleanup_locked(self.config, clock=Clock())
        self.assertEqual((report.status, report.error_category), ("completed_with_errors", "cleanup_failed"))
        self.assertEqual(report.counts["error"], 1)

    def test_orphan_started_cycle_is_protected(self):
        old = rid(NOW - timedelta(days=8), "a")
        path = self.config.lock_dir / "scheduled-cycles" / f"{old}.started.json"
        path.write_text(json.dumps({"scheduled_cycle_version": "atlas-scheduled-cycle-v1",
                                    "record_phase": "started", "cycle_id": old}))
        report = retention._cleanup_locked(self.config, clock=Clock())
        self.assertTrue(path.exists())
        self.assertEqual(report.reasons["active_or_incomplete"], 1)

    def test_public_entry_point_uses_existing_production_lock(self):
        observed = []
        real = retention.production_lock

        def wrapper(config, operation, **kwargs):
            observed.append(operation)
            return real(config, operation, **kwargs)

        with mock.patch.object(retention, "production_lock", side_effect=wrapper):
            report = retention.cleanup(config=self.config, dry_run=True, clock=Clock())
        self.assertEqual((report.status, observed), ("complete", ["retention"]))

    def test_cli_dry_run_emits_json_report(self):
        report = retention.RetentionReport(
            "2026-09-29T12:00:00Z", "2026-09-25T12:00:00Z", 96, True,
            items=[retention.RetentionItem("raw_run", "safe-id", "would_delete", "expired", 17)],
        ).finish()
        output = io.StringIO()
        with mock.patch.object(retention, "cleanup", return_value=report), redirect_stdout(output):
            code = cli.main(["retention", "--dry-run", "--json"])
        document = json.loads(output.getvalue())
        self.assertEqual((code, document["dry_run"], document["bytes"]["would_delete"]), (0, True, 17))


if __name__ == "__main__":
    unittest.main()
