"""Redesign Phase 1: mobile tables (ATLAS-MOBILE-001) and, later, the responsive pass. Browser tests skip without Chrome."""

import re
import unittest

from browser_harness import chrome, run_scenario
from redesign_site import page

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


if __name__ == "__main__":
    unittest.main()
