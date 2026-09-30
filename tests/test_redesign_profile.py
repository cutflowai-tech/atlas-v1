"""Redesign T4.4: the Editor profile drawer, bound to ``#/editor/<id>``: deep link, Esc, focus trap and return, route change, 390 px."""

import re
import unittest
from html import unescape

from browser_harness import Browser, chrome, run_scenario
from redesign_site import document, page

from atlas_commander import site_layout
from atlas_commander.dashboard_html import render_dashboard_html
from atlas_commander.i18n import AR, EN
from atlas_commander.verdict.site import VERDICTS_JSON
from atlas_commander.web import verdict_ui as ui


def template(html: str, editor_id: str) -> str:
    return html.split(f'<template id="vp-{editor_id}">', 1)[1].split("</template>", 1)[0]


def text(fragment: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", fragment))


class ProfileContentTests(unittest.TestCase):
    def test_every_editor_has_a_drawer_with_every_part(self):
        verdicts = document(VERDICTS_JSON)
        for locale, loc in (("en", EN), ("ar", AR)):
            html = page(locale)
            self.assertIn('<aside class="v-profile" id="vprofile" role="dialog" aria-modal="true" aria-hidden="true" aria-labelledby="vprofile-name">', html)
            for v in verdicts["editors"]:
                body = template(html, v["editor_id"])
                self.assertIn('class="v-av s96"', body)
                self.assertIn('<h2 id="vprofile-name">', body)
                self.assertIn(f'data-tier="{v["tier"]}"', body)
                self.assertIn(f'data-confidence="{v["confidence"]}"', body)
                self.assertIn(text(ui.message(v["headline"], loc.isolating())), text(body))
                self.assertEqual(body.count('class="v-prof-alert"'), len(v["overdue"]))
                self.assertEqual(body.count('class="v-metric"'), 4)
                self.assertEqual(body.split('class="v-prof-why"', 1)[1].split("</section>", 1)[0].count("<li>"), len(v["reasons"]))
                self.assertIn('<details class="v-prof-more">', body)
                self.assertIn(f'href="#/profile/{v["editor_id"]}"', body)
                self.assertIn("data-profile-close", body)
        ranked = next(v for v in verdicts["editors"] if v["rank"])
        self.assertIn(f"Rank <data value=\"{ranked['rank']}\">{ranked['rank']}</data> of", template(page("en"), ranked["editor_id"]))

    def test_without_verdicts_editor_routes_are_the_full_profile(self):
        html = render_dashboard_html(document(site_layout.DASHBOARD_JSON), {}, None, EN)
        self.assertFalse('id="vprofile"' in html or '<template id="vp-' in html)


UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class MoreDetailsTests(unittest.TestCase):
    """T4.5: methodology, this Editor's findings without duplicates, evidence, raw IDs only under Technical details."""

    def test_every_number_has_its_evidence_and_no_uuid_shows_before_technical_details(self):
        verdicts = document(VERDICTS_JSON)
        duplicates = {r["finding_id"] for r in verdicts["findings"]["hide_from_overview"] if r["reason"] == "duplicate"}
        for locale in ("en", "ar"):
            html = page(locale)
            templates = set(re.findall(r'<template id="([^"]+)"', html))
            for v in verdicts["editors"]:
                body = template(html, v["editor_id"])
                visible, technical = body.split('<details class="v-tech">', 1)
                self.assertIsNone(UUID.search(visible), (locale, v["editor_id"]))
                self.assertIn(v["editor_id"], technical)
                targets = re.findall(r'data-drawer="([^"]+)"', body)
                self.assertTrue(targets and set(targets) <= templates, (locale, v["editor_id"], set(targets) - templates))
                metrics = re.findall(r'class="v-metric-e" data-drawer="([^"]+)"', body)            # one click from each number shown
                expected = 2 + (v["metrics"]["late_rate"] is not None) + (v["metrics"]["speed_band"] is not None)   # projects and quality always
                self.assertEqual(len(metrics), expected, (locale, v["editor_id"]))
                self.assertIn(f'data-drawer="vp-{v["editor_id"]}-projects"', body)
                for finding_id in duplicates:
                    self.assertNotIn(f'data-drawer="iv2-{finding_id.replace(".", "-").replace(":", "-")}"', visible, (locale, finding_id))
                self.assertIn('class="v-more-s"', body)

    def test_the_projects_of_the_month_are_exactly_the_count_shown(self):
        verdicts = document(VERDICTS_JSON)
        html = page("en")
        for v in verdicts["editors"]:
            listed = html.split(f'<template id="vp-{v["editor_id"]}-projects"', 1)[1].split("</template>", 1)[0]
            self.assertEqual(listed.count('<button type="button" data-drawer='), v["metrics"]["completed"], v["display_name"])

    def test_methodology_states_the_approved_numbers(self):
        verdicts = document(VERDICTS_JSON)
        values = verdicts["config"]["values"]
        ranked = next(v for v in verdicts["editors"] if v["rank"])
        body = text(template(page("en"), ranked["editor_id"]))
        self.assertIn(f'Weakest when late at least {int(values["tier.weakest_late_above_team_pp"])} points above the team', body)
        self.assertIn(f"rank {ranked['rank']} of {ranked['ranked_of']} ranked Editors", body)
        self.assertIn("Judged on:", body)


def _state():
    return """({open: document.body.classList.contains('profile-open'), hash: location.hash, focus: document.activeElement.className,
             focusId: document.activeElement.getAttribute('data-editor-id'), inside: document.getElementById('vprofile').contains(document.activeElement),
             content: document.querySelector('.v-profile-in').children.length})"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class ProfileBehaviourTests(unittest.TestCase):
    def editor(self):
        return next(v for v in document(VERDICTS_JSON)["editors"] if v["overdue"] or v["rank"])["editor_id"]

    def test_a_deep_link_opens_the_drawer(self):
        editor = self.editor()
        for locale in ("en", "ar"):
            result = run_scenario(page(locale), f"await wait(400); return {_state()};", fragment=f"/editor/{editor}")
            self.assertTrue(result["open"] and result["inside"] and result["content"] > 0, (locale, result))
            self.assertEqual(result["focus"], "v-prof-x", result)

    def test_escape_closes_and_focus_returns_to_the_card_and_focus_is_trapped(self):
        editor = self.editor()
        with Browser(width=1440, height=900) as browser:
            browser.open(page("en"), "")
            browser.run(f"await wait(300); document.querySelector('.v-card[data-editor-id=\"{editor}\"]').click(); await wait(400); return null;")
            opened = browser.run(f"return {_state()};")
            for _ in range(30):
                browser.key("Tab")
            trapped = browser.run(f"return {_state()};")
            browser.key("Tab", shift=True)
            back = browser.run(f"return {_state()};")
            browser.key("Escape")
            closed = browser.run(f"await wait(500); return {_state()};")
        self.assertTrue(opened["open"] and opened["hash"] == f"#/editor/{editor}", opened)
        self.assertTrue(trapped["inside"] and back["inside"], (trapped, back))
        self.assertEqual((closed["open"], closed["hash"], closed["focusId"], closed["content"]), (False, "", editor, 0), closed)

    def test_a_route_change_closes_it(self):
        editor = self.editor()
        result = run_scenario(page("ar"), f"""
            await wait(300); location.hash = '#/editor/{editor}'; await wait(300);
            const opened = {_state()};
            location.hash = '#/system'; await wait(300);
            return {{opened, after: {_state()}, system: !document.querySelector('[data-view="system"]').hidden}};
        """)
        self.assertTrue(result["opened"]["open"], result)
        self.assertFalse(result["after"]["open"], result)
        self.assertEqual(result["after"]["content"], 0, result)
        self.assertTrue(result["system"], result)

    def test_it_works_at_390px(self):
        editor = self.editor()
        for locale in ("en", "ar"):
            result = run_scenario(page(locale), """
                await wait(400); const p = document.getElementById('vprofile'), r = p.getBoundingClientRect();
                return {width: Math.round(r.width), left: Math.round(r.left), overflow: p.scrollWidth - p.clientWidth,
                        pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth};
            """, width=390, height=844, fragment=f"/editor/{editor}")
            self.assertEqual((result["width"], result["left"], result["overflow"], result["pageOverflow"]), (390, 0, 0, 0), (locale, result))

    def test_evidence_opens_on_top_and_a_finding_is_two_clicks_away(self):
        editor = self.editor()
        with Browser(width=1440, height=900) as browser:
            browser.open(page("en"), f"/editor/{editor}")
            opened = browser.run("""await wait(400); document.querySelector('#vprofile .v-metric-e').click(); await wait(300);
                const d = document.getElementById('drawer').getBoundingClientRect();
                return {evidence: document.body.classList.contains('drawer-open'), onTop: !!document.elementFromPoint(d.left + d.width / 2, d.top + 60).closest('#drawer')};""")
            browser.key("Escape")
            after = browser.run("await wait(300); return {evidence: document.body.classList.contains('drawer-open'), profile: document.body.classList.contains('profile-open'), focus: document.activeElement.className};")
            finding = browser.run("""document.querySelector('#vprofile .v-prof-more summary').click(); await wait(100);
                const f = document.querySelector('#vprofile .v-more-s .v-link'); f.click(); await wait(300);
                return {evidence: document.body.classList.contains('drawer-open')};""")
        self.assertEqual(opened, {"evidence": True, "onTop": True})
        self.assertEqual(after, {"evidence": False, "profile": True, "focus": "v-metric-e"})
        self.assertTrue(finding["evidence"])

    def test_the_full_analysis_stays_reachable(self):
        editor = self.editor()
        result = run_scenario(page("en"), f"""
            await wait(300); document.querySelector('#vprofile .v-prof-more summary').click(); await wait(100);
            document.querySelector('#vprofile .v-prof-full').click(); await wait(400);
            return {{open: document.body.classList.contains('profile-open'), full: !document.querySelector('[data-view="editor:{editor}"]').hidden}};
        """, fragment=f"/editor/{editor}")
        self.assertEqual(result, {"open": False, "full": True})


if __name__ == "__main__":
    unittest.main()
