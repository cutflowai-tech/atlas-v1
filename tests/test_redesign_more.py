"""Redesign T4.6: the global More details area; nothing that was reachable before the redesign is unreachable now.

The pre-redesign page is the same snapshot rendered without ``verdicts.json``. Every section, anchor, tab, drawer template and drawer
trigger it had is looked up in the redesigned page, and each must be displayable from a route: it may sit in a closed tab, disclosure or
drawer template, never in content that no route shows.
"""

import re
import unittest

from browser_harness import chrome, run_scenario
from redesign_site import document, page

from atlas_commander import site_layout
from atlas_commander.dashboard_html import render_dashboard_html
from atlas_commander.i18n import locales

IDS = re.compile(r'\sid="([^"]+)"')
DRAWERS = re.compile(r'data-drawer="([^"]+)"')
SECTIONS = re.compile(r'data-section="([^"]+)"')
TABS = re.compile(r'data-tab="([^"]+)"')
ROUTES = re.compile(r'href="(#/[^"]*)"')


def pre_redesign(locale: str) -> str:
    loc = next(loc for loc in locales() if loc.code == locale)
    reports = {}
    return render_dashboard_html(document(site_layout.DASHBOARD_JSON), reports, None, loc, switch_href="x",
                                 intelligence=document("intelligence-v2.json"))


def inventory(html: str) -> dict[str, set[str]]:
    body = html.split("<script>", 1)[0]
    return {"ids": set(IDS.findall(body)), "drawers": set(DRAWERS.findall(body)), "sections": set(SECTIONS.findall(body)),
            "tabs": set(TABS.findall(body)), "routes": set(ROUTES.findall(body))}


class InventoryTests(unittest.TestCase):
    def test_every_old_section_anchor_tab_and_drawer_still_exists(self):
        for locale in ("en", "ar"):
            old, new = inventory(pre_redesign(locale)), inventory(page(locale))
            for kind in ("ids", "drawers", "sections", "tabs"):
                self.assertEqual(old[kind] - new[kind], set(), (locale, kind))
            self.assertLessEqual({r for r in old["routes"] if not r.startswith("#/editor/")}, new["routes"] | {"#/"}, locale)

    def test_the_top_bar_links_more_details_once(self):
        for locale, label in (("en", "More details"), ("ar", "مزيد من التفاصيل")):
            nav = re.search(r'<nav class="nav"[^>]*>(.*?)</nav>', page(locale)).group(1)
            self.assertEqual(re.findall(r'data-nav="([^"]+)"', nav), ["team", "system"])
            self.assertEqual(nav.count(label), 1, locale)
        self.assertIn("Data &amp; rules", re.search(r'<nav class="nav"[^>]*>(.*?)</nav>', pre_redesign("en")).group(1))

    def test_more_details_holds_findings_editors_team_pulse_rules_and_data_health(self):
        more = page("en").split('<div data-view="system"', 1)[1]
        for anchor in ("md-findings", "md-editors", "md-pulse", "md-rules", "md-data"):
            self.assertIn(f'id="{anchor}"', more)
            self.assertIn(f'data-jump="{anchor}"', more)

    def test_duplicates_are_listed_once_under_the_finding_kept(self):
        verdicts = document("verdicts.json")
        html = page("en")
        more = html.split('<div data-view="system"', 1)[1]
        for group in verdicts["findings"]["duplicates"]:
            kept = "iv2-" + group["kept"].replace(".", "-").replace(":", "-")
            for hidden in group["hidden"]:
                target = "iv2-" + hidden.replace(".", "-").replace(":", "-")
                # one click away: under the finding kept in the list, or from the drawer of the finding Intelligence V2 groups it under
                self.assertGreaterEqual(html.count(f'data-drawer="{target}"'), 1, hidden)
                self.assertLessEqual(more.count(f'data-drawer="{target}"'), more.count(f'data-drawer="{kept}"') or 1, hidden)


ROUTE_OF = """
    const routeOf = el => { const v = el.closest('[data-view]'); if (!v) return '#/'; const n = v.getAttribute('data-view');
      return n === 'team' ? '#/' : n === 'system' ? '#/system' : '#/profile/' + n.slice(7); };
"""

REACHABLE = ROUTE_OF + """
    const ids = %s, missing = [], unshown = [];
    const byRoute = {};
    for (const id of ids) { const el = document.getElementById(id); if (!el) { missing.push(id); continue; }
      if (el.tagName === 'TEMPLATE') continue; (byRoute[routeOf(el)] = byRoute[routeOf(el)] || []).push(id); }
    for (const [route, list] of Object.entries(byRoute)) {
      location.hash = route; await wait(150);
      for (const id of list) { const el = document.getElementById(id);
        // allowed to be closed until opened: a tab panel, a disclosure, the no-match note, a drawer
        let node = el, ok = true;
        while (node && node !== document.body) {
          if (node.hidden && !node.matches('[role="tabpanel"], #no-match, [data-view]')) ok = false;
          if (node.tagName === 'DETAILS' && !node.open && node !== el) {}
          node = node.parentElement; }
        const view = el.closest('[data-view]');
        if (!ok || (view && view.hidden)) unshown.push(id); } }
    return {missing, unshown};
"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class ReachabilityTests(unittest.TestCase):
    def test_everything_reachable_before_is_reachable_now(self):
        for locale in ("en", "ar"):
            old = inventory(pre_redesign(locale))
            ids = sorted(i for i in old["ids"] if i not in ("drawer", "drawer-title", "atlas-reports"))
            result = run_scenario(page(locale), REACHABLE % ids, width=1440, height=900)
            self.assertEqual(result, {"missing": [], "unshown": []}, locale)
            # every drawer the old page could open still has a trigger (triggers inside drawer templates count: that drawer opens them)
            self.assertEqual({t for t in old["drawers"] if f'data-drawer="{t}"' not in page(locale)}, set(), locale)


if __name__ == "__main__":
    unittest.main()
