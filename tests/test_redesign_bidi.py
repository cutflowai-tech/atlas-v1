"""Redesign T1.4: bidi isolation (ATLAS-RTL-002). In Arabic, every ID, date, timestamp, percentage and Latin term sits in an
isolating element, so it renders intact and in order; English pages are not changed by it."""

import unittest

from bidi_check import unisolated
from redesign_site import document, page, site

from atlas_commander import site_layout
from atlas_commander.i18n import AR, EN, isolate_latin


class IsolationHelperTests(unittest.TestCase):
    def test_latin_runs_are_wrapped_but_entities_and_placeholders_are_not(self):
        self.assertEqual(isolate_latin("موعد Requested ETA في {date} &amp; D53."),
                         'موعد <bdi dir="ltr">Requested ETA</bdi> في {date} &amp; <bdi dir="ltr">D53</bdi>.')

    def test_only_an_isolating_right_to_left_locale_changes_text(self):
        key = "ui.nav.system"
        self.assertEqual(EN.isolating().t(key), EN.t(key))
        self.assertEqual(AR.t(key), AR.isolating().t(key).replace('<bdi dir="ltr">', "").replace("</bdi>", ""))
        self.assertEqual(AR.when("2026-09-29T21:10:18Z"), AR.date("2026-09-29T21:10:18Z"))          # plain Loc: unchanged
        self.assertEqual(AR.isolating().when("2026-09-29T21:10:18Z"), f'<time datetime="2026-09-29T21:10:18Z">{AR.date("2026-09-29T21:10:18Z")}</time>')


class ArabicPagesTests(unittest.TestCase):
    def test_the_arabic_app_isolates_every_direction_sensitive_value(self):
        self.assertEqual(unisolated(page("ar")), [])

    def test_every_arabic_profile_report_isolates_every_direction_sensitive_value(self):
        for summary in document(site_layout.DASHBOARD_JSON)["editors"]:
            report = (site() / site_layout.profile_html("ar", summary["editor_id"])).read_text(encoding="utf-8")
            self.assertEqual(unisolated(report), [], summary["editor_id"])

    def test_english_catalogue_text_is_not_wrapped(self):
        self.assertNotIn('<bdi dir="ltr">Video Type</bdi>', page("en"))
        self.assertIn('<bdi dir="ltr">Video Type</bdi>', page("ar"))


if __name__ == "__main__":
    unittest.main()
