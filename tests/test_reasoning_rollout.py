"""Phase 20-A (REV/20 #1, #2, #3, #10, #11): Reasoning V3 rollout controls — the validated capability model, the six stages, shadow
mode, read/write separation, reversible rollback without data loss, degraded behaviour, legacy preservation, release metadata and
release eligibility. Repository-side only: no deployment, no live provider (``ScriptedAnalyst`` / ``ScriptedExecutive`` /
``FakeHoncho``), no change to any security control (the Phase 16/17 security tests run unchanged).
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

import reasoning_snapshots as snapshots
from reasoning_db import fresh_database, requires_db, test_database_url
from reasoning_engine_support import DEADLINE_12, changed_rows, payload_with, times
from reasoning_executive_support import ScriptedExecutive
from reasoning_fakes import ScriptedAnalyst, gateway
from test_reasoning_dashboard import BOSS, ORIGIN, api_settings, call

from atlas_reasoning import human_context, settings
from atlas_reasoning.atlas_questions import AtlasQuestions
from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.dashboard import DashboardService
from atlas_reasoning.engine import ReasoningEngine
from atlas_reasoning.executive import ExecutiveSynthesizer
from atlas_reasoning.executive_overview import ExecutiveOverviewService
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.gateway import ReasoningGateway
from atlas_reasoning.management_api import ManagementAPI
from atlas_reasoning.manager_notes import ManagerNotes
from atlas_reasoning.provider import ProviderUnavailable
from atlas_reasoning.reasoning_context import HumanContext
from atlas_reasoning.release_metadata import REQUIRED, eligibility, release_metadata
from atlas_reasoning.reliability import CircuitBreaker, ProviderControls
from atlas_reasoning.rollout import (
    AUDIENCE_ENV,
    CARDS_PRIMARY_ENV,
    EXECUTION_ENV,
    EXECUTIVE_HOME_ENV,
    HUMAN_CONTEXT_ENV,
    STAGES,
    Audience,
    ExecutionDisabled,
    RolloutConfig,
    RolloutError,
    Surface,
    require_execution,
    rollout_config,
    stage,
    stage_of,
)
from atlas_reasoning.run_control import OrchestrationPolicy, RunOrchestrator
from atlas_reasoning.settings import GatewaySettings, ReasoningDisabled
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.executive import ExecutiveStore
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.teach_atlas import TeachAtlas
from atlas_reasoning.web_app import CSP, ReasoningWebApp, WebSettings

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
V3 = settings.FLAG_ENV
OUTAGE = (ProviderUnavailable("down"), ProviderUnavailable("down"))


def env_of(name: str, **changes: str) -> dict[str, str]:
    return {**stage(name).env, **changes}


def config_of(name: str, **changes: str) -> RolloutConfig:
    return rollout_config(env_of(name, **changes))


# --- the capability model (no database) ------------------------------------------------------------------------------------------


class RolloutConfigTests(unittest.TestCase):
    def test_safe_defaults(self):
        off = rollout_config({})
        self.assertEqual((off.enabled, off.execution, off.reasoning_visible, off.human_context, off.executive_home, off.stage),
                         (False, False, False, False, False, "off"))
        shadow = rollout_config({V3: "on"})                      # the master switch alone never shows anything: shadow
        self.assertEqual((shadow.execution, shadow.audience, shadow.reasoning_visible, shadow.cards_primary, shadow.human_context,
                          shadow.executive_home, shadow.stage), (True, Audience.NONE, False, False, False, False, "shadow"))
        self.assertEqual(shadow.primary_surface, Surface.DETERMINISTIC_DASHBOARD)

    def test_the_six_stages_are_valid_ordered_and_recognised(self):
        self.assertEqual([s.name for s in STAGES], ["off", "shadow", "internal_review", "management_beta", "cards_primary", "human_context",
                                                    "executive_home"])
        self.assertEqual([s.number for s in STAGES], list(range(7)))
        expected = {
            "shadow": (True, "none", False, False, False, Surface.DETERMINISTIC_DASHBOARD),
            "internal_review": (True, "internal", False, False, False, Surface.DETERMINISTIC_DASHBOARD),
            "management_beta": (True, "management", False, False, False, Surface.DETERMINISTIC_DASHBOARD),
            "cards_primary": (True, "management", True, False, False, Surface.REASONING_CARDS),
            "human_context": (True, "management", True, True, False, Surface.REASONING_CARDS),
            "executive_home": (True, "management", True, True, True, Surface.EXECUTIVE_BRIEF),
        }
        for item in STAGES:
            config = item.config()
            self.assertEqual(stage_of(config), item.name)
            if item.name in expected:
                self.assertEqual((config.execution, config.audience.value, config.cards_primary, config.human_context, config.executive_home,
                                  config.primary_surface), expected[item.name], item.name)
        beta, primary = config_of("management_beta"), config_of("cards_primary")
        self.assertTrue(beta.management_beta and not primary.management_beta)          # beta differs from primary as designed
        self.assertTrue(config_of("internal_review").internal_review and not beta.internal_review)

    def test_invalid_dependencies_fail_closed(self):
        invalid = [
            {V3: "on", CARDS_PRIMARY_ENV: "on"},                                           # primary for nobody
            {V3: "on", AUDIENCE_ENV: "internal", CARDS_PRIMARY_ENV: "on"},               # primary for management only
            {V3: "on", AUDIENCE_ENV: "internal", EXECUTIVE_HOME_ENV: "on"},
            {V3: "on", EXECUTIVE_HOME_ENV: "on"},                                          # executive-primary without visible reasoning
            {V3: "on", HUMAN_CONTEXT_ENV: "on"},                                           # human writes without a reasoning surface
            {V3: "off", HUMAN_CONTEXT_ENV: "on"},                                          # validated even with the master switch off
        ]
        for env in invalid:
            with self.subTest(env=env), self.assertRaises(RolloutError):
                rollout_config(env)
        with self.assertRaises(RolloutError):
            RolloutConfig(True, True, Audience.NONE, False, True, False)                # the type itself refuses, not only the parser

    def test_unknown_values_are_refused_without_echoing_anything_else(self):
        for env in ({V3: "on", AUDIENCE_ENV: "everyone"}, {V3: "maybe"}, {V3: "on", EXECUTION_ENV: "sometimes"},
                    {V3: "on", AUDIENCE_ENV: "management", CARDS_PRIMARY_ENV: "2"}):
            with self.subTest(env=env), self.assertRaises(RolloutError) as raised:
                rollout_config({**env, "OPENROUTER_API_KEY": "sk-or-v1-secret"})
            self.assertNotIn("sk-or-v1-secret", str(raised.exception))

    def test_internal_and_human_context_combinations_are_allowed(self):
        config = rollout_config({V3: "on", AUDIENCE_ENV: "internal", HUMAN_CONTEXT_ENV: "on"})
        self.assertEqual((config.internal_review, config.human_context, stage_of(config)), (True, True, "custom"))
        incident = config_of("human_context", **{EXECUTION_ENV: "off"})                 # a stage with processing paused: still valid
        self.assertEqual((incident.execution, incident.reasoning_visible, incident.human_context, incident.stage), (False, True, True, "custom"))

    def test_the_master_switch_turns_everything_off(self):
        config = rollout_config({**stage("executive_home").env, V3: "off"})
        self.assertEqual((config.execution, config.reasoning_visible, config.cards_primary, config.human_context, config.executive_home,
                          config.stage), (False, False, False, False, False, "off"))

    def test_nothing_is_enabled_implicitly(self):
        # A credential, a database URL or the memory flag never turns a capability on.
        env = {V3: "on", "OPENROUTER_API_KEY": "k", "HONCHO_API_KEY": "k", settings.DATABASE_URL_ENV: "postgresql://x/y", "ATLAS_REASONING_MEMORY": "on",
               "ATLAS_REASONING_MANAGERS": BOSS}
        config = rollout_config(env)
        self.assertEqual((config.reasoning_visible, config.human_context, config.executive_home, config.cards_primary), (False, False, False, False))

    def test_representation_is_deterministic_and_content_free(self):
        a, b = config_of("human_context").to_dict(), config_of("human_context").to_dict()
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(set(a), {"version", "stage", "enabled", "execution", "audience", "reasoning_visible", "internal_review", "management_beta",
                                  "cards_primary", "human_context", "executive_home", "primary_surface", "configured"})

    def test_execution_gate(self):
        with self.assertRaises(ReasoningDisabled):
            require_execution({})
        with self.assertRaises(ExecutionDisabled):
            require_execution({V3: "on", EXECUTION_ENV: "off"})
        self.assertTrue(issubclass(ExecutionDisabled, ReasoningDisabled))                # the CLI's existing exit-2 handling covers it
        self.assertTrue(require_execution({V3: "on"}).execution)


# --- the web application (PostgreSQL, the real pipeline with offline models) ------------------------------------------------------

ROUTES = ("/reasoning/", "/reasoning/en/", "/reasoning/ar/", "/reasoning/en/teach", "/reasoning/assets/dashboard.css", "/reasoning/assets/dashboard.js",
          "/api/reasoning/read/results", "/api/reasoning/csrf")


def table_digest(store: ReasoningStore) -> dict[str, tuple[int, str]]:
    """Every canonical table's row count and content hash: proof that nothing was deleted or rewritten."""
    with store.transaction() as tx:
        tables = [row["table_name"] for row in tx._all("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'atlas_reasoning'
                                                           AND table_type = 'BASE TABLE' ORDER BY table_name""")]
        digest = {}
        for table in tables:
            row = tx._one(f"SELECT count(*) AS n, md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) AS h FROM atlas_reasoning.{table} t")
            digest[table] = (int(row["n"]), str(row["h"]))
    return digest


@requires_db
class RolloutWebTests(unittest.TestCase):
    """One canonical state (cards, a note, an answer, a teaching, an ExecutiveBrief) served under every stage."""

    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.analyst, self.model = ScriptedAnalyst(), ScriptedExecutive()
        self.engine = ReasoningEngine(self.store, gateway(self.analyst, recorder=StoreCallRecorder(self.store)), retries=1)
        sync = human_context.sync_service(self.store, FakeHoncho())
        self.notes, self.questions, self.teach = ManagerNotes(self.store, sync), AtlasQuestions(self.store, sync), TeachAtlas(self.store, sync)
        self.service = DashboardService(self.store, notes=self.notes, questions=self.questions, teachings=self.teach)
        self.overview = ExecutiveOverviewService(self.store, self.service)
        self.settings = WebSettings(api_settings())
        self.management = ManagementAPI(self.settings.api, notes=self.notes, questions=self.questions, teachings=self.teach)
        report = run_gate(snapshots.reasoning_input(), self.store, now=times(1)[0])
        self.engine.process_run(report.run_id)
        ExecutiveSynthesizer(ExecutiveStore(self.store), gateway(self.model, recorder=StoreCallRecorder(self.store)), retries=1).synthesize(report.run_id)
        with self.store.transaction() as tx:
            self.rid = tx.open_result(next(d.case_id for d in report.decisions if d.identity_key == DEADLINE_12)).result_id

    def app(self, name: str, **changes: str) -> ReasoningWebApp:
        return ReasoningWebApp(self.settings, self.service, self.management, executive=self.overview, rollout=config_of(name, **changes))

    def page(self, app: ReasoningWebApp, path: str) -> str:
        status, headers, body = call(app, "GET", path)
        self.assertEqual(status, 200, path)
        self.assertEqual(headers["Content-Security-Policy"], CSP)
        return body.decode()

    def post_note(self, app: ReasoningWebApp, text: str, *, token: str | None = None, origin: str = ORIGIN) -> int:
        headers = {"Content-Type": "application/json", "X-Atlas-CSRF": token or self.management.csrf_token(BOSS), "Origin": origin}
        status, _, _ = call(app, "POST", f"/api/reasoning/results/{self.rid}/notes", body=json.dumps({"body": text}).encode(), headers=headers)
        return status

    def test_shadow_exposes_no_route_and_reads_nothing(self):
        app = self.app("shadow")
        before = table_digest(self.store)
        reads: list[str] = []
        spy = mock.patch.object(DashboardService, "__getattribute__", lambda obj, name: (reads.append(name), object.__getattribute__(obj, name))[1])
        for path in ROUTES + (f"/reasoning/en/results/{self.rid}", f"/reasoning/en/results/{self.rid}/evidence", f"/api/reasoning/read/results/{self.rid}"):
            for actor in (BOSS, None, "intruder@example.com"):
                with self.subTest(path=path, actor=actor):
                    status, headers, body = call(app, "GET", path, actor=actor)
                    self.assertEqual((status, body), (404, b"Not Found"))                # indistinguishable from a route that never existed
                    self.assertEqual(headers["Content-Security-Policy"], CSP)
        with spy:
            for path in ROUTES:
                call(app, "GET", path)
        self.assertEqual(reads, [])                                                    # not one canonical read in shadow
        self.assertEqual(self.post_note(app, "shadow write"), 404)
        self.assertEqual(table_digest(self.store), before)

    def test_internal_review_is_marked_and_read_only(self):
        app = self.app("internal_review")
        home = self.page(app, "/reasoning/en/")
        self.assertIn('data-state="rollout_internal"', home)
        self.assertNotIn('id="executive-brief"', home)
        self.assertIn("/en/dashboard.html", home)                                       # the deterministic dashboard stays one click away
        card = self.page(app, f"/reasoning/en/results/{self.rid}")
        self.assertIn('data-state="human_context_disabled"', card)
        self.assertNotIn("/reasoning/en/teach", card)
        self.assertEqual(call(app, "GET", "/reasoning/en/teach")[0], 404)
        self.assertEqual(call(app, "GET", "/api/reasoning/read/results")[0], 200)
        self.assertEqual(self.post_note(app, "internal write"), 404)
        self.assertIn('data-state="rollout_internal"', self.page(app, "/reasoning/ar/"))   # both locales

    def test_beta_differs_from_primary_and_rollback_restores_beta(self):
        beta, primary = self.page(self.app("management_beta"), "/reasoning/en/"), self.page(self.app("cards_primary"), "/reasoning/en/")
        self.assertIn('data-state="rollout_beta"', beta)
        self.assertNotIn('data-state="rollout_', primary)
        self.assertNotIn('id="executive-brief"', primary)
        self.assertEqual(self.page(self.app("management_beta"), "/reasoning/en/"), beta)        # back to beta: the same presentation, byte for byte

    def test_human_context_toggles_without_losing_anything(self):
        on = self.app("human_context")
        self.assertEqual(self.post_note(on, "Assignments changed in March."), 200)
        self.assertEqual(self.page(on, "/reasoning/en/teach").count("<h1"), 1)
        self.assertIn("Assignments changed in March.", self.page(on, f"/reasoning/en/results/{self.rid}"))
        with_note = table_digest(self.store)
        off = self.app("cards_primary")
        self.assertEqual(self.post_note(off, "Should be refused."), 404)
        self.assertEqual(call(off, "GET", "/api/reasoning/csrf")[0], 404)
        card = self.page(off, f"/reasoning/en/results/{self.rid}")
        self.assertIn('data-state="human_context_disabled"', card)
        self.assertNotIn("Should be refused.", card)
        self.assertNotIn("Assignments changed in March.", card)                       # stored, but not shown while off
        status, _, body = call(off, "GET", f"/api/reasoning/read/results/{self.rid}")   # review M1: nor through the read API
        self.assertEqual(status, 200)
        self.assertNotIn(b"Assignments changed in March.", body)
        self.assertEqual(json.loads(body)["human_context"], {"available": False, "disabled": True, "label": "management_context", "notes": [],
                                                              "note_history": {}, "questions": []})
        self.assertIn(b"Assignments changed in March.", call(on, "GET", f"/api/reasoning/read/results/{self.rid}")[2])
        self.assertEqual(table_digest(self.store), with_note)                         # disabling deleted and wrote nothing
        self.assertIn("Assignments changed in March.", self.page(self.app("human_context"), f"/reasoning/en/results/{self.rid}"))

    def test_an_enabled_capability_keeps_every_security_control(self):
        app = self.app("executive_home")
        self.assertEqual(call(app, "GET", "/reasoning/en/", actor=None)[0], 401)
        self.assertEqual(call(app, "GET", "/reasoning/en/", actor="intruder@example.com")[0], 403)
        self.assertEqual(self.post_note(app, "x", token="forged"), 403)
        self.assertEqual(self.post_note(app, "x", origin="https://evil.example.com"), 403)
        status, _, _ = call(app, "POST", f"/api/reasoning/results/{self.rid}/notes", body=b'{"body":"x"}',
                            headers={"Content-Type": "text/plain", "X-Atlas-CSRF": self.management.csrf_token(BOSS), "Origin": ORIGIN})
        self.assertEqual(status, 415)

    def test_executive_home_only_with_its_flag_and_rollback_preserves_brief_history(self):
        lead = self.page(self.app("executive_home"), "/reasoning/en/")
        self.assertIn('id="executive-brief"', lead)
        before = table_digest(self.store)
        for name in ("human_context", "cards_primary", "management_beta", "internal_review", "shadow", "off"):
            app = self.app(name)
            _, _, body = call(app, "GET", "/reasoning/en/")
            self.assertNotIn(b'id="executive-brief"', body, name)
        self.assertEqual(table_digest(self.store), before)                            # every brief, version and run is still there
        self.assertEqual(self.page(self.app("executive_home"), "/reasoning/en/"), lead)    # forward again: the same lead
        with self.assertRaises(RolloutError):
            config_of("internal_review", **{EXECUTIVE_HOME_ENV: "on"})

    def test_rollback_across_all_stages_deletes_nothing(self):
        self.assertEqual(self.post_note(self.app("executive_home"), "A note to keep."), 200)
        before = table_digest(self.store)
        for item in reversed(STAGES):
            app = self.app(item.name)
            for path in ROUTES + (f"/reasoning/en/results/{self.rid}",):
                call(app, "GET", path)
        for item in STAGES:
            call(self.app(item.name), "GET", "/reasoning/en/")
        self.assertEqual(table_digest(self.store), before)
        self.assertIn("A note to keep.", self.page(self.app("human_context"), f"/reasoning/en/results/{self.rid}"))

    def test_execution_off_keeps_accepted_results_readable(self):
        app = self.app("cards_primary", **{EXECUTION_ENV: "off"})
        self.assertFalse(app.rollout.execution)
        self.assertIn(self.rid, self.page(app, "/reasoning/en/"))
        self.assertIn(self.rid, json.dumps(json.loads(call(app, "GET", "/api/reasoning/read/results")[2])))

    def test_create_app_applies_the_rollout(self):
        from atlas_reasoning.web_app import create_app

        base = {"ATLAS_REASONING_CSRF_SECRET": "s" * 40, "ATLAS_REASONING_MANAGERS": BOSS, settings.DATABASE_URL_ENV: test_database_url() or ""}
        shadow = create_app({**base, **stage("shadow").env})
        self.assertEqual(call(shadow, "GET", "/reasoning/en/")[0], 404)
        beta = create_app({**base, **stage("management_beta").env})
        self.assertEqual(call(beta, "GET", "/reasoning/en/")[0], 200)
        with self.assertRaises(RolloutError):
            create_app({**base, V3: "on", HUMAN_CONTEXT_ENV: "on"})
        with self.assertRaises(ReasoningDisabled):
            create_app({**base, **stage("off").env})


@requires_db
class DegradedRolloutTests(unittest.TestCase):
    """Provider, memory and orchestration failures never turn into deterministic-data failure, and the last accepted cards stay readable."""

    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.transport = ScriptedAnalyst()
        self.honcho = FakeHoncho()
        self.controls = ProviderControls(1, breaker=CircuitBreaker(1, 60, monotonic=lambda: 1000.0))
        self.engine = ReasoningEngine(self.store, gateway(self.transport, recorder=StoreCallRecorder(self.store)), retries=1,
                                      context=HumanContext(self.store, self.honcho, env={}))
        self.t = times(6)
        self.runs = 0
        sync = human_context.sync_service(self.store, None)
        notes = ManagerNotes(self.store, sync)
        self.service = DashboardService(self.store, notes=notes, questions=AtlasQuestions(self.store, sync), teachings=TeachAtlas(self.store, sync))
        self.app = ReasoningWebApp(WebSettings(api_settings()), self.service, ManagementAPI(api_settings(), notes=notes), rollout=config_of("cards_primary"))

    def gate(self, payload: Any = None) -> Any:
        report = run_gate(payload or snapshots.reasoning_input(), self.store, now=self.t[self.runs])
        self.runs += 1
        return report

    def visible_cards(self) -> int:
        status, _, body = call(self.app, "GET", "/reasoning/en/")
        self.assertEqual(status, 200)
        return body.decode().count('class="rv-card"')

    def test_provider_outage_partial_run_keeps_the_previous_cards_visible(self):
        first = self.gate()
        RunOrchestrator(self.engine).run(first.run_id)
        shown = self.visible_cards()
        second = self.gate(payload_with(changed_rows()))
        case_id = next(d.case_id for d in second.decisions if d.identity_key == DEADLINE_12)
        self.transport.script(case_id, *OUTAGE)
        self.assertEqual(RunOrchestrator(self.engine).run(second.run_id).status, "partial")
        self.assertEqual(self.visible_cards(), shown)

    def test_honcho_outage_degrades_without_hiding_results(self):
        self.honcho.outage()
        first = self.gate()
        self.assertEqual(RunOrchestrator(self.engine).run(first.run_id).status, "degraded")
        self.assertGreater(self.visible_cards(), 0)

    def test_open_circuit_and_budget_exhaustion_keep_accepted_results(self):
        first = self.gate()
        RunOrchestrator(self.engine, policy=OrchestrationPolicy(max_calls_per_pass=3)).run(first.run_id)     # budget exhausted: partial
        shown = self.visible_cards()
        self.assertGreater(shown, 0)
        guarded = ReasoningGateway(self.transport, GatewaySettings(max_retries=1, backoff_seconds=0, max_backoff_seconds=0, concurrency=1),
                                   recorder=StoreCallRecorder(self.store), sleep=lambda seconds: None, controls=self.controls)
        engine = ReasoningEngine(self.store, guarded, retries=1)
        self.controls.breaker.record(self.controls.breaker.admit(), "timeout")                         # the breaker is open
        report = RunOrchestrator(engine).resume(first.run_id)
        self.assertIn(report.status, ("failed", "partial"))
        self.assertEqual(self.visible_cards(), shown)


# --- processing entry points, legacy preservation, isolation -------------------------------------------------------------------


class EntryPointTests(unittest.TestCase):
    def run_cli(self, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        clean = {key: value for key, value in os.environ.items() if not key.startswith(("ATLAS_REASONING", "OPENROUTER", "HONCHO"))}
        return subprocess.run([sys.executable, "-m", "atlas_reasoning", *args], env={**clean, "PYTHONPATH": str(SRC), **env}, capture_output=True,
                              text=True, check=False)

    def test_processing_commands_honour_the_execution_flag(self):
        for command in (("gate", "/nonexistent-site"), ("reason", "run_" + "0" * 32)):
            off = self.run_cli(*command, env={V3: "on", EXECUTION_ENV: "off"})
            self.assertEqual((off.returncode, json.loads(off.stderr)["error"]), (2, "ExecutionDisabled"), command)
            self.assertNotIn("Traceback", off.stderr)

    def test_rollout_command(self):
        result = self.run_cli("rollout", env=stage("management_beta").env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["stage"], "management_beta")
        invalid = self.run_cli("rollout", env={V3: "on", EXECUTIVE_HOME_ENV: "on"})
        self.assertEqual((invalid.returncode, json.loads(invalid.stderr)["error"]), (2, "RolloutError"))
        stages = json.loads(self.run_cli("rollout", "--stages", env={}).stdout)["stages"]
        self.assertEqual([row["name"] for row in stages], [s.name for s in STAGES])

    def test_only_entry_points_read_the_rollout(self):
        """The rollout gates entry points; the reasoning core never reads it (no capability check inside the engine or the store)."""
        importers, readers = set(), set()
        names = ("ATLAS_REASONING_EXECUTION", "ATLAS_REASONING_AUDIENCE", "ATLAS_REASONING_CARDS_PRIMARY", "ATLAS_REASONING_HUMAN_CONTEXT",
                 "ATLAS_REASONING_EXECUTIVE_HOME")
        for path in (SRC / "atlas_reasoning").rglob("*.py"):
            text = path.read_text()
            tree = ast.parse(text)
            for node in ast.walk(tree):
                imported = (isinstance(node, ast.ImportFrom) and node.module is not None and node.module.endswith("rollout")) or \
                    (isinstance(node, ast.ImportFrom) and node.module == "atlas_reasoning" and any(a.name == "rollout" for a in node.names)) or \
                    (isinstance(node, ast.Import) and any(a.name.endswith(".rollout") for a in node.names))
                if imported:
                    importers.add(path.relative_to(SRC / "atlas_reasoning").as_posix())
            docstrings = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
                          and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
            literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in docstrings}
            if path.name != "rollout.py" and any(name in literal for literal in literals for name in names):
                readers.add(path.name)
        self.assertEqual(importers, {"__main__.py", "web_app.py", "release_metadata.py"})
        self.assertEqual(readers, set())                                               # nobody reads the variables around rollout.py

    def test_deterministic_atlas_never_imports_reasoning_rollout(self):
        for package in ("atlas_commander", "atlas_sync"):
            for path in (SRC / package).rglob("*.py"):
                text = path.read_text()
                self.assertNotIn("atlas_reasoning", text, path)
                for name in ("ATLAS_REASONING_AUDIENCE", "ATLAS_REASONING_EXECUTION", "ATLAS_REASONING_CARDS_PRIMARY"):
                    self.assertNotIn(name, text, path)


class LegacySiteTests(unittest.TestCase):
    """The deterministic Atlas site (Intelligence V2 views, dashboards, evidence) is byte-identical at every stage."""

    def test_static_site_is_identical_at_every_stage(self):
        from test_reasoning_boundary import build_showcase

        def build(env: dict[str, str]) -> dict[str, str]:
            out = Path(tempfile.mkdtemp(prefix="atlas-rollout-site-"))
            clean = {key: value for key, value in os.environ.items() if not key.startswith("ATLAS_REASONING")}
            with mock.patch.dict(os.environ, {**clean, **env}, clear=True):
                build_showcase(out)
            return {path.relative_to(out).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(out.rglob("*")) if path.is_file()}

        baseline = build(stage("off").env)
        self.assertTrue(any("dashboard" in name for name in baseline))
        for name in ("shadow", "executive_home"):
            self.assertEqual(build(stage(name).env), baseline, name)


# --- release metadata and eligibility ---------------------------------------------------------------------------------------------

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def passing_run() -> dict[str, Any]:
    """A Phase 19 runner result that is a release PASS (synthetic observations meeting every published expectation)."""
    from test_reasoning_evaluation import synthetic_observations

    from atlas_reasoning.evaluation import evaluate, load_golden_cases

    cases = load_golden_cases()
    report = evaluate(cases, synthetic_observations(cases), environment={"provider": "offline-model"})
    canonical = report.canonical_json()
    return {"schema": "reasoning-evaluation-run-v1", "runner": "evaluation-runner-v1", "mode": "offline", "result": "PASS", "code": "PASS",
            "exit_code": 0, "failures": [], "audit": None, "budget": None, "report_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "report": json.loads(canonical)}


class ReleaseMetadataTests(unittest.TestCase):
    ENV: ClassVar[dict[str, str]] = {V3: "on", "OPENROUTER_API_KEY": "sk-or-v1-supersecret", "HONCHO_API_KEY": "hch-supersecret",
           settings.DATABASE_URL_ENV: "postgresql://atlas:dbpassword@db/atlas", "ATLAS_REASONING_CSRF_SECRET": "c" * 40}

    def test_complete_deterministic_and_derived_from_code(self):
        first, second = release_metadata(commit=COMMIT, env=self.ENV), release_metadata(commit=COMMIT, env=self.ENV)
        self.assertEqual(first.missing(), [])
        self.assertEqual(first.to_json(), second.to_json())
        fields = first.to_dict()
        self.assertEqual(set(REQUIRED) - set(fields), set())
        self.assertEqual((fields["model"], fields["model_override"], fields["commit"]), (settings.PINNED_MODEL, False, COMMIT))
        self.assertEqual(fields["latest_migration"], max(p.name for p in (SRC / "atlas_reasoning" / "store" / "migrations").glob("*.sql")))
        self.assertEqual(fields["rollout"]["stage"], "shadow")
        self.assertEqual(fields["release_thresholds"], "release-thresholds-v1")

    def test_no_secret_ever(self):
        text = release_metadata(commit=COMMIT, env=self.ENV).to_json()
        for secret in ("sk-or-v1-supersecret", "hch-supersecret", "dbpassword", "c" * 40, "postgresql://"):
            self.assertNotIn(secret, text)

        def keys(value: Any) -> set[str]:
            if isinstance(value, dict):
                return set(value) | {k for v in value.values() for k in keys(v)}
            return set()

        for key in keys(json.loads(text)):
            self.assertFalse(any(word in key.lower() for word in ("key", "secret", "password", "token", "url")), key)

    def test_incomplete_without_a_valid_commit(self):
        for commit in (None, "", "not-a-sha", "ABC"):
            self.assertEqual(release_metadata(commit=commit, env=self.ENV).missing(), ["commit"])

    def test_the_commit_is_never_guessed(self):
        """Review L1: a dirty checkout or a foreign repository gives no commit (incomplete metadata), never the wrong one."""
        from atlas_reasoning import __main__ as entry

        package_root = str(SRC.parent)

        def runner(outputs: dict[str, str]) -> Any:
            def run(args: list[str], **kwargs: Any) -> Any:
                key = " ".join(args[1:])
                return subprocess.CompletedProcess(args, 0 if key in outputs else 1, outputs.get(key, ""), "")
            return run

        clean = {"rev-parse --show-toplevel": package_root + "\n", "rev-parse HEAD": COMMIT + "\n", "status --porcelain": ""}
        with mock.patch("subprocess.run", runner(clean)):
            self.assertEqual(entry._commit(None), COMMIT)
        with mock.patch("subprocess.run", runner({**clean, "status --porcelain": " M src/x.py\n"})):
            self.assertIsNone(entry._commit(None))
        with mock.patch("subprocess.run", runner({**clean, "rev-parse --show-toplevel": "/somewhere/else\n"})):
            self.assertIsNone(entry._commit(None))
        with mock.patch("subprocess.run", side_effect=OSError("no git")):
            self.assertIsNone(entry._commit(None))
        self.assertEqual(entry._commit(COMMIT), COMMIT)

    def test_model_override_is_recorded(self):
        fields = release_metadata(commit=COMMIT, env={**self.ENV, settings.MODEL_ENV: "openai/other", settings.MODEL_OVERRIDE_ENV: "on"}).to_dict()
        self.assertEqual((fields["model"], fields["model_override"]), ("openai/other", True))


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.rollout = config_of("management_beta")
        self.metadata = release_metadata(commit=COMMIT, env=stage("management_beta").env, rollout=self.rollout)
        self.run = passing_run()

    def test_a_release_pass_of_this_software_is_eligible(self):
        result = eligibility(self.run, self.metadata, self.rollout).to_dict()
        self.assertEqual((result["eligible"], result["reasons"], result["evaluation_mode"]), (True, [], "offline"))
        self.assertEqual(len(result["outstanding"]), 3)                               # live run, human review, stage approval remain
        self.assertIn("repository release eligibility", result["scope"])

    def test_every_failed_condition_blocks(self):
        def mutated(change: Any) -> dict[str, Any]:
            run = copy.deepcopy(self.run)
            change(run)
            return run

        def resign(run: dict[str, Any]) -> None:
            canonical = json.dumps(run["report"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            run["report_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()

        cases = {
            "no evaluation": None,
            "failed evaluation": mutated(lambda r: r.update(code="EVALUATION_FAILED", result="FAIL", exit_code=1)),
            "audit inconsistency": mutated(lambda r: r.update(code="EVALUATION_AUDIT_INCONSISTENCY", result="FAIL", exit_code=3, report=None)),
            "tampered report": mutated(lambda r: r["report"]["metrics"][0].update(numerator=0)),
            "other thresholds": mutated(lambda r: (r["report"]["thresholds"].update(version="lax"), resign(r))),
            "other fixtures": mutated(lambda r: (r["report"]["coverage"].update(fixture_digest="sha256:" + "0" * 64), resign(r))),
            "other software": mutated(lambda r: (r["report"]["versions"].update(engine="reasoning-engine-v0"), resign(r))),
            "partial coverage": mutated(lambda r: (r["report"]["coverage"].update(missing=[18]), resign(r))),
            "not a runner result": mutated(lambda r: r.update(schema="something-else")),
        }
        for name, run in cases.items():
            with self.subTest(name):
                result = eligibility(run, self.metadata, self.rollout)
                self.assertFalse(result.eligible)
                self.assertTrue(result.reasons)
        verdicts = mutated(lambda r: (r["report"]["threshold_results"][0].update(passed=False), resign(r)))     # review M3
        self.assertIn("evaluation: the report's own threshold verdicts and failures do not support its PASS",
                      eligibility(verdicts, self.metadata, self.rollout).reasons)
        overridden = release_metadata(commit=COMMIT, env={**stage("management_beta").env, settings.MODEL_ENV: "openai/other",
                                                          settings.MODEL_OVERRIDE_ENV: "on"}, rollout=self.rollout)              # review M2
        self.assertIn("model: the release runs an overridden model; Phase 19 evaluates the pinned model only",
                      eligibility(self.run, overridden, self.rollout).reasons)
        incomplete = release_metadata(commit=None, env=stage("management_beta").env, rollout=self.rollout)
        self.assertIn("metadata: missing commit", eligibility(self.run, incomplete, self.rollout).reasons)
        self.assertIn("rollout: the metadata does not describe this rollout configuration",
                      eligibility(self.run, self.metadata, config_of("cards_primary")).reasons)

    def test_eligibility_never_reads_threshold_values(self):
        """Phase 19 is the authority: eligibility trusts its PASS, checks integrity and binding, and never re-evaluates a metric."""
        tree = ast.parse((SRC / "atlas_reasoning" / "release_metadata.py").read_text())
        imported = {(node.module, alias.name) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
        self.assertEqual({name for module, name in imported if module == "atlas_reasoning.evaluation_thresholds"}, {"RELEASE_THRESHOLDS_VERSION"})
        self.assertFalse({name for module, name in imported if module in ("atlas_reasoning.evaluation_metrics", "fractions")})
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertFalse(used & {"evaluate_thresholds", "compute_metrics", "exact_bound", "bound", "check", "Fraction", "evaluate"})
        keys = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        self.assertFalse(keys & {"bound", "numerator", "denominator", "value", "exact_value"})      # never reads a metric or threshold value

    def test_cli_eligibility_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            path.write_text(json.dumps(self.run), encoding="utf-8")
            clean = {key: value for key, value in os.environ.items() if not key.startswith(("ATLAS_REASONING", "OPENROUTER", "HONCHO"))}
            env = {**clean, "PYTHONPATH": str(SRC), **stage("management_beta").env}
            ok = subprocess.run([sys.executable, "-m", "atlas_reasoning", "release-eligibility", "--evaluation", str(path), "--commit", COMMIT], env=env,
                                capture_output=True, text=True, check=False)
            self.assertEqual((ok.returncode, json.loads(ok.stdout)["eligible"]), (0, True), ok.stderr)
            path.write_text(json.dumps({**self.run, "code": "EVALUATION_FAILED"}), encoding="utf-8")
            bad = subprocess.run([sys.executable, "-m", "atlas_reasoning", "release-eligibility", "--evaluation", str(path), "--commit", COMMIT], env=env,
                                 capture_output=True, text=True, check=False)
            self.assertEqual(bad.returncode, 1)
            meta = subprocess.run([sys.executable, "-m", "atlas_reasoning", "release-metadata", "--commit", COMMIT], env=env, capture_output=True, text=True,
                                  check=False)
            self.assertEqual((meta.returncode, json.loads(meta.stdout)["complete"]), (0, True))
            self.assertNotIn("Traceback", ok.stderr + bad.stderr + meta.stderr)


if __name__ == "__main__":
    unittest.main()
