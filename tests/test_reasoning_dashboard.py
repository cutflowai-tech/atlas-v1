"""Phase 16 (REV/16): the reasoning-first dashboard.

Canonical rendering, evidence drill-down and resolution, lifecycle and version history, human context (notes, questions, answers,
Teach Atlas) mounted through the management API, security (escaping, CSRF, auth, forbidden actors, invalid IDs, headers), degraded and
error states, English/Arabic parity, and compatibility (flag off, unchanged Phase 12-14 fragments, nothing upstream imports the app).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from wsgiref.util import setup_testing_defaults

import reasoning_factory as factory
import reasoning_snapshots as snapshots
from human_context_fixtures import editor_case, patch_result, question, seed_case
from reasoning_db import fresh_database, requires_db
from reasoning_engine_support import DEADLINE_12, changed_rows, payload_with, times
from reasoning_fakes import ScriptedAnalyst, analyst_answer, gateway, update_answer

from atlas_reasoning import dashboard_html as H
from atlas_reasoning import dashboard_i18n as i18n
from atlas_reasoning import dashboard_routes as routes
from atlas_reasoning import human_context, lifecycle
from atlas_reasoning.atlas_questions import Answer, AtlasQuestions, Question
from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.contracts import ReasoningResult, new_result_id
from atlas_reasoning.dashboard import (
    EVIDENCE_CHANGED,
    MEMORY_DEGRADED,
    PROVIDER_FAILED,
    UPDATE_PENDING,
    VALIDATION_REFUSED,
    DashboardService,
    DashboardUnavailable,
)
from atlas_reasoning.dashboard_assets import CSS, JS
from atlas_reasoning.engine import ReasoningEngine
from atlas_reasoning.enums import GateAction, LifecycleStatus, WorkKind, WorkStatus
from atlas_reasoning.fake_honcho import FakeHoncho
from atlas_reasoning.human_context_html import note_panel, question_panel, teach_atlas_page
from atlas_reasoning.management_api import ApiSettings, ManagementAPI
from atlas_reasoning.manager_notes import ManagerNotes, Note
from atlas_reasoning.provider import ProviderAuthError
from atlas_reasoning.reasoning_context import HumanContext
from atlas_reasoning.settings import ReasoningConfigError, ReasoningDisabled
from atlas_reasoning.store import human_context as hc_sql
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.db import Database
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.teach_atlas import TeachAtlas, Teaching
from atlas_reasoning.web_app import CSP, ReasoningWebApp, WebSettings, create_app, web_settings

ROOT = Path(__file__).resolve().parents[1]
BOSS = "boss@example.com"
SECRET = b"s" * 40
ORIGIN = "https://atlas.example.com"
XSS = '<script>alert("x")</script>"><img src=x onerror=alert(1)>'
LIFECYCLES = ("new", "active", "updated", "cooling", "resolved", "superseded")
NOW = "2026-09-30T00:00:00.000000Z"


def api_settings() -> ApiSettings:
    return ApiSettings(managers=frozenset({BOSS}), csrf_secret=SECRET, allowed_origins=frozenset({ORIGIN}))


class Attrs(HTMLParser):
    """Every start tag's attributes, and ``<script>`` tags, of a page."""

    def __init__(self, page: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.feed(page)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def values(self, name: str) -> list[str]:
        return [str(attrs[name]) for _, attrs in self.tags if attrs.get(name) is not None]

    def ids(self) -> set[str]:
        return set(self.values("id"))

    def scripts(self) -> list[dict[str, str | None]]:
        return [attrs for tag, attrs in self.tags if tag == "script"]


def canonical_ids(page: str) -> dict[str, list[str]]:
    """The canonical identifiers a page shows (what must be identical in English and Arabic)."""
    parsed = Attrs(page)
    return {name: parsed.values(name) for name in ("data-result-id", "data-case-id", "data-version", "data-current-version", "data-lifecycle",
                                                   "data-confidence", "data-ref-id", "data-finding-id", "data-note-id", "data-question-id",
                                                   "data-answer-id", "data-notice", "data-source-type", "data-state", "data-teaching-id")}


def call(app: ReasoningWebApp, method: str, path: str, *, actor: str | None = BOSS, body: bytes = b"", headers: dict[str, str] | None = None
         ) -> tuple[int, dict[str, str], bytes]:
    environ: dict[str, Any] = {}
    setup_testing_defaults(environ)
    path, _, query = path.partition("?")
    environ.update(REQUEST_METHOD=method, PATH_INFO=path, QUERY_STRING=query, CONTENT_LENGTH=str(len(body)), **{"wsgi.input": io.BytesIO(body)})
    if actor is not None:
        environ["REMOTE_USER"] = actor
    for name, value in (headers or {}).items():
        if name.lower() == "content-type":
            environ["CONTENT_TYPE"] = value
        else:
            environ["HTTP_" + name.upper().replace("-", "_")] = value
    captured: dict[str, Any] = {}

    def start_response(status: str, header_list: list[tuple[str, str]]) -> None:
        captured["status"], captured["headers"] = int(status.split()[0]), dict(header_list)

    out = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], out


# --- no database ------------------------------------------------------------------------------------------------------------------


class RouteTests(unittest.TestCase):
    RID = "rr1_" + "a" * 32

    def test_stable_card_addresses(self):
        self.assertEqual(routes.card_path("en", self.RID), f"/reasoning/en/results/{self.RID}#result-{self.RID}")
        self.assertEqual(routes.card_path("ar", self.RID, version=2), f"/reasoning/ar/results/{self.RID}?version=2#result-{self.RID}")
        self.assertEqual(routes.evidence_path("en", self.RID), f"/reasoning/en/results/{self.RID}/evidence")
        self.assertEqual(routes.history_path("ar", self.RID), f"/reasoning/ar/results/{self.RID}/history")
        self.assertEqual(routes.card_anchor(self.RID), f"result-{self.RID}")
        links = routes.result_links("en", [self.RID, self.RID, "rr1_" + "b" * 32])
        self.assertEqual([link["result_id"] for link in links], [self.RID, "rr1_" + "b" * 32])
        self.assertEqual(set(links[0]), {"result_id", "card", "evidence", "history"})

    def test_injected_ids_and_locales_are_refused(self):
        for bad in ("rr1_" + "A" * 32, "../etc/passwd", "rr1_" + "a" * 31, f'{self.RID}"><script>', f"{self.RID}/../x", "", "javascript:alert(1)"):
            with self.assertRaises(routes.InvalidRoute, msg=bad):
                routes.card_path("en", bad)
            with self.assertRaises(routes.InvalidRoute):
                routes.result_links("en", [bad])
        with self.assertRaises(routes.InvalidRoute):
            routes.home_path("fr")
        for version in (0, -1, True, "2"):
            with self.assertRaises(routes.InvalidRoute):
                routes.card_path("en", self.RID, version=version)  # type: ignore[arg-type]


class CrossReviewFixTests(unittest.TestCase):
    """Regression tests for Chat B's cross-review of PR #37 (findings L1, L4, L5, L7)."""

    RID = "rr1_" + "a" * 32

    def test_a_trailing_newline_is_never_a_canonical_id(self):
        for bad in (self.RID + "\n", self.RID + "\r\n", None, 5):
            with self.assertRaises(routes.InvalidRoute):
                routes.card_path("en", bad)  # type: ignore[arg-type]
            with self.assertRaises(routes.InvalidRoute):
                routes.result_links("en", [bad])  # type: ignore[list-item]
            with self.assertRaises(routes.InvalidRoute):
                routes.parse_result_id(bad)  # type: ignore[arg-type]
        settings = WebSettings(api_settings())
        notes = ManagerNotes(ReasoningStore(Database("postgresql://nobody@127.0.0.1:1/atlas_reasoning_test")), human_context.sync_service(None, None))  # type: ignore[arg-type]
        app = ReasoningWebApp(settings, _Unavailable(), ManagementAPI(settings.api, notes=notes))  # type: ignore[arg-type]
        for path in (f"/reasoning/en/results/{self.RID}\n", f"/reasoning/en/results/{self.RID}/evidence\n", "/reasoning/en/\n",
                     f"/api/reasoning/read/results/{self.RID}\n", "/api/reasoning/read/results\n"):
            self.assertEqual(call(app, "GET", path)[0], 404, repr(path))
        self.assertEqual(call(app, "GET", f"/api/reasoning/read/results/{self.RID}?version=1%0A")[0], 400)
        token = app.management.csrf_token(BOSS)
        status, _, _ = call(app, "GET", f"/api/reasoning/results/{self.RID}/notes\n")
        self.assertEqual(status, 404)
        status, _, _ = call(app, "POST", "/api/reasoning/results/rr1_x/notes\n", body=b'{"body":"x"}',
                            headers={"Content-Type": "application/json", "X-Atlas-CSRF": token, "Origin": ORIGIN})
        self.assertEqual(status, 404)

    def test_form_actions_carry_ids_as_one_encoded_segment(self):
        hostile = "x/../../teachings"
        note = Note(hostile, hostile, "rc1_y", None, "b", 1, "t", "t")
        html = note_panel(hostile, [note], csrf_token="t")
        question = Question(hostile, "rc1", hostile, 1, "Q?", "r", "other", "open", 1, "t", "t", None, None, None, ())
        html += question_panel(hostile, [question], csrf_token="t")
        html += teach_atlas_page([Teaching(hostile, "b", "company", None, "context", "until_changed", None, None, "active", None, 1, False, True, "t", "t")],
                                 csrf_token="t")
        actions = Attrs(html).values("action")
        self.assertTrue(actions)
        for action in actions:
            self.assertNotIn("/../", action)
            if "x%2F..%2F..%2Fteachings" not in action:
                self.assertEqual(action, "/api/reasoning/teachings")                  # the create form, no ID

    def test_identities_never_collide_through_case_folding(self):
        settings = ApiSettings(managers=frozenset({"boss@x.com"}), csrf_secret=SECRET)
        api = ManagementAPI(settings, notes=None)  # type: ignore[arg-type]
        from atlas_reasoning.management_api import ApiError, authorize_actor
        self.assertEqual(authorize_actor(settings, "Boss@X.com"), "Boss@X.com")          # ASCII stays case-insensitive
        for intruder in ("boß@x.com", "ｂｏｓｓ@x.com"):
            with self.assertRaises(ApiError):
                authorize_actor(settings, intruder)
            self.assertNotEqual(api.csrf_token(intruder), api.csrf_token("boss@x.com"))

    def test_apostrophes_in_stored_text_render_as_before_phase_16(self):
        n = Note("mn_1", "rr1_x", "rc1_y", "o'neil@b.c", "It's \"quoted\" & <b>x</b>", 2, "t", "t")
        h = {"mn_1": [{"revision": 1, "body": "isn't", "author": "d'arcy", "recorded_at": "t"}]}
        a = Answer("aa_1", "qq_1", "Don't know", "o'neil", "t", "aa_0")
        q = [Question("qq_1", "rc1", "rr1_x", 1, "What's \"next\"?", "Monday doesn't show it's <i>", "assignment_context", "answered", 1, "t", "t", None,
                      None, None, (a,)),
             Question("qq_2", "rc1", "rr1_x", 1, "Q2", "why's", "other", "open", 1, "t", "t", None, None, None, ())]
        ts = [Teaching("tt_1", "It's a rule", "editor", "o'k", "correction", "date_range", "2026-01-01", "2026-02-01", "active", "o'neil", 2, True, False,
                       "t", "t")]
        out = note_panel("rr1_x", [n], csrf_token="t'k", history=h) + question_panel("rr1_x", q, csrf_token="t'k") + teach_atlas_page(ts, csrf_token="t'k")
        # SHA-256 of the same fragments rendered by human_context_html at fd4b140 (before Phase 16).
        self.assertEqual(hashlib.sha256(out.encode()).hexdigest(), "d3cb6a921e5f69e6757b3552827d07200c7f4cf8e2cd3a96322dbd8204236642")
        self.assertIn("Why it matters: Monday doesn&#x27;t show it&#x27;s &lt;i&gt;", out)


class LocalizationTests(unittest.TestCase):
    def test_catalogs_have_the_same_keys_and_placeholders(self):
        self.assertEqual(set(i18n.EN), set(i18n.AR))
        placeholder = re.compile(r"\{(\w+)\}")
        for key in i18n.EN:
            self.assertTrue(i18n.EN[key].strip() and i18n.AR[key].strip(), key)
            self.assertEqual(sorted(placeholder.findall(i18n.EN[key])), sorted(placeholder.findall(i18n.AR[key])), key)

    def test_every_lifecycle_confidence_notice_and_reason_has_wording(self):
        keys = [f"lifecycle.{s}" for s in LIFECYCLES] + [f"lifecycle.{s}.help" for s in LIFECYCLES]
        keys += [f"confidence.{c}" for c in ("weak", "moderate", "strong")]
        keys += [f"notice.{n}" for n in (EVIDENCE_CHANGED, UPDATE_PENDING, PROVIDER_FAILED, VALIDATION_REFUSED, "refresh_failed", MEMORY_DEGRADED)]
        keys += [f"reason.{r}" for transitions in lifecycle.TRANSITIONS.values() for r in transitions]
        keys += [f"subject.{s}" for s in ("editor", "team", "video_type", "workflow_stage", "project", "data_source")]
        for key in keys:
            self.assertTrue(i18n.has("en", key) and i18n.has("ar", key), key)

    def test_t_escapes_parameters(self):
        self.assertEqual(i18n.t("en", "card.version", n=XSS), "Version " + XSS.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


class FragmentCompatibilityTests(unittest.TestCase):
    """The Phase 12-14 fragments render exactly as before in English; Arabic changes only the interface wording."""

    def fragments(self, locale: str | None = None) -> str:
        kw = {} if locale is None else {"locale": locale}
        n1 = Note("mn_1", "rr1_x", "rc1_y", "a@b.c", "Hello <b>x</b>\nline2", 2, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        n2 = Note("mn_2", "rr1_x", "rc1_y", None, "Plain", 1, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
        hist = {"mn_1": [{"revision": 1, "body": "old <i>", "author": "z", "recorded_at": "t"}, {"revision": 2, "body": "x", "author": "a", "recorded_at": "t2"}]}
        a1, a2 = Answer("aa_1", "qq_1", "ans", "m", "t", None), Answer("aa_2", "qq_1", "ans2", None, "t2", "aa_1")
        qs = [Question("qq_1", "rc1", "rr1_x", 1, "Q <b>?", "why", "assignment_context", "answered", 1, "t", "t", None, None, None, (a1, a2)),
              Question("qq_2", "rc1", "rr1_x", 1, "Q2", "why2", "business_rule", "open", 2, "t", "t", None, None, None, ()),
              Question("qq_3", "rc1", "rr1_x", 1, "Q3", "why3", "other", "dismissed", 1, "t", "t", None, None, "r", ())]
        ts = [Teaching("tt_1", "body <x>", "editor", "e1", "correction", "date_range", "2026-01-01", "2026-02-01", "active", "au", 2, True, False, "t", "t"),
              Teaching("tt_2", "b2", "company", None, "context", "until_changed", None, None, "disabled", None, 1, False, False, "t", "t"),
              Teaching("tt_3", "b3", "client", "c", "context", "current_period", None, None, "archived", None, 1, False, False, "t", "t")]
        return (note_panel("rr1_x", [n1, n2], csrf_token="tok", history=hist, **kw) + note_panel("rr1_x", [], csrf_token="tok", **kw)
                + question_panel("rr1_x", qs, csrf_token="tok", **kw) + question_panel("rr1_x", [], csrf_token="t", **kw)
                + teach_atlas_page(ts, csrf_token="tok", **kw) + teach_atlas_page([], csrf_token="tok", **kw))

    def test_english_fragments_are_byte_identical_to_phases_12_14(self):
        # SHA-256 of these fragments rendered by human_context_html at fd4b140 (before Phase 16).
        self.assertEqual(hashlib.sha256(self.fragments().encode()).hexdigest(), "a52afce79337df7c91b32c67da7300cf425bc5b2f1fa329d697c998611711b3b")
        self.assertEqual(self.fragments("en"), self.fragments())

    def test_arabic_fragments_carry_the_same_records(self):
        en, ar = self.fragments("en"), self.fragments("ar")
        self.assertNotEqual(en, ar)
        self.assertEqual(canonical_ids(en), canonical_ids(ar))
        self.assertIn("سياق إداري، وليس دليلًا", ar)
        for stored in ("Hello &lt;b&gt;x&lt;/b&gt;", "Q &lt;b&gt;?", "body &lt;x&gt;"):
            self.assertIn(stored, ar)                                        # stored text is shown as written, escaped
        self.assertNotIn("<b>x", ar)


class StaticSafetyTests(unittest.TestCase):
    def test_the_script_computes_nothing_and_never_writes_markup(self):
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "Math.", "toFixed",
                          "confidence", "lifecycle", "metric", "localStorage", "sessionStorage"):
            self.assertNotIn(forbidden, JS, forbidden)
        self.assertIn('"X-Atlas-CSRF"', JS)
        self.assertIn("textContent", JS)
        self.assertNotIn("url(", CSS)                                       # no external resource from the stylesheet
        self.assertNotIn("@import", CSS)

    def test_nothing_upstream_imports_the_dashboard(self):
        for package in ("atlas_commander", "atlas_sync", "atlas_monday_probe"):
            for path in (ROOT / "src" / package).rglob("*.py"):
                self.assertNotIn("atlas_reasoning", path.read_text(), str(path))

    def test_web_settings_validation(self):
        WebSettings(api_settings(), diagnostics_url="/{locale}/dashboard.html", monday_item_url="https://x.monday.com/items/{item_id}")
        WebSettings(api_settings(), diagnostics_url="https://atlas.example.com/{locale}/dashboard.html")
        for bad in ("javascript:alert(1)", "//evil.example/x", "/x\" onmouseover=\"y", "http://plain.example/", "/a b"):
            with self.assertRaises(ReasoningConfigError, msg=bad):
                WebSettings(api_settings(), diagnostics_url=bad)
        for bad in ("http://x/{item_id}", "https://x/", "javascript:{item_id}", "https://x/{item_id}\"><"):
            with self.assertRaises(ReasoningConfigError, msg=bad):
                WebSettings(api_settings(), monday_item_url=bad)
        with self.assertRaises(ReasoningConfigError):
            WebSettings(api_settings(), actor_header="X-User: evil")
        env = {"ATLAS_REASONING_CSRF_SECRET": "s" * 40, "ATLAS_REASONING_MANAGERS": BOSS, "ATLAS_REASONING_ACTOR_HEADER": "X-Forwarded-User"}
        self.assertEqual(web_settings(env).actor_header, "X-Forwarded-User")

    def test_reasoning_v3_off_refuses_to_start_the_app(self):
        for env in ({}, {"ATLAS_REASONING_V3": "off"}):
            with self.assertRaises(ReasoningDisabled):
                create_app(env)


class _Unavailable:
    """A dashboard service whose canonical reads fail (database down)."""

    def __getattr__(self, name: str) -> Any:
        def fail(*args: Any, **kwargs: Any) -> Any:
            raise DashboardUnavailable("down")
        return fail


class WebSecurityTests(unittest.TestCase):
    """Mounting rules that need no database: auth, methods, invalid paths, headers, error pages."""

    def setUp(self):
        settings = WebSettings(api_settings())
        notes = ManagerNotes(ReasoningStore(Database("postgresql://nobody@127.0.0.1:1/atlas_reasoning_test")), human_context.sync_service(None, None))  # type: ignore[arg-type]
        self.app = ReasoningWebApp(settings, _Unavailable(), ManagementAPI(settings.api, notes=notes))  # type: ignore[arg-type]

    def test_pages_require_an_allowed_manager(self):
        status, _, body = call(self.app, "GET", "/reasoning/en/", actor=None)
        self.assertEqual(status, 401)
        self.assertIn(b'data-error="unauthenticated"', body)
        status, _, body = call(self.app, "GET", "/reasoning/ar/", actor="intruder@example.com")
        self.assertEqual(status, 403)
        self.assertIn('dir="rtl"', body.decode())
        self.assertEqual(call(self.app, "GET", "/api/reasoning/read/results", actor=None)[0], 401)
        self.assertEqual(call(self.app, "GET", "/api/reasoning/read/results", actor="intruder@example.com")[0], 403)

    def test_security_headers_on_every_response(self):
        for path in ("/reasoning/en/", "/api/reasoning/read/results", "/reasoning/assets/dashboard.js", "/nowhere"):
            _, headers, _ = call(self.app, "GET", path)
            self.assertEqual(headers["Content-Security-Policy"], CSP, path)
            self.assertEqual((headers["X-Content-Type-Options"], headers["X-Frame-Options"], headers["Referrer-Policy"]), ("nosniff", "DENY", "no-referrer"))
        self.assertNotIn("unsafe-inline", CSP)
        self.assertEqual(call(self.app, "GET", "/reasoning/assets/dashboard.css")[1]["Content-Type"], "text/css; charset=utf-8")
        status, headers, _ = call(self.app, "GET", "/reasoning/")
        self.assertEqual((status, headers["Location"]), (302, "/reasoning/ar/"))

    def test_read_failure_is_a_plain_503_with_the_deterministic_path(self):
        status, _, body = call(self.app, "GET", "/reasoning/en/")
        page = body.decode()
        self.assertEqual(status, 503)
        self.assertIn('data-error="unavailable"', page)
        self.assertIn('href="/en/dashboard.html"', page)                    # the deterministic diagnostics path stays reachable
        for leak in ("DashboardUnavailable", "Traceback", "postgresql", "down"):
            self.assertNotIn(leak, page)
        status, _, body = call(self.app, "GET", "/api/reasoning/read/results")
        self.assertEqual((status, json.loads(body)), (503, {"error": "READ_FAILED", "message": None}))

    def test_invalid_paths_ids_and_methods(self):
        for path in ("/reasoning/en/results/rr1_XYZ", "/reasoning/en/results/" + "rr1_" + "a" * 33, "/reasoning/fr/",
                     "/reasoning/en/results/rr1_%3Cscript%3E", "/reasoning/en/results/../../etc/passwd", "/reasoning/en/results/rr1_" + "a" * 32 + "/raw"):
            status, _, body = call(self.app, "GET", path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"<script>alert", body)
        self.assertEqual(call(self.app, "GET", "/reasoning/en/results/rr1_" + "a" * 32 + "?version=abc")[0], 404)
        self.assertEqual(call(self.app, "GET", "/api/reasoning/read/results/rr1_bad")[0], 404)
        self.assertEqual(call(self.app, "GET", "/api/reasoning/read/results/rr1_" + "a" * 32 + "?version=0")[0], 400)
        self.assertEqual(call(self.app, "POST", "/reasoning/en/")[0], 405)
        self.assertEqual(call(self.app, "DELETE", "/api/reasoning/read/results")[0], 405)
        self.assertEqual(call(self.app, "POST", "/reasoning/assets/dashboard.js")[0], 405)

    def test_head_returns_no_body(self):
        status, headers, body = call(self.app, "HEAD", "/reasoning/assets/dashboard.css")
        self.assertEqual((status, body), (200, b""))
        self.assertGreater(int(headers["Content-Length"]), 0)


class RenderEscapingTests(unittest.TestCase):
    """Model text and management text never become markup, in either language (no database: view objects built directly)."""

    def test_card_page_escapes_every_model_field(self):
        from atlas_reasoning.dashboard import CardSummary, EvidenceTrace, History, ResultCard, WhatChanged
        from atlas_reasoning.dashboard import HumanContext as Context
        document = factory.result_dict()
        document["title"] = XSS
        document["reasoning_summary"] = XSS
        document["observation"]["statement"] = XSS
        document["limitations"] = [XSS]
        document["alternative_explanations"][0]["explanation"] = XSS
        document["questions_for_management"][0]["text"] = XSS
        summary = CardSummary(document["result_id"], document["case_id"], 1, "active", XSS, XSS, "moderate", "editor", XSS, "deadline",
                              "editor_pattern", XSS, {"result_id": 'rr1_"><script>', "case_id": "x"}, (EVIDENCE_CHANGED,))
        card = ResultCard(summary, document, 1, WhatChanged(1, "patched", None, 1, "patched", XSS, ("title",), {"changed_values": 2}), ())
        trace = EvidenceTrace(document["result_id"], 1, {"subject_type": "editor", "subject_id": XSS, "source_snapshot_id": XSS}, (), (), (XSS,))
        history = History(summary, (), (), ())
        for locale in ("en", "ar"):
            page = H.card_page(card, Context(False), trace, history, H.PageContext(locale, csrf_token="tok"))
            self.assertNotIn("<script>alert", page)
            self.assertNotIn("<img src=x", page)
            self.assertNotIn('"><script>', page)
            self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", page)
            self.assertEqual([s.get("src") for s in Attrs(page).scripts()], ["/reasoning/assets/dashboard.js"])   # the only script
            self.assertIn('data-state="human_context_unavailable"', page)
            self.assertIn("/reasoning/" + locale + "/results/", page)
            self.assertNotIn("#/editor/" + XSS, page)
            self.assertIn("#/editor/%3Cscript%3E", page)                     # subject IDs are percent-encoded in links

    def test_lifecycle_is_never_colour_only(self):
        for locale in ("en", "ar"):
            ctx = H.PageContext(locale)
            for status in LIFECYCLES:
                badge = H.lifecycle_badge(status, ctx, help_text=True)
                self.assertIn(f'data-lifecycle="{status}"', badge)
                self.assertIn(i18n.t(locale, f"lifecycle.{status}"), badge)       # a text label
                self.assertIn(i18n.t(locale, f"lifecycle.{status}.help"), badge)
                self.assertIn('aria-hidden="true"', badge)                       # the symbol is decorative
            self.assertIn("&lt;b&gt;", H.lifecycle_badge("<b>", ctx))


def pending_case(store: ReasoningStore) -> str:
    with store.transaction() as tx:
        return str(tx._one("SELECT case_id FROM reasoning_work_items WHERE requires_llm ORDER BY created_at LIMIT 1")["case_id"])


# --- with PostgreSQL ------------------------------------------------------------------------------------------------------------------


class _DashboardDB(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.honcho = FakeHoncho()
        self.sync = human_context.sync_service(self.store, self.honcho)
        self.notes = ManagerNotes(self.store, self.sync)
        self.questions = AtlasQuestions(self.store, self.sync)
        self.teach = TeachAtlas(self.store, self.sync)
        self.service = DashboardService(self.store, notes=self.notes, questions=self.questions, teachings=self.teach)
        self.settings = WebSettings(api_settings(), monday_item_url="https://waset.monday.com/boards/1/pulses/{item_id}")
        self.management = ManagementAPI(self.settings.api, notes=self.notes, questions=self.questions, teachings=self.teach)
        self.app = ReasoningWebApp(self.settings, self.service, self.management)
        self.policy = lifecycle.policy_from_env({})
        self.token = self.management.csrf_token(BOSS)

    def get(self, path: str, **kw: Any) -> str:
        status, _, body = call(self.app, "GET", path, **kw)
        self.assertEqual(status, 200, path)
        return body.decode()

    def api(self, path: str) -> Any:
        status, _, body = call(self.app, "GET", "/api/reasoning/read" + path)
        self.assertEqual(status, 200, path)
        return json.loads(body)

    def write(self, method: str, path: str, payload: dict[str, Any], *, token: str | None = None, origin: str | None = ORIGIN,
              content_type: str = "application/json", actor: str | None = BOSS) -> tuple[int, Any]:
        headers = {"Content-Type": content_type, "X-Atlas-CSRF": self.token if token is None else token}
        if origin is not None:
            headers["Origin"] = origin
        status, _, body = call(self.app, method, path, actor=actor, body=json.dumps(payload).encode(), headers=headers)
        return status, json.loads(body)

    def move(self, result: dict[str, Any], to: LifecycleStatus, reason: str) -> dict[str, Any]:
        with self.store.transaction() as tx:
            current = tx.get_result(result["result_id"])
            new, _ = lifecycle.apply(tx, current, to, reason, policy=self.policy, now=NOW)
        return new.to_dict()

    def seeded(self, editor: str = "editor-a", *, questions: list[dict[str, str]] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """A case with one result at version 1, lifecycle ``new`` (as the analyst creates it), with its creation transition."""
        case = editor_case(editor)
        run_id = seed_case(self.store, case)
        result = factory.result_dict(case)
        result.update(result_id=new_result_id(), lifecycle_status="new", title=f"{editor} deadline: {result['title']}")
        if questions is not None:
            result["questions_for_management"] = questions
        with self.store.transaction() as tx:
            created = ReasoningResult.from_dict(result)
            tx.create_result(created, run_id=run_id)
            lifecycle.record_creation(tx, created, policy=self.policy, run_id=run_id)
        result["_run_id"] = run_id
        return result, case


@requires_db
class CanonicalRenderingTests(_DashboardDB):
    def test_empty_state_keeps_the_deterministic_path(self):
        for locale in ("en", "ar"):
            page = self.get(f"/reasoning/{locale}/")
            self.assertIn('data-state="empty"', page)
            self.assertIn(f'href="/{locale}/dashboard.html"', page)
        self.assertEqual(self.api("/results"), {"current": [], "history": [], "memory_backlog": 0, "first_reasoning_failed": 0,
                                                "first_reasoning_pending": 0, "first_reasoning_failed_by_class": {"provider": 0, "validation": 0}})

    def test_only_current_versions_are_cards_with_their_canonical_fields(self):
        result, case = self.seeded()
        patched = patch_result(self.store, result, case, title="Patched title", confidence={"level": "weak", "rationale": "Smaller sample."})
        page = self.get("/reasoning/en/")
        [card] = [attrs for tag, attrs in Attrs(page).tags if tag == "article"]
        self.assertEqual((card["data-result-id"], card["data-version"], card["data-lifecycle"], card["data-confidence"]),
                         (result["result_id"], "2", "new", "weak"))
        self.assertIn("Patched title", page)
        self.assertNotIn(result["title"], page)                             # version 1's title is history, not the card
        stored = self.store.get_result(result["result_id"]).to_dict()
        api = self.api("/results")["current"][0]
        self.assertEqual((api["title"], api["version"], api["confidence"], api["lifecycle_status"]),
                         (stored["title"], stored["version"], stored["confidence"]["level"], stored["lifecycle_status"]))
        full = self.api(f"/results/{result['result_id']}")["card"]
        self.assertEqual(full["result"], stored)                             # the card is the canonical document, untouched
        self.assertEqual((full["what_changed"]["content_kind"], full["what_changed"]["changed_fields"]), ("patched", ["confidence", "title"]))
        self.assertEqual(patched["version"], 2)

    def test_card_renders_every_required_part(self):
        result, _ = self.seeded(questions=[question("Did Class B assignments change in September?")])
        self.questions.record_result_questions(result["result_id"])
        page = self.get(f"/reasoning/en/results/{result['result_id']}")
        parts = set(Attrs(page).values("data-part"))
        self.assertEqual(parts, {"summary", "what_changed", "observation", "supporting", "counter", "interpretation", "alternatives", "confidence",
                                 "limitations", "significance", "investigations", "version_questions"})
        for source in ("atlas_reasoning", "management_context", "deterministic_evidence"):
            self.assertIn(f'data-source-type="{source}"', page)
        for label in ("ATLAS REASONING", "MANAGEMENT CONTEXT", "DETERMINISTIC EVIDENCE"):
            self.assertIn(label, page)
        self.assertIn(f'id="result-{result["result_id"]}"', page)
        self.assertIn("Manager interpretation", page)
        self.assertIn("Did Class B assignments change in September?", page)
        self.assertIn(result["reasoning_summary"].replace("'", "&#x27;"), page)
        self.assertNotIn("chain_of_thought", page)

    def test_refused_candidates_never_appear_and_the_previous_card_stays(self):
        result, case = self.seeded()
        with self.store.transaction() as tx:
            run_id = result["_run_id"]
            item = tx.create_work_item(run_id=run_id, case_id=case["case_id"], kind=WorkKind.NEW_RESULT, gate_action=GateAction.NEW, result_id=None,
                                       base_result_version=None, fingerprint_before=None, fingerprint_after=case["evidence_fingerprint"], material_delta=None,
                                       case_document=case)
            tx.set_work_item_status(item, WorkStatus.FAILED, error="validation:HR_JUDGMENT")
            refused = {**result, "title": "REFUSED CANDIDATE TITLE", "reasoning_summary": "Refused summary."}
            refused.pop("_run_id")
            tx.record_failed_candidate(case_id=case["case_id"], request_id="req_" + "9" * 32, purpose="update", attempt=1, validator_version="v",
                                       error_codes=["HR_JUDGMENT"], violations=[{"code": "HR_JUDGMENT"}], candidate=refused, run_id=run_id,
                                       work_item_id=item, result_id=result["result_id"], base_version=1)
        pages = [self.get(f"/reasoning/{locale}/{suffix}") for locale in ("en", "ar")
                 for suffix in ("", f"results/{result['result_id']}", f"results/{result['result_id']}/evidence", f"results/{result['result_id']}/history")]
        payloads = [json.dumps(self.api(path)) for path in ("/results", f"/results/{result['result_id']}", f"/results/{result['result_id']}/evidence",
                                                            f"/results/{result['result_id']}/history")]
        for text in pages + payloads:
            self.assertNotIn("REFUSED CANDIDATE TITLE", text)
            self.assertNotIn("Refused summary.", text)
            self.assertNotIn("HR_JUDGMENT", text)                            # codes stay in the debugging tables
        self.assertIn(f'data-notice="{VALIDATION_REFUSED}"', pages[0])
        self.assertEqual(self.api("/results")["current"][0]["version"], 1)


@requires_db
class EvidenceTests(_DashboardDB):
    def test_every_cited_reference_resolves_through_case_findings_to_monday(self):
        result, case = self.seeded()
        trace = self.service.evidence(result["result_id"])
        self.assertTrue(trace.resolves)
        references = {ref["ref_id"]: ref for ref in case["current_evidence"]["references"]}
        cited = {ref for claim in trace.claims for ref in claim.evidence_refs}
        self.assertTrue(cited)
        with self.store.transaction() as tx:
            linked = {row["ref_id"] for row in tx.evidence_links(result["result_id"], 1)}
        self.assertEqual(cited, linked)
        items = {item.ref_id: (finding, item) for finding in trace.findings for item in finding.evidence}
        self.assertEqual(set(items), set(references))                       # every record of the case, cited or not, is shown
        for ref in cited:
            finding, item = items[ref]
            self.assertEqual((item.finding_id, item.monday_item_id, item.cycle_id, list(item.event_ids)),
                             (references[ref]["finding_id"], references[ref]["monday_item_id"], references[ref]["cycle_id"], references[ref]["event_ids"]))
            self.assertEqual(finding.finding["member_key"], references[ref]["member_key"])
            self.assertTrue(finding.statements)                             # the finding's deterministic metrics travel with it
        member_keys = {f["member_key"] for f in case["supporting_findings"] + case["contradicting_findings"]}
        self.assertEqual({finding.finding["member_key"] for finding in trace.findings}, member_keys)

    def test_every_evidence_link_on_the_pages_resolves(self):
        result, _ = self.seeded()
        rid = result["result_id"]
        for locale in ("en", "ar"):
            card = self.get(f"/reasoning/{locale}/results/{rid}")
            evidence = self.get(f"/reasoning/{locale}/results/{rid}/evidence")
            targets = Attrs(evidence).ids()
            hrefs = [href for href in Attrs(card).values("href") + Attrs(evidence).values("href") if "#ev-" in href]
            self.assertTrue(hrefs)
            for href in hrefs:
                path, anchor = href.split("#")
                self.assertIn(path, ("", f"/reasoning/{locale}/results/{rid}/evidence"))     # same-page anchors on the evidence page
                self.assertIn(anchor, targets)
            self.assertIn('data-state="resolves"', evidence)
            self.assertIn("https://waset.monday.com/boards/1/pulses/1101", evidence)
            self.assertIn('href="/' + locale + '/dashboard.html#/editor/editor-a"', evidence)     # technical V2 output under diagnostics
            for link in Attrs(card).values("href"):
                if link.startswith("/reasoning/"):
                    self.assertEqual(call(self.app, "GET", link.split("#")[0])[0], 200, link)

    def test_a_historical_card_audits_its_own_version_evidence(self):
        result, case = self.seeded()
        patch_result(self.store, result, case, title="Second version")
        rid = result["result_id"]
        old = self.get(f"/reasoning/en/results/{rid}?version=1")
        hrefs = [href for href in Attrs(old).values("href") if "/evidence" in href]
        self.assertTrue(hrefs)
        self.assertTrue(all(href.startswith(f"/reasoning/en/results/{rid}/evidence?version=1") for href in hrefs), hrefs)
        page = self.get(f"/reasoning/en/results/{rid}/evidence?version=1")
        self.assertIn('data-version="1"', page)
        for href in Attrs(old).values("href"):
            if "#ev-" in href:
                self.assertIn(href.split("#")[1], Attrs(page).ids())

    def test_a_cited_reference_outside_every_finding_is_unresolved(self):
        document = factory.result_dict()
        case = factory.case_dict()
        links = {ref["ref_id"]: {} for ref in case["current_evidence"]["references"]}
        case["supporting_findings"] = case["supporting_findings"][:1]
        case["contradicting_findings"] = []
        trace = DashboardService._trace(document["result_id"], 1, document, case, links, {"last_evidence_fingerprint": None, "current_version": 1})
        self.assertFalse(trace.resolves)

    def test_management_context_is_never_shown_as_evidence(self):
        result, _ = self.seeded()
        self.notes.create(result["result_id"], "Class B work was reassigned (management view).", author=BOSS)
        evidence = self.get(f"/reasoning/en/results/{result['result_id']}/evidence")
        self.assertNotIn("Class B work was reassigned", evidence)
        self.assertNotIn("Class B work was reassigned", json.dumps(self.api(f"/results/{result['result_id']}/evidence")))
        card = self.get(f"/reasoning/en/results/{result['result_id']}")
        management = card.split('data-source-type="management_context"', 1)[1].split('data-source-type="deterministic_evidence"', 1)[0]
        self.assertIn("Class B work was reassigned", management)
        self.assertNotIn("Class B work was reassigned", card.split('data-source-type="deterministic_evidence"', 1)[1])


@requires_db
class LifecycleTests(_DashboardDB):
    def test_every_lifecycle_is_shown_with_history_and_supersession(self):
        new, _ = self.seeded("editor-new")
        active, _ = self.seeded("editor-active")
        self.move(active, LifecycleStatus.ACTIVE, lifecycle.OBSERVED_AGAIN)
        updated, _ = self.seeded("editor-updated")
        self.move(updated, LifecycleStatus.ACTIVE, lifecycle.OBSERVED_AGAIN)
        with self.store.transaction() as tx:
            current = tx.get_result(updated["result_id"])
            doc = current.to_dict()
            doc.update(version=current.version + 1, lifecycle_status="updated", title="Updated title", updated_at="2026-09-30T01:00:00Z")
        patch_result_doc = ReasoningResult.from_dict(doc)
        from atlas_reasoning.contracts import PATCHABLE_FIELDS, ReasoningUpdate
        from atlas_reasoning.enums import ResultChangeKind
        update = {"contract_version": "reasoning-v1", "case_id": doc["case_id"], "result_id": doc["result_id"], "base_version": current.version,
                  "action": "patch", "changed_fields": [{"field": "title", "value": "Updated title"}],
                  "preserved_fields": [n for n in PATCHABLE_FIELDS if n != "title"], "change_rationale": "Evidence moved.",
                  "evidence_fingerprint_before": doc["evidence_fingerprint"], "evidence_fingerprint_after": doc["evidence_fingerprint"]}
        with self.store.transaction() as tx:
            tx.append_version_with_diff(patch_result_doc, previous=current, change_kind=ResultChangeKind.PATCHED, update=ReasoningUpdate.from_dict(update))
            lifecycle.record_patch(tx, current, patch_result_doc, policy=self.policy)
        cooling, _ = self.seeded("editor-cooling")
        self.move(cooling, LifecycleStatus.COOLING, lifecycle.NOT_IN_SNAPSHOT)
        resolved, _ = self.seeded("editor-resolved")
        self.move(resolved, LifecycleStatus.COOLING, lifecycle.NOT_IN_SNAPSHOT)
        self.move(resolved, LifecycleStatus.RESOLVED, lifecycle.ABSENT_FOR_CONFIGURED_RUNS)
        old, _ = self.seeded("editor-old")
        replacement, _ = self.seeded("editor-replacement")
        lifecycle.supersede(self.store, old["result_id"], by_result_id=replacement["result_id"], policy=self.policy, clock=lambda: NOW)

        home = self.api("/results")
        current = {card["result_id"]: card["lifecycle_status"] for card in home["current"]}
        history = {card["result_id"]: card["lifecycle_status"] for card in home["history"]}
        self.assertEqual(current, {new["result_id"]: "new", active["result_id"]: "active", updated["result_id"]: "updated",
                                   cooling["result_id"]: "cooling", replacement["result_id"]: "new"})
        self.assertEqual(history, {resolved["result_id"]: "resolved", old["result_id"]: "superseded"})
        for locale in ("en", "ar"):
            page = self.get(f"/reasoning/{locale}/")
            current_html, history_html = page.split('id="reasoning-history"', 1)
            for rid, status in current.items():
                self.assertIn(f'id="result-{rid}"', current_html)
            for rid, status in history.items():
                self.assertIn(f'id="result-{rid}"', history_html)
            for status in LIFECYCLES:
                self.assertIn(i18n.t(locale, f"lifecycle.{status}"), page)
        # Superseded links to its replacement; the replacement links back; resolved stays inspectable.
        old_page = self.get(f"/reasoning/en/results/{old['result_id']}")
        self.assertIn(f'href="/reasoning/en/results/{replacement["result_id"]}#result-{replacement["result_id"]}"', old_page)
        self.assertIn('data-state="superseded"', old_page)
        self.assertIn(f'href="/reasoning/en/results/{old["result_id"]}#result-{old["result_id"]}"', self.get(f"/reasoning/en/results/{replacement['result_id']}"))
        resolved_page = self.get(f"/reasoning/en/results/{resolved['result_id']}")
        self.assertIn('data-state="resolved"', resolved_page)
        self.assertIn("data-state=\"resolves\"", self.get(f"/reasoning/en/results/{resolved['result_id']}/evidence"))
        # History: every version, lifecycle transitions with reasons, and every old version viewable.
        hist = self.api(f"/results/{resolved['result_id']}/history")["history"]
        self.assertEqual([(v["version"], v["lifecycle_status"]) for v in hist["versions"]], [(1, "new"), (2, "cooling"), (3, "resolved")])
        self.assertEqual([t["reason_code"] for t in hist["transitions"]], ["created", "not_in_snapshot", "absent_for_configured_runs"])
        old_version = self.get(f"/reasoning/en/results/{resolved['result_id']}?version=1")
        self.assertIn('data-state="historical_version"', old_version)
        self.assertIn('data-version="1" data-current-version="3" data-lifecycle="new"', old_version)
        self.assertEqual(call(self.app, "GET", f"/reasoning/en/results/{resolved['result_id']}?version=9")[0], 404)
        updated_card = self.api(f"/results/{updated['result_id']}")["card"]
        self.assertEqual((updated_card["lifecycle_status"], updated_card["what_changed"]["changed_fields"], updated_card["what_changed"]["change_rationale"]),
                         ("updated", ["title"], "Evidence moved."))
        lifecycle_card = self.api(f"/results/{cooling['result_id']}")["card"]["what_changed"]
        self.assertEqual((lifecycle_card["change_kind"], lifecycle_card["lifecycle_reason"], lifecycle_card["content_version"]),
                         ("lifecycle", "not_in_snapshot", 1))


@requires_db
class HumanContextTests(_DashboardDB):
    def test_notes_through_the_mounted_api_with_history_and_labels(self):
        result, _ = self.seeded()
        rid = result["result_id"]
        page = self.get(f"/reasoning/en/results/{rid}")
        self.assertIn(f'data-csrf="{self.token}"', page)
        status, body = self.write("POST", f"/api/reasoning/results/{rid}/notes", {"body": "First reading " + XSS})
        self.assertEqual(status, 200)
        note_id = body["note"]["note_id"]
        self.assertEqual(body["note"]["author"], BOSS)
        status, body = self.write("PUT", f"/api/reasoning/notes/{note_id}", {"body": "Second reading.", "expected_revision": 1})
        self.assertEqual((status, body["note"]["revision"]), (200, 2))
        self.assertEqual(self.write("PUT", f"/api/reasoning/notes/{note_id}", {"body": "Stale.", "expected_revision": 1})[0], 409)
        for locale in ("en", "ar"):
            card = self.get(f"/reasoning/{locale}/results/{rid}")
            self.assertIn(f'data-note-id="{note_id}" data-revision="2" data-source-type="manager_interpretation"', card)
            self.assertIn("Second reading.", card)
            self.assertIn("First reading &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", card)     # the earlier revision, escaped
            self.assertNotIn("<script>alert", card)
            self.assertNotIn("<img src=x", card)
        self.assertIn("MANAGEMENT CONTEXT", self.get(f"/reasoning/en/results/{rid}"))
        self.assertIn("سياق إداري", self.get(f"/reasoning/ar/results/{rid}"))

    def test_questions_answers_conflicts_and_dismissal(self):
        result, _ = self.seeded(questions=[question("Did Class B assignments change in September?"),
                                           question("Was a holiday scheduled for the team?", kind="temporary_situation")])
        rid = result["result_id"]
        self.questions.record_result_questions(rid)
        first, second = self.questions.for_result(rid)
        self.assertEqual(self.write("POST", f"/api/reasoning/questions/{first.question_id}/answers", {"body": "Yes, from week 2."})[0], 200)
        status, body = self.write("POST", f"/api/reasoning/questions/{first.question_id}/answers", {"body": "No, it changed in October."})
        self.assertEqual((status, body["answer"]["conflict"]), (200, True))
        self.assertEqual(self.write("POST", f"/api/reasoning/questions/{second.question_id}/dismiss", {})[0], 200)
        card = self.get(f"/reasoning/en/results/{rid}")
        self.assertIn(f'data-question-id="{first.question_id}" data-state="answered"', card)
        self.assertIn(f'data-question-id="{second.question_id}" data-state="dismissed"', card)
        self.assertIn("Differs from an earlier answer", card)
        self.assertEqual(card.count('data-source-type="manager_answer"'), 2)
        self.assertIn("يختلف عن إجابة سابقة", self.get(f"/reasoning/ar/results/{rid}"))
        api = self.api(f"/results/{rid}")["human_context"]
        self.assertTrue(api["questions"][0]["has_conflicting_answers"])

    def test_teach_atlas_through_the_mounted_api(self):
        status, body = self.write("POST", "/api/reasoning/teachings", {"body": "Class B work is " + XSS, "scope_type": "company", "teaching_type": "context",
                                                                         "validity_mode": "until_changed", "affects_source_data": False})
        self.assertEqual(status, 200, body)
        teaching_id = body["teaching"]["teaching_id"]
        for locale in ("en", "ar"):
            page = self.get(f"/reasoning/{locale}/teach")
            self.assertIn(f'data-teaching-id="{teaching_id}"', page)
            self.assertNotIn("<script>alert", page)
        self.assertIn("Management teaching", self.get("/reasoning/en/teach"))
        self.assertEqual(self.write("POST", f"/api/reasoning/teachings/{teaching_id}/disable", {})[0], 200)
        self.assertIn('data-status="disabled"', self.get("/reasoning/en/teach"))

    def test_writes_keep_csrf_origin_json_and_auth_rules(self):
        result, _ = self.seeded()
        path = f"/api/reasoning/results/{result['result_id']}/notes"
        payload = {"body": "x"}
        self.assertEqual(self.write("POST", path, payload, token="wrong")[1]["error"], "CSRF_TOKEN_INVALID")
        self.assertEqual(self.write("POST", path, payload, token="")[0], 403)
        self.assertEqual(self.write("POST", path, payload, origin="https://evil.example")[1]["error"], "ORIGIN_NOT_ALLOWED")
        self.assertEqual(self.write("POST", path, payload, content_type="application/x-www-form-urlencoded")[0], 415)
        self.assertEqual(self.write("POST", path, payload, actor=None)[0], 401)
        self.assertEqual(self.write("POST", path, payload, actor="intruder@example.com")[0], 403)
        other_token = self.management.csrf_token("other@example.com")
        self.assertEqual(self.write("POST", path, payload, token=other_token)[0], 403)        # a token is bound to its actor
        self.assertEqual(self.write("POST", path, {"body": "x", "author": "someone-else"})[1]["error"], "UNKNOWN_FIELD")
        big = b'{"body": "' + b"a" * 40000 + b'"}'
        status, _, body = call(self.app, "POST", path, body=big, headers={"Content-Type": "application/json", "X-Atlas-CSRF": self.token, "Origin": ORIGIN})
        self.assertEqual((status, json.loads(body)["error"]), (413, "BODY_TOO_LARGE"))
        self.assertEqual(self.notes.for_result(result["result_id"]), [])

    def test_heading_outline_and_noscript_notice(self):
        result, _ = self.seeded(questions=[question("Did Class B assignments change in September?")])
        self.questions.record_result_questions(result["result_id"])
        card = self.get(f"/reasoning/en/results/{result['result_id']}")
        self.assertIn('<h3 class="mi-title">', card)
        self.assertIn('<h3 class="qa-title">', card)
        self.assertNotIn("<h4", card.split('data-source-type="management_context"', 1)[1].split('data-source-type="deterministic_evidence"', 1)[0])
        self.assertIn('data-state="no_script"', card)

    def test_ambiguous_actor_values_are_never_an_identity(self):
        for actor in (f"{BOSS},other@example.com", f"{BOSS}\x00", "   "):
            self.assertEqual(call(self.app, "GET", "/reasoning/en/", actor=actor)[0], 401, actor)

    def test_actor_header_mode_ignores_remote_user_and_strips_the_header(self):
        settings = WebSettings(api_settings(), actor_header="X-Forwarded-User")
        app = ReasoningWebApp(settings, self.service, self.management)
        self.assertEqual(call(app, "GET", "/reasoning/en/", actor=BOSS)[0], 401)          # REMOTE_USER is not trusted in header mode
        self.assertEqual(call(app, "GET", "/reasoning/en/", actor=None, headers={"X-Forwarded-User": BOSS})[0], 200)

    def test_human_context_unavailable_keeps_the_reasoning(self):
        result, _ = self.seeded()

        class Broken:
            def for_result(self, result_id):
                raise Database("postgresql://nobody@127.0.0.1:1/x_test").connect()

        service = DashboardService(self.store, notes=Broken(), questions=self.questions, teachings=None)  # type: ignore[arg-type]
        app = ReasoningWebApp(self.settings, service, self.management)
        status, _, body = call(app, "GET", f"/reasoning/en/results/{result['result_id']}")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertIn('data-state="human_context_unavailable"', page)
        self.assertIn(result["reasoning_summary"].replace("'", "&#x27;"), page)
        self.assertIn('data-state="teach_unavailable"', call(app, "GET", "/reasoning/en/teach")[2].decode())
        self.assertNotIn("nobody", page)


@requires_db
class DegradedStateTests(_DashboardDB):
    def test_memory_degraded_and_backlog(self):
        result, case = self.seeded()
        with self.store.transaction() as tx:
            hc_sql.insert_injection(tx, case_id=case["case_id"], result_id=result["result_id"], run_id=None, work_item_id=None, request_id="req_" + "7" * 32,
                                    purpose="update", assembler_version="v", memory_status="degraded", degraded_reason="memory_unavailable",
                                    sessions=[], budget={}, selected=[], dropped={}, context_sha256="0" * 64)
        self.honcho.outage()
        self.notes.create(result["result_id"], "Written while Honcho is down.", author=BOSS)
        page = self.get("/reasoning/en/")
        self.assertIn(f'data-notice="{MEMORY_DEGRADED}"', page)
        self.assertIn('data-state="memory_backlog"', page)
        self.assertIn("Written while Honcho is down.", self.get(f"/reasoning/en/results/{result['result_id']}"))   # canonical note still shown

    def test_memory_notice_never_marks_a_resolved_card(self):
        result, case = self.seeded()
        self.move(result, LifecycleStatus.COOLING, lifecycle.NOT_IN_SNAPSHOT)
        self.move(result, LifecycleStatus.RESOLVED, lifecycle.ABSENT_FOR_CONFIGURED_RUNS)
        with self.store.transaction() as tx:
            hc_sql.insert_injection(tx, case_id=case["case_id"], result_id=result["result_id"], run_id=None, work_item_id=None, request_id="req_" + "6" * 32,
                                    purpose="update", assembler_version="v", memory_status="degraded", degraded_reason="memory_unavailable",
                                    sessions=[], budget={}, selected=[], dropped={}, context_sha256="0" * 64)
        self.assertEqual(self.api("/results")["history"][0]["notices"], [])

    def test_result_states_name_lifecycle_version_and_replacement(self):
        old, _ = self.seeded("editor-old")
        replacement, _ = self.seeded("editor-new")
        resolved, _ = self.seeded("editor-gone")
        self.move(resolved, LifecycleStatus.COOLING, lifecycle.NOT_IN_SNAPSHOT)
        self.move(resolved, LifecycleStatus.RESOLVED, lifecycle.ABSENT_FOR_CONFIGURED_RUNS)
        lifecycle.supersede(self.store, old["result_id"], by_result_id=replacement["result_id"], policy=self.policy, clock=lambda: NOW)
        unknown = "rr1_" + "e" * 32
        states = self.service.result_states([old["result_id"], resolved["result_id"], replacement["result_id"], unknown])
        self.assertEqual(states[old["result_id"]], {"result_id": old["result_id"], "exists": True, "lifecycle_status": "superseded", "current_version": 2,
                                                   "superseded_by": replacement["result_id"]})
        self.assertEqual((states[resolved["result_id"]]["lifecycle_status"], states[resolved["result_id"]]["current_version"]), ("resolved", 3))
        self.assertEqual((states[replacement["result_id"]]["lifecycle_status"], states[unknown]["exists"]), ("new", False))
        self.assertEqual(self.service.existing([old["result_id"], unknown]), {old["result_id"]})
        status, _, body = call(self.app, "GET", f"/api/reasoning/read/links?result_id={old['result_id']}&result_id={unknown}")
        links = json.loads(body)["links"]
        self.assertEqual((status, links[0]["superseded_by"], links[0]["card"].split("#")[0], links[1]["exists"], "card" in links[1]),
                         (200, replacement["result_id"], f"/reasoning/en/results/{old['result_id']}", False, False))

    def test_provider_failure_and_pending_update_keep_the_previous_card(self):
        result, case = self.seeded()
        with self.store.transaction() as tx:
            item = tx.create_work_item(run_id=result["_run_id"], case_id=case["case_id"], kind=WorkKind.NEW_RESULT, gate_action=GateAction.NEW,
                                       result_id=None, base_result_version=None, fingerprint_before=None, fingerprint_after=case["evidence_fingerprint"],
                                       material_delta=None, case_document=case)
        self.assertIn(f'data-notice="{UPDATE_PENDING}"', self.get("/reasoning/en/"))
        with self.store.transaction() as tx:
            tx.set_work_item_status(item, WorkStatus.FAILED, error="provider:timeout")
        self.assertIn(PROVIDER_FAILED, self.api(f"/results/{result['result_id']}/history")["history"]["notices"])
        for locale in ("en", "ar"):
            for suffix in ("", "/evidence", "/history"):
                self.assertIn(f'data-notice="{PROVIDER_FAILED}"', self.get(f"/reasoning/{locale}/results/{result['result_id']}{suffix}"))
            page = self.get(f"/reasoning/{locale}/results/{result['result_id']}")
            self.assertIn(f'data-notice="{PROVIDER_FAILED}"', page)
            self.assertIn('data-version="1"', page)
            self.assertNotIn("provider:timeout", page)


@requires_db
class PipelineTests(unittest.TestCase):
    """The real connected pipeline (gate → engine → guardrails → commit) rendered by the dashboard."""

    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.honcho = FakeHoncho()
        self.context = HumanContext(self.store, self.honcho, env={})
        self.transport = ScriptedAnalyst()
        self.engine = ReasoningEngine(self.store, gateway(self.transport, recorder=StoreCallRecorder(self.store)), context=self.context)
        self.notes = ManagerNotes(self.store, self.context.sync)
        self.questions = AtlasQuestions(self.store, self.context.sync)
        self.service = DashboardService(self.store, notes=self.notes, questions=self.questions, teachings=TeachAtlas(self.store, self.context.sync))
        settings = WebSettings(api_settings())
        self.app = ReasoningWebApp(settings, self.service, ManagementAPI(settings.api, notes=self.notes, questions=self.questions))
        self.t = times(6)

    def run_snapshot(self, index, payload=None):
        report = run_gate(payload or snapshots.reasoning_input(), self.store, now=self.t[index])
        return report, self.engine.process_run(report.run_id)

    def test_every_card_traces_to_published_intelligence_v2_and_monday(self):
        _, engine_report = self.run_snapshot(0)
        published = {f["finding_id"]: f for f in snapshots.intelligence_copy()["findings"]}

        def monday_records(finding):
            return {(r["monday_item_id"], r.get("cycle_id"), tuple(r.get("event_ids") or ())) for key in ("supporting_evidence", "contradicting_evidence",
                    "context_evidence") for block in finding.get(key) or [] for r in block.get("records") or []}

        home = self.service.home()
        self.assertEqual(len(home.current), len([o for o in engine_report.outcomes if o.status == "done"]))
        self.assertGreater(len(home.current), 3)
        for card in home.current:
            trace = self.service.evidence(card.result_id)
            self.assertTrue(trace.resolves, card.result_id)
            cited = {ref for claim in trace.claims for ref in claim.evidence_refs}
            self.assertTrue(cited)
            traced = set()
            for finding in trace.findings:
                upstream = published[finding.finding["finding_id"]]                     # a finding of the published V2 document
                self.assertEqual(upstream["finding_type"], finding.finding["finding_type"])
                records = monday_records(upstream)
                for item in finding.evidence:
                    # Every Monday record shown is one the V2 finding itself published (item, cycle and event IDs).
                    self.assertIn((item.monday_item_id, item.cycle_id, item.event_ids), records)
                    traced.add(item.ref_id)
            self.assertLessEqual(cited, traced)

    def test_refused_update_and_provider_failure_keep_the_last_valid_card(self):
        first, _ = self.run_snapshot(0)
        case_id = next(d.case_id for d in first.decisions if d.identity_key == DEADLINE_12)
        result_id = self.service.home().current[0].result_id
        result_id = next(c.result_id for c in self.service.home().current if c.case_id == case_id)
        before = self.service.card(result_id).document

        def bad(payload):
            fresh = analyst_answer(payload)
            fresh["interpretation"]["statement"] = "The Editor is lazy and should be fired."
            return update_answer(payload, change={"interpretation": fresh["interpretation"]})

        self.transport.script(case_id, bad, bad)                                    # the attempt and its one corrective retry
        self.run_snapshot(1, payload_with(changed_rows()))
        self.assertTrue(self.store.failed_candidates(case_id=case_id))
        content = ("title", "reasoning_summary", "observation", "interpretation", "supporting_evidence", "confidence")
        card = self.service.card(result_id)
        self.assertEqual({k: card.document[k] for k in content}, {k: before[k] for k in content})   # last valid content still shown
        self.assertNotEqual(card.document["interpretation"]["statement"], "The Editor is lazy and should be fired.")
        self.assertIn(VALIDATION_REFUSED, card.summary.notices)
        self.assertIn(EVIDENCE_CHANGED, card.summary.notices)
        status, _, body = call(self.app, "GET", f"/reasoning/en/results/{result_id}")
        self.assertEqual(status, 200)
        self.assertNotIn("lazy", body.decode())
        self.transport.script(case_id, ProviderAuthError("simulated"))
        self.run_snapshot(2, payload_with(changed_rows(0.875)))
        self.assertIn(PROVIDER_FAILED, self.service.card(result_id).summary.notices)
        self.assertEqual({k: self.service.card(result_id).document[k] for k in content}, {k: before[k] for k in content})

    def test_english_and_arabic_show_the_same_canonical_records(self):
        self.run_snapshot(0)
        rid = self.service.home().current[0].result_id
        self.notes.create(rid, "Management view.", author=BOSS)
        self.questions.record_result_questions(rid)
        for suffix in ("", f"results/{rid}", f"results/{rid}/evidence", f"results/{rid}/history"):
            en = call(self.app, "GET", f"/reasoning/en/{suffix}")[2].decode()
            ar = call(self.app, "GET", f"/reasoning/ar/{suffix}")[2].decode()
            self.assertEqual(canonical_ids(en), canonical_ids(ar), suffix)
            self.assertTrue(canonical_ids(en)["data-result-id"], suffix)
            self.assertTrue(en.startswith('<!doctype html><html lang="en" dir="ltr">'))
            self.assertTrue(ar.startswith('<!doctype html><html lang="ar" dir="rtl">'))
            document = self.service.card(rid).document
            for page in (en, ar):
                if suffix in ("", f"results/{rid}"):
                    self.assertIn(H.esc(document["reasoning_summary"]), page)       # reasoning text identical, never regenerated per language
        home = json.loads(call(self.app, "GET", "/api/reasoning/read/results")[2])
        en_ids = canonical_ids(call(self.app, "GET", "/reasoning/en/")[2].decode())["data-result-id"]
        self.assertEqual(sorted(en_ids), sorted(card["result_id"] for card in home["current"] + home["history"]))

    def test_links_route_for_later_executive_statements(self):
        self.run_snapshot(0)
        rids = [card.result_id for card in self.service.home().current[:2]]
        query = "&".join(f"result_id={rid}" for rid in rids)
        status, _, body = call(self.app, "GET", f"/api/reasoning/read/links?locale=ar&{query}")
        links = json.loads(body)["links"]
        self.assertEqual((status, [link["result_id"] for link in links]), (200, rids))
        for link in links:
            self.assertEqual(call(self.app, "GET", link["card"].split("#")[0])[0], 200)
            self.assertEqual(call(self.app, "GET", link["evidence"])[0], 200)
            self.assertEqual(call(self.app, "GET", link["history"])[0], 200)
        for link in links:
            self.assertEqual((link["exists"], link["lifecycle_status"], link["superseded_by"]), (True, "new", None))
            self.assertEqual(link["current_version"], self.service.card(link["result_id"]).summary.version)
        # One unknown ID never hides the others (cross-review M2 / L3).
        unknown = "rr1_" + "f" * 32
        status, _, body = call(self.app, "GET", f"/api/reasoning/read/links?locale=en&{query}&result_id={unknown}")
        mixed = json.loads(body)["links"]
        self.assertEqual((status, [link["exists"] for link in mixed]), (200, [True, True, False]))
        self.assertEqual(set(mixed[-1]), {"result_id", "exists", "lifecycle_status", "current_version", "superseded_by"})
        self.assertEqual(call(self.app, "GET", "/api/reasoning/read/links?result_id=bad")[0], 400)
        self.assertEqual(call(self.app, "GET", f"/api/reasoning/read/links?result_id={rids[0]}%0A")[0], 400)
        self.assertEqual(json.loads(call(self.app, "GET", f"/api/reasoning/read/links?locale=fr&{query}")[2]), {"error": "INVALID_LOCALE", "message": None})
        self.assertEqual(call(self.app, "GET", "/api/reasoning/read/links")[0], 400)

    def test_a_refused_first_reasoning_is_counted_and_never_shown(self):
        """Cross-review M1 (validation variant): a first analyst answer refused by the Phase 15 guardrails is a failed first reasoning;
        the refused candidate's text appears nowhere."""
        report = run_gate(snapshots.reasoning_input(), self.store, now=self.t[0])
        case_id = next(d.case_id for d in report.decisions if d.identity_key == DEADLINE_12)

        def refused(payload):
            answer = analyst_answer(payload)
            answer["title"] = "REFUSED FIRST CANDIDATE"
            answer["interpretation"]["statement"] = "The Editor is lazy and should be fired."
            return answer

        self.transport.script(case_id, refused, refused)
        self.engine.process_run(report.run_id)
        self.assertTrue(self.store.failed_candidates(case_id=case_id))
        home = self.service.home()
        self.assertEqual(home.to_dict()["first_reasoning_failed_by_class"]["validation"], 1)
        self.assertNotIn(case_id, {card.case_id for card in home.current})
        for locale in ("en", "ar"):
            page = call(self.app, "GET", f"/reasoning/{locale}/")[2].decode()
            self.assertIn('data-state="first_reasoning_failed"', page)
            self.assertNotIn("REFUSED FIRST CANDIDATE", page)
            self.assertNotIn("lazy", page)
        self.assertNotIn("REFUSED FIRST CANDIDATE", call(self.app, "GET", "/api/reasoning/read/results")[2].decode())

    def test_first_reasoning_failures_are_never_shown_as_nothing(self):
        """Cross-review M1: a first run whose reasoning all fails (provider down) is a degraded state, not an empty one."""
        for case_id in [d.case_id for d in run_gate(snapshots.reasoning_input(), self.store, now=self.t[0]).decisions]:
            self.transport.script(case_id, ProviderAuthError("simulated"))
        report = run_gate(snapshots.reasoning_input(), self.store, now=self.t[1])      # same evidence: no new work
        self.assertFalse(self.service.home().current)
        pending = self.service.home()
        self.assertGreater(pending.first_reasoning_pending, 0)                         # gated, not reasoned yet
        for locale in ("en", "ar"):
            page = call(self.app, "GET", f"/reasoning/{locale}/")[2].decode()
            self.assertIn('data-state="first_reasoning_pending"', page)
            self.assertIn('data-state="empty_unreasoned"', page)
            self.assertNotIn('data-state="empty"', page)
        first_run = self.store.observations(case_id=pending_case(self.store))[0]["run_id"]
        self.engine.process_run(first_run)
        self.engine.process_run(report.run_id)
        home = self.service.home()
        self.assertFalse(home.current)
        self.assertEqual((home.first_reasoning_pending, home.first_reasoning_failed > 0), (0, True))
        self.assertEqual(home.to_dict()["first_reasoning_failed_by_class"]["provider"], home.first_reasoning_failed)
        for locale in ("en", "ar"):
            page = call(self.app, "GET", f"/reasoning/{locale}/")[2].decode()
            self.assertIn('data-state="first_reasoning_failed"', page)
            self.assertNotIn('data-state="empty"', page)
            self.assertNotIn("simulated", page)
        self.assertEqual(json.loads(call(self.app, "GET", "/api/reasoning/read/results")[2])["first_reasoning_failed"], home.first_reasoning_failed)


if __name__ == "__main__":
    unittest.main()
