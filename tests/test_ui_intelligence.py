"""Intelligence V2 in the Atlas app (brief §23-§25): Top findings, evidence drill-down, confidence, contradicting evidence, EN/AR.

The site is built through the supported path (``profile_cli.build_all``) from the contract 1.5 showcase extract, with the D53
publication gate on. The page must render the published document exactly: the engine's Top findings in the engine's order,
every published finding with a drawer that lists every Monday project behind it, nothing computed by the page.
"""

import json
import re
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from atlas_commander import profile_cli
from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.investigation import site
from atlas_commander.investigation.engine import build_intelligence
from atlas_commander.runtime import load_contract_version
from atlas_commander.web import intel
from atlas_commander.web.app import render_app

CONTRACT = load_contract_version("1.5.0")


def section(html):
    return html.split('data-section="intelligence" aria-labelledby="iv-h">')[1].split("</section>")[0]


class IntelligencePagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="atlas-iv2-ui-"))
        cls.result = profile_cli.reconstruct_extract(showcase_extract(), CONTRACT)
        with mock.patch.object(site, "enabled", return_value=True):          # independent of the configured gate
            cls.doc = profile_cli.build_all(cls.result, CONTRACT, cls.out, GENERATED_AT)
        cls.iv2 = json.loads((cls.out / site.INTELLIGENCE_JSON).read_text())
        cls.en = (cls.out / "en/dashboard.html").read_text(encoding="utf-8")
        cls.ar = (cls.out / "ar/dashboard.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_the_artifact_is_the_published_approved_only_document(self):
        self.assertEqual((self.iv2["mode"], self.iv2["publishable"]), ("approved_only", True))
        self.assertTrue(self.iv2["findings"], "the showcase must exercise the section")

    def test_top_findings_are_the_engines_at_most_five_in_its_order_in_both_languages(self):
        top = self.iv2["sections"]["top_findings"]["finding_ids"]
        self.assertLessEqual(len(top), 5)
        for html in (self.en, self.ar):
            cards = re.findall(r'<article class="iv-card" data-finding="([^"]+)"', section(html))
            self.assertEqual(cards, top)
            self.assertEqual(re.findall(r'<span class="iv-rank"><data value="(\d+)">', section(html)), [str(i) for i in range(1, len(top) + 1)])

    def test_each_top_card_answers_what_why_evidence_confidence_and_next_step(self):
        for html, words in ((self.en, ("What Atlas noticed", "Why it matters", "Suggested investigation", "Open evidence", "Confidence:")),
                            (self.ar, ("ما لاحظه Atlas", "لماذا يهم", "التحقق المقترح", "قوة الأدلة:"))):
            cards = re.findall(r'<article class="iv-card" data-finding=.*?</article>', section(html), re.DOTALL)
            for card in cards:
                visible = re.sub(r'</?bdi[^>]*>', "", card)          # Latin terms are isolated in Arabic (redesign T1.4)
                for word in words:
                    self.assertIn(word, visible)

    def test_confidence_is_a_word_never_a_percentage(self):
        levels = {f["finding_id"]: f["confidence"]["level"] for f in self.iv2["findings"]}
        for html in (self.en, self.ar):
            for finding_id, level in re.findall(r'data-finding="([^"]+)">.*?data-confidence="([a-z]+)"', html, re.DOTALL):
                self.assertEqual(level, levels[finding_id])
            for chip in re.findall(r'<span class="iv-conf [^"]+"[^>]*>(.*?)</span>', html):
                self.assertNotRegex(chip, r"\d")

    def test_contradicting_evidence_is_shown_next_to_the_claim(self):
        mixed = [f["finding_id"] for f in self.iv2["findings"] if f["contradicting_evidence"]]
        for html in (self.en, self.ar):
            for finding_id in mixed:
                card = re.search(rf'<article class="iv-card[^"]*" data-finding="{re.escape(finding_id)}">(.*?)</article>', html, re.DOTALL)
                if card:
                    self.assertIn('data-mixed="true"', card.group(1))

    def test_every_published_finding_has_a_drawer_with_every_monday_project(self):
        for finding in self.iv2["findings"]:
            template = re.search(rf'<template id="{re.escape(intel.tid(finding))}"[^>]*>(.*?)</template>', self.en, re.DOTALL)
            self.assertIsNotNone(template, finding["finding_id"])
            shown = set(re.findall(r'<code dir="ltr">(\d+)</code>', template.group(1)))
            for key in ("supporting_evidence", "contradicting_evidence", "context_evidence"):
                for block in finding[key]:
                    self.assertLessEqual({r["monday_item_id"] for r in block["records"]}, shown, finding["finding_id"])

    def test_evidence_chips_open_the_projects_own_monday_evidence(self):
        templates = set(re.findall(r'<template id="([^"]+)"', self.en))
        for target in re.findall(r'<button type="button" class="chip" data-drawer="([^"]+)">', self.en):
            self.assertIn(target, templates)

    def test_both_languages_render_the_same_findings_values_and_attributes(self):
        attributes = re.compile(r'data-(finding|confidence|category|mixed|block)="([^"]*)"')
        self.assertEqual(Counter(attributes.findall(self.en)), Counter(attributes.findall(self.ar)))
        # Every primary finding is reachable from the overview: a Top card or a row of "All published findings".
        overview = section(self.en)
        for finding in self.iv2["findings"]:
            if not (finding["cluster"] or {}).get("suppressed_in_sections"):
                self.assertTrue(f'data-finding="{finding["finding_id"]}"' in overview or f'data-drawer="{intel.tid(finding)}"' in overview, finding["finding_id"])

    def test_weak_exploratory_findings_are_not_on_the_page(self):
        review = build_intelligence(self.result, CONTRACT, GENERATED_AT, mode="review")
        published = {f["finding_id"] for f in self.iv2["findings"]}
        for finding in review["findings"]:
            weak_only = (finding["confidence"]["level"] == "weak" and finding["evidence_level"] != "fact" and finding["category"] != "data_warning")
            if weak_only:
                self.assertNotIn(finding["finding_id"], published)
                self.assertNotIn(f'data-finding="{finding["finding_id"]}"', self.en)

    def test_raw_detector_codes_never_appear_in_management_text(self):
        for html in (self.en, self.ar):
            cards = " ".join(re.findall(r'<article class="iv-card".*?</article>', html, re.DOTALL))
            visible = re.sub(r"<[^>]+>", " ", re.sub(r'<code dir="ltr">.*?</code>', "", cards))
            self.assertNotRegex(visible, r"\b[a-z]+_[a-z_]+\b")                 # snake_case codes
            self.assertNotRegex(visible, r"\b(contradiction|pattern|risk|change|bottleneck)\.[a-z_]+")

    def test_editor_profiles_list_their_findings_in_the_section_bar(self):
        for block in self.iv2["editors"]:
            sid = f's-{block["editor_id"]}-intelligence'
            for html in (self.en, self.ar):
                self.assertIn(f'<section id="{sid}"', html)
                profile = html.split(f'<section id="{sid}"')[1].split("</section>")[0]
                self.assertEqual(re.findall(r'data-finding="([^"]+)"', profile), block["finding_ids"])

    def test_data_and_rules_state_the_approved_parameters(self):
        for html in (self.en, self.ar):
            card = html.split('data-section="intelligence-rules"')[1].split("</div></div>")[0]
            for parameter in self.iv2["parameters"]["parameters"]:
                self.assertIn(f'<code dir="ltr">{parameter["name"]}</code>', card)


class WithoutIntelligenceTests(unittest.TestCase):
    """Rollback safety: without a published document the page is exactly the page without Intelligence."""

    def test_no_document_or_a_review_document_renders_nothing(self):
        result = profile_cli.reconstruct_extract(showcase_extract(), CONTRACT)
        out = Path(tempfile.mkdtemp(prefix="atlas-iv2-none-"))
        try:
            profiles, pages = profile_cli.build_profiles(result, CONTRACT, out, GENERATED_AT, None)
            doc = profile_cli.build_dashboard_files(result, CONTRACT, out, GENERATED_AT, profiles, pages)
            review = build_intelligence(result, CONTRACT, GENERATED_AT, mode="review")
            from atlas_commander.i18n import EN
            plain = render_app(doc, pages["en"], None, EN, None, None, None)
            self.assertEqual(plain, render_app(doc, pages["en"], None, EN, None, None, review))
            self.assertNotIn('data-section="intelligence"', plain)
            self.assertNotIn("iv2-", plain)
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
