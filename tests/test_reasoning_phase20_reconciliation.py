"""Phase 20 A+B reconciliation gates (PM decision): blocking, automatic, on the real Phase 20-A code and the real Phase 20-B artifacts.

No mocks and no opaque evidence. Every check reads what is actually in the repository: Phase 20-A's ``rollout`` / ``release_metadata`` and
the operator commands; Phase 20-B's ``compose.reasoning.yaml``, ``reasoning.env.example``, rollout plan, ``release_checklist`` and
``restore_drill``; and the real Phase 19 runner and report. Any missing value, false result, error or drift fails:

==================================  =====================================================================================================
P20A_RELEASE_METADATA_COMPLETE      release metadata is complete for the checkout's commit, its content hashes match the migration SQL the
                                    database records (via Phase 20-B's restore-drill reader) and the prompt files, and Phase 20-B's backup
                                    release record accepts its identifiers
P20A_ROLLOUT_STAGE_MATCH            each of the six stages (and stage 0) passes through Phase 20-B's overlay allow-list and env template
                                    into exactly that stage; template = stage 0; the plan describes the same six stages in order
P20A_REPOSITORY_ELIGIBILITY_        the real offline Phase 19 release evaluation of this tree reproduces the approved Phase 19 report
CONTRACT                            (sha256 pinned below) and Phase 20-A ``release-eligibility`` accepts it
fail-closed readiness               without live-provider evidence and/or a human review, actual release readiness is FALSE and rollout is
                                    never authorized — in Phase 20-A's readiness and in Phase 20-B's release checklist alike
==================================  =====================================================================================================
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from reasoning_db import fresh_database, requires_db, test_database_url

from atlas_reasoning import settings
from atlas_reasoning.analyst import prompt_sha256
from atlas_reasoning.release_metadata import ReleaseMetadata, eligibility, release_metadata, release_readiness
from atlas_reasoning.rollout import ROLLOUT_ENVS, STAGES, rollout_config, stage_of
from atlas_reasoning.store.migrate import available_migrations

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "deploy" / "production"
sys.path.insert(0, str(PRODUCTION))

from reasoning_ops import release_checklist, restore_drill

# The approved Phase 19 evidence: the canonical report of the offline release evaluation. A change of evaluated software must
# re-establish (and re-approve) it. 3b8e9781…a44a was the report from PHASE19_CLOSURE (74c015f) to analyst-v2/update-v2. It was
# re-established for analyst-v3/update-v3 (docs/evidence/REASONING-V3-PROMPT-V3.md): the only report difference is those two prompt
# versions, and every metric, threshold and coverage value is identical.
APPROVED_PHASE19_REPORT_SHA256 = "67dabca2a4d3885d7d7f6eae14651cc003bbd6caac094f0062aca926e2ba6c59"
_COMPOSE_LINE = re.compile(r"^\s+(ATLAS_REASONING_[A-Z0-9_]+):\s*\$\{([A-Z0-9_]+)(:?-)([^}]*)\}\s*$")


def overlay_passthrough() -> dict[str, tuple[str, str, str]]:
    """Phase 20-B's overlay ``environment:`` interpolations: container variable -> (source variable, operator, default)."""
    text = (PRODUCTION / "compose.reasoning.yaml").read_text(encoding="utf-8")
    found = {}
    for line in text.splitlines():
        match = _COMPOSE_LINE.match(line)
        if match:
            found[match.group(1)] = (match.group(2), match.group(3), match.group(4))
    return found


def through_overlay(env_file: Mapping[str, str]) -> dict[str, str]:
    """What the reasoning-ops container sees for the rollout variables, by Compose's interpolation rules: ``:-`` defaults when the
    variable is unset or empty, ``-`` only when it is unset."""
    container = {}
    for target, (source, operator, default) in overlay_passthrough().items():
        if target not in ROLLOUT_ENVS:
            continue
        value = env_file.get(source)
        container[target] = default if value is None or (operator == ":-" and value == "") else value
    return container


def env_template() -> dict[str, str]:
    values = {}
    for line in (PRODUCTION / "reasoning.env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def checkout_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=30)
    return result.stdout.strip()


class StageMatchGate(unittest.TestCase):
    """P20A_ROLLOUT_STAGE_MATCH."""

    def test_the_overlay_passes_every_rollout_variable(self):
        self.assertEqual(set(ROLLOUT_ENVS) - set(overlay_passthrough()), set())
        for name in ROLLOUT_ENVS:
            source, _, _ = overlay_passthrough()[name]
            self.assertEqual(source, name)                                  # passed through, never renamed

    def test_each_stage_arrives_in_the_container_as_exactly_that_stage(self):
        self.assertEqual([stage.number for stage in STAGES], list(range(7)))
        for stage in STAGES:
            with self.subTest(stage=stage.name):
                container = through_overlay(stage.env)
                config = rollout_config(container)
                self.assertEqual(stage_of(config), stage.name)
                self.assertEqual(config.to_dict(), stage.config().to_dict())

    def test_defaults_and_template_are_stage_zero(self):
        self.assertEqual(stage_of(rollout_config(through_overlay({}))), "off")              # nothing set: off
        template = env_template()
        off = dict(STAGES[0].env)
        self.assertEqual({name: template[name] for name in ROLLOUT_ENVS}, off)              # the template is stage 0, exactly
        self.assertEqual(stage_of(rollout_config(through_overlay(template))), "off")
        self.assertEqual(stage_of(rollout_config(through_overlay({settings.FLAG_ENV: "on"}))), "shadow")   # master alone: shadow

    def test_a_blank_kill_switch_stays_off_in_the_container(self):
        container = through_overlay({**STAGES[3].env, "ATLAS_REASONING_EXECUTION": ""})
        self.assertFalse(rollout_config(container).execution)                               # fail-safe blank (Phase 20-B L-4)

    def test_the_plan_describes_the_same_six_stages_in_order(self):
        plan = (ROOT / "docs" / "REASONING-V3-PRODUCTION-ROLLOUT.md").read_text(encoding="utf-8")
        numbers = [int(n) for n in re.findall(r"^### Stage (\d) —", plan, flags=re.MULTILINE)]
        self.assertEqual(numbers, [stage.number for stage in STAGES if stage.number > 0])

    def test_the_operator_command_lists_the_same_stages(self):
        clean = {key: value for key, value in os.environ.items() if not key.startswith(("ATLAS_REASONING", "OPENROUTER", "HONCHO"))}
        result = subprocess.run([sys.executable, "-m", "atlas_reasoning", "rollout", "--stages"], env={**clean, "PYTHONPATH": str(ROOT / "src")},
                                capture_output=True, text=True, check=True, timeout=60)
        listed = json.loads(result.stdout)["stages"]
        self.assertEqual([(row["number"], row["name"], row["env"]) for row in listed], [(s.number, s.name, dict(s.env)) for s in STAGES])


@requires_db
class MetadataGate(unittest.TestCase):
    """P20A_RELEASE_METADATA_COMPLETE."""

    def test_metadata_is_complete_and_bound_to_content(self):
        commit = checkout_commit()
        metadata = release_metadata(commit=commit, env=through_overlay(STAGES[6].env))
        self.assertEqual(metadata.missing(), [])
        fields = metadata.to_dict()
        self.assertEqual(fields["commit"], commit)
        self.assertEqual(fields["rollout"]["stage"], "executive_home")
        for version, digest in fields["prompts_content_sha256"].items():
            self.assertEqual(digest, prompt_sha256(version))
        # The migration content hash equals the one built from what the database records (Phase 20-B's restore-drill reader).
        db = fresh_database()
        recorded = restore_drill.applied(db)
        self.assertEqual([row["name"] for row in recorded], [m.name for m in available_migrations()])
        import hashlib

        content = "\n".join(f"{row['version']}\t{row['name']}\t{row['checksum']}" for row in recorded)
        self.assertEqual(fields["migrations_content_sha256"], hashlib.sha256(content.encode()).hexdigest())

    def test_phase20b_backup_release_record_accepts_the_metadata_identifiers(self):
        fields = release_metadata(commit=checkout_commit(), env=through_overlay(STAGES[1].env)).to_dict()
        record = {key: value for key, value in fields.items() if isinstance(value, str)}
        record.update({"migrations_content_sha256": fields["migrations_content_sha256"], "stage": fields["rollout"]["stage"]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "release.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            loaded = restore_drill.load_release(path)
        self.assertEqual(loaded["commit"], fields["commit"])
        self.assertEqual(loaded["model"], settings.PINNED_MODEL)

    def test_an_incomplete_or_dirty_release_is_detected(self):
        self.assertEqual(release_metadata(commit=None, env={}).missing(), ["commit"])


def real_release_evaluation() -> dict[str, Any]:
    """The real offline Phase 19 release evaluation of this tree (Phase 19-B runner, every golden case) on the disposable test database."""
    from atlas_reasoning.evaluation_runner import EvaluationPlan, run_evaluation

    result = run_evaluation(EvaluationPlan(database_url=test_database_url() or "", environment={"provider": "offline-model"}))
    return result.to_dict()


@requires_db
class EligibilityAndReadinessGate(unittest.TestCase):
    """P20A_REPOSITORY_ELIGIBILITY_CONTRACT and the fail-closed actual release readiness."""

    evaluation: ClassVar[dict[str, Any]] = {}

    @classmethod
    def setUpClass(cls):
        cls.evaluation = real_release_evaluation()
        cls.config = rollout_config(through_overlay(STAGES[1].env))
        cls.metadata = release_metadata(commit=checkout_commit(), env=through_overlay(STAGES[1].env), rollout=cls.config)

    def test_the_real_evaluation_reproduces_the_approved_phase19_evidence(self):
        self.assertEqual((self.evaluation["code"], self.evaluation["result"], self.evaluation["mode"]), ("PASS", "PASS", "offline"))
        self.assertEqual(self.evaluation["report_sha256"], APPROVED_PHASE19_REPORT_SHA256)

    def test_repository_eligibility_is_true_for_this_release(self):
        result = eligibility(self.evaluation, self.metadata, self.config)
        self.assertEqual((result.eligible, result.reasons), (True, ()))

    def test_missing_live_or_human_evidence_is_never_release_ready(self):
        repository = eligibility(self.evaluation, self.metadata, self.config)
        cases = {
            "nothing beyond the repository evaluation": {},
            "the offline evaluation presented as live evidence": {"live_run": self.evaluation},
            "a review without live evidence": {"review": {"schema": "reasoning-management-review-v1"}},
        }
        for name, extra in cases.items():
            with self.subTest(name):
                readiness = release_readiness(repository, self.metadata, self.config, **extra)
                document = readiness.to_dict()
                self.assertEqual((document["actual_release_ready"], document["rollout_authorized"], document["repository_eligible"]),
                                 (False, False, True))
                self.assertTrue(any(reason.startswith("live:") for reason in readiness.missing))
                self.assertTrue(any(reason.startswith("review:") for reason in readiness.missing))

    def test_phase20b_checklist_agrees_fail_closed(self):
        verdict = release_checklist.validate(release_checklist.template())
        self.assertEqual((verdict["actual_release_ready"], verdict["rollout_authorized"], verdict["authorizes_deployment"], verdict["complete"]),
                         (False, False, False, False))

    def test_the_operator_commands_report_eligible_but_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            path.write_text(json.dumps(self.evaluation), encoding="utf-8")
            clean = {key: value for key, value in os.environ.items() if not key.startswith(("ATLAS_REASONING", "OPENROUTER", "HONCHO"))}
            env = {**clean, "PYTHONPATH": str(ROOT / "src"), **through_overlay(STAGES[1].env)}
            commit = ["--commit", checkout_commit()]
            eligible = subprocess.run([sys.executable, "-m", "atlas_reasoning", "release-eligibility", "--evaluation", str(path), *commit], env=env,
                                      capture_output=True, text=True, check=False, timeout=120)
            ready = subprocess.run([sys.executable, "-m", "atlas_reasoning", "release-readiness", "--evaluation", str(path), *commit], env=env,
                                   capture_output=True, text=True, check=False, timeout=120)
        self.assertEqual((eligible.returncode, json.loads(eligible.stdout)["eligible"]), (0, True), eligible.stderr)
        document = json.loads(ready.stdout)
        self.assertEqual((ready.returncode, document["actual_release_ready"], document["rollout_authorized"]), (1, False, False))


class NoMetadataShortcut(unittest.TestCase):
    def test_metadata_type_is_not_constructible_into_a_pass(self):
        """A hand-made metadata record without the content bindings is incomplete (no shortcut around the gates)."""
        partial = ReleaseMetadata({"commit": "a" * 40, "model": settings.PINNED_MODEL})
        self.assertIn("migrations_content_sha256", partial.missing())
        self.assertIn("prompts_content_sha256", partial.missing())


if __name__ == "__main__":
    unittest.main()
