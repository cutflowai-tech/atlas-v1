"""Task 9 static production deployment and runbook contract."""

import re
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from test_ingest import FakeMonday, items
from test_sync_run import HISTORY, T0, TOKEN, Clock, Monotonic, logs

from atlas_sync import publish, scheduled, status
from atlas_sync.config import load_sync_config

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/production"
SERVICE = DEPLOY / "waset-atlas.service"
TIMER = DEPLOY / "waset-atlas.timer"
ENV = DEPLOY / "atlas.env.example"
COMPOSE = DEPLOY / "compose.yaml"
RUNBOOK = ROOT / "docs/PRODUCTION-RUNBOOK.md"


class ProductionDeploymentTests(unittest.TestCase):
    def text(self, path):
        return path.read_text(encoding="utf-8")

    def test_service_runs_exactly_one_scheduler_cycle_in_unprivileged_container(self):
        unit = self.text(SERVICE)
        starts = re.findall(r"^ExecStart=(.+)$", unit, re.MULTILINE)
        expected = (
            "/usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env "
            "--project-directory /opt/waset-atlas/current "
            "-f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps "
            "atlas-runtime scheduled-run --json"
        )
        self.assertEqual(starts, [expected])
        self.assertEqual(starts[0].count("scheduled-run"), 1)
        self.assertIn("Type=oneshot", unit)
        self.assertNotRegex(unit, r"(?m)^(User|Group)=")
        self.assertIn('user: "${ATLAS_UID:-10001}:${ATLAS_GID:-10001}"', self.text(COMPOSE))
        self.assertIn("USER ${ATLAS_UID}:${ATLAS_GID}", self.text(DEPLOY / "Dockerfile.app"))
        self.assertIn("EnvironmentFile=/etc/waset-atlas/atlas.env", unit)
        self.assertIn("Restart=no", unit)
        self.assertIn("TimeoutStartSec=2h15min", unit)
        self.assertIn("SuccessExitStatus=75", unit)
        self.assertNotRegex(unit, r"Restart=(always|on-failure)")

    def test_timer_is_hourly_persistent_and_jittered_without_catchup_loop(self):
        timer = self.text(TIMER)
        self.assertIn("OnCalendar=hourly", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("RandomizedDelaySec=10min", timer)
        self.assertIn("AccuracySec=1min", timer)
        self.assertIn("Unit=waset-atlas.service", timer)
        self.assertNotIn("OnUnitInactiveSec", timer)
        self.assertNotIn("OnBootSec", timer)

    def test_compose_path_service_and_cli_match_repository(self):
        compose = self.text(COMPOSE)
        cli = self.text(ROOT / "src/atlas_sync/__main__.py")
        self.assertIn("atlas-runtime:", compose)
        self.assertIn("scheduled-run", cli)
        self.assertIn('sub.add_parser("scheduled-run"', cli)
        self.assertEqual(compose.count("target: /var/lib/waset-atlas"), 2)
        self.assertNotIn("/var/lib/atlas", compose)
        self.assertIn("/etc/waset-atlas/secrets/monday_api_token", compose)
        self.assertIn("/run/secrets/monday_api_token", compose)
        self.assertIn('restart: "no"', compose)
        self.assertNotRegex(compose, r"(?m)^\s+build:")

    def test_environment_example_is_complete_and_contains_no_secret(self):
        env = self.text(ENV)
        required = {
            "ATLAS_APP_IMAGE", "ATLAS_WEB_IMAGE", "ATLAS_HOST_DATA_DIR", "ATLAS_TOKEN_FILE",
            "ATLAS_UID", "ATLAS_GID", "ATLAS_HTTP_BIND", "ATLAS_HTTP_PORT", "ATLAS_HISTORY_START",
            "ATLAS_SYNC_INTERVAL_SECONDS",
            "ATLAS_STALE_AFTER_SECONDS", "ATLAS_MAX_CONSECUTIVE_FAILURES", "ATLAS_SYNC_MAX_DURATION_SECONDS",
            "ATLAS_CONTRACT_VERSION", "ATLAS_MONDAY_BOARD_ID", "MONDAY_API_VERSION",
        }
        assigned = {match.group(1) for match in re.finditer(r"^([A-Z][A-Z0-9_]*)=", env, re.MULTILINE)}
        self.assertTrue(required <= assigned)
        self.assertNotRegex(env, r"(?m)^MONDAY_API_TOKEN=")
        self.assertIn("ATLAS_TOKEN_FILE=/etc/waset-atlas/secrets/monday_api_token", env)

    def test_units_and_templates_never_embed_credentials(self):
        combined = "\n".join(self.text(path) for path in (SERVICE, TIMER, COMPOSE, ENV))
        self.assertNotRegex(combined, r"(?im)^\s*(MONDAY_API_TOKEN|Authorization)\s*=")
        self.assertNotRegex(combined, r"(?i)Bearer\s+[A-Za-z0-9._-]+")
        self.assertNotIn("REPLACE_WITH_REVIEWED_DIGEST", self.text(SERVICE))

    def test_every_production_compose_command_loads_the_external_environment(self):
        book = self.text(RUNBOOK)
        commands = [line for line in book.splitlines() if line.startswith("sudo /usr/bin/docker compose")]
        self.assertGreaterEqual(len(commands), 10)
        for command in commands:
            self.assertIn("compose --env-file /etc/waset-atlas/atlas.env ", command)
        self.assertIn("compose --env-file /etc/waset-atlas/atlas.env ", self.text(SERVICE))

    def test_runbook_has_required_operations_and_exact_recovery_commands(self):
        book = self.text(RUNBOOK)
        for heading in (
            "Host setup and permissions", "Configuration and secrets", "Data layout and truth hierarchy",
            "Deploy a release", "Normal operation", "Manual operations", "Failure response",
            "Metadata inconsistency recovery", "Upgrade and restart", "Security, disk, and backups",
            "Task 10 preparation",
        ):
            self.assertIn(heading, book)
        for command in (
            "sudo systemctl stop waset-atlas.timer", "systemctl is-active waset-atlas.service",
            "atlas-runtime status --json", "readlink /var/lib/waset-atlas/published/current",
            "atlas-runtime publish ATTEMPT_ID --json", "sudo systemctl start waset-atlas.timer",
        ):
            self.assertIn(command, book)
        self.assertIn("Task 6", book)
        self.assertIn("exit 75", book)
        self.assertIn("no retention deletion", book)
        self.assertIn("https://atlas.wasetco.com", book)
        self.assertIn("TLS", book)
        self.assertIn("not delivered externally", book)
        for failure in ("Monday unavailable", "Stale data", "Consecutive failures", "Build failure",
                        "Publish failure", "Lock contention"):
            self.assertIn(failure, book)
        self.assertNotIn("rm -rf", book)
        self.assertNotIn("find /var/lib/waset-atlas -delete", book)

    def test_fake_monday_cycle_status_lock_and_rollback_use_production_layout(self):
        data = Path(tempfile.mkdtemp(prefix="atlas-production-layout-"))
        try:
            env = {"MONDAY_API_TOKEN": TOKEN, "ATLAS_DATA_DIR": str(data), "ATLAS_HISTORY_START": HISTORY}
            config = load_sync_config(env, now=T0)

            def cycle(day, letter):
                instant = T0 + timedelta(days=day)
                return scheduled.scheduled_run(
                    config=config, transport=FakeMonday(logs(), items()), clock=Clock(instant),
                    monotonic=Monotonic(), sleep=lambda _: None,
                    cycle_id_factory=lambda _: f"2026092{day}T120000Z-{letter * 12}",
                    attempt_id_factory=lambda _: f"2026092{day}T120001Z-{chr(ord(letter) + 1) * 12}",
                    publication_id_factory=lambda _: f"2026092{day}T120002Z-{chr(ord(letter) + 2) * 12}",
                )

            first = cycle(0, "a")
            second = cycle(1, "d")
            self.assertEqual((first.status, second.status), ("published", "published"))
            snapshot = status.evaluate_status(config=config, clock=lambda: T0 + timedelta(days=1))
            self.assertTrue(snapshot.live_usable)
            self.assertEqual(publish.live_attempt(config), second.attempt_id)
            rolled_back = publish.rollback(config=config, clock=Clock(T0 + timedelta(days=2)),
                                           publication_id_factory=lambda _: "20260922T120002Z-gggggggggggg")
            self.assertEqual((rolled_back.status, publish.live_attempt(config)), ("published", first.attempt_id))
            self.assertTrue((data / "raw/monday").is_dir())
            for path in ("builds", "published/current", "published/history", "locks/scheduled-cycles",
                         "locks/alerts/state.json"):
                self.assertTrue((data / path).exists(), path)
        finally:
            shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
