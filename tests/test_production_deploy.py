"""Task 9 static production deployment and runbook contract."""

import re
import unittest
from pathlib import Path

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

    def test_service_runs_exactly_one_scheduler_cycle_as_atlas(self):
        unit = self.text(SERVICE)
        starts = re.findall(r"^ExecStart=(.+)$", unit, re.MULTILINE)
        expected = (
            "/usr/bin/docker compose --project-directory /opt/waset-atlas/current "
            "-f /opt/waset-atlas/current/deploy/production/compose.yaml run --rm --no-deps "
            "atlas-runtime scheduled-run --json"
        )
        self.assertEqual(starts, [expected])
        self.assertEqual(starts[0].count("scheduled-run"), 1)
        self.assertIn("Type=oneshot", unit)
        self.assertIn("User=atlas", unit)
        self.assertIn("Group=atlas", unit)
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
        self.assertIn("/var/lib/waset-atlas", compose)
        self.assertIn("/var/lib/atlas", compose)
        self.assertIn("/etc/waset-atlas/secrets/monday_api_token", compose)
        self.assertIn("/run/secrets/monday_api_token", compose)
        self.assertIn('restart: "no"', compose)

    def test_environment_example_is_complete_and_contains_no_secret(self):
        env = self.text(ENV)
        required = {
            "ATLAS_IMAGE", "ATLAS_DATA_DIR", "ATLAS_HISTORY_START", "ATLAS_SYNC_INTERVAL_SECONDS",
            "ATLAS_STALE_AFTER_SECONDS", "ATLAS_MAX_CONSECUTIVE_FAILURES", "ATLAS_SYNC_MAX_DURATION_SECONDS",
            "ATLAS_CONTRACT_VERSION", "ATLAS_MONDAY_BOARD_ID", "MONDAY_API_VERSION", "MONDAY_API_TOKEN_FILE",
        }
        assigned = {match.group(1) for match in re.finditer(r"^([A-Z][A-Z0-9_]*)=", env, re.MULTILINE)}
        self.assertTrue(required <= assigned)
        self.assertNotRegex(env, r"(?m)^MONDAY_API_TOKEN=")
        self.assertIn("MONDAY_API_TOKEN_FILE=/run/secrets/monday_api_token", env)

    def test_units_and_templates_never_embed_credentials(self):
        combined = "\n".join(self.text(path) for path in (SERVICE, TIMER, COMPOSE, ENV))
        self.assertNotRegex(combined, r"(?im)^\s*(MONDAY_API_TOKEN|Authorization)\s*=")
        self.assertNotRegex(combined, r"(?i)Bearer\s+[A-Za-z0-9._-]+")
        self.assertNotIn("REPLACE_WITH_REVIEWED_DIGEST", self.text(SERVICE))

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
        self.assertNotIn("rm -rf", book)
        self.assertNotIn("find /var/lib/waset-atlas -delete", book)


if __name__ == "__main__":
    unittest.main()
