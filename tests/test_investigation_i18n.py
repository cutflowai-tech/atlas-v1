"""Intelligence V2 in English and Arabic: one structure, the same facts (brief §24).

The English (``narrative``) and Arabic (``narrative_ar``) renderers must have the same keys in every table, render every statement
code the engine can emit, and put exactly the same Monday values and numbers in each sentence. The corpus is every finding of the
showcase build plus every detector run over the synthetic detector fixtures, and it must reach every template code.
"""

import dataclasses
import re
import unittest
from collections import Counter

import investigation_factory as f
import test_investigation_d53 as d53
import test_investigation_detectors as det

from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.investigation import narrative, narrative_ar
from atlas_commander.investigation.catalog import DETECTORS
from atlas_commander.investigation.context import run_guarded
from atlas_commander.investigation.engine import build_intelligence
from atlas_commander.investigation.facts import ItemTimeline, StageVisit
from atlas_commander.profile_cli import reconstruct_extract
from atlas_commander.runtime import load_contract_version

CONTRACT = load_contract_version("1.5.0")
ISOLATED = re.compile("[\u2066\u2068](.*?)\u2069")
APPROVED_LATIN = ("Ready For Approval", "Requested ETA", "In Progress", "Video Type", "Monday", "Atlas")


def _fact_bases():
    A, B, C = det.A, det.B, det.C
    headline = det.ContradictionTests.bad_headline_rows(None)
    peers = det.PersonSystemTests.peers(None)
    risk_history = det.RiskTests.history(None)
    shared = det.PatternTests.shared
    open_items = [f.open_work("o1", eta_in_hours=-3), f.open_work("o2", started_hours_ago=2, eta_in_hours=3),
                  f.open_work("o3", started_hours_ago=1, eta_in_hours=5), f.open_work("o4", status="Ready For Approval", started_hours_ago=400),
                  f.open_work("o5", started_hours_ago=300, eta_in_hours=500)]
    hidden = [f.fact(f"h{i}", editor=A, start=f.days_before(3 + i), eta_hours=11,
                     labels=(f.label("Poor Communication", item=f"h{i}"),) if i < 6 else ()) for i in range(12)]
    labels = [f.fact(f"l{i}", editor=A, start=f.days_before(5 + i), eta_hours=11,
                     labels=(f.label("Late Delivery", scored=False, item=f"l{i}"),) if i < 6 else (f.label("Poor Communication", item=f"l{i}"),))
              for i in range(7)]
    quality = [f.fact(f"q{i}", editor=[A, B, C][i % 3], cohort="6", start=f.days_before(5 + i), eta_hours=11,
                      labels=(f.label("Poor Communication", item=f"q{i}"),)) for i in range(6)]
    no_team = ([det.proj(f"c{i}", A, late=i < 10, days=3 + i) for i in range(12)] + [det.proj(f"p{i}", A, late=i < 2, days=33 + i) for i in range(12)]
               + [det.proj(f"bc{i}", B, days=3 + i) for i in range(3)] + [det.proj(f"bp{i}", B, days=33 + i) for i in range(3)])
    speed = [f.fact(f"s{i}", editor=A, start=f.days_before(70 + i), hours=10) for i in range(6)] + [
        f.fact(f"t{i}", editor=A, start=f.days_before(3 + i), hours=20) for i in range(6)]
    team = ([det.proj(f"tc{i}", [A, B, C][i % 3], late=i < 11, days=3 + i) for i in range(12)]
            + [det.proj(f"tp{i}", [A, B, C][i % 3], late=i < 2, days=33 + i) for i in range(12)])
    bases = [
        (det.ConcentrationTests.fixture(None), ()), (det.runway_fixture(), ()), (det.runway_fixture(18, 20, 4, 16), open_items),
        (det.workload_rows(), ()), (det.workload_rows(late_high=True), ()), (shared(None), ()), (shared(None, elevated=(A,)), ()),
        (peers + [det.proj(f"a{i}", A, "8", late=i < 9, days=5 + i) for i in range(10)], ()),
        (peers + [det.proj(f"a{i}", A, "4", late=i < 9, days=5 + i) for i in range(10)], ()),
        (peers + [det.proj(f"a{i}", A, "8", late=i < 2, days=5 + i) for i in range(10)], ()),
        (headline, ()), (hidden, ()), (labels, ()), (quality, ()), (no_team, ()), (speed, ()), (team, ()), (risk_history, open_items),
        (d53.concentration_rows(10, 6, 40, 14), ()), (d53.breadth_rows(3), ()), (d53.team_rows(35, 20), ()),
        (d53.workload_history(), [f.open_work(f"w{i}", editor=A, started_hours_ago=1, eta_in_hours=48) for i in range(4)]),
    ]
    # Paths the showcase does not reach, each built to exercise one template family.
    below_material = peers + [det.proj(f"m8{i}", A, "8", late=True, days=5 + i) for i in range(9)] + [
        det.proj(f"m4{i}", A, "4", late=i < 2, days=5 + i) for i in range(7)]
    eta_passed = det.runway_fixture() + [f.fact(f"x{i}", editor=[A, B, C][i % 3], start=f.days_before(3 + i), hours=10, eta_hours=-2) for i in range(3)]
    headline_passed = headline + [f.fact("ax", editor=A, start=f.days_before(4), hours=10, eta_hours=-1)]
    rising = ([f.fact(f"rc{i}", editor=A, start=f.stamp(f.at(f.days_before(10)) + f.timedelta(hours=i)), hours=30, eta_hours=31,
                      labels=(f.label("Poor Communication", item=f"rc{i}"),) if i < 8 else ()) for i in range(12)]
              + [f.fact(f"rp{i}", editor=A, start=f.days_before(40 + 2 * i), hours=10, eta_hours=11,
                        labels=(f.label("Poor Communication", item=f"rp{i}"),) if i < 1 else ()) for i in range(12)]
              + [f.fact(f"rh{i}", editor=A, start=f.days_before(80 + 2 * i), hours=10, eta_hours=11) for i in range(12)])
    review = [f.fact(f"v{i}", editor=[A, B, C][i % 3], start=f.days_before(20 + i), hours=10, eta_hours=11, review_hours=2) for i in range(12)]
    waiting = [f.open_work("vw", status="Ready For Approval", started_hours_ago=400, eta_in_hours=10)]
    timed = [dataclasses.replace(f.fact(f"tm{i}", editor=[A, B, C][i % 3], start=f.days_before(5 + i), hours=10, eta_hours=11, review_hours=3,
                                        delivered_hours=8 if i % 2 else 2, labels=(f.label("Late Delivery", scored=False, item=f"tm{i}"),) if i % 4 == 1 else ()),
                                 created_at=f.stamp(f.at(f.days_before(5 + i)) - f.timedelta(hours=6))) for i in range(24)]
    data = ([f.fact(f"u{i}", editor=None, start=f.days_before(5 + i)) for i in range(3)]
            + [f.fact(f"e{i}", editor=A, start=f.days_before(5 + i), eta_hours=11, eta_observed_after_start=True) for i in range(3)])
    label_bands = []
    for block in range(12):
        for position in range(3):
            start = f.stamp(f.at(f.days_before(100 - block * 7)) + f.timedelta(hours=position))
            label_bands.append(f.fact(f"lb{block}-{position}", editor=A, start=start, hours=10, eta_hours=11,
                                      labels=(f.label("Poor Communication", item=f"lb{block}-{position}"),) if position == 2 else ()))
    busier = [f.fact(f"bs{i}", editor=A, start=f.days_before(70 + 3 * i), hours=10) for i in range(6)] + [
        f.fact(f"bc{i}", editor=A, start=f.stamp(f.at(f.days_before(5)) + f.timedelta(hours=i)), hours=20) for i in range(6)]
    bases += [(below_material, ()), (eta_passed, ()), (headline_passed, ()), (rising, ()), (review, waiting), (timed, ()), (data, ()),
              (label_bands, ()), (busier, ())]
    profiles = [{A: det.profile(A)}, {A: det.profile(A, "negative", "positive", 2)}, {A: det.profile(A, "neutral", "positive", 7, 10)},
                {A: det.profile(A, "positive", "neutral", 2)}]
    return bases, profiles


def corpus():
    """Every finding (as a document entry) the showcase build and the detector fixtures produce, in review mode."""
    findings = []
    result = reconstruct_extract(showcase_extract(), CONTRACT)
    for mode in ("review", "approved_only"):
        findings += build_intelligence(result, CONTRACT, GENERATED_AT, mode=mode)["findings"]
    bases, profiles = _fact_bases()
    for rows, open_items in bases:
        for profile_set in profiles:
            projects = rows.projects if hasattr(rows, "projects") else rows       # some fixtures already return a fact base
            facts = f.base(projects, open_items)
            if projects and projects[0].monday_item_id == "u0":                  # the data fixture also carries an unknown-status span
                facts = dataclasses.replace(facts, timelines={"u0": ItemTimeline("u0", (StageVisit("Downloading", f.days_before(6), f.days_before(5), "u0-a", "u0-b",
                                                                                                   "pre_editor", "unknown_or_cleared_status_within_visit"),), 0, 0, 0)})
            ctx = f.context(facts, "review", None, profile_set)
            for detector in DETECTORS:
                findings += [finding.to_dict() for finding in run_guarded(detector, ctx).findings]
    return findings


def texts(finding, lang):
    rendered = narrative.finding_text(narrative.view(finding), lang, marked=True)
    return {key: value for key, value in rendered.items() if isinstance(value, str)}


class TablesTests(unittest.TestCase):
    def test_every_table_has_the_same_keys_in_both_languages(self):
        for name in narrative.TABLES:
            self.assertEqual(set(getattr(narrative, name)), set(getattr(narrative_ar, name)), name)

    def test_arabic_is_marked_for_review(self):
        self.assertEqual(narrative_ar.REVIEW_STATUS, "Needs Arabic Review")


class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.findings = corpus()

    def test_the_corpus_reaches_every_template(self):
        used = Counter()
        for finding in self.findings:
            for statement in [*finding["statements"], finding["significance"], *finding["suggested_investigations"]]:
                used[statement["code"]] += 1
        self.assertEqual(sorted(set(narrative.T) - set(used)), [])
        self.assertEqual(sorted({finding["finding_type"] for finding in self.findings} - set(narrative.TITLES)), [])

    def test_both_languages_state_the_same_values(self):
        for finding in self.findings:
            en, ar = texts(finding, "en"), texts(finding, "ar")
            for key in en:
                self.assertEqual(Counter(ISOLATED.findall(en[key])), Counter(ISOLATED.findall(ar[key])),
                                 f"{finding['finding_type']}.{key}\nEN: {narrative.plain(en[key])}\nAR: {narrative.plain(ar[key])}")

    def test_arabic_has_no_english_outside_isolated_values(self):
        for finding in self.findings:
            for key, value in texts(finding, "ar").items():
                rest = ISOLATED.sub("", value)
                for allowed in APPROVED_LATIN:
                    rest = rest.replace(allowed, "")
                rest = re.sub(r"\bD\d+\b", "", rest)
                self.assertNotRegex(rest, "[A-Za-z]", f"{finding['finding_type']}.{key}: {narrative.plain(value)}")

    def test_the_stored_english_text_is_the_rendered_english_text(self):
        for finding in self.findings:
            if finding.get("text"):
                self.assertEqual(finding["text"], narrative.finding_text(narrative.view(finding), "en"), finding["finding_type"])

    def test_confidence_levels_are_weak_moderate_strong_in_words_never_a_percentage(self):
        for finding in self.findings:
            for lang, names in (("en", ("Weak", "Moderate", "Strong")), ("ar", ("محدودة", "متوسطة", "قوية"))):
                explanation = narrative.finding_text(narrative.view(finding), lang)["confidence_explanation"]
                self.assertTrue(explanation.startswith(names), explanation)
                self.assertNotRegex(explanation, r"\d+(\.\d+)?%")


if __name__ == "__main__":
    unittest.main()
