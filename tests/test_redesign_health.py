"""Redesign T4.7: the plain data-health line (ATLAS-DATA-001), its three states from status-snapshot fixtures, and no technical field
on the first layer."""

import unittest

from browser_harness import chrome, run_scenario
from redesign_site import document

from atlas_commander import site_layout
from atlas_commander.dashboard_html import render_dashboard_html
from atlas_commander.i18n import AR, EN
from atlas_commander.verdict.site import VERDICTS_JSON
from atlas_commander.web.health import DELAYED, SAFE, UNAVAILABLE, data_health

RETRIEVED = "2026-09-28T09:00:00Z"


def snapshot(freshness: str, system: str = "unknown", retrieved: str | None = RETRIEVED) -> dict:
    """A Task 7 status snapshot as the build writes it (atlas_sync.status.build_time_snapshot), with a blank publication ID."""
    return {"generated_at": "2026-09-28T09:05:00Z", "snapshot_scope": "build_time", "system_state": system, "freshness_state": freshness,
            "current_publication": {"attempt_id": "attempt-20260928T090000Z-abc", "publication_id": None, "monday_retrieved_at": retrieved,
                                    "source_run_id": "20260928T090000Z-abc", "board_id": "5091110326", "contract_version": "1.5.0"},
            "freshness": {"age_seconds": 300, "expected_interval_seconds": 3600, "stale_after_seconds": 7200}}


FIXTURES = {SAFE: snapshot("fresh"), DELAYED: snapshot("delayed"), UNAVAILABLE: snapshot("fresh", system="failed")}


def render(status, loc=EN):
    return render_dashboard_html(document(site_layout.DASHBOARD_JSON), {}, None, loc, status_snapshot=status,
                                 intelligence=document("intelligence-v2.json"), verdicts=document(VERDICTS_JSON))


def top_bar(html: str) -> str:
    return html.split('<header class="top">', 1)[1].split("</header>", 1)[0]


class HealthStateTests(unittest.TestCase):
    def test_the_state_is_read_from_the_snapshot(self):
        self.assertEqual(data_health(snapshot("fresh"), None), (SAFE, RETRIEVED))
        self.assertEqual(data_health(snapshot("delayed"), None), (DELAYED, RETRIEVED))
        self.assertEqual(data_health(snapshot("stale"), None), (DELAYED, RETRIEVED))
        self.assertEqual(data_health(snapshot("unknown"), None), (DELAYED, RETRIEVED))           # never claims more than the snapshot proves
        self.assertEqual(data_health(None, RETRIEVED), (DELAYED, RETRIEVED))                    # a build without a snapshot
        self.assertEqual(data_health(snapshot("fresh", system="failed"), None), (UNAVAILABLE, None))
        self.assertEqual(data_health(snapshot("fresh", retrieved=None), None), (UNAVAILABLE, None))
        self.assertEqual(data_health(None, None), (UNAVAILABLE, None))

    def test_all_three_states_in_the_top_bar_in_both_languages(self):
        expected = {SAFE: ("Data is safe to use", "البيانات صالحة للاستخدام"), DELAYED: ("Data is delayed (last refresh", "البيانات متأخرة (آخر تحديث"),
                    UNAVAILABLE: ("Data unavailable", "البيانات غير متاحة")}
        for state, status in FIXTURES.items():
            for loc, text in ((EN, expected[state][0]), (AR, expected[state][1])):
                bar = top_bar(render(status, loc))
                self.assertIn(f'data-health="{state}"', bar)
                self.assertIn(text, bar)
        self.assertIn("28 Sep 2026, 09:00 UTC", top_bar(render(FIXTURES[DELAYED])))

    def test_technical_fields_are_under_data_health_technical_details(self):
        html = render(FIXTURES[DELAYED])
        more = html.split('<div data-view="system"', 1)[1]
        plain, technical = more.split('<details class="v-tech v-health-tech">', 1)
        self.assertIn("attempt-20260928T090000Z-abc", technical)
        self.assertNotIn("attempt-20260928T090000Z-abc", plain)
        self.assertIn('class="card v-health-card" data-health="delayed"', plain)


FIRST_LAYER = """
    await wait(300);
    const visible = [...document.querySelectorAll('body *')].filter(e => e.offsetParent !== null && e.children.length === 0).map(e => e.textContent).join(' ');
    return {attempt: visible.includes('attempt-20260928'), publicationLabel: /Publication ID|Attempt ID|معرّف الإصدار المنشور|معرّف محاولة المزامنة/.test(visible), dash: visible.includes('ceo-dashboard-v0.1'),
            health: document.querySelector('.v-health').innerText.trim()};
"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class FirstLayerTests(unittest.TestCase):
    def test_no_blank_publication_id_or_technical_label_on_the_first_layer(self):
        for loc in (EN, AR):
            result = run_scenario(render(FIXTURES[DELAYED], loc), FIRST_LAYER, width=390, height=844)
            self.assertFalse(result["attempt"] or result["publicationLabel"] or result["dash"], (loc, result))
            self.assertTrue(result["health"], (loc, result))                              # the plain line is visible on a phone too


if __name__ == "__main__":
    unittest.main()
