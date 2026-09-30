"""Redesign Phase 1: routing correctness in a real browser (ATLAS-MOBILE-002, ATLAS-MOBILE-003).

Each test renders the showcase site and drives the page in headless Chrome (see ``browser_harness``); it is skipped without Chrome.
"""

import unittest

from browser_harness import chrome, run_scenario
from redesign_site import document, page

from atlas_commander import site_layout


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class ScrollOnRouteChangeTests(unittest.TestCase):
    """T1.1: a new route opens at the top; Back returns to where the previous route was left."""

    def test_forward_route_starts_at_the_top_and_back_restores_the_position(self):
        editor = document(site_layout.DASHBOARD_JSON)["editors"][0]["editor_id"]
        result = run_scenario(page("en"), """
            window.scrollTo(0, 2400); await wait(500);
            const deep = window.scrollY;
            document.querySelector('.nav a[data-nav="system"]').click(); await wait(500);
            const afterNav = window.scrollY, systemShown = !document.querySelector('[data-view="system"]').hidden;
            history.back(); await wait(800);
            return {deep, afterNav, systemShown, afterBack: window.scrollY, hash: location.hash};
        """, width=390, height=844, fragment=f"/editor/{editor}")
        self.assertGreater(result["deep"], 1000, result)                 # the profile really was scrolled deep
        self.assertTrue(result["systemShown"], result)
        self.assertEqual(result["afterNav"], 0, result)                  # Data & rules opens at its top
        self.assertEqual(result["hash"], f"#/editor/{editor}", result)
        self.assertEqual(result["afterBack"], result["deep"], result)    # Back returns to the old position

    def test_arabic_page_behaves_the_same(self):
        result = run_scenario(page("ar"), """
            window.scrollTo(0, 1500); await wait(500);
            const deep = window.scrollY;
            document.querySelector('.nav a[data-nav="system"]').click(); await wait(500);
            const afterNav = window.scrollY;
            history.back(); await wait(800);
            return {deep, afterNav, afterBack: window.scrollY};
        """, width=390, height=844)
        self.assertEqual((result["afterNav"], result["afterBack"]), (0, result["deep"]), result)


DRAWER_STATE = """
    const d = document.getElementById('drawer');
    return {open: document.body.classList.contains('drawer-open'), hidden: d.getAttribute('aria-hidden'),
            content: d.querySelector('.body').childNodes.length, title: d.querySelector('h2').textContent};
"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class DrawerOnRouteChangeTests(unittest.TestCase):
    """T1.2: an evidence drawer never survives a route change."""

    def test_switching_route_closes_and_empties_the_evidence_drawer(self):
        editor = document(site_layout.DASHBOARD_JSON)["editors"][0]["editor_id"]
        result = run_scenario(page("en"), f"""
            const opener = document.querySelector('[data-view="editor:{editor}"] [data-drawer]');
            opener.click(); await wait(200);
            const opened = (() => {{ {DRAWER_STATE} }})();
            document.querySelector('.nav a[data-nav="system"]').click(); await wait(300);
            const afterRoute = (() => {{ {DRAWER_STATE} }})();
            return {{opened, afterRoute, focusInHiddenView: !!document.activeElement.closest('[data-view][hidden]')}};
        """, fragment=f"/editor/{editor}")
        self.assertTrue(result["opened"]["open"], result)
        self.assertGreater(result["opened"]["content"], 0, result)
        self.assertEqual(result["afterRoute"], {"open": False, "hidden": "true", "content": 0, "title": ""}, result)
        self.assertFalse(result["focusInHiddenView"], result)

    def test_browser_back_also_closes_the_drawer(self):
        editor = document(site_layout.DASHBOARD_JSON)["editors"][0]["editor_id"]
        result = run_scenario(page("ar"), f"""
            location.hash = '#/editor/{editor}'; await wait(300);
            document.querySelector('[data-view="editor:{editor}"] [data-drawer]').click(); await wait(200);
            const opened = document.body.classList.contains('drawer-open');
            history.back(); await wait(500);
            return {{opened, hash: location.hash, after: (() => {{ {DRAWER_STATE} }})()}};
        """)
        self.assertTrue(result["opened"], result)
        self.assertEqual(result["hash"], "", result)
        self.assertFalse(result["after"]["open"], result)

    def test_escape_still_closes_and_returns_focus_to_the_claim(self):
        editor = document(site_layout.DASHBOARD_JSON)["editors"][0]["editor_id"]
        result = run_scenario(page("en"), f"""
            const opener = document.querySelector('[data-view="editor:{editor}"] [data-drawer]');
            opener.click(); await wait(200);
            document.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Escape'}})); await wait(200);
            return {{open: document.body.classList.contains('drawer-open'), focusBack: document.activeElement === opener}};
        """, fragment=f"/editor/{editor}")
        self.assertEqual(result, {"open": False, "focusBack": True})


if __name__ == "__main__":
    unittest.main()
