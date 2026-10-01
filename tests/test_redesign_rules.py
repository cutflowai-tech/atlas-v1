"""Redesign T4.8: every rule that is not approved shows the rule Atlas proposes and what it would unlock, and the management decision
card links to it."""

import re
import unittest

from browser_harness import chrome, run_scenario
from redesign_site import document, page

from atlas_commander import site_layout
from atlas_commander.management import V15_PENDING_SLOTS
from atlas_commander.verdict.site import VERDICTS_JSON


def more(locale: str) -> str:
    return page(locale).split('<div data-view="system"', 1)[1]


class ProposalTests(unittest.TestCase):
    def test_every_rule_not_approved_has_a_proposal_and_what_it_unlocks(self):
        view = document(site_layout.DASHBOARD_JSON)["editors"][0]["interpretation"]
        expected = (["quality"] if view["components"]["quality"]["rule_status"] != "approved" else []) + [
            s for s in V15_PENDING_SLOTS if s != "trend_direction" or view["trend_rule_status"] != "approved"]
        for locale, words in (("en", ("Proposed rule", "It would unlock", "Proposed · not approved")),
                              ("ar", ("القاعدة المقترحة", "ما الذي ستتيحه", "مقترحة · غير معتمدة"))):
            section = more(locale)
            self.assertEqual(re.findall(r'<article class="v-rule" id="rule-([a-z_]+)"', section), expected, locale)
            for slot in expected:
                article = section.split(f'id="rule-{slot}"', 1)[1].split("</article>", 1)[0]
                for word in words:
                    self.assertIn(word, article, (locale, slot, word))
            self.assertNotIn(">Rules awaiting approval</h3><ul", section)            # the old list became the proposals

    def test_the_quality_proposal_and_the_numbers_come_from_the_approved_configuration(self):
        values = document(VERDICTS_JSON)["config"]["values"]
        section = re.sub(r"<[^>]+>", "", more("en"))
        self.assertIn("Approve Quality: any project with a negative client-quality label on Monday counts as a quality issue", section)
        self.assertIn(f'({int(values["score.weight_quality"] * 100)}% of the score', section)
        self.assertIn(f'by at least {int(values["reasoning.material_rate_difference"] * 100)} points or the median time by at least '
                      f'{int(values["reasoning.material_duration_pct"])}%', section)


class DecisionLinkTests(unittest.TestCase):
    def test_the_management_decision_card_links_to_the_rule(self):
        verdicts = document(VERDICTS_JSON)
        rule = next(d for d in verdicts["decision_candidates"] if d["type"] == "approve_rule")
        dimension = rule["target"].split(":", 1)[1]
        for locale in ("en", "ar"):
            html = page(locale)
            cards = re.findall(rf'<article class="v-dec" data-horizon="management" data-decision-id="{rule["id"]}">.*?</article>', html, flags=re.DOTALL)
            self.assertGreaterEqual(len(cards), 1, locale)                          # on the overview (when in the first five) and in More details
            for card in cards:
                self.assertIn(f'href="#/system/rule-{dimension}"', card)
            self.assertIn(f'id="rule-{dimension}"', more(locale))

    def test_every_decision_is_listed_in_more_details_with_its_link(self):
        verdicts = document(VERDICTS_JSON)
        section = more("en").split('<section id="md-decisions"', 1)[1].split("</section>", 1)[0]
        self.assertEqual(re.findall(r'data-decision-id="([^"]+)"', section), [d["id"] for d in verdicts["decision_candidates"]])
        for d in verdicts["decision_candidates"]:
            card = section.split(f'data-decision-id="{d["id"]}"', 1)[1].split("</article>", 1)[0]
            self.assertIn('class="v-dec-more', card, d["type"])


FOLLOW = """
    await wait(300);
    const link = document.querySelector('.v-rail a.v-dec-more[href^="#/system/rule-"]') || document.querySelector('a.v-dec-more[href^="#/system/rule-"]');
    const target = link.getAttribute('href').split('/').pop();
    link.click(); await wait(500);
    const el = document.getElementById(target), r = el.getBoundingClientRect();
    return {system: !document.querySelector('[data-view="system"]').hidden, inView: r.top >= 0 && r.top < window.innerHeight, focused: document.activeElement === el};
"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class FollowTests(unittest.TestCase):
    def test_the_link_opens_more_details_at_the_rule(self):
        for locale in ("en", "ar"):
            for width in (1440, 390):
                self.assertEqual(run_scenario(page(locale), FOLLOW, width=width, height=900), {"system": True, "inView": True, "focused": True},
                                 (locale, width))


if __name__ == "__main__":
    unittest.main()
