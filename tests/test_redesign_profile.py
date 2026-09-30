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
                self.assertEqual(body.split('class="v-prof-why"', 1)[1].count("<li>"), len(v["reasons"]))
                self.assertIn('<details class="v-prof-more">', body)
                self.assertIn(f'href="#/profile/{v["editor_id"]}"', body)
                self.assertIn("data-profile-close", body)
        ranked = next(v for v in verdicts["editors"] if v["rank"])
        self.assertIn(f"Rank <data value=\"{ranked['rank']}\">{ranked['rank']}</data> of", template(page("en"), ranked["editor_id"]))

    def test_without_verdicts_editor_routes_are_the_full_profile(self):
        html = render_dashboard_html(document(site_layout.DASHBOARD_JSON), {}, None, EN)
        self.assertFalse('id="vprofile"' in html or '<template id="vp-' in html)


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
