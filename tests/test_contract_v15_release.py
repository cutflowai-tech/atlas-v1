"""Contract 1.5 release regressions: reconstructable evidence, Cairo history, bilingual rendering, canonical Editors and
publication identity (review findings RB-4..RB-8, AB-6, AB-7).

Reconstruction tests recompute every published value from the profile JSON's own evidence records only, never from Atlas
internals: that is what an auditor can do with a published profile.
"""

import copy
import json
import re
import tempfile
import unittest
from collections import Counter
from datetime import timedelta
from pathlib import Path
from statistics import median

import monday_factory as mf

from atlas_commander import cycles as c
from atlas_commander import site_layout
from atlas_commander.contracts import validate
from atlas_commander.dashboard import build_dashboard
from atlas_commander.i18n import catalog
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.profile import build_editor_profile
from atlas_commander.profile_cli import build_all
from atlas_commander.runtime import load_contract_version

NOW = "2026-09-29T12:00:00Z"          # current window 30 Aug - 28 Sep, comparison 31 Jul - 29 Aug (Cairo)
WILL, AHMED, SAMRA = (6, "Will"), (12, "Ahmed"), (8, "Samra")
SCHEMA = "editor-profile-v1.5.schema.json"


def project(item_id, editor, end, hours, late, labels=()):
    finish = c.parse_time(end)
    start = finish - timedelta(hours=hours)
    stamp = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    eta = finish + timedelta(hours=-1 if late else 1)
    logs = [mf.eta(f"{item_id}-eta", item_id, stamp(start - timedelta(hours=3)), eta.strftime("%Y-%m-%d"), eta.strftime("%H:%M:%S")),
            mf.editor(f"{item_id}-ed", item_id, stamp(start - timedelta(hours=2)), [editor[0]], [editor[1]]),
            mf.video_type(f"{item_id}-vt", item_id, stamp(start - timedelta(hours=1)), [4]),
            mf.status(f"{item_id}-s1", item_id, stamp(start), "Create File", "In Progress"),
            mf.status(f"{item_id}-s2", item_id, stamp(finish), "In Progress", "Ready For Approval")]
    for n, (column, label_id, name) in enumerate(labels):
        logs.append(mf.dropdown(f"{item_id}-l{n}", item_id, column, stamp(finish + timedelta(hours=2)), [label_id], [name]))
    return logs


BONUS = "dropdown_mm3tyvvc"


def dataset():
    logs = []
    # Current window (Cairo 30 Aug - 28 Sep): Will 3 projects (2 late), Ahmed 2 (0 late)
    logs += project("101", WILL, "2026-09-10T10:00:00Z", 10, True, [(mf.ISSUES, 2, "Poor Communication"), (BONUS, 4, "Client Praise")])
    logs += project("102", WILL, "2026-09-12T10:00:00Z", 12, True, [(mf.ISSUES, 1, "Late Delivery")])
    logs += project("103", WILL, "2026-09-14T10:00:00Z", 14, False, [(BONUS, 6, "High Workload")])
    logs += project("201", AHMED, "2026-09-11T10:00:00Z", 20, False)
    logs += project("202", AHMED, "2026-09-13T10:00:00Z", 22, False)
    # Comparison window (31 Jul - 29 Aug): Will 2 projects (0 late), Ahmed 1 (1 late)
    logs += project("111", WILL, "2026-08-10T10:00:00Z", 8, False, [(BONUS, 1, "1- Exceptional Quality")])
    logs += project("112", WILL, "2026-08-12T10:00:00Z", 9, False)
    logs += project("211", AHMED, "2026-08-11T10:00:00Z", 30, True)
    # Older history, outside both windows; 22:30Z on 30 June is 01:30 on 1 July in Cairo (D24 month boundary).
    logs += project("121", WILL, "2026-06-10T10:00:00Z", 11, True)
    logs += project("122", WILL, "2026-06-30T22:30:00Z", 11, False)
    return mf.payload(*logs)


class ContractV15ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.5.0")
        cls.result = reconstruct_cycles(dataset(), cls.contract, ingestion={"retrieved_at": NOW})
        cls.profile = build_editor_profile(cls.result, cls.contract, "editor-label-6", NOW)

    # ------------------------------------------------------------ RB-7: history is not the scoring window
    def test_monthly_history_spans_every_cairo_month_not_only_the_current_window(self):
        months = [row["month"] for row in self.profile["trend"]["deadline_by_month"]]
        self.assertEqual(months, ["2026-06", "2026-07", "2026-08", "2026-09"])
        self.assertEqual({row["month"]: row["evaluated"] for row in self.profile["trend"]["deadline_by_month"]},
                         {"2026-06": 1, "2026-07": 1, "2026-08": 2, "2026-09": 3}, "22:30Z on 30 June belongs to Cairo's July")
        self.assertEqual({row["month"] for row in self.profile["trend"]["speed_by_cohort_month"]}, set(months))
        self.assertEqual(self.profile["deadline"]["summary"]["evaluated"], 3, "the Deadline block itself stays window-scoped (D42)")
        self.assertIn("Africa/Cairo", self.profile["trend"]["note"])

    # ------------------------------------------------------------ RB-6: every value is recomputable from its evidence
    def assert_block(self, block):
        self.assertEqual(block["source"], "monday")
        for key in ("monday_board_id", "rule_version", "calculated_at", "calculation"):
            self.assertTrue(block[key], key)
        self.assertTrue(block["column_ids"])
        self.assertEqual(block["date_range"]["timezone"], "Africa/Cairo")
        for record in block["records"]:
            self.assertTrue(record["event_ids"] and record["source_timestamps"] and record["source_values"]["editor_id"], record)
        return block["records"]

    def test_quality_rates_are_recomputable_from_their_records(self):
        rates = self.profile["quality"]["rates"]
        records = self.assert_block(rates["evidence"])
        labels = [label for record in records for label in record["source_values"]["labels"]]
        scored = Counter(label["label_class"] for label in labels if label["scored_quality"])
        self.assertEqual(len(records), rates["eligible_completed_projects"])
        self.assertEqual((scored["Positive"], scored["Negative"]), (rates["positive_count"], rates["negative_count"]))
        self.assertEqual(round(scored["Negative"] / len(records), 4), rates["negative_rate"])
        self.assertEqual((rates["positive_count"], rates["negative_count"]), (1, 1), "Late Delivery and High Workload are visible but not scored")

    def test_recent_change_current_and_comparison_values_are_recomputable(self):
        changes = self.profile["trend"]["recent_change"]
        for measurement in ("positive_quality_rate", "negative_quality_rate"):
            change = changes[measurement]
            for window in ("current", "comparison"):
                records = self.assert_block(change["evidence"][window])
                label_class = "Positive" if measurement.startswith("positive") else "Negative"
                count = sum(label["scored_quality"] and label["label_class"] == label_class for r in records for label in r["source_values"]["labels"])
                self.assertEqual(change[f"{window}_sample"], len(records))
                self.assertEqual(change[window], round(count / len(records), 4) if records else None, (measurement, window))
        late = changes["late_rate"]
        for window, expected in (("current", 2 / 3), ("comparison", 0.0)):
            records = self.assert_block(late["evidence"][window])
            recomputed = sum(r["source_values"]["result"] == "late" for r in records) / len(records)
            self.assertEqual((late[window], late[f"{window}_sample"]), (round(recomputed, 4), len(records)))
            self.assertAlmostEqual(recomputed, expected)
        self.assertEqual(late["difference"], round(2 / 3 - 0.0, 4))
        self.assertEqual(late["direction"], "lower_is_better")
        for row in changes["speed_by_video_type"]:
            change = row["change"]
            for window in ("current", "comparison"):
                durations = [r["source_values"]["duration_seconds"] for r in self.assert_block(change["evidence"][window])]
                self.assertEqual(change[window], int(median(durations)) if durations else None)

    def test_speed_and_deadline_components_are_recomputable_leave_one_out(self):
        cohort = self.profile["speed"]["cohorts"][0]
        records = self.assert_block(cohort["evidence"])
        mine = [r["source_values"]["duration_seconds"] for r in records if r["source_values"]["editor_id"] == "editor-label-6"]
        peers = [r["source_values"]["duration_seconds"] for r in records if r["source_values"]["editor_id"] != "editor-label-6"]
        self.assertEqual((cohort["editor_median_seconds"], cohort["team_median_seconds"]), (int(median(mine)), int(median(peers))))
        self.assertEqual((cohort["editor_sample_size"], cohort["team_sample_size"], cohort["team_editor_count"]), (3, 2, 1))
        self.assertFalse(cohort["team_includes_subject_editor"])
        component = self.profile["deadline"]["component"]
        records = self.assert_block(component["evidence"])
        mine = [r for r in records if r["source_values"]["editor_id"] == "editor-label-6"]
        peers = [r for r in records if r["source_values"]["editor_id"] != "editor-label-6"]
        late = lambda rows: sum(r["source_values"]["result"] == "late" for r in rows) / len(rows)
        self.assertEqual((component["facts"]["absolute_late_rate"], component["facts"]["comparator_late_rate"]),
                         (round(late(mine), 4), round(late(peers), 4)))
        self.assertEqual(component["facts"]["late_rate_difference"], round(late(mine) - late(peers), 4))
        self.assertEqual((component["state"], component["reason"], component["rule"]["status"]), ("not_classifiable", "rule_not_approved", "rule_not_approved"))

    def test_schema_rejects_empty_or_incomplete_evidence(self):
        self.assertEqual(validate(self.profile, SCHEMA), [])
        mutations = {
            "empty event ids": lambda p: p["quality"]["rates"]["evidence"]["records"][0].update(event_ids=[]),
            "no calculation time": lambda p: p["deadline"]["component"]["evidence"].pop("calculated_at"),
            "no date range": lambda p: p["speed"]["component"]["evidence"].update(date_range=None),
            "unclassified without a reason": lambda p: p["quality"]["component"].update(reason=None),
            "classified with a reason": lambda p: p["deadline"]["component"].update(state="positive"),
            "comparison evidence missing": lambda p: p["trend"]["recent_change"]["late_rate"]["evidence"].pop("comparison"),
            "status without classification": lambda p: p["overall"].update(status="Good"),
            "invented rule approval": lambda p: p["overall"]["rule"].update(decision_id="D37"),
            "speed verdict under an unapproved rule": lambda p: p["speed"]["cohorts"][0].update(verdict="faster"),
            "overall classified under an unapproved lookup": lambda p: p["overall"].update(status="Strong", status_label="Strong", status_state="classified", reason=None),
            "component classified under an unapproved rule": lambda p: p["quality"]["component"].update(state="positive", reason=None),
            "trend label under an unapproved rule": lambda p: p["trend"]["recent_change"]["late_rate"].update(trend="Improving", trend_reason=None),
            "rate as text": lambda p: p["quality"]["rates"].update(positive_rate="0.5"),
            "extra overall evidence key": lambda p: p["overall"]["evidence"].update(extra=1),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                profile = copy.deepcopy(self.profile)
                mutate(profile)
                self.assertTrue(validate(profile, SCHEMA), f"schema accepted: {name}")

    def test_evidence_records_must_match_their_samples(self):
        from atlas_commander.profile import evidence_consistency_errors
        self.assertEqual(evidence_consistency_errors(self.profile), [])
        for name, mutate in {
            "empty speed records": lambda p: p["speed"]["cohorts"][0]["evidence"].update(records=[]),
            "missing quality record": lambda p: p["quality"]["rates"]["evidence"]["records"].pop(),
            "comparison sample overstated": lambda p: p["trend"]["recent_change"]["late_rate"].update(comparison_sample=99),
        }.items():
            with self.subTest(mutation=name):
                profile = copy.deepcopy(self.profile)
                mutate(profile)
                self.assertTrue(evidence_consistency_errors(profile), name)

    def test_project_rows_keep_their_own_results_outside_the_scoring_window(self):
        rows = {row["monday_item_id"]: row for row in self.profile["projects"]}
        self.assertEqual((rows["121"]["window"], rows["121"]["deadline_result"]), ("outside", "late"))
        self.assertEqual((rows["111"]["window"], rows["111"]["quality_labels"]), ("comparison", ["1- Exceptional Quality"]))
        items = {occurrence["evidence"]["monday_item_id"] for occurrence in self.profile["quality"]["occurrences"]}
        self.assertIn("111", items, "the timeline keeps labels from before the current window")

    def test_deadline_evidence_lists_the_editors_unclassifiable_window_projects(self):
        logs = [*project("301", WILL, "2026-09-15T10:00:00Z", 10, True), *project("302", AHMED, "2026-09-15T10:00:00Z", 10, False)]
        logs += [log for log in project("303", WILL, "2026-09-16T10:00:00Z", 10, True) if not log["id"].endswith("-eta")]   # no Requested ETA
        result = reconstruct_cycles(mf.payload(*logs), self.contract, ingestion={"retrieved_at": NOW})
        profile = build_editor_profile(result, self.contract, "editor-label-6", NOW)
        exclusions = profile["deadline"]["component"]["evidence"]["exclusions"]
        self.assertEqual([row["monday_item_id"] for row in exclusions], ["303"])
        self.assertTrue(exclusions[0]["reasons"])

    def test_timeline_groups_contract_1_5_events_by_cairo_month(self):
        from atlas_commander.dashboard import editor_summary
        events = {event["monday_item_id"]: event for event in editor_summary(self.profile)["events"] if event["kind"] == "delivery"}
        self.assertEqual((events["122"]["at"][:7], events["122"]["month"]), ("2026-06", "2026-07"))
        self.assertTrue(events["122"]["local_at"].endswith("+03:00"))

    def test_not_enough_data_and_rule_not_approved_are_distinct_reasons(self):
        overall = self.profile["overall"]
        self.assertEqual((overall["status"], overall["status_label"], overall["status_state"]),
                         (None, "Not enough approved logic to classify", "rule_not_approved"))
        self.assertEqual({row["component"]: row["reason"] for row in overall["why"]},
                         {"quality": "rule_not_approved", "speed": "rule_not_approved", "deadline": "rule_not_approved",
                          "overall_lookup": "rule_not_approved"})
        alone = build_editor_profile(reconstruct_cycles(mf.payload(*project("1", WILL, "2026-09-10T10:00:00Z", 10, True)), self.contract,
                                                        ingestion={"retrieved_at": NOW}), self.contract, "editor-label-6", NOW)
        self.assertEqual(alone["deadline"]["component"]["reason"], "no_other_editors_in_cohort", "no benchmark is a data reason, not the rule")
        self.assertEqual(alone["speed"]["cohorts"][0]["comparison_status"], "no_other_editors_in_cohort")

    def test_profile_reports_the_configured_policy_not_placeholders(self):
        self.assertEqual(self.profile["speed"]["component"]["rule"],
                         {"rule": "speed", "rule_version": "speed-component-v1.0", "status": "rule_not_approved", "decision_id": None,
                          "values": {"minimum_editor_sample_size": None, "minimum_comparator_sample_size": None, "minimum_comparator_editor_count": None,
                                     "faster_band": None, "slower_band": None}})
        self.assertEqual(self.profile["coverage"]["metrics"]["classification"]["overall_status"]["availability"], "rule_not_approved")
        self.assertNotIn("equal_to_team_median", json.dumps(self.profile), "contract 1.5 says similar (inclusive band), never equal")

    # ------------------------------------------------------------ RB-4 / RB-5: the layer is visible, identically in both languages
    def test_bilingual_pages_render_the_same_interpretation_layer(self):
        attributes = re.compile(r'data-(component|state|reason|verdict|measurement|overall-status|status-state|section)="([^"]*)"')
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            doc = build_all(self.result, self.contract, out, NOW)
            for summary in doc["editors"]:
                self.assertIn("interpretation", summary)
            for page in ("dashboard.html", "profiles/editor-label-6.html", "profiles/editor-label-12.html"):
                en, ar = (out / "en" / page).read_text(encoding="utf-8"), (out / "ar" / page).read_text(encoding="utf-8")
                self.assertIn('data-section="interpretation"', en)
                self.assertEqual(Counter(attributes.findall(en)), Counter(attributes.findall(ar)), page)
                self.assertEqual(Counter(re.findall(r'<data value="([^"]*)">', en)), Counter(re.findall(r'<data value="([^"]*)">', ar)), page)
            english = (out / "en" / "profiles" / "editor-label-6.html").read_text(encoding="utf-8")
            for text in ("Not enough approved logic to classify", "Why this status", "Recent Change", "Absolute late rate", "Positive quality rate",
                         "Median first-pass time", "Current window", "Evidence records"):
                self.assertIn(text, english)
            self.assertNotIn("UTC month", english)
            self.assertNotIn("—</b><span>Not evaluated yet", (out / "en" / "dashboard.html").read_text(encoding="utf-8"),
                             "the Overview card shows the real Overall Status, not the 1.4 placeholder")
        entries = catalog()
        keys = [key for key in entries if key.startswith("interp.")]
        self.assertGreater(len(keys), 60)
        self.assertEqual([key for key in keys if not (entries[key].get("en") and entries[key].get("ar"))], [])

    # ------------------------------------------------------------ AB-6: one row per canonical Editor
    def test_canonical_editors_are_listed_once(self):
        doc = build_dashboard([], NOW, mapped_editors=self.contract["editor_attribution"]["entries"], contract_version="1.5.0")
        rows = doc["editors_without_attributable_data"]
        ids = [row["editor_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), len({entry["editor_id"] for entry in self.contract["editor_attribution"]["entries"]}))
        ahmed = next(row for row in rows if row["editor_id"] == "editor-label-12")
        self.assertEqual((ahmed["display_name"], ahmed["monday_label"]), ("Ahmed", "12"))
        self.assertEqual({(label["source_label_id"], label["logged_name"]) for label in ahmed["monday_labels"]}, {("12", "Ahmed"), ("5", "Ahmed")})
        anas = next(row for row in rows if row["editor_id"] == "editor-label-5")
        self.assertEqual(anas["display_name"], "Anas", "label 5 is shown as its canonical owner only")
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            site = build_all(self.result, self.contract, out, NOW)
            profiled = {summary["display_name"] for summary in site["editors"]}
            for locale in ("en", "ar"):
                page = (out / locale / "dashboard.html").read_text(encoding="utf-8")
                for name in ("Mansour", "Michael", "Mario", "Anas"):
                    self.assertNotIn(name, profiled)
                    self.assertEqual(page.count(f">{name}<"), 1, f"{name} rendered more than once in {locale}")

    # ------------------------------------------------------------ RB-8: publication identity is enforced for 1.5, never for 1.4
    def test_publication_identity_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_all(self.result, self.contract, out, NOW)
            editors = ["editor-label-12", "editor-label-6"]
            files = lambda: {p.relative_to(out).as_posix(): p for p in out.rglob("*") if p.is_file()}
            problems = lambda: site_layout.publication_problems(files(), editors, "1.5.0", NOW)
            self.assertEqual(problems(), [])
            self.assertEqual(site_layout.publication_problems({}, editors, "1.4.0", NOW), [], "1.4 builds never need publication identity")
            original = {name: path.read_bytes() for name, path in files().items()}

            def mutated(name, change):
                path = out / name
                path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")
                try:
                    return problems()
                finally:
                    path.write_bytes(original[name])

            publication = json.loads(original["publication.json"])
            other = "release-" + "0" * 20
            cases = {
                "ar/index.html": lambda text: text.replace(publication["release_id"], other),
                "en/profiles/editor-label-6.html": lambda text: text.replace(publication["snapshot_id"], "another-snapshot"),
                "publication.json": lambda text: text.replace('"/ar": {', '"/ar": {"release_id": "' + other + '", "x": {', 1),
                "dashboard.json": lambda text: text.replace(publication["release_id"], other),
                "profiles/editor-label-12.json": lambda text: text.replace(publication["release_id"], other),
            }
            for name, change in cases.items():
                with self.subTest(file=name):
                    self.assertTrue(mutated(name, change), f"accepted a mismatched {name}")
            (out / "publication.json").unlink()
            self.assertEqual(problems(), ["publication.json is missing or invalid"])
            self.assertNotIn(site_layout.PUBLICATION_JSON, site_layout.required_files(editors, "1.4.0"))

    def test_production_sync_still_refuses_contract_1_5(self):
        from atlas_sync.config import ConfigError, load_sync_config
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ConfigError, "not allowed for production sync"):
            load_sync_config({"MONDAY_API_TOKEN": "x", "ATLAS_DATA_DIR": directory, "ATLAS_CONTRACT_VERSION": "1.5.0"})


if __name__ == "__main__":
    unittest.main()
