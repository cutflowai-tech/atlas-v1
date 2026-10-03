"""Phase 20-B: operational recovery scenarios on a disposable PostgreSQL with offline fakes (no provider, no Honcho, no live system).

- **Provider outage** (OpenRouter down): prior results and the current ExecutiveBrief survive unchanged; the run is classified by the
  Phase 18 policy; the breaker stops sending (no retry storm); recovery is the normal ``resume``; a repeated resume makes no call.
- **Honcho outage**: PostgreSQL stays canonical; notes and results are written; the run reports memory degradation; the dashboard still
  renders; the existing memory-sync retry restores the copies.
- **Capability rollback**: Reasoning V3 off refuses every reasoning entry point without touching canonical state; memory off falls back
  to canonical context; the model rollback path needs the explicit override.
- **Migrations before writes**: an unmigrated database is unhealthy and refuses Reasoning V3 writes; ``migrate`` then makes it healthy;
  replay applies nothing.
- **Isolated restore drill** (``deploy/production/reasoning_ops/restore_drill.py``): backup, restore into a second disposable database,
  health, migrations, canonical fingerprints (results, versions, ExecutiveBrief history, human context, audit), release metadata.
  It needs PostgreSQL client tools at least as new as the server; without them the full drill is skipped with that reason unless
  ``ATLAS_REASONING_REQUIRE_RESTORE_DRILL=1``. The verification half always runs.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from reasoning_db import fresh_database, requires_db, test_database_url
from reasoning_executive_support import ScriptedExecutive

from atlas_reasoning.evaluation import load_golden_cases
from atlas_reasoning.evaluation_offline_model import OfflineModel
from atlas_reasoning.evaluation_runner import ShowcaseDataset, gate_times
from atlas_reasoning.evaluation_types import EvidenceVariant
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.provider import ProviderRequest, ProviderResponse, ProviderUnavailable
from atlas_reasoning.reasoning_context import HumanContext
from atlas_reasoning.reasoning_runtime import ReasoningRuntime, build_runtime
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.db import SCHEMA, Database
from atlas_reasoning.store.executive import ExecutiveStore
from atlas_reasoning.store.repository import ReasoningStore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "production"))

from reasoning_ops import restore_drill

MANAGER = "manager@example.com"
RUNTIME_ENV = {"ATLAS_REASONING_LLM_MAX_RETRIES": "1", "ATLAS_REASONING_LLM_BACKOFF_SECONDS": "0", "ATLAS_REASONING_LLM_MAX_BACKOFF_SECONDS": "0",
               "ATLAS_REASONING_BREAKER_THRESHOLD": "1", "ATLAS_REASONING_BREAKER_COOLDOWN_SECONDS": "1"}
FOCUS = next(case.focus for case in load_golden_cases() if case.fixture_id == "updated-material-evidence")


class OpsTransport:
    """The offline model (analyst / update) and the executive fake behind one switch: ``down`` = the provider is unreachable."""

    provider_name = "fake"

    def __init__(self) -> None:
        self.reasoning, self.executive = OfflineModel(), ScriptedExecutive()
        self.down = False
        self.requests = 0
        self.requests_while_down = 0
        self._lock = threading.Lock()

    def complete(self, request: ProviderRequest, *, model: str, timeout: float) -> ProviderResponse:
        with self._lock:
            self.requests += 1
            self.requests_while_down += self.down
        if self.down:
            raise ProviderUnavailable("simulated OpenRouter outage")
        target = self.executive if request.context.purpose == "executive" else self.reasoning
        return target.complete(request, model=model, timeout=timeout)


class Scenario:
    """One process's Reasoning V3 runtime on a fresh database, driven through the same interfaces the operator commands use."""

    def __init__(self) -> None:
        self.db = fresh_database()
        self.store = ReasoningStore(self.db)
        self.transport = OpsTransport()
        self.honcho = FakeHoncho()
        self.context = HumanContext(self.store, self.honcho, env={})
        self.runtime: ReasoningRuntime = build_runtime(self.store, self.transport, env=RUNTIME_ENV, recorder=StoreCallRecorder(self.store),
                                                       context=self.context)
        self.dataset = ShowcaseDataset()
        self.times = iter(gate_times(24))

    def gate(self, variant: EvidenceVariant = EvidenceVariant.SHOWCASE) -> str:
        from atlas_reasoning.change_gate import run_gate

        return run_gate(self.dataset.evidence(variant, FOCUS), self.store, now=next(self.times)).run_id

    def status(self, run_id: str) -> tuple[str, str | None]:
        with self.store.transaction() as tx:
            row = tx._one("SELECT status, error FROM reasoning_runs WHERE run_id = %s", (run_id,))
        assert row is not None
        return str(row["status"]), row["error"]

    def count(self, table: str, where: str = "TRUE") -> int:
        with self.store.transaction() as tx:
            row = tx._one(f"SELECT count(*) AS n FROM {table} WHERE {where}")
        return int(row["n"]) if row else 0

    def fingerprint(self, *tables: str) -> dict[str, Any]:
        prints = restore_drill.fingerprints(self.db)
        return {table: prints[table] for table in tables}

    def rows(self, table: str) -> set[str]:
        with self.store.transaction() as tx:
            return {str(row["t"]) for row in tx._all(f"SELECT t::text AS t FROM {table} t")}

    def brief(self) -> dict[str, Any] | None:
        current = ExecutiveStore(self.store).current_brief()
        return current.to_dict() if current is not None else None

    def focus_result(self) -> str:
        with self.store.transaction() as tx:
            row = tx._one("SELECT r.result_id FROM reasoning_results r JOIN reasoning_cases c USING (case_id) WHERE c.identity_key = %s", (FOCUS,))
        assert row is not None
        return str(row["result_id"])

    def seed(self) -> str:
        """A healthy baseline: one complete run, a current ExecutiveBrief, and canonical human context (note, answer, teaching)."""
        from atlas_reasoning.manager_notes import ManagerNotes
        from atlas_reasoning.teach_atlas import TeachAtlas

        run_id = self.gate()
        report = self.runtime.orchestrator.run(run_id)
        assert report.status == "complete", report.to_dict()
        outcome = self.runtime.synthesize(run_id)
        assert outcome.failure is None and outcome.brief_id is not None, outcome.to_dict()
        ManagerNotes(self.store, self.context.sync).create(self.focus_result(), "Class B work moved to another Editor this month.", author=MANAGER)
        with self.store.transaction() as tx:
            question = tx._one("SELECT question_id FROM atlas_questions WHERE state = 'open' ORDER BY dedup_key LIMIT 1")
        assert question is not None
        self.context.questions.answer(question["question_id"], "Yes, Class B work went to another Editor.", author=MANAGER)
        TeachAtlas(self.store, self.context.sync).create(body="This Editor covers urgent Class B work.", scope_type="editor",
                                                         scope_id=FOCUS.split("|")[2], teaching_type="context", validity_mode="until_changed",
                                                         author=MANAGER)
        return run_id


APPEND_ONLY = ("reasoning_result_versions", "reasoning_result_diffs", "reasoning_lifecycle_transitions")
RESULT_TABLES = ("reasoning_results", "reasoning_result_versions", "reasoning_result_diffs", "reasoning_lifecycle_transitions")
BRIEF_TABLES = ("executive_briefs", "executive_brief_versions", "executive_brief_inputs", "executive_statement_refs")
HUMAN_TABLES = ("manager_notes", "manager_note_revisions", "atlas_questions", "atlas_answers", "teachings", "teaching_revisions")


@requires_db
class ProviderOutageTests(unittest.TestCase):
    def test_openrouter_outage_preserves_state_and_recovers_by_resume(self):
        s = Scenario()
        s.seed()
        history = {table: s.rows(table) for table in APPEND_ONLY}
        results, briefs, brief_before = s.rows("reasoning_results"), s.fingerprint(*BRIEF_TABLES), s.brief()
        content_versions = s.count("reasoning_result_versions", "change_kind <> 'lifecycle'")

        s.transport.down = True
        outage_run = s.gate(EvidenceVariant.MATERIAL_CHANGE)
        report = s.runtime.orchestrator.run(outage_run)
        status, reasons = s.status(outage_run)
        self.assertEqual(report.status, status)
        # Phase 18 policy: the prior results are usable, the failure is retryable -> partial / resumable_failures (never "complete")
        self.assertEqual((status, reasons), ("partial", "resumable_failures"))
        self.assertIn(outage_run, s.runtime.orchestrator.incomplete_runs())
        # the breaker (threshold 1, one transport retry) stops sending: at most threshold x (1 + retries) requests, no storm
        self.assertLessEqual(s.transport.requests_while_down, 1 * 2)
        self.assertEqual(s.runtime.controls.snapshot()["breaker"]["state"], "open")
        # executive synthesis during the outage keeps the current brief
        outcome = s.runtime.synthesize(outage_run)
        self.assertEqual(outcome.failure, "provider:circuit_open")              # refused before any request while the circuit is open
        self.assertLessEqual(s.transport.requests_while_down, 2)
        assert brief_before is not None
        self.assertEqual(outcome.brief_version, brief_before["version"])       # "the current version after this run (unchanged on failure)"
        self.assertEqual(s.brief(), brief_before)
        # nothing committed was lost or rewritten: every earlier version, diff and transition is still there unchanged; the only new
        # versions are Phase 09's model-free lifecycle settles (new -> active, ``observed_again``); no content version was written
        for table, before in history.items():
            self.assertLessEqual(before, s.rows(table), table)
        self.assertEqual(s.count("reasoning_result_versions", "change_kind <> 'lifecycle'"), content_versions)
        self.assertEqual({row.split(",")[0] for row in s.rows("reasoning_results")}, {row.split(",")[0] for row in results})
        self.assertEqual(s.fingerprint(*BRIEF_TABLES), briefs)                # the ExecutiveBrief and its history: identical

        # recovery: the provider is back; wait out the breaker cooldown; the normal resume (no manual retry, no safeguard bypassed)
        s.transport.down = False
        time.sleep(1.1)
        resumed = s.runtime.orchestrator.resume(outage_run)
        self.assertEqual(resumed.status, "complete", resumed.to_dict())
        self.assertGreater(s.count("reasoning_result_versions", "change_kind = 'patched'"), 0)   # the material change is now reasoned
        recovered = s.runtime.synthesize(outage_run)
        self.assertIsNone(recovered.failure, recovered.to_dict())
        self.assertGreater(recovered.brief_version or 0, brief_before["version"])
        # the previous brief stays in history
        self.assertEqual(s.count("executive_brief_versions", f"brief_id = '{brief_before['brief_id']}' AND version = {brief_before['version']}"), 1)
        # an idempotent second resume makes no call
        calls = s.transport.requests
        again = s.runtime.orchestrator.resume(outage_run)
        self.assertEqual((again.status, s.transport.requests), ("complete", calls))


@requires_db
class HonchoOutageTests(unittest.TestCase):
    def test_honcho_outage_degrades_memory_only_and_memory_sync_recovers(self):
        from atlas_reasoning.human_context import sync_service
        from atlas_reasoning.manager_notes import ManagerNotes

        s = Scenario()
        s.seed()
        s.honcho.outage()
        note = ManagerNotes(s.store, s.context.sync).create(s.focus_result(), "Urgent Class B work arrived late from the client.", author=MANAGER)
        self.assertIsNotNone(note)
        self.assertEqual(s.count("manager_notes"), 2)                         # canonical row written despite the outage
        self.assertGreater(s.count("memory_sync_log", "status IN ('pending', 'failed')"), 0)

        run_id = s.gate(EvidenceVariant.MATERIAL_CHANGE)
        report = s.runtime.orchestrator.run(run_id)
        status, reasons = s.status(run_id)
        self.assertEqual(status, "degraded")
        self.assertIn("memory_degraded", reasons or "")
        self.assertGreater(len([o for o in report.outcomes if getattr(o, "result_id", None)]), 0)   # reasoning still committed results

        # the dashboard renders from PostgreSQL while memory is down
        self.assertEqual(self.dashboard_status(s), 200)

        canonical = s.fingerprint(*RESULT_TABLES, *HUMAN_TABLES)
        s.honcho.restore()
        outcomes = sync_service(s.store, s.honcho).retry(limit=100)
        self.assertTrue(outcomes)
        self.assertEqual({o.status for o in outcomes} - {"synced", "duplicate"}, set())
        self.assertEqual(s.count("memory_sync_log", "status IN ('pending', 'failed')"), 0)
        self.assertEqual(s.fingerprint(*RESULT_TABLES, *HUMAN_TABLES), canonical)   # memory sync never rewrites canonical rows

    def dashboard_status(self, s: Scenario) -> int:
        from atlas_reasoning.atlas_questions import AtlasQuestions
        from atlas_reasoning.dashboard import DashboardService
        from atlas_reasoning.executive_overview import ExecutiveOverviewService
        from atlas_reasoning.human_context import sync_service
        from atlas_reasoning.management_api import ManagementAPI
        from atlas_reasoning.manager_notes import ManagerNotes
        from atlas_reasoning.teach_atlas import TeachAtlas
        from atlas_reasoning.web_app import ReasoningWebApp, web_settings

        web = web_settings({"ATLAS_REASONING_MANAGERS": MANAGER, "ATLAS_REASONING_CSRF_SECRET": "x" * 40,
                            "ATLAS_REASONING_ALLOWED_ORIGINS": "https://atlas.example.com"})
        sync = sync_service(s.store, s.honcho)
        notes, questions, teachings = ManagerNotes(s.store, sync), AtlasQuestions(s.store, sync), TeachAtlas(s.store, sync)
        service = DashboardService(s.store, notes=notes, questions=questions, teachings=teachings)
        app = ReasoningWebApp(web, service, ManagementAPI(web.api, notes=notes, questions=questions, teachings=teachings),
                              executive=ExecutiveOverviewService(s.store, service))
        captured: dict[str, Any] = {}
        body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": f"/reasoning/en/results/{s.focus_result()}", "REMOTE_USER": MANAGER},
                            lambda status, headers, *rest: captured.update(status=status)))
        self.assertNotIn(b"Traceback", body)
        return int(str(captured["status"]).split()[0])


@requires_db
class CapabilityRollbackTests(unittest.TestCase):
    def test_reasoning_off_refuses_every_entry_point_and_keeps_canonical_state(self):
        from atlas_reasoning import settings
        from atlas_reasoning.__main__ import main
        from atlas_reasoning.web_app import create_app

        s = Scenario()
        run_id = s.seed()
        before = restore_drill.fingerprints(s.db)
        off = {"ATLAS_REASONING_V3": "off", "ATLAS_REASONING_DATABASE_URL": test_database_url() or ""}
        with self.assertRaises(settings.ReasoningDisabled):
            create_app(off)
        for argv in (["reason", run_id], ["gate", str(ROOT)]):
            err = io.StringIO()
            with mock.patch.dict(os.environ, off, clear=False), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                self.assertEqual(main(argv), 2, argv)
            self.assertIn("ReasoningDisabled", err.getvalue(), argv)         # refused by the master switch, not some other error
        with mock.patch.dict(os.environ, off, clear=False), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["db-health"]), 0)                         # read-only operations still work with reasoning off
        self.assertEqual(restore_drill.fingerprints(s.db), before)           # disabling never deletes or rewrites reasoning rows

    def test_memory_off_uses_canonical_context_only(self):
        from atlas_reasoning.honcho_client import backend_from_env
        from atlas_reasoning.human_context import sync_service
        from atlas_reasoning.manager_notes import ManagerNotes

        self.assertIsNone(backend_from_env({"ATLAS_REASONING_MEMORY": "off"}))
        s = Scenario()
        s.seed()
        notes = ManagerNotes(s.store, sync_service(s.store, None))
        notes.create(s.focus_result(), "Written while memory is disabled.", author=MANAGER)
        self.assertEqual(s.count("manager_notes"), 2)

    def test_model_rollback_needs_the_explicit_override(self):
        from atlas_reasoning import settings

        with self.assertRaises(settings.ReasoningConfigError):
            settings.gateway_settings({"ATLAS_REASONING_MODEL": "openai/previous-model"})
        self.assertEqual(settings.gateway_settings({"ATLAS_REASONING_MODEL": "openai/previous-model",
                                                    "ATLAS_REASONING_ALLOW_MODEL_OVERRIDE": "on"}).model, "openai/previous-model")


@requires_db
class MigrationsBeforeWritesTests(unittest.TestCase):
    def test_an_unmigrated_database_refuses_writes_until_migrate(self):
        from atlas_reasoning.__main__ import main
        from atlas_reasoning.change_gate import run_gate
        from atlas_reasoning.store.health import database_health

        url = test_database_url() or ""
        db = Database(url)
        with db.transaction() as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        health = database_health(db)
        self.assertFalse(health["ok"])
        self.assertTrue(health["pending"])
        import psycopg

        with self.assertRaises(psycopg.errors.UndefinedTable):              # no Reasoning V3 write is possible before migration
            run_gate(ShowcaseDataset().evidence(EvidenceVariant.SHOWCASE, FOCUS), ReasoningStore(db), now=gate_times(1)[0])
        env = {"ATLAS_REASONING_DATABASE_URL": url, "ATLAS_REASONING_V3": "off"}
        outputs = []
        for argv in (["db-health"], ["migrate"], ["db-health"], ["migrate"]):
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False), contextlib.redirect_stdout(out):
                outputs.append((main(argv), json.loads(out.getvalue())))
        self.assertEqual([code for code, _ in outputs], [1, 0, 0, 0])
        self.assertTrue(outputs[1][1]["applied"])
        self.assertEqual((outputs[2][1]["ok"], outputs[2][1]["pending"]), (True, []))
        self.assertEqual(outputs[3][1]["applied"], [])                       # replay is idempotent
        password = Database(url).display_url != url and __import__("urllib.parse").parse.urlsplit(url).password
        for _, document in outputs:
            if password:
                self.assertNotIn(password, json.dumps(document))
            self.assertEqual(document.get("database", Database(url).display_url), Database(url).display_url)


@requires_db
class MonitoringFieldTests(unittest.TestCase):
    """Every field path the monitoring checklist names exists in a real Phase 18-C report (no second metric definition)."""

    def test_every_monitoring_path_exists_in_the_reliability_report(self):
        import re

        from atlas_reasoning.store.reliability_metrics import reliability_report

        s = Scenario()
        run_id = s.seed()
        document = reliability_report(s.store, [run_id]).to_dict()
        run = document["runs"][0]
        monitoring = (ROOT / "docs" / "REASONING-V3-MONITORING.md").read_text(encoding="utf-8")
        paths = re.findall(r"`((?:provider_calls|work|validation|gate|executive|memory|status_inputs|orchestration|run|backlog)\.[a-z_.]+)`", monitoring)
        self.assertGreater(len(paths), 30)
        for path in paths:
            node: Any = document if path.startswith("backlog.") else run
            for part in path.split("."):
                self.assertIsInstance(node, dict, path)
                self.assertIn(part, node, path)
                node = node[part]


@requires_db
class RestoreDrillVerificationTests(unittest.TestCase):
    """The verification half of the drill (no client tools needed): it detects any canonical difference and any migration drift."""

    def test_verification_detects_differences(self):
        s = Scenario()
        s.seed()
        manifest = {"tables": restore_drill.fingerprints(s.db), "migrations": restore_drill.applied(s.db),
                    "schema_objects": restore_drill.schema_objects(s.db), "release": {"commit": "a" * 40}}
        report = restore_drill.verify(s.db, manifest)
        self.assertTrue(report["ok"], report)
        tampered = json.loads(json.dumps(manifest))
        tampered["tables"]["executive_brief_versions"]["sha256"] = "0" * 64
        tampered["migrations"] = tampered["migrations"][:-1]
        report = restore_drill.verify(s.db, tampered)
        self.assertFalse(report["ok"])
        self.assertEqual(report["differing_tables"], ["executive_brief_versions"])
        self.assertFalse(report["checks"]["migrations_match_manifest"])

    def test_verification_detects_missing_schema_objects(self):
        """The append-only triggers and constraints the rollback guarantees rely on are part of what a restore must reproduce."""
        s = Scenario()
        objects = restore_drill.schema_objects(s.db)
        self.assertGreater(objects["triggers"]["count"], 0)
        self.assertGreater(objects["functions"]["count"], 0)
        self.assertGreater(objects["constraints"]["count"], 0)
        manifest = {"tables": restore_drill.fingerprints(s.db), "migrations": restore_drill.applied(s.db), "schema_objects": objects, "release": {}}
        self.assertTrue(restore_drill.verify(s.db, manifest)["ok"])
        manifest["schema_objects"] = dict(objects, triggers={"count": objects["triggers"]["count"] + 1, "sha256": "0" * 64})
        report = restore_drill.verify(s.db, manifest)
        self.assertFalse(report["ok"])
        self.assertFalse(report["checks"]["schema_objects_identical"])


class RestoreDrillGuardTests(unittest.TestCase):
    def test_targets_must_be_disposable_and_distinct(self):
        with self.assertRaisesRegex(restore_drill.DrillRefused, "target"):
            restore_drill.restore(Path("/nonexistent"), "postgresql://atlas:pw@db/atlas_reasoning", env={})
        with self.assertRaisesRegex(restore_drill.DrillRefused, "ATLAS_REASONING_DATABASE_URL"):
            restore_drill.restore(Path("/nonexistent"), "postgresql://atlas@db:5432/atlas_reasoning_test",
                                  env={"ATLAS_REASONING_DATABASE_URL": "postgresql://atlas@db:5432/atlas_reasoning_test"})
        with self.assertRaisesRegex(restore_drill.DrillRefused, "different"):
            restore_drill.drill("postgresql://atlas@db:5432/x_test", "postgresql://atlas@db:5432/x_test?connect_timeout=3", env={})

    def test_urls_must_state_their_target_and_carry_no_ssl_password(self):
        for url in ("postgresql://atlas@/atlas_reasoning_test", "postgresql://atlas@db/atlas_reasoning_test", "postgresql:///atlas_reasoning_test",
                    "postgresql://atlas@db:5432/atlas_reasoning_test?sslpassword=hunter2hunter2"):
            with self.subTest(url=url), self.assertRaises(restore_drill.DrillRefused) as raised:
                restore_drill.guard(url, {}, "target")
            self.assertNotIn("hunter2", str(raised.exception))
        self.assertTrue(restore_drill.guard("postgresql://atlas@db:5432/atlas_reasoning_test", {}, "target"))

    def test_errors_exit_three_without_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / restore_drill.MANIFEST_NAME).write_text(json.dumps({"schema": restore_drill.MANIFEST_SCHEMA}), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = restore_drill.main(["restore", "--backup", tmp, "--target-url", "postgresql://atlas:pw@db:5432/atlas_reasoning_test"], env={})
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out.getvalue())["error"], "KeyError")
        self.assertNotIn("pw@", out.getvalue())

    def test_a_tampered_artifact_is_refused_before_any_tool_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / restore_drill.DUMP_NAME).write_bytes(b"not the dump")
            (directory / restore_drill.MANIFEST_NAME).write_text(json.dumps(
                {"schema": restore_drill.MANIFEST_SCHEMA, "artifact": {"file": restore_drill.DUMP_NAME, "sha256": "0" * 64}}), encoding="utf-8")
            with mock.patch.object(restore_drill, "find_tools", side_effect=AssertionError("no tool may run")), \
                 self.assertRaisesRegex(restore_drill.DrillRefused, "sha256"):
                restore_drill.restore(directory, "postgresql://atlas@db:5432/atlas_reasoning_drill_test", env={})

    def test_release_records_must_be_plain_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "release.json"
            for bad in ({"database": "postgresql://atlas:pw@db/x"}, {"openrouter": "sk-or-v1-abcdefabcdefabcdef"}, {"api_key": "abc"}):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(restore_drill.DrillRefused) as raised:
                    restore_drill.load_release(path)
                self.assertNotIn("pw@db", str(raised.exception))
            path.write_text(json.dumps({"integration_sha": "a" * 40, "model": "openai/gpt-5.6-sol"}), encoding="utf-8")
            self.assertEqual(restore_drill.load_release(path)["integration_sha"], "a" * 40)

    def test_the_password_never_reaches_a_command_line(self):
        conninfo, env = restore_drill._connection("postgresql://atlas:s3cret@db:5432/atlas_reasoning_test")
        self.assertNotIn("s3cret", conninfo)
        self.assertEqual(env["PGPASSWORD"], "s3cret")
        self.assertIn("dbname='atlas_reasoning_test'", conninfo)

    def test_an_unhealthy_source_is_refused(self):
        with mock.patch.object(restore_drill, "database_health", return_value={"ok": False}), \
             self.assertRaisesRegex(restore_drill.DrillRefused, "not healthy"):
            restore_drill.backup("postgresql://atlas@db:5432/atlas_reasoning_test", Path(tempfile.gettempdir()) / "never", env={})


def _tools_or_skip(url: str) -> None:
    required = os.environ.get("ATLAS_REASONING_REQUIRE_RESTORE_DRILL") == "1"
    try:
        restore_drill.check_tools(restore_drill.find_tools(os.environ), Database(url))
    except restore_drill.DrillRefused as reason:
        if required:
            raise
        raise unittest.SkipTest(f"isolated restore drill needs PostgreSQL client tools for this server: {reason}") from None


@requires_db
class IsolatedRestoreDrillTests(unittest.TestCase):
    """The full drill: synthetic data, two disposable databases on the test server, no production data or credential."""

    target: ClassVar[str] = ""

    @classmethod
    def setUpClass(cls):
        import psycopg

        from atlas_reasoning.store.evaluation_scenario import connection_target

        url = test_database_url() or ""
        _tools_or_skip(url)
        name = connection_target(url)["dbname"] + "_restore"
        cls.target = url.rsplit("/", 1)[0] + "/" + name + ("?" + url.split("?", 1)[1] if "?" in url else "")
        with psycopg.connect(url, autocommit=True) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
                conn.execute(f'CREATE DATABASE "{name}"')

    def test_backup_restore_and_verify(self):
        s = Scenario()
        s.seed()
        s.honcho.outage()                                                    # include unsynced memory state in the backup
        from atlas_reasoning.manager_notes import ManagerNotes

        ManagerNotes(s.store, s.context.sync).create(s.focus_result(), "A note written during a memory outage.", author=MANAGER)
        release = {"integration_sha": "a" * 40, "model": "openai/gpt-5.6-sol", "migration_version": "0600", "evaluation_report_sha256": "b" * 64}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "backup"
            report = restore_drill.drill(test_database_url() or "", self.target, env={}, out=out, release=release)
            self.assertEqual({path.name for path in out.iterdir()}, {restore_drill.DUMP_NAME, restore_drill.MANIFEST_NAME})
            self.assertEqual(out.stat().st_mode & 0o777, 0o700)
            for path in out.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            manifest = restore_drill.load_manifest(out)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["label"], restore_drill.DRILL_LABEL)
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(report["release"], release)
        for table in (*RESULT_TABLES[:2], *BRIEF_TABLES[:2], "manager_notes", "atlas_answers", "teachings", "llm_calls", "reasoning_runs",
                      "memory_sync_log", "schema_migrations"):
            self.assertGreater(manifest["tables"][table]["rows"], 0, table)
        serialized = json.dumps(report) + json.dumps(manifest)
        self.assertNotIn("postgresql://", serialized)

    def test_cli_drill_output_is_safe(self):
        Scenario().seed()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = restore_drill.main(["drill", "--source-url", test_database_url() or "", "--target-url", self.target], env={})
        document = json.loads(out.getvalue())
        self.assertEqual((code, document["ok"]), (0, True))
        self.assertNotIn("postgresql://", out.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
