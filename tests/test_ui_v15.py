"""The contract 1.5 Editors app and report (``atlas_commander.web``): HANDOFF-V2 UX rules, fairness and bilingual parity.

Built from the local showcase dataset (``atlas_commander.demo.showcase_extract``), which gives Editors every Overall Status, every
speed verdict, positive / negative / context labels, revisions and current work, so each presentation rule is exercised.
"""

import json
import re
import shutil
import tempfile
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from atlas_commander import profile_cli, site_layout
from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.i18n import catalog
from atlas_commander.investigation import site as iv2_site
from atlas_commander.runtime import load_contract_version

APPROVED_LATIN = ("Ready For Approval", "Requested ETA", "In Progress", "Performance Issues", "For Bonus", "Video Type", "Monday", "Atlas", "UTC",
                  "English", "P25", "P75", "V1", "D10", "DECISIONS.md")
ISOLATING = ("script", "style", "bdi", "code", "template")
TEXT_ATTRIBUTES = ("aria-label", "title", "placeholder")


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.chunks = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ISOLATING:
            self.stack.append(tag)
        if not self.stack:
            self.chunks += [v for k, v in attrs if k in TEXT_ATTRIBUTES and v]

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if not self.stack and data.strip():
            self.chunks.append(data)


def visible(html):
    parser = _Visible()
    parser.feed(html)
    return parser.chunks


def app_only(html):
    """The dashboard page without its embedded report documents (separate pages, tested on their own)."""
    return html.split('<script type="application/json" id="atlas-reports">')[0]


class EditorsAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="atlas-ui-"))
        extract = showcase_extract()
        contract = load_contract_version("1.5.0")
        result = profile_cli.reconstruct_extract(extract, contract)
        cls.doc = profile_cli.build_all(result, contract, cls.out, GENERATED_AT)
        cls.editors = {s["editor_id"]: s for s in cls.doc["editors"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def page(self, relative):
        return (self.out / relative).read_text(encoding="utf-8")

    def pages(self):
        yield "en/dashboard.html", "ar/dashboard.html"
        for editor in self.editors:
            yield site_layout.profile_html("en", editor), site_layout.profile_html("ar", editor)

    # ------------------------------------------------------------ information architecture (§12, §13, #1, #2)
    def test_navigation_is_editors_and_data_only(self):
        for locale in ("en", "ar"):
            html = app_only(self.page(f"{locale}/dashboard.html"))
            nav = re.search(r'<nav class="nav"[^>]*>(.*?)</nav>', html).group(1)
            self.assertEqual(re.findall(r'data-nav="([^"]+)"', nav), ["team", "system"])
            self.assertEqual(len(re.findall(r"<h1[ >]", html)), 2 + len(self.editors), "one h1 per view: Editors, each profile, Data & rules")
            self.assertIn('role="dialog" aria-modal="true"', html)
        english = app_only(self.page("en/dashboard.html"))
        for retired in ("Management insights are being calibrated", "Good evening", "Suggested action", "Pattern detection is not active yet"):
            self.assertNotIn(retired, english, "no calibrating placeholders on the primary surface (#38)")

    def test_profile_sections_follow_the_required_order(self):
        html = app_only(self.page("en/dashboard.html"))
        for editor in self.editors:
            ids = re.findall(rf'<section id="s-{re.escape(editor)}-([a-z]+)"', html)
            # Intelligence V2 follows the signals when the publication gate is on; without a published document the section is absent.
            intelligence = ["intelligence"] if iv2_site.enabled() else []
            self.assertEqual(ids, ["summary", "change", "signals", *intelligence, "quality", "speed", "deadlines", "revisions", "work", "history", "evidence"])

    # ------------------------------------------------------------ cards: status, scannable, no leaderboard (#1, #7, #36, §24)
    def test_cards_show_the_engine_status_in_alphabetical_order(self):
        html = app_only(self.page("en/dashboard.html"))
        cards = re.findall(r'<article class="ed" data-editor-card data-status="([^"]+)".*?<h3><a href="#/editor/([^"]+)">', html)
        names = [self.editors[eid]["display_name"] for _, eid in cards]
        self.assertEqual(names, sorted(names, key=str.casefold), "cards are alphabetical, never ranked")
        for status, eid in cards:
            label = self.editors[eid]["interpretation"]["overall"]["status_label"]
            expected = {"Strong": "strong", "Good": "good", "Mixed": "mixed", "Below Expectations": "below_expectations"}.get(label, "none")
            self.assertEqual(status, expected, eid)
        self.assertEqual(len({status for status, _ in cards}), 5, "the showcase exercises every status group")
        # The pre-redesign cards never rank. The redesign's verdict overview (tiers and ranks) supersedes that rule for the verdict layer
        # only (D54; docs/redesign/DECISIONS.md R0), so the check reads the page without it.
        legacy = re.sub(r'<div class="v-page".*?(?=<div class="ph">)', "", html, flags=re.DOTALL)
        for phrase in ("Top Editor", "Best", "Worst", "Rank", "#1", "Leaderboard"):
            self.assertNotIn(phrase, " ".join(visible(legacy)))

    def test_filters_count_each_status_and_search_covers_names(self):
        html = app_only(self.page("en/dashboard.html"))
        counts = Counter(re.findall(r'data-editor-card data-status="([^"]+)"', html))
        for key, n in counts.items():
            self.assertRegex(html, rf'data-filter="{key}"[^>]*>.*?<data value="{n}">{n}</data>')
        self.assertIn('id="editor-search"', html)
        for s in self.doc["editors"]:
            self.assertIn(f'data-search="{s["display_name"].casefold()}', html)

    # ------------------------------------------------------------ fairness (§23, #18, #21, #38)
    def test_missing_evidence_and_revisions_never_look_negative(self):
        html = app_only(self.page("en/dashboard.html"))
        for block in re.findall(r'<section id="s-[^"]+-revisions".*?</section>', html):
            self.assertNotRegex(block, r'class="[^"]*\b(neg|negative|late|sc negative)\b', "revisions are neutral context")
        self.assertNotIn('class="sc negative" data-state="not_classifiable"', html)
        for state in re.findall(r'<span class="sc ([a-z_]+)" data-state="([a-z_]+)"', html):
            self.assertEqual(state[0], state[1], "a chip is styled by its own state only")

    def test_every_speed_row_and_comparison_shows_its_sample(self):
        html = app_only(self.page("en/dashboard.html"))
        rows = re.findall(r'<div class="vt" data-verdict="[^"]+">(.*?)</div></div></div>', html)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("this Editor", row)
            self.assertIn("other Editors' projects", row)

    def test_signals_are_facts_not_unapproved_ratings(self):
        html = app_only(self.page("en/dashboard.html"))
        self.assertIn("These are not Strength or Attention ratings", html)
        text = " ".join(visible(html))
        for judgement in ("Needs Attention Now:", "Recognition:", "Under Pressure", "Overloaded"):
            self.assertNotIn(judgement, text)

    # ------------------------------------------------------------ bilingual parity (§20, #32, #33)
    def test_arabic_pages_have_no_english_atlas_ui(self):
        sources = set()
        for s in self.doc["editors"]:
            sources |= {s["display_name"], *s["current_workload"]["by_current_status"]}
            sources |= {row["label"] for name in ("negative", "positive", "context") for row in s["quality"][name]["by_label"]}
            sources |= {label for c in s["speed"]["cohorts"] for label in c["labels"]}
        for _, ar_name in self.pages():
            for chunk in visible(app_only(self.page(ar_name))):
                rest = chunk
                for allowed in sorted([*APPROVED_LATIN, *sources], key=len, reverse=True):
                    rest = rest.replace(allowed, "")
                rest = re.sub(r"\bD\d+\b", "", rest)   # decision references (docs/DECISIONS.md) stay as IDs
                self.assertNotRegex(rest, r"[A-Za-z]", f"{ar_name}: {chunk[:120]!r}")

    def test_languages_share_numbers_values_and_classifications(self):
        attributes = re.compile(r'data-(component|state|reason|verdict|measurement|overall-status|status-state|section|status|classification)="([^"]*)"')
        for en_name, ar_name in self.pages():
            en, ar = self.page(en_name), self.page(ar_name)
            self.assertEqual(Counter(re.findall(r'<data value="([^"]*)">', en)), Counter(re.findall(r'<data value="([^"]*)">', ar)), en_name)
            self.assertEqual(Counter(re.findall(r"<bdi>(.*?)</bdi>", en)), Counter(re.findall(r"<bdi>(.*?)</bdi>", ar)), en_name)
            self.assertEqual(Counter(re.findall(r'<code dir="ltr">(.*?)</code>', en)), Counter(re.findall(r'<code dir="ltr">(.*?)</code>', ar)), en_name)
            self.assertEqual(Counter(attributes.findall(en)), Counter(attributes.findall(ar)), en_name)

    def test_new_strings_are_in_both_languages_and_flagged_for_review(self):
        entries = catalog()
        keys = [key for key in entries if key.startswith("ui.")]
        self.assertGreater(len(keys), 50)
        for key in keys:
            self.assertTrue(entries[key]["en"] and entries[key]["ar"], key)
            self.assertEqual(entries[key]["status"], "Needs Arabic Review", key)
        source = "".join(p.read_text() for p in (Path(__file__).resolve().parents[1] / "src" / "atlas_commander" / "web").glob("*.py"))
        used = set(re.findall(r"""\b(?:t|text|count|count_text|plural)\(\s*["']([a-z_]+\.[a-z_.0-9]+)["']""", source))
        self.assertEqual({key for key in used if not key.endswith(".") and not key.endswith("_")} - set(entries), set())

    # ------------------------------------------------------------ the report: static, self-contained, full evidence (#28, §18)
    def test_report_is_static_and_carries_every_evidence_record(self):
        for editor in self.editors:
            html = self.page(site_layout.profile_html("en", editor))
            self.assertNotIn("<script", html, "the report works without JavaScript and prints cleanly")
            self.assertIn('data-section="interpretation"', html)
            self.assertIn("Evidence records", html)
            profile = json.loads(self.page(site_layout.profile_json(editor)))
            for row in profile["projects"]:
                self.assertIn(f'<code dir="ltr">{row["evidence_event_ids"]["ready_for_approval"]}</code>', html)
            self.assertEqual(len(re.findall(r'data-classification="', html)), len(profile["projects"]))

    def test_pages_make_no_network_request(self):
        for name in site_layout.html_files(self.editors):
            html = self.page(name)
            self.assertNotRegex(html, r'(src|href)="https?://', name)
            self.assertNotIn("@import", html)
            self.assertNotIn("fonts.googleapis", html)


if __name__ == "__main__":
    unittest.main()
