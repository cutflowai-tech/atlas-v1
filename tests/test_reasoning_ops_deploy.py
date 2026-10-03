"""Phase 20-B: static production-readiness checks for Reasoning V3 (no database, no Docker, no network, no live system).

Deployment configuration (the Compose overlay, the image, the environment template) is validated statically: structure, interpolation
with the tracked example values, hardening, no published port, nothing started by default, no committed secret. The deterministic Atlas
deployment is unchanged. The release checklist detects missing or inconsistent metadata. The credential scan passes on the deployment
surface and reports findings without their values. Docs and tooling agree with the code (metrics, commands, checklist items).
"""

from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "deploy" / "production"
sys.path.insert(0, str(PRODUCTION))

from reasoning_ops import release_checklist, secret_scan

BASE_COMPOSE = PRODUCTION / "compose.yaml"
OVERLAY = PRODUCTION / "compose.reasoning.yaml"
ENV_EXAMPLE = PRODUCTION / "reasoning.env.example"
ATLAS_ENV_EXAMPLE = PRODUCTION / "atlas.env.example"
DOCKERFILE = PRODUCTION / "Dockerfile.reasoning"
DOCS = {name: ROOT / "docs" / f"REASONING-V3-{name}.md" for name in ("PRODUCTION-ROLLOUT", "RECOVERY", "RELEASE-CHECKLIST", "MONITORING")}
RUNBOOK = ROOT / "docs" / "PRODUCTION-RUNBOOK.md"
_VAR = re.compile(r"\$\{([A-Z0-9_]+)(?:(:?)-([^}]*))?\}")
# Phase 20-A's *planned* interfaces (PR #45; merged after this branch): its rollout variables and operator commands. Nothing here imports
# or runs Phase 20-A code; the overlay only passes these names through (inert until Phase 20-A lands) and the docs label them.
PHASE20A_ROLLOUT_ENVS = frozenset({"ATLAS_REASONING_EXECUTION", "ATLAS_REASONING_AUDIENCE", "ATLAS_REASONING_CARDS_PRIMARY",
                                   "ATLAS_REASONING_HUMAN_CONTEXT", "ATLAS_REASONING_EXECUTIVE_HOME"})
PHASE20A_COMMANDS = frozenset({"rollout", "release-metadata", "release-eligibility"})
# Settings only the web process reads, and secret values (always *_FILE mounts): never in the operations container's environment.
WEB_ONLY = frozenset({"ATLAS_REASONING_MANAGERS", "ATLAS_REASONING_ALLOWED_ORIGINS", "ATLAS_REASONING_ACTOR_HEADER", "ATLAS_REASONING_CSRF_SECRET",
                      "ATLAS_REASONING_CSRF_SECRET_FILE", "ATLAS_REASONING_DIAGNOSTICS_URL", "ATLAS_REASONING_MONDAY_ITEM_URL"})


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def env_assignments(path: Path) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(r"(?m)^([A-Z][A-Z0-9_]*)=(.*)$", text(path))}


def services(compose: str) -> dict[str, str]:
    """The restricted Compose subset used here: two-space service keys under ``services:``; returns each service's block."""
    body = compose.split("\nservices:\n", 1)[1]
    blocks: dict[str, str] = {}
    for match in re.finditer(r"(?m)^  ([a-z][a-z0-9-]*):\n((?:(?:    .*|\s*)\n)*)", body + "\n"):
        blocks[match.group(1)] = match.group(2)
    return blocks


def interpolate(compose: str, env: dict[str, str]) -> str:
    """``docker compose config`` interpolation: ``${VAR:-default}`` (unset or empty -> default), ``${VAR-default}`` (only unset ->
    default), ``${VAR}``; an unset variable without a default is an error."""
    def value(match: re.Match[str]) -> str:
        name, colon, default = match.group(1), match.group(2), match.group(3)
        if name in env and (env[name] or not colon or default is None):
            return env[name]
        if default is None:
            raise AssertionError(f"${{{name}}} has no value and no default")
        return default
    return _VAR.sub(value, compose)


def known_settings() -> set[str]:
    """Every environment variable name the application code reads, plus Phase 20-A's rollout controls."""
    names: set[str] = set(PHASE20A_ROLLOUT_ENVS)
    for path in (ROOT / "src" / "atlas_reasoning").rglob("*.py"):
        names |= set(re.findall(r'"((?:ATLAS_REASONING|ATLAS_HONCHO|HONCHO|OPENROUTER)_[A-Z0-9_]+)"', text(path)))
    return names


def overlay_environment() -> dict[str, str]:
    block = services(text(OVERLAY))["reasoning-ops"].split("environment:", 1)[1].split("volumes:", 1)[0]
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(?m)^\s+([A-Z][A-Z0-9_]+): ?(.*)$", block)}


class ComposeOverlayTests(unittest.TestCase):
    def test_overlay_defines_only_the_opt_in_operations_service(self):
        blocks = services(text(OVERLAY))
        self.assertEqual(set(blocks), {"reasoning-ops"})
        ops = blocks["reasoning-ops"]
        self.assertIn('profiles: ["reasoning-operations"]', ops)
        self.assertIn('restart: "no"', ops)
        self.assertIn('command: ["db-health"]', ops)                      # read-only by default
        self.assertNotRegex(ops, r"command:.*(?:reason|migrate|memory-sync|evaluate)")

    def test_no_port_is_published_and_no_host_network(self):
        overlay = text(OVERLAY)
        self.assertNotRegex(overlay, r"(?m)^\s+(ports|expose|network_mode|privileged|pid|ipc|cap_add|devices):")
        self.assertNotIn("0.0.0.0", overlay)

    def test_hardening_matches_the_existing_runtime_service(self):
        ops = services(text(OVERLAY))["reasoning-ops"]
        runtime = services(text(BASE_COMPOSE))["atlas-runtime"]
        for line in ('user: "${ATLAS_UID:-10001}:${ATLAS_GID:-10001}"', "read_only: true", "init: true", "- no-new-privileges:true",
                     "cap_drop:\n      - ALL", "/tmp:size=32m,mode=1777"):
            self.assertIn(line, runtime)
            self.assertIn(line, ops)

    def test_secrets_are_read_only_files_never_values(self):
        overlay = text(OVERLAY)
        mounts = re.findall(r"source: (\S+)\n\s+target: (\S+)\n\s+read_only: true", overlay)
        self.assertEqual({target for _, target in mounts},
                         {"/run/secrets/reasoning_database_url", "/run/secrets/openrouter_api_key", "/run/secrets/honcho_api_key"})
        for source, _ in mounts:
            self.assertRegex(source, r"^\$\{ATLAS_REASONING_HOST_[A-Z_]+_FILE:-/etc/waset-atlas/secrets/[a-z_]+\}$")
        environment = services(overlay)["reasoning-ops"].split("environment:", 1)[1].split("volumes:", 1)[0]
        for name in ("ATLAS_REASONING_DATABASE_URL", "OPENROUTER_API_KEY", "HONCHO_API_KEY", "ATLAS_REASONING_CSRF_SECRET"):
            self.assertNotRegex(environment, rf"(?m)^\s+{name}:")         # only the *_FILE forms
        self.assertIn("ATLAS_REASONING_DATABASE_URL_FILE: /run/secrets/reasoning_database_url", environment)

    def test_capabilities_default_off_and_every_variable_is_a_real_setting(self):
        environment = services(text(OVERLAY))["reasoning-ops"].split("environment:", 1)[1].split("volumes:", 1)[0]
        names = set(re.findall(r"(?m)^\s+([A-Z][A-Z0-9_]+):", environment))
        self.assertEqual(names - known_settings(), set(), "the overlay invents no setting")
        env = overlay_environment()
        expected = {"ATLAS_REASONING_V3": "off", "ATLAS_REASONING_MEMORY": "off", "ATLAS_REASONING_EXECUTION": "on", "ATLAS_REASONING_AUDIENCE": "none",
                    "ATLAS_REASONING_CARDS_PRIMARY": "off", "ATLAS_REASONING_HUMAN_CONTEXT": "off", "ATLAS_REASONING_EXECUTIVE_HOME": "off",
                    "ATLAS_REASONING_MODEL": "", "ATLAS_REASONING_ALLOW_MODEL_OVERRIDE": "off"}
        for name, default in expected.items():
            form = "-" if name == "ATLAS_REASONING_EXECUTION" else ":-"
            self.assertEqual(env[name], f"${{{name}{form}{default}}}", name)   # the application's own default; stage 0
        self.assertNotIn("EVALUATION", environment)

    def test_every_documented_switch_reaches_the_container(self):
        """--env-file only feeds interpolation: a switch the runbooks tell operators to flip must be in the environment allow-list."""
        documented = set()
        for path in (DOCS["PRODUCTION-ROLLOUT"], DOCS["RECOVERY"]):
            documented |= set(re.findall(r"`((?:ATLAS_REASONING|ATLAS_HONCHO)_[A-Z0-9_]+)(?:=[^`]*)?`", text(path)))
        runtime = (documented & known_settings()) - WEB_ONLY - {"ATLAS_REASONING_DATABASE_URL", "ATLAS_REASONING_DATABASE_URL_FILE"}
        self.assertTrue({"ATLAS_REASONING_EXECUTION", "ATLAS_REASONING_MODEL", "ATLAS_REASONING_ALLOW_MODEL_OVERRIDE"} <= runtime)
        self.assertEqual(runtime - set(overlay_environment()), set())


    def test_interpolation_with_the_tracked_examples_resolves_everything(self):
        env = env_assignments(ATLAS_ENV_EXAMPLE) | env_assignments(ENV_EXAMPLE)
        merged = interpolate(text(BASE_COMPOSE), env) + interpolate(text(OVERLAY), env)
        self.assertNotIn("${", merged)
        self.assertIn("image: registry.example.com/waset/atlas-reasoning@sha256:REPLACE_WITH_REVIEWED_DIGEST", merged)
        self.assertIn("ATLAS_REASONING_V3: off", merged)
        self.assertIn('"127.0.0.1:18000:8080"', merged)                     # the only published port is still atlas-web on loopback
        self.assertEqual(len(re.findall(r"(?m)^\s+ports:", merged)), 1)
        # and with an empty environment every reference still has a safe default
        self.assertIn("ATLAS_REASONING_V3: off", interpolate(text(OVERLAY), {}))
        self.assertIn("ATLAS_REASONING_EXECUTION: on", interpolate(text(OVERLAY), {}))

    def test_a_blank_kill_switch_is_never_turned_on(self):
        """PR #45 review L-4: an operator who blanks ATLAS_REASONING_EXECUTION gets blank (the application's off), never `on`."""
        resolved = interpolate(text(OVERLAY), {"ATLAS_REASONING_EXECUTION": ""})
        self.assertRegex(resolved, r"(?m)^\s+ATLAS_REASONING_EXECUTION: $")
        self.assertIn("ATLAS_REASONING_EXECUTION: off", interpolate(text(OVERLAY), {"ATLAS_REASONING_EXECUTION": "off"}))
        from atlas_reasoning import settings

        self.assertFalse(settings.flag({"X": ""}, "X", default=True))      # the application's parser: blank is off


class DeterministicDeploymentUnchangedTests(unittest.TestCase):
    """Shadow-mode support: Reasoning V3 writes only to PostgreSQL; nothing serves it, so no UI changes for anyone."""

    def test_default_up_still_starts_only_the_static_web_service(self):
        blocks = services(text(BASE_COMPOSE))
        self.assertEqual(set(blocks), {"atlas-web", "atlas-runtime"})
        self.assertNotIn("profiles:", blocks["atlas-web"])
        self.assertIn('profiles: ["operations"]', blocks["atlas-runtime"])
        self.assertNotIn("reasoning", text(BASE_COMPOSE).lower())

    def test_nginx_serves_only_the_deterministic_locales(self):
        nginx = text(PRODUCTION / "nginx.conf")
        self.assertNotIn("reasoning", nginx)
        self.assertNotIn("proxy_pass", nginx)
        self.assertEqual(set(re.findall(r"location (?:= )?(\S+)", nginx)), {"/", "/en/", "/ar/"})

    def test_deterministic_images_and_units_never_contain_reasoning(self):
        for name in ("Dockerfile.app", "Dockerfile.nginx", "runtime-requirements.txt", "waset-atlas.service", "waset-atlas.timer", "atlas.env.example"):
            content = text(PRODUCTION / name)
            self.assertNotIn("psycopg", content, name)
            self.assertNotIn("atlas_reasoning", content, name)
            self.assertNotIn("REASONING", content, name)

    def test_deterministic_packages_never_import_reasoning(self):
        for package in ("atlas_sync", "atlas_commander"):
            for path in (ROOT / "src" / package).rglob("*.py"):
                self.assertNotRegex(text(path), r"(?m)^\s*(from|import) atlas_reasoning", str(path))


class ReasoningImageTests(unittest.TestCase):
    def test_image_is_pinned_unprivileged_and_safe_by_default(self):
        dockerfile = text(DOCKERFILE)
        app = text(PRODUCTION / "Dockerfile.app")
        self.assertEqual(dockerfile.splitlines()[3], next(line for line in app.splitlines() if line.startswith("FROM ")))
        self.assertRegex(dockerfile, r"FROM python:3\.12\.\d+-slim-bookworm@sha256:[0-9a-f]{64}")
        self.assertIn("USER ${ATLAS_UID}:${ATLAS_GID}", dockerfile)
        self.assertIn('ENTRYPOINT ["python", "-m", "atlas_reasoning"]', dockerfile)
        self.assertIn('CMD ["--help"]', dockerfile)
        self.assertNotRegex(dockerfile, r"(?m)^(EXPOSE|ARG .*(KEY|TOKEN|SECRET|PASSWORD)|ENV .*(KEY|TOKEN|SECRET|PASSWORD))")

    def test_requirements_are_exact_pins_and_deterministic_set_is_a_subset(self):
        reasoning = [line for line in text(PRODUCTION / "reasoning-runtime-requirements.txt").splitlines() if line and not line.startswith("#")]
        deterministic = [line for line in text(PRODUCTION / "runtime-requirements.txt").splitlines() if line and not line.startswith("#")]
        self.assertTrue(all(re.fullmatch(r"[a-z0-9-]+==[0-9.]+", line) for line in reasoning), reasoning)
        self.assertTrue(set(deterministic) <= set(reasoning))
        self.assertIn("psycopg==3.3.6", reasoning)
        self.assertIn("psycopg-binary==3.3.6", reasoning)

    def test_build_context_excludes_secrets_tests_and_data(self):
        ignore = text(PRODUCTION / "Dockerfile.reasoning.dockerignore")
        self.assertTrue(ignore.startswith("**\n"))
        self.assertNotIn("!tests", ignore)
        self.assertNotIn("!deploy/production/reasoning_ops", ignore)
        self.assertIn("!deploy/production/reasoning-runtime-requirements.txt", ignore)


@unittest.skipUnless(__import__("os").environ.get("ATLAS_RUN_DOCKER_TESTS") == "1",
                     "set ATLAS_RUN_DOCKER_TESTS=1 with a Docker daemon for image/runtime tests")
class ReasoningImageDockerTests(unittest.TestCase):
    """Builds the reasoning operations image locally and checks its identity and zero-action startup (no registry, no push)."""

    def test_image_builds_runs_as_non_root_and_starts_with_help_only(self):
        import subprocess

        tag = "waset-atlas-reasoning:phase20b-test"
        subprocess.run(["docker", "build", "-f", str(DOCKERFILE), "-t", tag, str(ROOT)], check=True, capture_output=True, timeout=1800)
        user = subprocess.run(["docker", "image", "inspect", "--format", "{{.Config.User}}", tag], check=True, capture_output=True, text=True).stdout
        self.assertEqual(user.strip(), "10001:10001")
        result = subprocess.run(["docker", "run", "--rm", "--network", "none", "--read-only", tag], capture_output=True, text=True, timeout=120,
                                check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertIn("migrate", result.stdout)
        probe = subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "python", tag, "-c", "import psycopg, atlas_reasoning"],
                               capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(probe.returncode, 0, probe.stderr[-500:])


class EnvironmentTemplateTests(unittest.TestCase):
    def test_template_uses_only_real_settings_and_host_paths(self):
        assigned = set(env_assignments(ENV_EXAMPLE))
        deployment = {name for name in assigned if name.startswith("ATLAS_REASONING_HOST_") or name == "ATLAS_REASONING_IMAGE"}
        self.assertEqual(assigned - deployment - known_settings(), set())
        self.assertEqual(deployment, {"ATLAS_REASONING_IMAGE", "ATLAS_REASONING_HOST_DATABASE_URL_FILE", "ATLAS_REASONING_HOST_OPENROUTER_KEY_FILE",
                                      "ATLAS_REASONING_HOST_HONCHO_KEY_FILE"})

    def test_capabilities_default_to_stage_zero_and_no_test_switch(self):
        env = env_assignments(ENV_EXAMPLE)
        self.assertEqual({name: env[name] for name in ("ATLAS_REASONING_V3", "ATLAS_REASONING_MEMORY", "ATLAS_REASONING_EXECUTION",
                                                       "ATLAS_REASONING_AUDIENCE", "ATLAS_REASONING_CARDS_PRIMARY", "ATLAS_REASONING_HUMAN_CONTEXT",
                                                       "ATLAS_REASONING_EXECUTIVE_HOME", "ATLAS_REASONING_MODEL", "ATLAS_REASONING_ALLOW_MODEL_OVERRIDE")},
                         {"ATLAS_REASONING_V3": "off", "ATLAS_REASONING_MEMORY": "off", "ATLAS_REASONING_EXECUTION": "on", "ATLAS_REASONING_AUDIENCE": "none",
                          "ATLAS_REASONING_CARDS_PRIMARY": "off", "ATLAS_REASONING_HUMAN_CONTEXT": "off", "ATLAS_REASONING_EXECUTIVE_HOME": "off",
                          "ATLAS_REASONING_MODEL": "", "ATLAS_REASONING_ALLOW_MODEL_OVERRIDE": "off"})
        for name in env:
            self.assertNotIn("EVALUATION", name)

    def test_credentials_only_as_file_references(self):
        env = env_assignments(ENV_EXAMPLE)
        for secret in ("ATLAS_REASONING_DATABASE_URL", "OPENROUTER_API_KEY", "HONCHO_API_KEY", "ATLAS_REASONING_CSRF_SECRET"):
            self.assertNotIn(secret, env)
        for name, value in env.items():
            if name.endswith("_FILE"):
                self.assertRegex(value, r"^/(etc/waset-atlas/secrets|run/secrets)/[a-z_]+$", name)
        self.assertRegex(env["ATLAS_REASONING_IMAGE"], r"@sha256:REPLACE_WITH_REVIEWED_DIGEST$")
        self.assertNotRegex(text(ENV_EXAMPLE), r"postgres(ql)?://")

    def test_settings_accept_the_template(self):
        from atlas_reasoning import settings

        env = env_assignments(ENV_EXAMPLE)
        self.assertFalse(settings.flag(env, settings.FLAG_ENV))
        self.assertEqual(settings.gateway_settings(env).model, settings.PINNED_MODEL)       # empty model = the pinned model
        settings.reliability_settings(env)
        self.assertEqual(settings.validation_retries(env), 1)
        self.assertEqual(settings.reliability_settings(env).run_call_budget, 200)


class SecretScanTests(unittest.TestCase):
    def test_the_deployment_surface_has_no_credential(self):
        findings, unreadable = secret_scan.scan(secret_scan.tracked(secret_scan.DEFAULT_SURFACE))
        self.assertEqual((findings, unreadable), ([], []))

    def test_the_new_artifacts_are_in_the_scanned_surface(self):
        scanned = {str(path.relative_to(ROOT)) for path in secret_scan.tracked(secret_scan.DEFAULT_SURFACE)}
        for name in ("deploy/production/compose.reasoning.yaml", "deploy/production/reasoning.env.example", "deploy/production/Dockerfile.reasoning",
                     "docs/REASONING-V3-PRODUCTION-ROLLOUT.md", "docs/REASONING-V3-RECOVERY.md", ".github/workflows/ci.yml"):
            self.assertIn(name, scanned)

    def test_findings_are_reported_without_their_values(self):
        planted = {
            "openrouter_key": "sk-or-v1-" + "a1" * 16,
            "database_url_with_password": "postgresql://atlas:" + "hunter2hunter2" + "@db/atlas_reasoning",
            "private_key": "-----BEGIN " + "PRIVATE KEY-----",
            "assigned_secret": "HONCHO_API_KEY=" + "abcdefghijklmnop",
            "bearer_token": "Authorization: Bearer " + "abcdefghijklmnopqrstuv",
            "libpq_keyword_password": "host=db dbname=atlas user=atlas password=" + "s3cr3tvalue",
            "json_secret": '{"honcho_api_key": "' + "abcdefghijklmnop" + '"}',
        }
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "captured-output.txt"
            sample.write_text("\n".join(planted.values()) + "\n", encoding="utf-8")
            safe = Path(tmp) / "safe.env"
            safe.write_text("OPENROUTER_API_KEY_FILE=/run/secrets/openrouter_api_key\nURL=postgresql://atlas:***@db/x\nDIGEST=REPLACE_WITH_REVIEWED_DIGEST\n"
                            "CI=postgresql://atlas:atlas-ci-only@localhost:5432/atlas_reasoning_test\n", encoding="utf-8")
            driver_url = Path(tmp) / "driver.txt"
            driver_url.write_text("postgresql+psycopg://atlas:" + "realpassword1" + "@db/x\n", encoding="utf-8")
            self.assertEqual([f.pattern for f in secret_scan.scan([driver_url])[0]], ["database_url_with_password"])
            findings, _ = secret_scan.scan([sample, safe])
            self.assertEqual({f.pattern for f in findings}, set(planted))
            self.assertTrue(all(f.path.endswith("captured-output.txt") for f in findings))
            output = io.StringIO()
            with redirect_stdout(output):
                code = secret_scan.main([str(sample)])
        self.assertEqual(code, 1)
        for value in planted.values():
            self.assertNotIn(value, output.getvalue())


class ReleaseChecklistTests(unittest.TestCase):
    A_ITEMS: ClassVar[dict[str, str]] = {"release_metadata_complete": "P20A_RELEASE_METADATA_COMPLETE", "phase19_release_thresholds": "P20A_REPOSITORY_ELIGIBILITY_CONTRACT",
               "phase20a_rollout_configuration_valid": "P20A_ROLLOUT_STAGE_MATCH"}

    def b_complete_record(self) -> dict[str, Any]:
        record = release_checklist.template()
        record["target_stage"] = "shadow"
        record["deployment"].update(ci_run_id="37098821248", app_image="r.example/app@sha256:" + "b" * 64,
                                    web_image="r.example/web@sha256:" + "c" * 64, reasoning_image="r.example/reasoning@sha256:" + "d" * 64)
        for item_id, entry in record["checks"].items():
            if item_id not in self.A_ITEMS:
                entry.update(status="pass", evidence="recorded")
        return record

    def test_the_checklist_covers_every_required_item(self):
        self.assertEqual(set(release_checklist.ITEM_IDS), {
            "reviewed_integration_sha", "exact_head_ci", "full_tests", "migrations_healthy", "phase19_closure", "phase19_release_thresholds",
            "phase20a_rollout_configuration_valid", "release_metadata_complete", "backup_target_approved", "isolated_restore_drill",
            "provider_outage_test", "honcho_outage_test", "deterministic_atlas_regression", "credential_scan", "rollback_plan_reviewed"})
        self.assertEqual(dict(release_checklist.A_DEPENDENT_ITEMS), self.A_ITEMS)
        doc = text(DOCS["RELEASE-CHECKLIST"])
        for item_id in release_checklist.ITEM_IDS:
            self.assertIn(f"`{item_id}`", doc)
        for field in release_checklist.DEPLOYMENT_FIELDS:
            self.assertIn(f"`{field}`", doc)
        for key in (*self.A_ITEMS.values(), "PENDING_PHASE20A_RECONCILIATION"):
            self.assertIn(key, doc)

    def test_it_neither_imports_phase20a_code_nor_derives_release_metadata(self):
        """B-first: the validator stands alone on the Phase 19 base; it imports no application module at all."""
        import ast

        tool = PRODUCTION / "reasoning_ops" / "release_checklist.py"
        modules = set()
        for node in ast.walk(ast.parse(text(tool))):
            if isinstance(node, ast.Import):
                modules |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        self.assertEqual({m for m in modules if m.startswith("atlas_")}, set())
        self.assertNotIn("import_module", text(tool))
        for constant in ("PINNED_MODEL", "PROMPT_VERSION", "CONTRACT_VERSION", "available_migrations"):
            self.assertNotIn(constant, text(tool))

    def test_b_side_complete_is_reported_but_the_record_stays_pending(self):
        result = release_checklist.validate(self.b_complete_record())
        self.assertEqual((result["b_independent_complete"], result["complete"], result["authorizes_deployment"], result["problems"]),
                         (True, False, False, []))
        self.assertEqual(result["a_dependent_acceptance"], "PENDING_PHASE20A_RECONCILIATION")
        self.assertEqual(result["pending"], {key: "PENDING" for key in self.A_ITEMS.values()})
        self.assertEqual((result["actual_release_ready"], result["rollout_authorized"]), (False, False))

    def test_release_readiness_is_fail_closed_and_separate_from_repository_eligibility(self):
        """PM final decision: repository eligibility != actual release readiness. Without live-provider evaluation and human-review evidence
        (which this tool never establishes) actual release readiness is FALSE, whatever a record claims."""
        record = self.b_complete_record()
        record["actual_release_ready"] = True
        record["rollout_authorized"] = True
        record["release_eligibility"] = {"eligible": True}
        for item_id in self.A_ITEMS:
            record["checks"][item_id].update(status="pass", evidence="claimed")
        for result in (release_checklist.validate(record), release_checklist.validate([])):
            self.assertEqual((result["actual_release_ready"], result["rollout_authorized"], result["authorizes_deployment"]), (False, False, False))
            self.assertIn("live-provider Phase 19 evaluation evidence (separately authorized)", result["release_readiness_requires"])
            self.assertIn("human management review evidence", result["release_readiness_requires"])

    def test_phase20a_items_can_never_pass_before_reconciliation(self):
        """Operator-marked pass plus attached Phase 20-A outputs is opaque review evidence only — never a pass."""
        record = self.b_complete_record()
        for item_id in self.A_ITEMS:
            record["checks"][item_id].update(status="pass", evidence="release-metadata complete=true; eligible=true; stage=shadow")
        record["release_metadata"] = {"metadata": {"commit": "a" * 40}, "complete": True, "missing": []}
        record["release_eligibility"] = {"eligible": True, "reasons": []}
        record["rollout"] = {"stage": "shadow"}
        record["a_dependent_acceptance"] = "PASS"
        result = release_checklist.validate(record)
        self.assertFalse(result["complete"])
        self.assertTrue(result["b_independent_complete"])
        self.assertEqual(result["a_dependent_acceptance"], "PENDING_PHASE20A_RECONCILIATION")
        self.assertEqual(set(result["pending"].values()), {"PENDING"})

    def test_the_template_records_the_pending_contract(self):
        template = release_checklist.template()
        self.assertEqual(template["a_dependent_acceptance"], "PENDING_PHASE20A_RECONCILIATION")
        for item_id in self.A_ITEMS:
            self.assertEqual(template["checks"][item_id]["status"], "PENDING_PHASE20A_RECONCILIATION")

    def test_b_side_gaps_are_detected(self):
        record = self.b_complete_record()
        record["deployment"]["web_image"] = ""
        record["checks"]["isolated_restore_drill"]["status"] = "pending"
        record["checks"]["credential_scan"]["evidence"] = ""
        record["checks"]["full_tests"]["evidence"] = "ran against postgresql://atlas:pw@db/x"
        record["rollout"] = "not an object"
        record["deployment"]["app_image"] = "r.example/app:latest"
        record["authorizes_deployment"] = True
        record["target_stage"] = ""
        result = release_checklist.validate(record)
        self.assertFalse(result["b_independent_complete"])
        self.assertEqual(result["missing_metadata"], ["deployment.web_image"])
        self.assertEqual(sorted(result["incomplete_items"]), ["credential_scan", "isolated_restore_drill"])
        for problem in ("checks.full_tests.evidence looks like it carries a credential (value not shown)", "deployment.app_image is not well formed",
                        "authorizes_deployment must be false: this checklist never authorizes deployment", "target_stage is required (one REV/20 stage)",
                        "rollout must be a JSON object (opaque Phase 20-A review evidence)"):
            self.assertIn(problem, result["problems"])
        self.assertNotIn("pw@db", json.dumps(result))

    def test_opaque_evidence_is_credential_scanned(self):
        record = self.b_complete_record()
        record["release_metadata"] = {"metadata": {"note": "Bearer abcdefghijklmnopqrstuvwxyz"}}
        result = release_checklist.validate(record)
        self.assertIn("release_metadata.metadata.note looks like it carries a credential (value not shown)", result["problems"])
        self.assertNotIn("abcdefghijklmnop", json.dumps(result))

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.json"
            with redirect_stdout(io.StringIO()):
                path.write_text(json.dumps(self.b_complete_record()), encoding="utf-8")
                self.assertEqual(release_checklist.main(["validate", str(path)]), 3)       # B complete, A pending: never 0 before reconciliation
                path.write_text(json.dumps(release_checklist.template()), encoding="utf-8")
                self.assertEqual(release_checklist.main(["validate", str(path)]), 1)
                path.write_text("[", encoding="utf-8")
                self.assertEqual(release_checklist.main(["validate", str(path)]), 2)


class ContinuousIntegrationTests(unittest.TestCase):
    """CI runs the isolated restore drill mandatorily, with client tools matching the PostgreSQL service (a skip there is a failure)."""

    def test_the_restore_drill_is_mandatory_in_ci_with_matching_client_tools(self):
        ci = text(ROOT / ".github" / "workflows" / "ci.yml")
        server = re.search(r"image: postgres:(\d+)", ci)
        assert server is not None
        install = ci.index("postgresql-client-")
        step = ci.index("- name: Reasoning V3 foundation tests")
        self.assertLess(install, step)                                       # installed before the Reasoning V3 suite runs
        self.assertIn("/usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y", ci)   # the official PGDG repository
        self.assertIn(f"postgresql-client-{server.group(1)}", ci)
        reasoning = ci[step:].split("\n      - name:", 1)[0]
        self.assertIn('ATLAS_REASONING_REQUIRE_RESTORE_DRILL: "1"', reasoning)
        self.assertIn(f"ATLAS_RESTORE_DRILL_PG_BIN: /usr/lib/postgresql/{server.group(1)}/bin", reasoning)
        self.assertIn('ATLAS_REASONING_REQUIRE_DB_TESTS: "1"', reasoning)
        self.assertIn("make reasoning", reasoning)

    def test_ci_permissions_and_credentials_are_unchanged(self):
        ci = text(ROOT / ".github" / "workflows" / "ci.yml")
        self.assertTrue(ci.startswith("name: Atlas CI\n\npermissions:\n  contents: read\n  pull-requests: read\n"))
        self.assertEqual(ci.count("secrets."), 0)
        self.assertEqual(len(re.findall(r"POSTGRES_PASSWORD: atlas-ci-only", ci)), 1)


class RunbookTests(unittest.TestCase):
    def test_runbooks_exist_and_never_instruct_destructive_or_unsafe_actions(self):
        for name, path in DOCS.items():
            content = text(path)
            self.assertNotRegex(content, r"(?i)\bDELETE FROM\b|\bTRUNCATE\b|\bDROP (TABLE|SCHEMA|DATABASE)\b|rm -rf|down -v|volume rm", name)
            self.assertNotRegex(content, r"(?i)while true|for i in|until .*; do", name)       # no shell retry loops
            # a live health check is only ever invoked with --dry-run, or on a line carrying the live-approval label
            for command in ("provider-health", "memory-health"):
                self.assertNotRegex(content, rf"(?:atlas_reasoning|reasoning-ops) {command}(?! --dry-run)(?![^\n]*DO NOT EXECUTE)", name)

    def test_live_commands_are_labelled(self):
        for name, path in DOCS.items():
            for block in re.findall(r"```(?:sh|bash|text)?\n(.*?)```", text(path), re.DOTALL):
                if re.search(r"sudo |docker compose|systemctl ", block):
                    self.assertIn("DO NOT EXECUTE WITHOUT LIVE-ROLLOUT APPROVAL", block, f"{name}: {block[:80]}")

    def test_compose_commands_load_both_environment_files(self):
        for path in (*DOCS.values(), RUNBOOK):
            for line in text(path).splitlines():
                if "compose.reasoning.yaml" in line and "docker compose" in line:
                    self.assertIn("--env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env", line)

    def test_documented_operator_commands_exist(self):
        from atlas_reasoning.__main__ import COMMANDS

        content = "\n".join(text(path) for path in DOCS.values())
        for command in re.findall(r"python -m atlas_reasoning ([a-z-]+)", content) + re.findall(r"reasoning-ops ([a-z][a-z-]*)", content):
            self.assertTrue(command in COMMANDS or command in PHASE20A_COMMANDS, command)
        for command in ("migrate", "db-health", "reason", "memory-sync"):
            self.assertIn(f"python -m atlas_reasoning {command}", content)
        self.assertIn("python -m atlas_reasoning.reliability_report", content)

    def test_six_stages_each_have_the_required_fields_and_explicit_approval(self):
        rollout = text(DOCS["PRODUCTION-ROLLOUT"])
        stages = re.findall(r"(?m)^### Stage (\d) — (.+)$", rollout)
        self.assertEqual([number for number, _ in stages], ["1", "2", "3", "4", "5", "6"])
        sections = re.split(r"(?m)^### Stage \d — ", rollout)[1:]
        for section in sections:
            for field in ("Prerequisite", "Expected visible behaviour", "Verification", "Monitoring", "Rollback condition", "Rollback target",
                          "Approval"):
                self.assertIn(f"**{field}**", section)
        self.assertIn("REQUIRES_FRESH_OPERATOR_SECURITY_APPROVAL", rollout)

    def test_monitoring_uses_only_canonical_metric_fields(self):
        """Every metric path the monitoring checklist names exists in the Phase 18-C report or the Phase 19 evaluation report."""
        from atlas_reasoning.evaluation_metrics import METRICS
        from atlas_reasoning.reliability_metrics import METRICS_VERSION

        monitoring = text(DOCS["MONITORING"])
        self.assertIn(METRICS_VERSION, monitoring)
        # every field path is walked against a real report in test_reasoning_ops_recovery.MonitoringFieldTests
        for metric in re.findall(r"`([a-z_]+_rate|case_identity_stability)`", monitoring):
            self.assertIn(metric, {definition.name for definition in METRICS}, metric)

    def test_production_runbook_points_to_the_reasoning_docs_and_keeps_its_contract(self):
        book = text(RUNBOOK)
        self.assertIn("## 12. Reasoning V3 (prepared, not active)", book)
        for path in DOCS.values():
            self.assertIn(path.name, book)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
