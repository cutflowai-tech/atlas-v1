"""Redesign T4.2: the Editors page opens with the judgment-first Team overview, filled from ``verdicts.json`` only, in both languages."""

import re
import unittest
from html import unescape

from browser_harness import chrome, run_scenario
from redesign_site import document, page

from atlas_commander import site_layout
from atlas_commander.dashboard_html import render_dashboard_html
from atlas_commander.i18n import AR, EN
from atlas_commander.verdict.site import VERDICTS_JSON
from atlas_commander.web import verdict_ui as ui

TIER_ORDER = ("best", "steady", "watch", "weakest", "low_activity")


def team_view(html: str) -> str:
    return html.split('<div data-view="team">', 1)[1].split("<div data-view=", 1)[0]


def text(fragment: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", fragment))


class OverviewStructureTests(unittest.TestCase):
    def test_band_tiers_and_rail_come_first(self):
        verdicts = document(VERDICTS_JSON)
        for locale, loc in (("en", EN), ("ar", AR)):
            view = team_view(page(locale))
            self.assertTrue(view.startswith('<div class="v-page"'), locale)
            band, rest = view.split('<div class="v-layout">', 1)
            self.assertIn(text(ui.message(verdicts["team"]["headline"], loc.isolating())), text(band))
            self.assertEqual(len(re.findall(r'class="v-kpi"', band)), len(verdicts["team"]["kpis"]))
            tiers = re.findall(r'<section class="v-tsec" data-tier="([a-z_]+)"', rest)
            self.assertEqual(tiers, [t for t in TIER_ORDER if any(e["tier"] == t for e in verdicts["editors"])], locale)
            self.assertEqual(len(re.findall(r'<article class="v-dec"', rest)), len(verdicts["decisions"]), locale)

    def test_every_editor_once_in_tier_then_rank_order(self):
        verdicts = document(VERDICTS_JSON)
        expected = [e["editor_id"] for e in sorted(verdicts["editors"], key=lambda e: (TIER_ORDER.index(e["tier"]), e["rank"] is None, e["rank"] or 0,
                                                                                            e["display_name"].casefold()))]
        view = team_view(page("en")).split('<aside class="v-rail"', 1)[0]
        self.assertEqual(re.findall(r'<a class="v-card" href="#/editor/([^"]+)"', view), expected)

    def test_every_number_comes_from_the_snapshot(self):
        verdicts = document(VERDICTS_JSON)
        view = team_view(page("en"))
        for e in verdicts["editors"]:
            card = view.split(f'<a class="v-card" href="#/editor/{e["editor_id"]}"', 1)[1].split("</a>", 1)[0]
            self.assertIn(text(ui.message(e["headline"], EN.isolating())), text(card))
            m = e["metrics"]
            if m["late_rate"] is not None:
                self.assertIn(f'inline-size:{ui.whole_pct(m["late_rate"])}%', card)
            self.assertIn(f'<data value="{m["completed"]}">{m["completed"]}</data> this month', card)

    def test_without_verdicts_the_page_is_the_pre_redesign_page(self):
        dashboard = document(site_layout.DASHBOARD_JSON)
        html = render_dashboard_html(dashboard, {}, None, EN, intelligence=document("intelligence-v2.json"))
        self.assertFalse('class="v-page"' in html, "no judgment-first overview without verdicts.json")
        self.assertTrue('<div data-view="team"><div class="ph">' in html)


LAYOUT = """
    await wait(300);
    const rail = document.querySelector('.v-rail').getBoundingClientRect(), main = document.querySelector('.v-main').getBoundingClientRect();
    return {overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, railAbove: rail.bottom <= main.top + 1,
            sideBySide: rail.top < main.bottom && (rail.right <= main.left + 1 || rail.left >= main.right - 1),
            sticky: getComputedStyle(document.querySelector('.v-rail')).position};
"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class OverviewLayoutTests(unittest.TestCase):
    def test_rail_sticky_beside_the_team_from_1000px_and_above_it_below(self):
        for locale in ("en", "ar"):
            for width, beside in ((390, False), (768, False), (1000, True), (1440, True)):
                result = run_scenario(page(locale), LAYOUT, width=width, height=900)
                self.assertEqual(result["overflow"], 0, (locale, width, result))
                if beside:
                    self.assertTrue(result["sideBySide"] and result["sticky"] == "sticky", (locale, width, result))
                else:
                    self.assertTrue(result["railAbove"] and result["sticky"] == "static", (locale, width, result))


if __name__ == "__main__":
    unittest.main()
