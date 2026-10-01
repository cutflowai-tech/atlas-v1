"""Redesign Phase 1: mobile tables (ATLAS-MOBILE-001), and T6.1: the responsive pass of the redesigned pages. Browser tests skip without
Chrome."""

import re
import unittest
from pathlib import Path

from browser_harness import chrome, run_scenario
from redesign_site import document, page

TABLE_CHECK = """
    await wait(300);
    const doc = document.documentElement, tables = [...document.querySelectorAll('[data-view="system"] .tbl table')];
    const codes = [...document.querySelectorAll('[data-view="system"] .tbl code')];
    return {
      overflow: doc.scrollWidth - doc.clientWidth,
      tables: tables.length,
      display: tables.map(t => getComputedStyle(t).display),
      brokenCodes: codes.filter(c => c.textContent.length <= 24 && c.getClientRects().length > 1).map(c => c.textContent),
      narrowCells: [...document.querySelectorAll('[data-view="system"] .tbl td')].filter(td => td.offsetParent && td.clientWidth < 200).length,
    };
"""


class TableMarkupTests(unittest.TestCase):
    def test_every_body_cell_names_its_column(self):
        for locale in ("en", "ar"):
            system = page(locale).split('data-view="system"')[1]
            for body in re.findall(r"<tbody>(.*?)</tbody>", system, re.DOTALL):
                for attrs in re.findall(r"<td([^>]*)>", body):
                    if "colspan" not in attrs:
                        self.assertIn("data-label=", attrs, (locale, attrs))


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class MobileTableTests(unittest.TestCase):
    """T1.3: at 390 px every Data & rules table is a stack of key/value records; nothing wraps character by character."""

    def test_390px_tables_are_stacked_records_without_page_overflow(self):
        for locale in ("en", "ar"):
            result = run_scenario(page(locale), TABLE_CHECK, width=390, height=844, fragment="/system")
            self.assertGreater(result["tables"], 3, result)
            self.assertEqual(result["overflow"], 0, (locale, result))
            self.assertEqual(set(result["display"]), {"block"}, (locale, result))
            self.assertEqual(result["brokenCodes"], [], (locale, result))
            self.assertEqual(result["narrowCells"], 0, (locale, result))

    def test_desktop_keeps_real_tables(self):
        result = run_scenario(page("en"), TABLE_CHECK, width=1280, height=900, fragment="/system")
        self.assertEqual(set(result["display"]), {"table"}, result)
        self.assertEqual(result["overflow"], 0, result)


CHECK = (Path(__file__).resolve().parent / "js" / "responsive_check.js").read_text(encoding="utf-8")
WIDTHS = (390, 768, 1024, 1440, 2560)


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class ResponsivePassTests(unittest.TestCase):
    """T6.1: at 390, 768, 1024, 1440 and 2560 px, in both languages, the overview, a profile drawer and More details have no horizontal
    scroll, no text cut by an overflow rule and no overlapping cards, tiles, decisions or metrics (``tests/js/responsive_check.js``)."""

    def test_every_width_both_languages(self):
        editor = next(e for e in document("verdicts.json")["editors"] if e["overdue"] or e["rank"])["editor_id"]
        for locale in ("en", "ar"):
            for route in ("", f"/editor/{editor}", "/system"):
                for width in WIDTHS:
                    result = run_scenario(page(locale), CHECK, width=width, height=900, fragment=route)
                    self.assertEqual(result, {"overflow": 0, "clipped": [], "overlap": []}, (locale, route, width))

    def test_the_check_finds_what_it_looks_for(self):
        sabotage = """
            document.querySelector('.v-card-name').style.cssText = 'overflow:hidden;white-space:nowrap;display:block;width:30px';
            const cards = document.querySelector('.v-grid').children; if (cards[1]) cards[1].style.marginInlineStart = '-200px';
            const wide = document.createElement('div'); wide.style.width = '3000px'; wide.textContent = 'x'; document.querySelector('.v-page').appendChild(wide);
        """
        result = run_scenario(page("en"), sabotage + CHECK, width=1440, height=900)
        self.assertGreater(result["overflow"], 0)
        self.assertTrue(any(c.startswith("v-card-name") for c in result["clipped"]), result)


if __name__ == "__main__":
    unittest.main()
