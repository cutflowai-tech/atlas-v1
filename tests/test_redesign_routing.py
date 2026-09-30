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


if __name__ == "__main__":
    unittest.main()
