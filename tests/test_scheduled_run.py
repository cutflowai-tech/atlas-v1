"""Task 8 scheduled-run core: one lock, one exact attempt, immutable safe evidence."""

import functools
import io
import json
import shutil
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from test_ingest import FakeMonday, items
from test_sync_run import HISTORY, T0, TOKEN, Clock, Faulty, Monotonic, logs

from atlas_monday_probe.client import HttpFailure
from atlas_sync import __main__ as cli
from atlas_sync import alerts, lock, publish, retention, run, scheduled
from atlas_sync.config import load_sync_config

CYCLE_ID = "20260920T120000Z-aaaaaaaaaaaa"
ATTEMPT_ID = "20260920T120001Z-bbbbbbbbbbbb"
PUBLICATION_ID = "20260920T120002Z-cccccccccccc"


class ScheduledRunTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-scheduled-"))
        self.env = {"MONDAY_API_TOKEN": TOKEN, "ATLAS_DATA_DIR": str(self.data), "ATLAS_HISTORY_START": HISTORY}
        self.config = load_sync_config(self.env, now=T0)
        self.fake = FakeMonday(logs(), items())

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    def cycle(self, **kwargs):
        options = {"config": self.config, "transport": self.fake, "clock": Clock(T0), "monotonic": Monotonic(),
                   "sleep": lambda _: None, "cycle_id_factory": lambda _: CYCLE_ID,
                   "attempt_id_factory": lambda _: ATTEMPT_ID, "publication_id_factory": lambda _: PUBLICATION_ID}
        return scheduled.scheduled_run(**{**options, **kwargs})

    def live_attempt(self):
        return publish.live_attempt(self.config)

    def test_success_holds_one_lock_and_publishes_the_exact_attempt(self):
        real_sync, real_publish = run._run_once_locked, publish._publish_locked
        observed = []

        def assert_held(label):
            with self.assertRaises(lock.OperationLocked), lock.production_lock(self.config, "publish", clock=lambda: T0):
                pass
            observed.append(label)

        def sync_locked(**kwargs):
            assert_held("sync")
            return real_sync(**kwargs)

        def publish_locked(attempt_id, **kwargs):
            assert_held("publish")
            self.assertEqual(attempt_id, ATTEMPT_ID)
            return real_publish(attempt_id, **kwargs)

        with mock.patch.object(run, "_run_once_locked", side_effect=sync_locked), \
             mock.patch.object(publish, "_publish_locked", side_effect=publish_locked):
            result = self.cycle()
        self.assertEqual((result.status, scheduled.exit_code(result), observed), ("published", 0, ["sync", "publish"]))
        self.assertEqual((result.attempt_id, self.live_attempt()), (ATTEMPT_ID, ATTEMPT_ID))
        self.assertTrue(result.switched)

    def test_immutable_safe_cycle_record(self):
        result = self.cycle()
        path = Path(result.cycle_record)
        document, text = json.loads(path.read_text()), path.read_text()
        self.assertEqual((document["scheduled_cycle_version"], document["cycle_id"], document["attempt_id"],
                          document["status"]), (scheduled.SCHEDULED_VERSION, CYCLE_ID, ATTEMPT_ID, "published"))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("exception", text.lower())
        records = sorted((self.data / "locks/scheduled-cycles").glob("*.json"))
        self.assertEqual({item.name for item in records}, {
            f"{CYCLE_ID}.started.json", f"{CYCLE_ID}.outcome.json", f"{CYCLE_ID}.json",
        })
        self.assertIn(path.resolve(), [item.resolve() for item in records])
        self.assertEqual(document["previous_live_attempt"], None)
        self.assertEqual(document["resulting_live_attempt"], ATTEMPT_ID)
        self.assertEqual(document["final_system_state"], "healthy")
        self.assertIn("active_alert_types", document)

    def test_contention_records_skip_but_does_no_request_build_publish_or_alert_update(self):
        with lock.production_lock(self.config, "publish", clock=lambda: T0):
            result = self.cycle()
        self.assertEqual((result.status, scheduled.exit_code(result), len(self.fake.queries)), ("locked", 75, 0))
        self.assertFalse((self.data / "builds").exists())
        self.assertIsNone(self.live_attempt())
        self.assertIsNotNone(result.cycle_record)
        self.assertEqual(json.loads(Path(result.cycle_record).read_text())["status"], "locked")
        self.assertFalse((self.data / "locks/alerts/state.json").exists())

    def test_configuration_and_sync_failures_never_publish(self):
        missing = {key: value for key, value in self.env.items() if key != "MONDAY_API_TOKEN"}
        configured = scheduled.scheduled_run(missing, clock=Clock(T0), cycle_id_factory=lambda _: CYCLE_ID)
        self.assertEqual((configured.status, scheduled.exit_code(configured)), ("configuration_failed", 2))
        denied = Faulty(FakeMonday(logs(), items()), at=1,
                        error=HttpFailure(401, b'{"errors":[{"message":"Not Authenticated"}]}'))
        failed = self.cycle(transport=denied)
        self.assertEqual((failed.status, failed.failure_stage, scheduled.exit_code(failed)), ("sync_failed", "sync", 3))
        self.assertIsNone(failed.publication_id)
        self.assertIsNone(self.live_attempt())
        self.assertIsNotNone(failed.cycle_record)

    def test_build_stage_failure_is_recorded_and_not_published(self):
        with mock.patch.object(run, "build_dashboard_files", side_effect=RuntimeError("raw secret exception")):
            result = self.cycle()
        self.assertEqual((result.status, result.sync_failure_stage, result.sync_failure_category),
                         ("sync_failed", "dashboard", "dashboard_generation"))
        self.assertNotIn("raw secret exception", Path(result.cycle_record).read_text())
        self.assertIsNone(self.live_attempt())

    def test_publish_failure_never_falls_back_and_preserves_last_good(self):
        first = self.cycle()
        self.assertEqual(first.status, "published")
        second_attempt = "20260921T120001Z-dddddddddddd"
        second_cycle = "20260921T120000Z-eeeeeeeeeeee"
        second_publication = "20260921T120002Z-ffffffffffff"
        real_sync = run._run_once_locked

        def incomplete(**kwargs):
            result = real_sync(**kwargs)
            Path(result.staged_build_dir, run.COMPLETE_NAME).unlink()
            return result

        with mock.patch.object(run, "_run_once_locked", side_effect=incomplete):
            result = self.cycle(clock=Clock(T0 + timedelta(days=1)), cycle_id_factory=lambda _: second_cycle,
                                attempt_id_factory=lambda _: second_attempt,
                                publication_id_factory=lambda _: second_publication)
        self.assertEqual((result.status, result.attempt_id, scheduled.exit_code(result)),
                         ("publish_failed", second_attempt, 4))
        self.assertEqual(self.live_attempt(), ATTEMPT_ID)
        self.assertFalse(result.switched)

    def test_post_switch_metadata_failure_is_distinct_and_keeps_new_live(self):
        with mock.patch.object(publish, "_write_current_metadata", side_effect=OSError("disk details")):
            result = self.cycle()
        self.assertEqual((result.status, scheduled.exit_code(result), result.switched), ("publish_inconsistent", 5, True))
        self.assertEqual(self.live_attempt(), ATTEMPT_ID)
        self.assertNotIn("disk details", Path(result.cycle_record).read_text())

    def test_pre_rename_failure_keeps_old_live_post_rename_fsync_failure_marks_new_live_inconsistent(self):
        first = self.cycle()
        self.assertEqual(first.status, "published")

        def options(day, suffix):
            return {"clock": Clock(T0 + timedelta(days=day)),
                    "cycle_id_factory": lambda _: f"2026092{day}T120000Z-{suffix * 12}",
                    "attempt_id_factory": lambda _: f"2026092{day}T120001Z-{chr(ord(suffix) + 1) * 12}",
                    "publication_id_factory": lambda _: f"2026092{day}T120002Z-{chr(ord(suffix) + 2) * 12}"}

        with mock.patch.object(publish, "_replace_pointer", side_effect=OSError("before rename")):
            before = self.cycle(**options(1, "d"))
        self.assertEqual((before.status, before.switched, self.live_attempt()), ("publish_failed", False, ATTEMPT_ID))

        after_options = options(2, "a")
        with mock.patch.object(publish, "_fsync_dir", side_effect=OSError("after rename")):
            after = self.cycle(**after_options)
        self.assertEqual((after.status, after.switched), ("publish_inconsistent", True))
        self.assertEqual(self.live_attempt(), "20260922T120001Z-bbbbbbbbbbbb")
        self.assertEqual(after.publish_failure_category, "post_switch_durability_failed")

    def test_cycle_record_failure_is_safe_and_publication_stays_live(self):
        with mock.patch.object(scheduled, "_record_final", side_effect=OSError("private path")):
            result = self.cycle()
        self.assertEqual((result.status, scheduled.exit_code(result), result.failure_category),
                         ("record_failed", 7, "record_write_failed"))
        self.assertEqual(self.live_attempt(), ATTEMPT_ID)
        self.assertIsNone(result.cycle_record)
        self.assertIsNotNone(result.outcome_record)
        self.assertEqual(scheduled._cycle_records(self.config)[-1]["status"], "published")
        state = alerts.read_alert_state(self.config.lock_dir)
        self.assertEqual(state["last_observation"]["consecutive_scheduled_failures"], 0)

    def test_retention_runs_last_under_same_lock_and_failure_does_not_invalidate_publication(self):
        observed = []

        def cleanup(**kwargs):
            with self.assertRaises(lock.OperationLocked), lock.production_lock(self.config, "retention", clock=lambda: T0):
                pass
            observed.append(Path(kwargs["config"].lock_dir, "scheduled-cycles", f"{CYCLE_ID}.outcome.json").exists())
            raise OSError("cleanup failure")

        with mock.patch.object(retention, "_cleanup_locked", side_effect=cleanup):
            result = self.cycle()
        self.assertEqual((result.status, result.retention_status, scheduled.exit_code(result)),
                         ("published", "failed", 0))
        self.assertEqual(observed, [True])
        self.assertEqual(self.live_attempt(), ATTEMPT_ID)
        self.assertEqual(json.loads(Path(result.cycle_record).read_text())["retention_status"], "failed")

    def test_started_record_is_durable_before_monday_and_orphan_is_recovered_as_failure(self):
        with mock.patch.object(scheduled, "_record_started", side_effect=OSError("disk")):
            refused = self.cycle()
        self.assertEqual((refused.status, refused.failure_category, len(self.fake.queries)),
                         ("record_failed", "record_start_failed", 0))
        self.assertIsNone(self.live_attempt())

        orphan = scheduled.ScheduledResult(
            cycle_id="20260919T120000Z-999999999999", started_at="2026-09-19T12:00:00Z", sequence=1,
        )
        scheduled._record_started(self.config, orphan)
        reconstructed = scheduled._cycle_records(self.config)
        recovered = next(item for item in reconstructed if item["cycle_id"] == orphan.cycle_id)
        self.assertEqual((recovered["status"], recovered["failure_category"]),
                         ("interrupted", "interrupted_before_outcome"))
        self.assertEqual(alerts.scheduled_failure_streak(reconstructed), 1)

    def test_cli_human_json_and_exit_codes(self):
        success = self.cycle()
        for json_mode in (False, True):
            output = io.StringIO()
            with mock.patch.object(cli, "scheduled_run", return_value=success), redirect_stdout(output):
                code = cli.main(["scheduled-run", *(["--json"] if json_mode else [])])
            self.assertEqual(code, 0)
            if json_mode:
                self.assertEqual(json.loads(output.getvalue())["attempt_id"], ATTEMPT_ID)
            else:
                self.assertIn("exact attempt:", output.getvalue())
                self.assertIn("SCHEDULED RUN PUBLISHED", output.getvalue())

    def test_direct_entry_points_still_take_their_own_lock(self):
        calls = []

        @functools.wraps(lock.production_lock)
        def observed(config, operation, **kwargs):
            calls.append(operation)
            return lock.production_lock(config, operation, **kwargs)

        with mock.patch.object(run, "production_lock", side_effect=observed):
            attempt = run.run_once(config=self.config, transport=self.fake, clock=Clock(T0), monotonic=Monotonic(),
                                   sleep=lambda _: None, attempt_id_factory=lambda _: ATTEMPT_ID)
        with mock.patch.object(publish, "production_lock", side_effect=observed):
            published = publish.publish(attempt.attempt_id, config=self.config, clock=Clock(T0 + timedelta(days=1)),
                                        publication_id_factory=lambda _: PUBLICATION_ID)
        self.assertEqual((attempt.status, published.status, calls), ("success", "published", ["run-once", "publish"]))

    def test_every_run_failure_stage_stops_before_publish_and_keeps_last_good(self):
        self.assertEqual(self.cycle().status, "published")
        stages = {
            "ingestion": "rate_limited", "verification": "verification_failed",
            "profiles": "profile_generation", "dashboard": "dashboard_generation",
            "validation": "build_validation",
        }
        for index, (stage, category) in enumerate(stages.items(), start=1):
            attempt_id = f"2026100{index}T120001Z-{index:012x}"
            failed = run.SyncResult(attempt_id=attempt_id, status="failed", started_at="2026-10-01T12:00:00Z",
                                    finished_at="2026-10-01T12:00:01Z", failing_stage=stage,
                                    error_category=category)
            with self.subTest(stage=stage), mock.patch.object(run, "_run_once_locked", return_value=failed), \
                 mock.patch.object(publish, "_publish_locked") as promote:
                result = self.cycle(
                    clock=Clock(T0 + timedelta(days=10 + index)),
                    cycle_id_factory=lambda _, i=index: f"2026100{i}T120000Z-{i + 5:012x}",
                )
            promote.assert_not_called()
            self.assertEqual((result.status, result.sync_failure_category), ("sync_failed", category))
            self.assertEqual((result.previous_live_attempt, result.resulting_live_attempt), (ATTEMPT_ID, ATTEMPT_ID))

    def test_failure_then_success_recovers_resets_counter_and_survives_restart(self):
        first = self.cycle()
        self.assertEqual((first.status, first.resulting_live_attempt), ("published", ATTEMPT_ID))
        denied = Faulty(FakeMonday(logs(), items()), at=1,
                        error=HttpFailure(401, b'{"errors":[{"message":"denied"}]}'))
        failed = self.cycle(
            transport=denied, clock=Clock(T0 + timedelta(days=1)),
            cycle_id_factory=lambda _: "20260921T120000Z-dddddddddddd",
            attempt_id_factory=lambda _: "20260921T120001Z-eeeeeeeeeeee",
            publication_id_factory=lambda _: "20260921T120002Z-ffffffffffff",
        )
        self.assertEqual((failed.status, failed.resulting_live_attempt, failed.consecutive_scheduled_failures),
                         ("sync_failed", ATTEMPT_ID, 1))
        self.assertNotIn(alerts.SCHEDULED_FAILURES, failed.active_alert_types)

        recovered_attempt = "20260922T120001Z-222222222222"
        recovered = self.cycle(
            transport=FakeMonday(logs(), items()), clock=Clock(T0 + timedelta(days=2)),
            cycle_id_factory=lambda _: "20260922T120000Z-111111111111",
            attempt_id_factory=lambda _: recovered_attempt,
            publication_id_factory=lambda _: "20260922T120002Z-333333333333",
        )
        self.assertEqual((recovered.status, recovered.resulting_live_attempt,
                          recovered.consecutive_scheduled_failures), ("published", recovered_attempt, 0))
        self.assertNotIn(alerts.SCHEDULED_FAILURES, recovered.active_alert_types)
        restarted = alerts.read_alert_state(self.config.lock_dir)
        self.assertEqual(restarted["last_observation"]["consecutive_scheduled_failures"], 0)

    def test_three_scheduled_failures_open_critical_alert_but_manual_or_locked_do_not_count(self):
        self.assertEqual(self.cycle().status, "published")
        latest = None
        for index in range(1, 4):
            denied = Faulty(FakeMonday(logs(), items()), at=1,
                            error=HttpFailure(401, b'{"errors":[{"message":"denied"}]}'))
            latest = self.cycle(
                transport=denied, clock=Clock(T0 + timedelta(days=index)),
                cycle_id_factory=lambda _, i=index: f"2026092{i}T130000Z-{i:012x}",
                attempt_id_factory=lambda _, i=index: f"2026092{i}T130001Z-{i + 3:012x}",
                publication_id_factory=lambda _, i=index: f"2026092{i}T130002Z-{i + 6:012x}",
            )
        assert latest is not None
        self.assertEqual(latest.consecutive_scheduled_failures, 3)
        self.assertIn(alerts.SCHEDULED_FAILURES, latest.active_alert_types)
        state = alerts.read_alert_state(self.config.lock_dir)
        incident = next(item for item in state["incidents"] if item["kind"] == alerts.SCHEDULED_FAILURES)
        self.assertEqual((incident["state"], incident["severity"]), ("active", "critical"))

        before = state["last_observation"]["consecutive_scheduled_failures"]
        with lock.production_lock(self.config, "publish", clock=lambda: T0):
            skipped = self.cycle(
                clock=Clock(T0 + timedelta(days=5)),
                cycle_id_factory=lambda _: "20260925T130000Z-aaaaaaaaaaaa",
            )
        self.assertEqual((skipped.status, scheduled.exit_code(skipped)), ("locked", 75))
        self.assertEqual(alerts.read_alert_state(self.config.lock_dir)["last_observation"]["consecutive_scheduled_failures"], before)


if __name__ == "__main__":
    unittest.main()
