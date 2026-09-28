"""Arabic/English presentation (i18n): one analytical dataset, two languages, no semantic difference."""

import json
import re
import shutil
import tempfile
import unittest
from collections import Counter
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from test_ingest import FakeMonday, items
from test_profile import NOW, dataset
from test_sync_run import T0, TOKEN, Clock, Monotonic, logs

from atlas_commander import i18n, profile_cli, site_layout
from atlas_commander.contracts import validate
from atlas_commander.i18n import AR, EN, Loc, TranslationError, catalog, plural_category
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.profile import OVERALL_NOTE, POSITIVE_NOTE, REVISION_NOTE
from atlas_commander.runtime import load_contract_version
from atlas_sync import publish as pub
from atlas_sync import run as sync

ROOT = Path(__file__).resolve().parents[1]
EDITORS = ("editor-label-6", "editor-label-12")
# Atlas-approved source/technical terms that stay in English on Arabic pages (brief, section 2 and 17).
APPROVED_LATIN = ("Ready For Approval", "Requested ETA", "In Progress", "Performance Issues", "For Bonus", "Video Type", "Monday", "Atlas", "UTC",
                  "DECISIONS.md", "D10", "V1", "P25", "P75", "English")
ISOLATING = ("script", "style", "bdi", "code")
TEXT_ATTRIBUTES = ("aria-label", "title", "data-title", "alt", "data-morning", "data-afternoon", "data-evening")


class _Visible(HTMLParser):
    """Visible text and text attributes, outside <script>, <style> and direction-isolated source values."""

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


def data_values(html):
    return Counter(re.findall(r'<data value="([^"]*)">', html))


def isolated(html, pattern):
    return Counter(re.findall(pattern, html))


class BilingualSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.4.0")
        activity, items_payload = dataset()
        cls.result = reconstruct_cycles(activity, cls.contract, items_payload=items_payload, ingestion={"retrieved_at": NOW})
        cls.out = Path(tempfile.mkdtemp(prefix="atlas-i18n-"))
        cls.doc = profile_cli.build_all(cls.result, cls.contract, cls.out, NOW)
        cls.sources = set()
        for s in cls.doc["editors"]:
            cls.sources |= {s["display_name"], *s["current_workload"]["by_current_status"], *(row["label"] for row in s["quality"]["by_label"])}
            cls.sources |= {label for c in s["speed"]["cohorts"] for label in c["labels"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def page(self, relative):
        return (self.out / relative).read_text(encoding="utf-8")

    def pairs(self):
        yield "en/dashboard.html", "ar/dashboard.html"
        for editor in EDITORS:
            yield site_layout.profile_html("en", editor), site_layout.profile_html("ar", editor)

    # 1, 2, 3, 24 — both trees exist, every English page has an Arabic counterpart
    def test_1_2_3_both_locale_trees_are_generated(self):
        files = sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file())
        self.assertEqual(files, sorted(site_layout.required_files(EDITORS)))
        english = {p.name for p in (self.out / "en" / "profiles").iterdir()}
        self.assertEqual(english, {p.name for p in (self.out / "ar" / "profiles").iterdir()})
        self.assertEqual(english, {f"{e}.html" for e in EDITORS})

    # 4, 5 — structural language and direction
    def test_4_5_documents_declare_language_and_direction(self):
        for name, locale in site_layout.html_files(EDITORS).items():
            self.assertTrue(self.page(name).startswith(f'<!doctype html><html lang="{locale}" dir="{"rtl" if locale == "ar" else "ltr"}">'), name)
        self.assertTrue(self.page("index.html").startswith('<!doctype html><html lang="en" dir="ltr">'))

    # 6, 7 — the language switch keeps the equivalent page
    def test_6_7_language_switch_points_to_the_equivalent_page(self):
        en, ar = self.page("en/dashboard.html"), self.page("ar/dashboard.html")
        self.assertRegex(en, r'<a class="lang" href="\.\./ar/dashboard\.html" hreflang="ar" lang="ar" dir="rtl" data-keep-hash aria-label="[^"]+">العربية</a>')
        self.assertRegex(ar, r'<a class="lang" href="\.\./en/dashboard\.html" hreflang="en" lang="en" dir="ltr" data-keep-hash aria-label="[^"]+">English</a>')
        self.assertIn("keep.setAttribute('href', keep.getAttribute('href').split('#')[0] + location.hash)", en)   # #/editor/<id> is kept
        for editor in EDITORS:
            en_profile, ar_profile = self.page(site_layout.profile_html("en", editor)), self.page(site_layout.profile_html("ar", editor))
            self.assertIn(f'href="../../ar/profiles/{editor}.html" hreflang="ar"', en_profile)
            self.assertIn(f'href="../../en/profiles/{editor}.html" hreflang="en"', ar_profile)
            self.assertIn(f'href="../dashboard.html#/editor/{editor}"', ar_profile)
            self.assertIn('aria-label="عرض هذه الصفحة باللغة الإنجليزية"', ar_profile)   # the switch has an accessible, localized label

    # 8, 9 — catalogue completeness and failure on unknown keys
    def test_8_every_production_key_has_both_languages(self):
        entries = catalog()
        self.assertGreater(len(entries), 300)
        for key, entry in entries.items():
            for locale in i18n.LOCALES:
                self.assertTrue(entry[locale], (key, locale))
            self.assertIn(entry["status"], i18n.REVIEW_STATUSES)
        used = set()
        for module in ("dashboard_html.py", "profile_html.py", "profile_cli.py", "i18n.py"):
            source = (ROOT / "src" / "atlas_commander" / module).read_text()
            used |= set(re.findall(r"""\b(?:t|text|count|count_text|plural)\(\s*["']([a-z_]+\.[a-z_.0-9]+)["']""", source))
        self.assertEqual({key for key in used if not key.endswith(".")} - set(entries), set())

    def test_9_unknown_keys_and_locales_fail_clearly(self):
        with self.assertRaisesRegex(TranslationError, "unknown translation key 'home.nope'"):
            AR.t("home.nope")
        with self.assertRaises(TranslationError):
            Loc("fr")
        with self.assertRaises(TranslationError):
            AR.t("noun.project")                                     # a plural entry used as plain text
        self.assertTrue(i18n._check_entry("x", {"en": "Hello", "context": "c", "status": i18n.REVIEW_STATUSES[0]}))   # no Arabic → invalid
        broken = {"en": {"one": "a", "other": "b"}, "ar": {"one": "x"}, "context": "c", "status": i18n.REVIEW_STATUSES[0]}
        self.assertTrue(i18n._check_entry("y", broken))              # incomplete Arabic plural forms → invalid

    # 10, 29 — no accidental English Atlas UI in Arabic pages
    def test_10_29_arabic_pages_have_no_english_atlas_ui(self):
        for name, locale in site_layout.html_files(EDITORS).items():
            if locale != "ar":
                continue
            for chunk in visible(self.page(name)):
                rest = chunk
                for allowed in sorted([*APPROVED_LATIN, *self.sources], key=len, reverse=True):
                    rest = rest.replace(allowed, "")
                self.assertNotRegex(rest, r"[A-Za-z]", f"{name}: {chunk[:160]!r}")

    # 11-14, 34 — Monday-derived values are unchanged and direction-isolated
    def test_11_to_14_34_source_values_are_identical_and_isolated(self):
        for en_name, ar_name in self.pairs():
            en, ar = self.page(en_name), self.page(ar_name)
            self.assertEqual(set(isolated(en, r"<bdi>(.*?)</bdi>")), set(isolated(ar, r"<bdi>(.*?)</bdi>")), en_name)
            self.assertEqual(isolated(en, r'<code dir="ltr">(.*?)</code>'), isolated(ar, r'<code dir="ltr">(.*?)</code>'), en_name)
        ar = self.page("ar/dashboard.html")
        for value in ("Will", "Ahmed", "Class A", "Late Delivery", "In Progress", "Revisions"):   # names, Video Type, labels, statuses
            self.assertIn(f"<bdi>{value}</bdi>", ar)
        for editor in self.doc["editors"]:
            self.assertIn(f"<h3><bdi>{editor['display_name']}</bdi></h3>", ar)                    # never translated or transliterated
        self.assertIn('<code dir="ltr">1-s2</code>', self.page(site_layout.profile_html("ar", "editor-label-6")))   # Monday event IDs

    # 15, 16, 18, 19, 20 — every number, percentage and duration is the same in both languages
    def test_15_16_18_19_20_numbers_are_analytically_identical(self):
        for en_name, ar_name in self.pairs():
            en, ar = self.page(en_name), self.page(ar_name)
            self.assertEqual(data_values(en), data_values(ar), en_name)
            self.assertEqual(isolated(en, r'<bdi dir="ltr">(.*?)</bdi>'), isolated(ar, r'<bdi dir="ltr">(.*?)</bdi>'), en_name)
        will = next(s for s in self.doc["editors"] if s["editor_id"] == "editor-label-6")
        ar = self.page("ar/dashboard.html")
        self.assertIn('<bdi dir="ltr">33.3%</bdi>', ar)
        self.assertIn(f'<data value="{will["revisions"]["client_revision_events"]}">', ar)
        self.assertIn(f'<data value="{will["quality"]["total_occurrences"]}">', ar)

    # 17, 35 — same instants; the timeline is never mirrored
    def test_17_35_timestamps_and_chronology_are_preserved(self):
        for en_name, ar_name in self.pairs():
            en, ar = self.page(en_name), self.page(ar_name)
            self.assertEqual(Counter(re.findall(r"\b\d{2}:\d{2} UTC", en)), Counter(re.findall(r"\b\d{2}:\d{2} UTC", ar)), en_name)
        for moment in ("2026-09-01T18:00:00Z", "2026-12-31T23:59:00Z"):
            self.assertEqual(re.findall(r"\d+", EN.date(moment)), re.findall(r"\d+", AR.date(moment)))
        self.assertEqual(AR.month("2026-09"), "سبتمبر 2026")
        en, ar = self.page("en/dashboard.html"), self.page("ar/dashboard.html")
        self.assertIn('<div class="tl" dir="ltr">', ar)
        positions = r'class="mk [a-z_]+" style="left:([0-9.]+)%'
        self.assertEqual(re.findall(positions, en), re.findall(positions, ar))                   # same place on the axis, same order
        ticks = [float(x) for x in re.findall(r'<div class="axis"><span style="left:([0-9.]+)%', ar)]
        axis = re.search(r'<div class="axis">(.*?)</div>', ar).group(1)
        lefts = [float(x) for x in re.findall(r'<span style="left:([0-9.]+)%">', axis)]
        self.assertEqual(lefts, sorted(lefts))                                                    # day 1 at the left, later days to the right
        self.assertTrue(ticks)
        self.assertIn("يسير الخط الزمني من اليسار (الأقدم) إلى اليمين (الأحدث).", ar)

    # 21 — both languages come from the same language-neutral documents
    def test_21_one_analytical_source_for_both_languages(self):
        for editor in EDITORS:
            profile = json.loads(self.page(site_layout.profile_json(editor)))
            self.assertEqual(validate(profile, "editor-profile-v1.4.schema.json"), [])
        self.assertEqual(json.loads(self.page("dashboard.json"))["editors"][0]["profile_ref"], "profiles/editor-label-6.json")
        self.assertFalse(list(self.out.glob("**/*.ar.json")) + list((self.out / "ar").glob("**/*.json")))   # no Arabic metric JSON
        rendered = []
        real = profile_cli.render_dashboard_html
        with mock.patch.object(profile_cli, "render_dashboard_html", side_effect=lambda doc, *a, **k: rendered.append(doc) or real(doc, *a, **k)):
            profile_cli.build_all(self.result, self.contract, Path(tempfile.mkdtemp()), NOW)
        self.assertEqual(len(rendered), 2)
        self.assertIs(rendered[0], rendered[1])                                                  # the very same document object

    # 22, 23 — either language failing fails the build
    def test_22_23_a_failing_locale_fails_the_build(self):
        for failing in ("en", "ar"):
            real = profile_cli.render_profile_html

            def render(profile, url=None, loc=EN, failing=failing, real=real, **kwargs):
                if loc.code == failing:
                    raise TranslationError("missing")
                return real(profile, url, loc, **kwargs)

            with self.subTest(locale=failing), mock.patch.object(profile_cli, "render_profile_html", render), self.assertRaises(TranslationError):
                profile_cli.build_all(self.result, self.contract, Path(tempfile.mkdtemp()), NOW)

    # 27 — business-rule modules know nothing about language
    def test_27_no_business_rule_module_depends_on_locale(self):
        for module in ("metrics.py", "cycles.py", "attribution.py", "quality.py", "video_type.py", "profile.py", "pipeline.py", "dashboard.py",
                       "management.py", "identity.py", "normalization.py", "monday_source.py", "ingest.py"):
            source = (ROOT / "src" / "atlas_commander" / module).read_text()
            self.assertNotRegex(source, r"i18n|locale|\bLoc\b|arabic", module)

    # 30 — deterministic root entry
    def test_30_root_resolves_to_english(self):
        root = self.page("index.html")
        self.assertIn('<meta http-equiv="refresh" content="0; url=en/dashboard.html">', root)
        self.assertNotIn("atlas-reports", root)                                                  # not a third dashboard
        for locale in i18n.LOCALES:
            self.assertIn('url=dashboard.html"', self.page(site_layout.locale_index(locale)))

    # 32 — Western digits only
    def test_32_western_digits_in_arabic(self):
        for name, locale in site_layout.html_files(EDITORS).items():
            if locale == "ar":
                self.assertNotRegex(self.page(name), "[٠-٩۰-۹]", name)
        self.assertEqual(AR.hours_text(36000), "10.0 ساعة")

    # 33 — Arabic plurals
    def test_33_arabic_pluralization(self):
        expected = {0: "0 مشروع", 1: "مشروع واحد", 2: "مشروعان", 3: "3 مشاريع", 5: "5 مشاريع", 10: "10 مشاريع", 11: "11 مشروعًا",
                    99: "99 مشروعًا", 100: "100 مشروع", 101: "101 مشروع", 103: "103 مشاريع", 111: "111 مشروعًا"}
        for n, text in expected.items():
            self.assertEqual(AR.count_text("noun.project", n), text, n)
        self.assertEqual(AR.count_text("noun.project", 2, case="gen"), "مشروعين")
        self.assertEqual(AR.count_text("noun.editor", 2), "مونتيران")
        self.assertEqual(AR.count_text("noun.issue_signal", 3), "3 مؤشرات مشكلات")
        self.assertEqual(AR.count_text("noun.completed_project", 7), "7 مشاريع مكتملة")
        self.assertEqual(EN.count_text("noun.project", 1), "1 project")
        self.assertEqual(EN.count_text("noun.project", 0), "0 projects")
        self.assertEqual([plural_category("ar", n) for n in (0, 1, 2, 3, 10, 11, 99, 100, 102)],
                         ["zero", "one", "two", "few", "few", "many", "many", "other", "other"])
        self.assertEqual(AR.count("noun.project", 2), '<data value="2">مشروعان</data>')         # the value stays machine-readable
        for key, entry in catalog().items():                                                     # every Arabic plural covers every form
            if isinstance(entry["ar"], dict):
                self.assertTrue(set(i18n.PLURAL_FORMS["ar"]) <= set(entry["ar"]), key)

    # 36, 37, 38 — Arabic never claims more than the data supports
    def test_36_benchmarks_are_never_targets(self):
        texts = [self.page(name) for name, locale in site_layout.html_files(EDITORS).items() if locale == "ar"]
        texts.append(json.dumps([entry["ar"] for entry in catalog().values()], ensure_ascii=False))   # every Arabic string
        for text in texts:
            for phrase in ("الوقت المطلوب", "المعدل المطلوب", "الهدف", "SLA"):
                self.assertNotIn(phrase, text)
            for match in re.finditer("هدف", text):                                               # only ever negated: "وليس هدفًا"
                self.assertRegex(text[max(0, match.start() - 6):match.start()], "ليست? ")

    def test_37_revision_wording_never_implies_fault(self):
        core = "للسياق فقط. وجود تعديلات من العميل لا يعني أن المونتير أخطأ، ولا يؤثر على أي من مؤشرات الأداء."
        self.assertIn(core, self.page("ar/dashboard.html"))
        self.assertIn(core, self.page(site_layout.profile_html("ar", "editor-label-6")))
        everything = json.dumps(catalog(), ensure_ascii=False) + "".join(self.page(n) for n in site_layout.html_files(EDITORS))
        for phrase in ("أخطاء", "بسبب المونتير", "خطأ المونتير", "Editor mistake", "caused by the Editor"):
            self.assertNotIn(phrase, everything)

    def test_38_missing_data_is_never_a_negative_judgement(self):
        ar = self.page("ar/dashboard.html")
        self.assertIn("لا توجد مؤشرات مدعومة بالبيانات حتى الآن", ar)
        self.assertEqual(catalog()["quality.empty_detail"]["ar"],
                         "هذا لا يُعد تقييمًا لجودة العمل؛ بل يعني فقط أنه لم تتم إضافة أي Performance Issues لهذا المونتير على Monday.")
        for phrase in ("لا توجد نقاط إيجابية", "ضعيف", "سيئ", "بطيء", "المحرر", "الإثباتات"):
            self.assertNotIn(phrase, json.dumps(catalog(), ensure_ascii=False) + ar)
        self.assertIn("أسرع بنسبة", ar)                                                         # a comparison, never "المونتير بطيء"

    def test_profile_notes_use_the_profile_text_in_english(self):
        entries = catalog()
        profile = json.loads(self.page(site_layout.profile_json("editor-label-6")))
        self.assertEqual((entries["note.overall"]["en"], entries["note.positive"]["en"], entries["note.revisions"]["en"]),
                         (OVERALL_NOTE, POSITIVE_NOTE, REVISION_NOTE))
        self.assertEqual(entries["note.workload"]["en"], profile["current_workload"]["note"])
        self.assertEqual(entries["note.trend"]["en"], profile["trend"]["note"])
        self.assertEqual(entries["note.not_attributed"]["en"], profile["coverage"]["not_attributed_note"])

    def test_translation_review_artifact_is_current(self):
        self.assertEqual((ROOT / "docs" / "i18n" / "ARABIC-TRANSLATION-REVIEW.md").read_text(encoding="utf-8"), i18n.review_markdown())
        review = i18n.review_markdown()
        for status in i18n.REVIEW_STATUSES:
            self.assertIn(status, review)
        self.assertNotIn("| Will |", review)                                                     # no raw Monday values

    def test_accessibility_basics_in_both_languages(self):
        for locale in i18n.LOCALES:
            html = self.page(site_layout.dashboard_html(locale))
            page = html.split('<script type="application/json"')[0]                          # the embedded reports are separate documents
            self.assertEqual(len(re.findall(r"<h1[ >]", page)), 2 + len(EDITORS))              # one per view: home, each profile, system
            self.assertIn('<nav class="nav" aria-label="', html)
            self.assertIn('role="dialog" aria-modal="true"', html)
            self.assertIn('<th scope=col>', html)
        self.assertIn('aria-label="إغلاق"', self.page("ar/dashboard.html"))
        self.assertIn('aria-label="القائمة الرئيسية"', self.page("ar/dashboard.html"))


class BilingualBuildAndPublishTests(unittest.TestCase):
    """Task 4 staging, Task 5 publication and rollback treat both languages as one build."""

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-i18n-sync-"))
        self.env = {"MONDAY_API_TOKEN": TOKEN, "ATLAS_DATA_DIR": str(self.data), "ATLAS_HISTORY_START": "2026-08-15T00:00:00Z"}
        self.days = 0

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    def stage(self, **patches):
        self.days += 1
        return sync.run_once(self.env, transport=FakeMonday(logs(), items()), clock=Clock(start=T0 + timedelta(days=self.days)),
                             monotonic=Monotonic(), sleep=lambda s: None)

    def test_22_23_24_staged_builds_need_both_languages(self):
        real = sync.build_dashboard_files

        def without_arabic(result, contract, site, *args, **kwargs):
            document = real(result, contract, site, *args, **kwargs)
            shutil.rmtree(site / "ar")
            return document

        with mock.patch.object(sync, "build_dashboard_files", without_arabic):
            result = self.stage()
        self.assertEqual((result.status, result.failing_stage, result.error_category), ("failed", "validation", "build_validation"))
        real_render = profile_cli.render_dashboard_html

        def arabic_breaks(doc, pages, url=None, loc=EN, **kwargs):
            if loc.code == "ar":
                raise TranslationError("unknown translation key")
            return real_render(doc, pages, url, loc, **kwargs)

        with mock.patch.object(profile_cli, "render_dashboard_html", arabic_breaks):
            result = self.stage()
        self.assertEqual((result.status, result.failing_stage), ("failed", "dashboard"))
        self.assertFalse((Path(result.staged_build_dir) / "COMPLETE.json").exists())

    def test_wrong_direction_fails_validation_and_publication(self):
        real = sync.build_dashboard_files

        def mirrored(result, contract, site, *args, **kwargs):
            document = real(result, contract, site, *args, **kwargs)
            page = site / "ar" / "dashboard.html"
            page.write_text(page.read_text(encoding="utf-8").replace('dir="rtl"', 'dir="ltr"', 1), encoding="utf-8")
            return document

        with mock.patch.object(sync, "build_dashboard_files", mirrored):
            result = self.stage()
        self.assertEqual((result.status, result.error_category), ("failed", "build_validation"))

    def test_25_26_28_publish_and_rollback_switch_both_languages_together(self):
        first, second = self.stage(), self.stage()
        self.assertEqual((first.status, second.status), ("success", "success"))
        pointer = self.data / "published" / "current"
        self.assertEqual(pub.publish(first.attempt_id, self.env).status, pub.PUBLISHED)
        self.assertEqual(pub.publish(second.attempt_id, self.env).status, pub.PUBLISHED)
        for locale in i18n.LOCALES:                                                             # one pointer: both languages from one build
            self.assertEqual((pointer / locale / "dashboard.html").resolve().parents[1], (Path(second.staged_build_dir) / "site").resolve())
        self.assertEqual(pub.rollback(None, self.env).status, pub.PUBLISHED)
        for locale in i18n.LOCALES:
            self.assertEqual((pointer / locale / "dashboard.html").resolve().parents[1], (Path(first.staged_build_dir) / "site").resolve())
        (Path(second.staged_build_dir) / "site" / "ar" / "dashboard.html").write_text("<html>tampered</html>")
        rejected = pub.publish(second.attempt_id, self.env)                                     # a tampered Arabic page blocks the whole build
        self.assertEqual((rejected.status, rejected.failure_category), (pub.REJECTED, "build_tampered"))
        for path in [p for p in self.data.rglob("*") if p.is_file()]:
            self.assertNotIn(TOKEN.encode(), path.read_bytes(), path)


if __name__ == "__main__":
    unittest.main()
