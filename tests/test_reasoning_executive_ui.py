"""Phase 17 UI (``REV/17`` #10): the persisted canonical ExecutiveBrief as the lead of the reasoning-first home, every statement linked to
the Phase 16 card and evidence of the result version it was synthesized from.

Includes the card-linking test deferred by the Phase 17 core (``DEFERRED_TO_PHASE17_UI_AFTER_PHASE16``), now real: ExecutiveBrief →
ReasoningResult card (pinned version) → evidence page, through Phase 16's public routes. Page GETs are proven read-only: no provider
call, no Honcho call, no database write.
"""

from __future__ import annotations

import json
import re
import unittest
from typing import Any
from unittest import mock

import reasoning_snapshots as snapshots
from reasoning_db import fresh_database, requires_db
from reasoning_engine_support import DEADLINE_12, changed_rows, payload_with, times
from reasoning_executive_support import ScriptedExecutive, generic_answer
from reasoning_fakes import ScriptedAnalyst, gateway
from test_reasoning_dashboard import Attrs, api_settings, call

from atlas_reasoning import dashboard_routes as routes
from atlas_reasoning import executive_html, human_context, lifecycle
from atlas_reasoning.atlas_questions import AtlasQuestions
from atlas_reasoning.change_gate import run_gate
from atlas_reasoning.dashboard import DashboardService
from atlas_reasoning.dashboard_html import PageContext
from atlas_reasoning.engine import ReasoningEngine
from atlas_reasoning.enums import LifecycleStatus
from atlas_reasoning.executive import BriefProvenance, Decision, ExecutiveSynthesizer, assemble_brief, executive_input
from atlas_reasoning.executive_contracts import SECTIONS, ExecutiveBrief
from atlas_reasoning.executive_overview import CitedResult, ExecutiveOverviewService, Overview, StatementView
from atlas_reasoning.management_api import ManagementAPI
from atlas_reasoning.manager_notes import ManagerNotes
from atlas_reasoning.provider import ProviderAuthError
from atlas_reasoning.settings import PINNED_MODEL
from atlas_reasoning.store.calls import StoreCallRecorder
from atlas_reasoning.store.db import Database
from atlas_reasoning.store.executive import ExecutiveStore
from atlas_reasoning.store.repository import ReasoningStore
from atlas_reasoning.teach_atlas import TeachAtlas
from atlas_reasoning.web_app import CSP, ReasoningWebApp, WebSettings

XSS = '<script>alert("x")</script>"><img src=x onerror=alert(1)>'
NOW = "2026-09-30T00:00:00.000000Z"
_V2_FINDING = re.compile(r"[a-z_.]+:[0-9a-f]{16}")


def executive_section(page: str) -> str:
    """The executive lead: from its ``<section id="executive-brief"`` tag up to the Phase 16 results section."""
    start = page.rindex("<section", 0, page.index('id="executive-brief"'))
    return page[start: page.rindex("<section", 0, page.index('id="reasoning-results"'))]


def executive_ids(page: str) -> dict[str, list[str]]:
    parsed = Attrs(executive_section(page) if 'id="executive-brief"' in page else "")
    hrefs = [re.sub(r"^/reasoning/(en|ar)/", "/reasoning/<l>/", href) for href in parsed.values("href")]
    return {**{name: parsed.values(name) for name in ("data-brief-id", "data-brief-version", "data-run-id", "data-statement-id", "data-section",
                                                     "data-result-id", "data-pinned-version", "data-current-version", "data-lifecycle", "data-state")},
            "href": hrefs}


@requires_db
class ExecutiveUITests(unittest.TestCase):
    def setUp(self):
        self.store = ReasoningStore(fresh_database())
        self.executive_store = ExecutiveStore(self.store)
        self.analyst = ScriptedAnalyst()
        self.engine = ReasoningEngine(self.store, gateway(self.analyst, recorder=StoreCallRecorder(self.store)), retries=1)
        self.model = ScriptedExecutive()
        self.synthesizer = ExecutiveSynthesizer(self.executive_store, gateway(self.model, recorder=StoreCallRecorder(self.store)), retries=1)
        sync = human_context.sync_service(self.store, None)
        self.notes, self.questions, self.teach = ManagerNotes(self.store, sync), AtlasQuestions(self.store, sync), TeachAtlas(self.store, sync)
        self.dashboard = DashboardService(self.store, notes=self.notes, questions=self.questions, teachings=self.teach)
        self.overview = ExecutiveOverviewService(self.store, self.dashboard)
        settings = WebSettings(api_settings())
        self.management = ManagementAPI(settings.api, notes=self.notes, questions=self.questions, teachings=self.teach)
        self.app = ReasoningWebApp(settings, self.dashboard, self.management, executive=self.overview)
        self.phase16_app = ReasoningWebApp(settings, self.dashboard, self.management)
        self.t = times(12)
        self.runs = 0

    # --- helpers ------------------------------------------------------------------------------------------------------------------

    def run_snapshot(self, payload: Any = None) -> Any:
        report = run_gate(payload or snapshots.reasoning_input(), self.store, now=self.t[self.runs])
        self.runs += 1
        self.engine.process_run(report.run_id)
        return report

    def get(self, path: str, app: ReasoningWebApp | None = None) -> str:
        status, headers, body = call(app or self.app, "GET", path)
        self.assertEqual(status, 200, path)
        self.assertEqual(headers["Content-Security-Policy"], CSP)
        return body.decode()

    def current(self) -> ExecutiveBrief:
        brief = self.executive_store.current_brief()
        assert brief is not None
        return brief

    def persist(self, run_id: str, sections: dict[str, list[dict[str, Any]]]) -> ExecutiveBrief:
        """Persist a contract-valid brief through the core store (the UI tests' way to reach every section)."""
        with self.executive_store.transaction() as tx:
            inp = executive_input(tx.canonical_results(run_id))
            current = tx.current_brief()
        version = current.version + 1 if current else 1
        brief_id = current.brief_id if current else "eb1_" + "e" * 32
        provenance = BriefProvenance(brief_id, version, run_id, NOW, provider="fake", model=PINNED_MODEL, request_ids=("req_" + "d" * 32,))
        brief = ExecutiveBrief.from_dict(assemble_brief({"sections": {name: sections.get(name, []) for name in SECTIONS}}, inp, provenance))
        with self.executive_store.transaction() as tx:
            tx.append_brief(brief, expected_version=current.version if current else None)
        return brief

    def digest(self) -> dict[str, str]:
        """Every table of the canonical schema, hashed: equal before and after a request means the request wrote nothing."""
        with self.store.transaction() as tx:
            tables = [row["table_name"] for row in tx._all("SELECT table_name FROM information_schema.tables WHERE table_schema = 'atlas_reasoning'")]
            return {name: str(tx._one(f'SELECT md5(coalesce(string_agg(t::text, \'|\' ORDER BY t::text), \'\')) AS h FROM "{name}" t')["h"])
                    for name in sorted(tables)}

    def no_model_memory_or_write(self):
        """Context: any provider or Honcho call fails the test; the database must be byte-identical afterwards."""
        test = self

        class Guard:
            def __enter__(self_inner):
                self_inner.before = test.digest()
                self_inner.requests = len(test.model.requests) + len(test.analyst.requests)
                self_inner.patches = [mock.patch("atlas_reasoning.gateway.ReasoningGateway.call", side_effect=AssertionError("provider call on GET")),
                                      mock.patch("atlas_reasoning.openrouter_client.OpenRouterTransport.complete",
                                                 side_effect=AssertionError("OpenRouter call on GET")),
                                      mock.patch("atlas_reasoning.honcho_client.HonchoClient.read", side_effect=AssertionError("Honcho read on GET")),
                                      mock.patch("atlas_reasoning.honcho_client.HonchoClient.write", side_effect=AssertionError("Honcho write on GET")),
                                      mock.patch("atlas_reasoning.executive.ExecutiveSynthesizer.synthesize", side_effect=AssertionError("synthesis on GET"))]
                for patch in self_inner.patches:
                    patch.start()
                return self_inner

            def __exit__(self_inner, *exc: object) -> None:
                for patch in self_inner.patches:
                    patch.stop()
                if exc[0] is None:
                    test.assertEqual(len(test.model.requests) + len(test.analyst.requests), self_inner.requests)
                    test.assertEqual(test.digest(), self_inner.before)

        return Guard()

    # --- acceptance -----------------------------------------------------------------------------------------------------------------

    def test_full_phase17_acceptance_brief_to_card_to_evidence(self):
        """Canonical results → persisted ExecutiveBrief → home request → brief leads the page → each statement resolves to the right Phase 16
        card version → that card resolves to its evidence. No model call, no Honcho call and no write during any request."""
        report = self.run_snapshot()
        outcome = self.synthesizer.synthesize(report.run_id)
        self.assertEqual(outcome.decision, Decision.SYNTHESIZED)
        brief = self.current()
        pinned = {row.result_id: row.result_version for row in brief.input_results}
        with self.no_model_memory_or_write():
            for locale in ("en", "ar"):
                page = self.get(f"/reasoning/{locale}/")
                self.assertLess(page.index('id="executive-brief"'), page.index('id="reasoning-results"'))     # the brief leads; cards stay below
                self.assertIn('id="result-', page.split('id="reasoning-results"', 1)[1])
                lead = executive_section(page)
                parsed = Attrs(lead)
                self.assertEqual(parsed.values("data-brief-id"), [brief.brief_id])
                self.assertEqual(parsed.values("data-brief-version"), [str(brief.version)])
                self.assertEqual(parsed.values("data-run-id"), [brief.run_id])
                statements = [row for section in SECTIONS for row in getattr(brief.sections, section)]
                self.assertTrue(statements)
                self.assertEqual(parsed.values("data-statement-id"), [row.statement_id for row in statements])
                for row in statements:
                    block = lead.split(f'data-statement-id="{row.statement_id}"', 1)[1].split("rv-exec-statement", 1)[0]
                    self.assertIn(executive_html.esc(row.text), block)
                    for result_id in row.result_ids:
                        card = routes.card_path(locale, result_id, version=pinned[result_id])
                        evidence = routes.evidence_path(locale, result_id, version=pinned[result_id])
                        self.assertIn(f'href="{executive_html.esc(card)}"', block)
                        self.assertIn(f'href="{executive_html.esc(evidence)}"', block)
                        card_page = self.get(card.split("#")[0])
                        self.assertIn(f'data-result-id="{result_id}"', card_page)
                        self.assertIn(f'data-version="{pinned[result_id]}"', card_page)
                        evidence_page = self.get(evidence)
                        self.assertIn('data-state="resolves"', evidence_page)
                        self.assertIn(f'data-version="{pinned[result_id]}"', evidence_page)
                        for href in Attrs(card_page).values("href"):         # the card's own evidence links resolve on the evidence page
                            if "#ev-" in href:
                                self.assertIn(href.split("#")[1], Attrs(self.get(href.split("#")[0])).ids())

    def test_statement_links_are_the_deferred_card_links_made_real(self):
        """Every statement's result IDs become Phase 16 card / evidence links of the synthesized version, and nothing else."""
        report = self.run_snapshot()
        self.synthesizer.synthesize(report.run_id)
        brief = self.current()
        lead = executive_section(self.get("/reasoning/en/"))
        refs = {result_id for section in SECTIONS for row in getattr(brief.sections, section) for result_id in row.result_ids}
        self.assertEqual(set(Attrs(lead).values("data-result-id")), refs)
        for href in Attrs(lead).values("href"):
            self.assertRegex(href, r"^/reasoning/en/results/rr1_[0-9a-f]{32}(/evidence)?(\?version=[1-9][0-9]*)?(#result-rr1_[0-9a-f]{32})?$")
            self.assertNotIn("#ev-", href)                              # never straight to a Monday record
            self.assertIsNone(_V2_FINDING.search(href))                # never to an Intelligence V2 finding
            self.assertNotIn("monday", href)

    # --- sections -------------------------------------------------------------------------------------------------------------------

    def test_every_populated_section_renders_and_empty_ones_are_not_invented(self):
        report = self.run_snapshot()
        with self.executive_store.transaction() as tx:
            rows = {row.result.result_id: row for row in tx.canonical_results(report.run_id)}
        rid, editor_row = next((r, row) for r, row in rows.items() if row.subject_type == "editor")
        statement = {"text": "Text " + XSS, "result_ids": [rid]}
        sections = {name: [dict(statement, text=f"{name} statement")] for name in SECTIONS if name not in ("editor_context", "system_patterns")}
        sections["editor_context"] = [{"editor_id": editor_row.subject_id, "text": "Editor statement " + XSS, "result_ids": [rid]}]
        brief = self.persist(report.run_id, sections)
        for locale in ("en", "ar"):
            lead = executive_section(self.get(f"/reasoning/{locale}/"))
            rendered = [value for value in Attrs(lead).values("data-section") if value]
            self.assertEqual(list(dict.fromkeys(rendered)), [name for name in SECTIONS if name != "system_patterns"])
            self.assertNotIn('data-section="system_patterns"', lead)     # empty canonical section: not rendered, nothing invented
            self.assertNotIn("<script>alert", lead)
            self.assertNotIn("<img src=x", lead)
            self.assertIn("Editor statement &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", lead)
            self.assertIn(f'<code dir="ltr">{editor_row.subject_id}</code>', lead)
        self.assertEqual(brief.version, 1)

    def test_a_brief_with_no_statements_and_no_brief_at_all(self):
        self.run_snapshot()
        page = self.get("/reasoning/en/")
        self.assertIn('data-state="executive_none"', page)
        self.assertIn("Executive brief not available yet.", page)
        self.assertIn('id="result-', page)                                  # Phase 16 cards still render
        self.assertIn("الملخص التنفيذي غير متاح بعد", self.get("/reasoning/ar/"))
        phase16 = self.get("/reasoning/en/", self.phase16_app)
        self.assertNotIn('id="executive-brief"', phase16)                   # without the reader, Phase 16's home is unchanged
        empty_run = self.run_snapshot(payload_with([]))                 # every case absent: cards cool, none is eligible
        outcome = self.synthesizer.synthesize(empty_run.run_id)
        self.assertEqual(outcome.decision, Decision.SYNTHESIZED_EMPTY)
        lead = executive_section(self.get("/reasoning/en/"))
        self.assertIn('data-state="executive_empty"', lead)
        self.assertNotIn("rv-exec-statement", lead)

    # --- pinned versions, moved on, lifecycle ----------------------------------------------------------------------------------------

    def test_links_pin_the_synthesized_version_and_say_when_the_card_moved_on(self):
        first = self.run_snapshot()
        self.synthesizer.synthesize(first.run_id)
        brief = self.current()
        case_id = next(d.case_id for d in first.decisions if d.identity_key == DEADLINE_12)
        with self.store.transaction() as tx:
            result_id = tx.open_result(case_id).result_id
        cited = {r for section in SECTIONS for row in getattr(brief.sections, section) for r in row.result_ids}
        if result_id not in cited:
            brief = self.persist(first.run_id, {"top_concerns": [{"text": "This open result deserves attention first.", "result_ids": [result_id]}]})
        pinned = next(row.result_version for row in brief.input_results if row.result_id == result_id)
        self.run_snapshot(payload_with(changed_rows()))                  # the card is patched; the brief is not re-synthesized
        current = self.dashboard.result_states([result_id])[result_id]["current_version"]
        self.assertGreater(current, pinned)
        stored = [row.text for section in SECTIONS for row in getattr(self.current().sections, section)]
        for locale in ("en", "ar"):
            lead = executive_section(self.get(f"/reasoning/{locale}/"))
            item = lead.split(f'data-result-id="{result_id}" data-pinned-version="{pinned}" data-current-version="{current}"', 1)[1].split("</li>", 1)[0]
            self.assertIn(f'href="{executive_html.esc(routes.card_path(locale, result_id, version=pinned))}"', item)
            self.assertIn(f'href="{executive_html.esc(routes.evidence_path(locale, result_id, version=pinned))}"', item)
            self.assertIn('data-state="moved_on"', item)
            self.assertIn(f'href="{executive_html.esc(routes.card_path(locale, result_id))}"', item)
            for text in stored:
                self.assertIn(executive_html.esc(text), lead)              # the statement is never rewritten
        self.assertEqual(self.current().version, brief.version)

    def test_resolved_and_superseded_cited_results(self):
        report = self.run_snapshot()
        with self.executive_store.transaction() as tx:
            rows = [row.result for row in tx.canonical_results(report.run_id)]
        old, gone, replacement = rows[0], rows[1], rows[2]
        self.persist(report.run_id, {"top_concerns": [{"text": "These open results deserve attention first.", "result_ids": [old.result_id, gone.result_id]}]})
        policy = lifecycle.policy_from_env({})
        with self.store.transaction() as tx:
            current = tx.get_result(gone.result_id)
            cooled, _ = lifecycle.apply(tx, current, LifecycleStatus.COOLING, lifecycle.NOT_IN_SNAPSHOT, policy=policy, now=NOW)
            lifecycle.apply(tx, cooled, LifecycleStatus.RESOLVED, lifecycle.ABSENT_FOR_CONFIGURED_RUNS, policy=policy, now=NOW)
        lifecycle.supersede(self.store, old.result_id, by_result_id=replacement.result_id, policy=policy, clock=lambda: NOW)
        for locale in ("en", "ar"):
            lead = executive_section(self.get(f"/reasoning/{locale}/"))
            superseded = lead.split(f'data-result-id="{old.result_id}"', 1)[1].split("</li>", 1)[0]
            self.assertIn('data-lifecycle="superseded"', lead)
            self.assertIn('data-state="superseded"', superseded)
            self.assertIn(f'href="{executive_html.esc(routes.card_path(locale, replacement.result_id))}"', superseded)
            resolved = lead.split(f'data-result-id="{gone.result_id}"', 1)[1].split("</li>", 1)[0]
            self.assertIn('data-state="resolved"', resolved)
            self.assertIn('data-state="moved_on"', resolved)              # resolution is a newer (lifecycle) version
            self.assertIn(f'href="{executive_html.esc(routes.card_path(locale, gone.result_id, version=1))}"', resolved)

    # --- failures, preservation, purity -----------------------------------------------------------------------------------------------

    def test_a_failed_or_refused_synthesis_keeps_the_valid_brief_and_never_shows_the_candidate(self):
        first = self.run_snapshot()
        self.synthesizer.synthesize(first.run_id)
        brief = self.current()

        def refused(payload):
            answer = generic_answer(payload)
            answer["sections"]["top_concerns"] = [{"text": "REJECTED EXEC TEXT: the Editor is lazy and should be fired.",
                                                   "result_ids": [payload["results"][0]["result_id"]]}]
            return answer

        self.model.script(refused, refused)
        second = self.run_snapshot(payload_with(changed_rows()))
        self.assertEqual(self.synthesizer.synthesize(second.run_id).decision, Decision.FAILED)
        self.assertEqual(self.current().version, brief.version)
        for locale in ("en", "ar"):
            page = self.get(f"/reasoning/{locale}/")
            self.assertIn('data-state="executive_latest_failed"', page)
            self.assertNotIn("REJECTED EXEC TEXT", page)
            self.assertNotIn("lazy", page)
            self.assertNotIn("validation:", page)
            self.assertEqual(Attrs(executive_section(page)).values("data-brief-version"), [str(brief.version)])
        self.model.script(ProviderAuthError("upstream refused: secret-ish detail"))                    # not retryable
        third = self.run_snapshot(payload_with(changed_rows(0.875)))
        self.assertEqual(self.synthesizer.synthesize(third.run_id).decision, Decision.FAILED)
        page = self.get("/reasoning/en/")
        self.assertNotIn("secret-ish", page)
        self.assertNotIn("authentication", page)

    def test_a_preserved_brief_renders_exactly_without_a_new_synthesis_claim(self):
        report = self.run_snapshot()
        self.synthesizer.synthesize(report.run_id)
        before = executive_section(self.get("/reasoning/en/"))
        self.assertEqual(self.synthesizer.synthesize(report.run_id).decision, Decision.UNCHANGED)
        after = executive_section(self.get("/reasoning/en/"))
        self.assertEqual(before, after)
        self.assertNotIn("executive_latest_failed", after)

    def test_page_gets_never_call_a_model_or_honcho_and_never_write(self):
        report = self.run_snapshot()
        self.synthesizer.synthesize(report.run_id)
        result_id = self.current().input_results[0].result_id
        with self.no_model_memory_or_write():
            for path in ("/reasoning/en/", "/reasoning/ar/", f"/reasoning/en/results/{result_id}", f"/reasoning/en/results/{result_id}/evidence",
                         f"/reasoning/en/results/{result_id}/history", "/reasoning/en/teach", "/api/reasoning/read/results"):
                self.assertEqual(call(self.app, "GET", path)[0], 200, path)

    def test_an_unreadable_brief_never_breaks_the_home(self):
        self.run_snapshot()
        broken = ExecutiveOverviewService(ReasoningStore(Database("postgresql://nobody@127.0.0.1:1/atlas_reasoning_test")), self.dashboard)
        app = ReasoningWebApp(WebSettings(api_settings()), self.dashboard, self.management, executive=broken)
        page = self.get("/reasoning/en/", app)
        self.assertIn('data-state="executive_unavailable"', page)
        self.assertIn('id="result-', page)
        for leak in ("nobody", "postgresql", "Traceback", "DatabaseError"):
            self.assertNotIn(leak, page)

    # --- EN / AR -------------------------------------------------------------------------------------------------------------------

    def test_english_and_arabic_show_the_same_canonical_brief(self):
        report = self.run_snapshot()
        self.synthesizer.synthesize(report.run_id)
        self.run_snapshot(payload_with(changed_rows()))
        en, ar = self.get("/reasoning/en/"), self.get("/reasoning/ar/")
        self.assertTrue(en.startswith('<!doctype html><html lang="en" dir="ltr">') and ar.startswith('<!doctype html><html lang="ar" dir="rtl">'))
        self.assertEqual(executive_ids(en), executive_ids(ar))
        self.assertTrue(executive_ids(en)["data-statement-id"])
        self.assertIn("Executive brief", en)
        self.assertIn("الملخص التنفيذي", ar)
        for section in SECTIONS:
            for row in getattr(self.current().sections, section):
                self.assertIn(executive_html.esc(row.text), executive_section(ar))   # stored text, never regenerated per language

    def test_the_read_api_and_existing_phase16_routes_are_unchanged(self):
        report = self.run_snapshot()
        self.synthesizer.synthesize(report.run_id)
        result_id = self.current().input_results[0].result_id
        for app in (self.app, self.phase16_app):
            self.assertEqual(json.loads(call(app, "GET", "/api/reasoning/read/results")[2])["current"][0]["result_id"] is not None, True)
        for path in (f"/reasoning/en/results/{result_id}", f"/reasoning/en/results/{result_id}/evidence", f"/reasoning/en/results/{result_id}/history",
                     "/reasoning/en/teach"):
            self.assertEqual(self.get(path), self.get(path, self.phase16_app), path)       # every non-home page is byte-identical
        self.assertEqual(call(self.app, "POST", "/reasoning/en/")[0], 405)
        self.assertEqual(call(self.app, "GET", "/api/reasoning/read/executive")[0], 404)   # no executive API; nothing to write


class ExecutiveRenderTests(unittest.TestCase):
    """No database: the renderer never turns a non-canonical ID into a URL and escapes everything."""

    def test_a_non_canonical_cited_id_is_never_a_url(self):
        for bad in ('rr1_"><script>', "../../etc", "rr1_" + "a" * 32 + "\n", "change.editor:1f35caa3e91fe30c"):
            row = CitedResult(bad, 1, "active", XSS, True, 1, "active", None)
            html = executive_html.cited_result(row, PageContext("en"))
            self.assertNotIn("href", html)
            self.assertNotIn("<script>", html)

    def test_titles_text_and_states_are_escaped(self):
        rid = "rr1_" + "a" * 32
        row = CitedResult(rid, 1, "active", XSS, True, 3, "superseded", 'rr1_"><b>')
        statement = StatementView("top_concerns-1", "top_concerns", XSS, None, (row,))
        html = executive_html.statement(statement, PageContext("ar"))
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<img", html)
        self.assertNotIn('"><b>', html)
        self.assertIn('data-state="superseded"', html)
        self.assertNotIn("rv-exec-replacement", html)                  # a non-canonical replacement ID is never linked

    def test_overview_states_render_without_a_brief(self):
        for state, marker in (("none", "executive_none"), ("unavailable", "executive_unavailable")):
            html = executive_html.overview_html(Overview(state), PageContext("en"))
            self.assertIn(f'data-state="{marker}"', html)
            self.assertNotIn("<script", html)


if __name__ == "__main__":
    unittest.main()
