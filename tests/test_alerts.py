"""Task 8 persisted operational alert state and deterministic lifecycle."""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from atlas_sync import alerts, status
from atlas_sync.status import HealthCheck, StatusSnapshot

NOW = "2026-09-29T12:00:00Z"
TOKEN = "never-persist-this-token"


def snapshot(*, freshness="fresh", checks=(), warnings=(), threshold=3, age=100.0, scope="runtime"):
    return StatusSnapshot(
        generated_at=NOW, snapshot_scope=scope, system_state="healthy", freshness_state=freshness,
        live_usable=True, current_publication={"attempt_id": "20260929T100000Z-aaaaaaaaaaaa"},
        last_attempt=None, last_successful_attempt=None,
        freshness={"age_seconds": age, "expected_interval_seconds": 3600, "stale_after_seconds": 7200},
        failure_threshold=threshold, checks=list(checks), warnings=list(warnings),
    )


def cycle(number, result="failed", **extra):
    return {
        "cycle_id": f"cycle-{number}", "scheduled_for": f"2026-09-29T{number:02d}:00:00Z",
        "finished_at": f"2026-09-29T{number:02d}:01:00Z", "status": result,
        "error_category": "timeout" if result == "failed" else None, **extra,
    }


class AlertStateTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-alerts-"))

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    def update(self, state=None, cycles=(), at=NOW):
        return alerts.update_alert_state(snapshot=state or snapshot(), scheduled_cycles=cycles,
                                         data_dir=self.data, observed_at=at)

    def test_stale_uses_status_boundary_and_is_critical(self):
        now = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
        at_boundary = "2026-09-29T10:00:00Z"
        before = "2026-09-29T10:00:00.001000Z"
        self.assertEqual(status._freshness_values(before, 3600, 7200, now)[0], "delayed")
        self.assertEqual(status._freshness_values(at_boundary, 3600, 7200, now)[0], "stale")
        self.assertEqual(alerts.derive_alert_signals(snapshot(freshness="delayed", age=7199.999), ()), ())
        signals = alerts.derive_alert_signals(snapshot(freshness="stale", age=7200), ())
        self.assertEqual([(signal.kind, signal.severity) for signal in signals], [(alerts.DATA_STALE, alerts.CRITICAL)])
        self.assertEqual(signals[0].evidence, {"age_seconds": 7200, "stale_after_seconds": 7200})

    def test_scheduled_failure_threshold_exact_boundary_and_success_reset(self):
        two = alerts.derive_alert_signals(snapshot(), [cycle(1), cycle(2)])
        self.assertEqual(two, ())
        below = self.update(snapshot(), [cycle(1), cycle(2)])
        self.assertEqual((below.consecutive_scheduled_failures, below.active_incidents), (2, ()))
        persisted = alerts.read_alert_state(self.data)
        self.assertEqual(persisted["last_observation"]["consecutive_scheduled_failures"], 2)
        three = alerts.derive_alert_signals(snapshot(), [cycle(1), cycle(2), cycle(3)])
        self.assertEqual((three[0].kind, three[0].severity, three[0].evidence["failure_threshold"]),
                         (alerts.SCHEDULED_FAILURES, alerts.CRITICAL, 3))
        four = alerts.derive_alert_signals(snapshot(), [cycle(1), cycle(2), cycle(3), cycle(4)])
        self.assertEqual(four[0].severity, alerts.CRITICAL)
        self.assertEqual(alerts.derive_alert_signals(snapshot(), [cycle(1), cycle(2, "success")]), ())

    def test_running_cycle_does_not_erase_persisted_failure_streak(self):
        records = [cycle(1), cycle(2, "running"), cycle(3, "locked"), cycle(4, "skipped"), {"not": "a cycle"}]
        self.assertEqual(alerts.scheduled_failure_streak(records), 1)

    def test_publication_integrity_is_critical_and_metadata_is_warning(self):
        state = snapshot(
            checks=[HealthCheck("artifact_hashes", "failed", "build_tampered"),
                    HealthCheck("current_metadata", "warning", "current_metadata_inconsistent")],
            warnings=["publication_metadata_inconsistent"],
        )
        state.live_usable = False
        signals = {signal.kind: signal for signal in alerts.derive_alert_signals(state, ())}
        self.assertEqual(signals[alerts.PUBLICATION_INTEGRITY].severity, alerts.CRITICAL)
        self.assertEqual(signals[alerts.PUBLICATION_INTEGRITY].evidence["failed_checks"], ["artifact_hashes"])
        self.assertEqual(signals[alerts.METADATA_INCONSISTENCY].severity, alerts.WARNING)
        # A Task 7 system failure without a publication check is not reinterpreted here.
        state.system_state = "failed"
        state.live_usable = True
        state.checks = [HealthCheck("configuration", "failed", "configuration")]
        state.warnings = []
        self.assertEqual(alerts.derive_alert_signals(state, ()), ())

    def test_dedupe_update_resolution_and_reactivation_are_persisted(self):
        stale = snapshot(freshness="stale", age=7200)
        first = self.update(stale)
        first_id = first.active_incidents[0]["incident_id"]
        self.assertEqual(first.emitted_events[0]["action"], "opened")

        second = self.update(stale, at="2026-09-29T12:05:00Z")
        self.assertEqual((len(second.active_incidents), second.active_incidents[0]["incident_id"]), (1, first_id))
        self.assertEqual((second.active_incidents[0]["occurrence_count"], second.active_incidents[0]["last_observed_at"]),
                         (2, "2026-09-29T12:05:00Z"))
        self.assertEqual(second.emitted_events[0]["action"], "updated")

        resolved = self.update(snapshot(), at="2026-09-29T12:10:00Z")
        self.assertEqual(resolved.active_incidents, ())
        self.assertEqual(resolved.emitted_events[0]["action"], "resolved")
        persisted = alerts.read_alert_state(self.data)
        self.assertEqual(persisted["incidents"][0]["last_observed_at"], "2026-09-29T12:05:00Z")
        self.assertEqual(persisted["incidents"][0]["resolved_at"], "2026-09-29T12:10:00Z")

        returned = self.update(stale, at="2026-09-29T12:15:00Z")
        new_incident = returned.active_incidents[0]
        self.assertNotEqual(new_incident["incident_id"], first_id)
        self.assertEqual(new_incident["previous_incident_id"], first_id)
        self.assertEqual(returned.emitted_events[0]["action"], "reactivated")

    def test_state_survives_restart_and_single_file_is_atomically_replaced(self):
        self.update(snapshot(freshness="stale", age=7200))
        state_path = self.data / "alerts/state.json"
        reloaded = alerts.read_alert_state(self.data)
        self.assertEqual(reloaded["alert_version"], alerts.ALERT_VERSION)
        self.assertEqual(reloaded["incidents"][0]["occurrence_count"], 1)
        self.update(snapshot(freshness="stale", age=7300), at="2026-09-29T12:01:00Z")
        reloaded = json.loads(state_path.read_text())
        self.assertEqual(reloaded["incidents"][0]["occurrence_count"], 2)
        self.assertEqual(list((self.data / "alerts").glob("*.tmp")), [])

    def test_stale_temporary_file_from_crash_cannot_block_restart(self):
        root = self.data / alerts.ALERTS_DIR
        root.mkdir(parents=True)
        stale = root / f".{alerts.STATE_FILE}.{os.getpid()}.tmp"
        stale.write_text("crash residue")
        update = self.update(snapshot(freshness="stale", age=7200))
        self.assertTrue(update.state_path.is_file())
        self.assertEqual(update.active_incidents[0]["kind"], alerts.DATA_STALE)
        self.assertEqual(stale.read_text(), "crash residue")

    def test_only_safe_allowlisted_fields_are_persisted(self):
        unsafe = [cycle(number, raw_exception=f"traceback {TOKEN}", authorization=TOKEN,
                        error_category=f"timeout-{TOKEN}") for number in range(1, 4)]
        self.update(snapshot(freshness="stale", age=7200), unsafe)
        encoded = (self.data / "alerts/state.json").read_text()
        self.assertNotIn(TOKEN, encoded)
        self.assertNotIn("traceback", encoded)
        self.assertNotIn("authorization", encoded)

    def test_build_time_snapshot_and_corrupt_existing_state_fail_closed(self):
        with self.assertRaises(alerts.AlertStateError):
            self.update(snapshot(scope="build_time"))
        state_path = self.data / "alerts/state.json"
        state_path.parent.mkdir(exist_ok=True)
        state_path.write_text("not json")
        before = state_path.read_bytes()
        with self.assertRaises(alerts.AlertStateError):
            self.update(snapshot(freshness="stale"))
        self.assertEqual(state_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
