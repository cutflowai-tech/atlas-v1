"""Redesign T6.2: accessibility of the redesigned pages. An automated audit (``tests/a11y.py``: contrast against the tokens, accessible
names from Chrome's accessibility tree, focusable content under aria-hidden, ARIA references, images, language, one h1) finds zero
serious issues on every route in both languages and themes; reduced motion is honoured; the keyboard reaches everything in order and
the profile drawer keeps focus. Browser tests skip without Chrome."""

import unittest

from a11y import audit, reduced_motion
from browser_harness import Browser, chrome
from redesign_site import document, page

from atlas_commander.verdict.site import VERDICTS_JSON

FOCUS = """const el = document.activeElement; return el === document.body ? 'body'
  : (el.closest('#vprofile') ? 'drawer:' : el.closest('#drawer') ? 'evidence:' : el.closest('header.top') ? 'top:' : 'page:') + (el.className || el.tagName);"""


def editor() -> str:
    return next(e for e in document(VERDICTS_JSON)["editors"] if e["rank"])["editor_id"]


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class AuditTests(unittest.TestCase):
    def test_zero_serious_issues_on_every_route_theme_and_language(self):
        for locale in ("en", "ar"):
            for route in ("", f"/editor/{editor()}", f"/profile/{editor()}", "/system"):
                for dark in (True, False):
                    self.assertEqual(audit(page(locale), route, dark=dark), [], (locale, route, dark))

    def test_the_audit_finds_what_it_looks_for(self):
        broken = page("en").replace("</main>", '<button type="button"></button><div aria-hidden="true"><a href="#/x">x</a></div>'
                                    '<p style="color:#ccc;background:#fff">faint</p></main>', 1)
        issues = audit(broken, "", dark=False)
        for kind in ("contrast", "aria-hidden focusable", "button without an accessible name"):
            self.assertTrue(any(kind in issue for issue in issues), (kind, issues))

    def test_reduced_motion_stops_the_redesigned_transitions(self):
        for locale in ("en", "ar"):
            self.assertEqual(reduced_motion(page(locale)), [], locale)


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class KeyboardTests(unittest.TestCase):
    def test_tab_order_top_bar_then_the_cards_in_rank_order(self):
        with Browser(width=1440, height=900) as browser:
            browser.open(page("en"), "")
            browser.run("await wait(300); return null;")
            order = []
            for _ in range(5 + len(document(VERDICTS_JSON)["editors"])):
                browser.key("Tab")
                order.append(browser.run("const el = document.activeElement; return [el.className, el.getAttribute('data-editor-id')];"))
        cards = [editor_id for cls, editor_id in order if cls == "v-card"]
        self.assertEqual([cls for cls, _ in order[:5]], ["brand", "", "", "fresh v-health", "lang"])
        expected = [card for card in page("en").split('<div data-view="team">', 1)[1].split('<a class="v-card" href="#/editor/')[1:]]
        self.assertEqual(cards, [c.split('"', 1)[0] for c in expected][: len(cards)])

    def test_the_drawer_keeps_focus_in_both_directions_and_escape_closes_the_top_layer_first(self):
        for locale in ("en", "ar"):
            with Browser(width=1440, height=900) as browser:
                browser.open(page(locale), f"/editor/{editor()}")
                browser.run("await wait(400); return null;")
                seen = []
                for shift in (False, True):
                    for _ in range(12):
                        browser.key("Tab", shift=shift)
                        seen.append(browser.run(FOCUS))
                browser.run("document.querySelector('#vprofile .v-prof-more summary').focus(); return null;")
                browser.key("Enter")                                                       # open More details, then go round again
                for _ in range(40):
                    browser.key("Tab")
                    seen.append(browser.run(FOCUS))
                browser.run("document.querySelector('#vprofile .v-metric-e').focus(); return null;")
                browser.key("Enter")
                evidence = browser.run("await wait(300); return document.body.classList.contains('drawer-open');")
                browser.key("Escape")
                first = browser.run("await wait(300); return [document.body.classList.contains('drawer-open'), document.body.classList.contains('profile-open'), document.activeElement.className];")
                browser.key("Escape")
                second = browser.run("await wait(400); return document.body.classList.contains('profile-open');")
            self.assertTrue(all(s.startswith("drawer:") for s in seen), (locale, [s for s in seen if not s.startswith("drawer:")]))
            self.assertTrue(evidence, locale)
            self.assertEqual(first, [False, True, "v-metric-e"], locale)
            self.assertFalse(second, locale)


if __name__ == "__main__":
    unittest.main()
