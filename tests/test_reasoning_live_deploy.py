"""Reasoning V3 live topology (REV/20 rollout): the production WSGI entry point and ``compose.reasoning-live.yaml``.

The Phase 20-B artifacts (``compose.reasoning.yaml``, ``reasoning.env.example``) are unchanged and keep their own tests
(``test_reasoning_ops_deploy``). This file checks what the live rollout adds: the database is unreachable from outside its internal
network, the web process publishes one loopback port only, every secret is a read-only file, and the WSGI entry point is exactly
``create_app`` (it refuses to start with Reasoning V3 off and serves nothing in shadow).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "deploy" / "production"
LIVE = PRODUCTION / "compose.reasoning-live.yaml"
TOPOLOGY_DOC = ROOT / "docs" / "REASONING-V3-LIVE-TOPOLOGY.md"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def services(compose: str) -> dict[str, str]:
    body = compose.split("\nservices:\n", 1)[1].split("\nnetworks:\n", 1)[0]
    parts = re.split(r"(?m)^  ([a-z][a-z0-9-]*):\n", body)
    return dict(zip(parts[1::2], parts[2::2]))


class LiveComposeTests(unittest.TestCase):
    def test_services_and_profiles(self):
        blocks = services(text(LIVE))
        self.assertEqual(set(blocks), {"reasoning-db", "reasoning-web", "reasoning-ops"})
        for name in ("reasoning-db", "reasoning-web"):
            self.assertIn('profiles: ["reasoning-live"]', blocks[name])
            self.assertIn("restart: unless-stopped", blocks[name])
        # reasoning-ops keeps its Phase 20-B definition (profile, read-only default command); only networks and the site mount are added
        self.assertNotRegex(blocks["reasoning-ops"], r"(?m)^\s+(command|entrypoint|profiles|restart|environment|image):")

    def test_database_is_internal_only(self):
        compose = text(LIVE)
        db = services(compose)["reasoning-db"]
        self.assertNotRegex(db, r"(?m)^\s+(ports|expose|network_mode):")
        self.assertRegex(db, r"networks:\n\s+- reasoning-db\n")
        self.assertRegex(compose, r"(?m)^networks:\n  reasoning-db:\n    internal: true\n")
        self.assertRegex(db, r"image: \$\{ATLAS_REASONING_DB_IMAGE:-postgres:17-bookworm@sha256:[0-9a-f]{64}\}")
        self.assertIn("POSTGRES_PASSWORD_FILE: /run/secrets/reasoning_db_password", db)
        self.assertNotRegex(db, r"(?m)^\s+POSTGRES_PASSWORD:")

    def test_only_one_loopback_port_is_published(self):
        compose = text(LIVE)
        self.assertEqual(re.findall(r"(?m)^\s+ports:\n\s+- (.+)$", compose), ['"127.0.0.1:${ATLAS_REASONING_WEB_PORT:-18002}:8080"'])
        self.assertNotIn("0.0.0.0:", compose.replace('"0.0.0.0:8080"', ""))   # gunicorn binds inside the container only

    def test_hardening(self):
        blocks = services(text(LIVE))
        ops = services(text(PRODUCTION / "compose.reasoning.yaml"))["reasoning-ops"]
        for name, user in (("reasoning-db", 'user: "999:999"'), ("reasoning-web", 'user: "${ATLAS_UID:-10001}:${ATLAS_GID:-10001}"')):
            block = blocks[name]
            for line in ("read_only: true", "- no-new-privileges:true", "cap_drop:\n      - ALL", user, "/tmp:size=32m,mode=1777"):
                self.assertIn(line, block, name)
            self.assertNotRegex(block, r"(?m)^\s+(privileged|pid|ipc|cap_add|devices|network_mode|extends):")
        self.assertIn(user, ops)

    def test_web_environment_is_the_operations_allow_list_plus_web_settings(self):
        def environment(block: str) -> dict[str, str]:
            body = block.split("environment:\n", 1)[1].split("    volumes:\n", 1)[0]
            return {m.group(1): m.group(2).strip() for m in re.finditer(r"(?m)^\s+([A-Z][A-Z0-9_]+): ?(.*)$", body)}

        ops = environment(services(text(PRODUCTION / "compose.reasoning.yaml"))["reasoning-ops"])
        web = environment(services(text(LIVE))["reasoning-web"])
        self.assertEqual({name: web[name] for name in ops}, ops)        # same names and the same defaults: no drift
        self.assertEqual(set(web) - set(ops), {"ATLAS_REASONING_MANAGERS", "ATLAS_REASONING_ALLOWED_ORIGINS", "ATLAS_REASONING_ACTOR_HEADER",
                                               "ATLAS_REASONING_CSRF_SECRET_FILE", "ATLAS_REASONING_DIAGNOSTICS_URL",
                                               "ATLAS_REASONING_MONDAY_ITEM_URL"})

    def test_secrets_are_read_only_files(self):
        compose = text(LIVE)
        mounts = re.findall(r"source: (\S+)\n\s+target: (/run/secrets/\S+)\n\s+read_only: true", compose)
        self.assertEqual({target for _, target in mounts}, {"/run/secrets/reasoning_db_password", "/run/secrets/reasoning_csrf_secret",
                                                          "/run/secrets/reasoning_database_url", "/run/secrets/openrouter_api_key",
                                                          "/run/secrets/honcho_api_key"})
        for source, _ in mounts:
            self.assertRegex(source, r"^\$\{ATLAS_REASONING_HOST_[A-Z_]+_FILE:-/etc/waset-atlas/secrets/[a-z_]+\}$")
        for name in ("ATLAS_REASONING_DATABASE_URL", "OPENROUTER_API_KEY", "HONCHO_API_KEY", "ATLAS_REASONING_CSRF_SECRET"):
            self.assertNotRegex(compose, rf"(?m)^\s+{name}:")

    def test_site_mount_is_read_only(self):
        ops = services(text(LIVE))["reasoning-ops"]
        self.assertIn("target: /var/lib/waset-atlas\n        read_only: true", ops)

    def test_web_process_serves_the_wsgi_entry_point(self):
        web = services(text(LIVE))["reasoning-web"]
        self.assertIn('entrypoint: ["gunicorn"]', web)
        self.assertIn('"atlas_reasoning.wsgi:application"', web)
        self.assertIn("ATLAS_REASONING_CSRF_SECRET_FILE: /run/secrets/reasoning_csrf_secret", web)
        requirements = text(PRODUCTION / "reasoning-runtime-requirements.txt")
        self.assertIn("gunicorn==23.0.0", requirements)
        self.assertNotIn("gunicorn", text(PRODUCTION / "runtime-requirements.txt"))

    def test_deterministic_deployment_is_unchanged(self):
        self.assertNotIn("reasoning", text(PRODUCTION / "compose.yaml").lower())
        self.assertNotIn("reasoning", text(PRODUCTION / "nginx.conf"))

    def test_topology_doc_describes_the_rollback(self):
        doc = text(TOPOLOGY_DOC)
        for needle in ("compose.reasoning-live.yaml", "ATLAS_REASONING_ACTOR_HEADER", "reasoning-db", "reasoning-web", "Rollback"):
            self.assertIn(needle, doc)
        self.assertNotRegex(doc, r"(?i)\bDROP (TABLE|SCHEMA|DATABASE)\b|rm -rf|down -v|volume rm")


class DailyScheduleTests(unittest.TestCase):
    def test_timer_runs_once_per_day_and_the_hourly_sync_is_unchanged(self):
        timer = text(PRODUCTION / "waset-atlas-reasoning.timer")
        calendars = re.findall(r"(?m)^OnCalendar=(.+)$", timer)
        self.assertEqual(calendars, ["*-*-* 03:40:00 UTC"])
        self.assertIn("Unit=waset-atlas-reasoning.service", timer)
        self.assertIn("OnCalendar=hourly", text(PRODUCTION / "waset-atlas.timer"))
        self.assertNotIn("reasoning", text(PRODUCTION / "waset-atlas.service").lower())

    def test_service_is_a_hardened_oneshot_running_the_script(self):
        service = text(PRODUCTION / "waset-atlas-reasoning.service")
        for line in ("Type=oneshot", "Restart=no", "NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes",
                     "ExecStart=/opt/waset-atlas/current/deploy/production/reasoning-daily.sh", "ConditionPathExists=/etc/waset-atlas/reasoning.env"):
            self.assertIn(line, service)

    def test_script_gates_first_and_reasons_only_when_there_is_work(self):
        script = text(PRODUCTION / "reasoning-daily.sh")
        self.assertTrue(script.startswith("#!/bin/sh\n"))
        self.assertIn("set -eu", script)
        for name in ("compose.yaml", "compose.reasoning.yaml", "compose.reasoning-live.yaml"):
            self.assertIn(f"$ROOT/deploy/production/{name}", script)
        self.assertIn("--env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env", script)
        self.assertIn("reasoning-ops gate /var/lib/waset-atlas/published/current", script)
        self.assertIn('if [ "$work" -eq 0 ]; then', script)
        self.assertLess(script.index("reasoning-ops gate"), script.index("reasoning-ops reason"))
        commands = re.findall(r"reasoning-ops ([a-z-]+)", script)
        self.assertEqual(commands, ["gate", "reason"])       # no migrate, memory-sync, evaluate or provider calls of its own
        self.assertTrue((PRODUCTION / "reasoning-daily.sh").stat().st_mode & 0o111)

    def test_script_skips_reason_when_the_gate_reports_no_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / "calls"
            fake = Path(tmp) / "docker"
            fake.write_text("#!/bin/sh\necho \"$@\" >> " + str(calls) + "\n"
                            "case \"$*\" in *\" gate \"*) echo '{\"run_id\": \"run_x\", \"counts\": {\"llm_work_items\": '\"$WORK\"', \"lifecycle_work_items\": 0}}';; esac\n",
                            encoding="utf-8")
            fake.chmod(0o755)
            script = text(PRODUCTION / "reasoning-daily.sh").replace("/usr/bin/docker", str(fake))
            for work, expected in (("0", ["gate"]), ("3", ["gate", "reason"])):
                calls.write_text("", encoding="utf-8")
                result = subprocess.run(["sh", "-c", script], env={**os.environ, "WORK": work}, capture_output=True, text=True, timeout=60, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                ran = [re.search(r"reasoning-ops ([a-z-]+)", line).group(1) for line in calls.read_text().splitlines()]
                self.assertEqual(ran, expected, work)


class WsgiEntryPointTests(unittest.TestCase):
    def run_wsgi(self, extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
        script = ("import io, json, sys\n"
                  "from atlas_reasoning.wsgi import application\n"
                  "out = {}\n"
                  "def start(status, headers): out['status'] = status\n"
                  "body = b''.join(application({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/reasoning/en/', 'wsgi.input': io.BytesIO(),"
                  " 'HTTP_X_ATLAS_ACTOR': 'manager@example.com'}, start))\n"
                  "print(json.dumps(out))\n")
        env = {key: value for key, value in os.environ.items() if not key.startswith(("ATLAS_REASONING", "OPENROUTER", "HONCHO"))}
        env.update({"PYTHONPATH": str(ROOT / "src")}, **extra)
        return subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=60, check=False)

    def test_refuses_to_start_with_reasoning_off(self):
        result = self.run_wsgi({"ATLAS_REASONING_V3": "off"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ReasoningDisabled", result.stderr)

    def test_shadow_serves_nothing_and_opens_no_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / "csrf"
            secret.write_text("s" * 48 + "\n", encoding="utf-8")
            result = self.run_wsgi({"ATLAS_REASONING_V3": "on", "ATLAS_REASONING_AUDIENCE": "none",
                                    "ATLAS_REASONING_DATABASE_URL": "postgresql://nobody@127.0.0.1:1/unreachable",
                                    "ATLAS_REASONING_CSRF_SECRET_FILE": str(secret), "ATLAS_REASONING_ACTOR_HEADER": "X-Atlas-Actor",
                                    "ATLAS_REASONING_MANAGERS": "manager@example.com"})
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertEqual(json.loads(result.stdout.splitlines()[-1])["status"], "404 Not Found")


if __name__ == "__main__":
    unittest.main()
