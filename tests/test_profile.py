"""Editor Profile (editor-profile 1.1.0) and its HTML view, through the public pipeline path."""

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import monday_factory as mf

from atlas_commander import cycles as c
from atlas_commander.contracts import validate
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.profile import ProfileError, build_editor_profile, profiled_editors
from atlas_commander.profile_cli import main as profile_cli
from atlas_commander.profile_html import render_profile_html
from atlas_commander.runtime import load_contract_version

NOW = "2026-09-28T00:00:00Z"
WILL, AHMED, MARIO = 6, 12, 4


def project(item_id, editor=WILL, video=(4,), hours=10.0, eta=None, extra=()):
    end = c.parse_time("2026-09-01T10:00:00Z") + timedelta(hours=hours)
    logs = [mf.editor(f"{item_id}-ed", item_id, "2026-09-01T09:00:00Z", [editor]),
            mf.video_type(f"{item_id}-vt", item_id, "2026-09-01T09:00:01Z", list(video)),
            mf.status(f"{item_id}-s1", item_id, "2026-09-01T10:00:00Z", "Create File", "In Progress"),
            mf.status(f"{item_id}-s2", item_id, end.strftime("%Y-%m-%dT%H:%M:%SZ"), "In Progress", "Ready For Approval")]
    if eta:
        logs.append(mf.eta(f"{item_id}-eta", item_id, "2026-09-01T08:00:00Z", eta[0], eta[1]))
    return logs + list(extra)


def issue(log_id, item, ids, names):
    return mf.dropdown(log_id, item, mf.ISSUES, "2026-09-03T00:00:00Z", ids, names)


def dataset():
    logs = []
    for n, hours in enumerate((8, 9, 10, 11, 12)):
        logs += project(f"{n + 1}", hours=hours, eta=("2026-09-01", "20:00:00"))           # Will, Class A, early/late mix
    for n, hours in enumerate((18, 19, 20, 21, 22)):
        logs += project(f"{n + 11}", editor=AHMED, hours=hours)                             # Ahmed, Class A
    logs += project("21", video=(5,), hours=30, eta=("2026-09-02", None))                   # Will, Class B, date-only ETA
    logs += project("22", editor=MARIO, hours=5)                                            # unverified Editor
    logs += [issue("q1", "1", [1], ["Late Delivery"]), issue("q2", "2", [1, 2], ["Late Delivery", "Poor Communication"]),
             mf.dropdown("b1", "3", "dropdown_mm3tyvvc", "2026-09-03T00:00:00Z", [1], ["1- Exceptional Quality"]),
             mf.status("r1", "4", "2026-09-04T00:00:00Z", "Ready For Approval", "Sent"),
             mf.status("r2", "4", "2026-09-05T00:00:00Z", "Sent", "Revisions")]
    current = lambda item, editor, name, status: {"id": item, "board": {"id": mf.BOARD}, "column_values": [
        {"id": mf.EDITOR, "type": "dropdown", "value": json.dumps({"ids": [editor]}), "text": name},
        {"id": mf.STATUS, "type": "status", "value": json.dumps({"index": 9}), "text": status}]}
    items = {"items": [{"id": "3", "board": {"id": mf.BOARD}, "column_values": [{"id": "dropdown_mm3tyvvc", "type": "dropdown", "value": json.dumps({"ids": [1]}), "text": ""}]},
                       current("30", WILL, "Will", "In Progress"), current("31", WILL, "Will", "Revisions"), current("32", WILL, "Anas", "In Progress"),
                       current("33", AHMED, "Ahmed", "In Progress")]}
    return mf.payload(*logs), items


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.3.0")
        activity, items = dataset()
        cls.activity, cls.items = activity, items
        cls.result = reconstruct_cycles(activity, cls.contract, items_payload=items, ingestion={"retrieved_at": NOW})
        cls.profile = build_editor_profile(cls.result, cls.contract, "editor-label-6", NOW)

    def test_profile_is_contract_valid_and_has_no_score(self):
        self.assertEqual(validate(self.profile, "editor-profile-v1.2.schema.json"), [])
        self.assertEqual((self.profile["overall"]["status"], self.profile["overall"]["rule_version"]), (None, None))
        self.assertNotIn("score", json.dumps(self.profile).lower().replace("scoring", ""))
        self.assertEqual((self.profile["editor"]["display_name"], self.profile["executable_contract_version"]), ("Will", "1.3.0"))

    def test_speed_section(self):
        cohorts = {cohort["cohort_key"]: cohort for cohort in self.profile["speed"]["cohorts"]}
        class_a = cohorts["4"]
        self.assertEqual((class_a["editor_sample_size"], class_a["team_sample_size"], class_a["conclusion"]), (5, 10, "faster_than_team_median"))
        self.assertEqual((class_a["editor_median_seconds"], class_a["team_median_seconds"], class_a["editor_vs_team_median_pct"]), (36000, 54000, -33.3))
        self.assertEqual((cohorts["5"]["editor_sample_size"], cohorts["5"]["conclusion"]), (1, "not_comparable"))
        self.assertEqual(self.profile["speed"]["benchmark_statistic"], "median")

    def test_deadline_section_separates_unclassifiable_eta(self):
        summary = self.profile["deadline"]["summary"]
        # ETA 20:00; Ready at 18:00..22:00 -> 2 early, 1 exactly on time, 2 late.
        self.assertEqual((summary["early"], summary["on_time"], summary["late"], summary["evaluated"]), (2, 1, 2, 5))
        self.assertEqual(summary["not_classifiable_insufficient_eta_precision"], 1)
        for metric in self.profile["deadline"]["results"]:
            self.assertEqual(validate(metric, "deadline-metric-v1.1.schema.json"), [])

    def test_quality_section_and_for_bonus_context(self):
        quality = self.profile["quality"]
        self.assertEqual((quality["negative"]["total_occurrences"], quality["negative"]["projects_with_issues"]), (3, 2))
        self.assertEqual((quality["positive"]["count"], quality["positive"]["source"]), (0, None))
        self.assertEqual((quality["for_bonus_context"]["projects"], quality["for_bonus_context"]["affects_quality"]), (["3"], False))

    def test_revisions_are_context_only(self):
        revisions = self.profile["revisions"]
        self.assertEqual((revisions["context_only"], revisions["projects_with_client_revisions"], revisions["client_revision_events"]), (True, 1, 1))
        self.assertIn("does not imply Editor fault", revisions["note"])

    def test_projects_carry_evidence_and_coverage_is_explicit(self):
        rows = {row["monday_item_id"]: row for row in self.profile["projects"]}
        self.assertEqual(set(rows), {"1", "2", "3", "4", "5", "21"})
        self.assertEqual((rows["1"]["evidence_event_ids"]["in_progress"], rows["1"]["evidence_event_ids"]["ready_for_approval"]), ("1-s1", "1-s2"))
        self.assertEqual(rows["21"]["requested_eta_issue"], "REQUESTED_ETA_DATE_ONLY")
        self.assertEqual(rows["1"]["quality_labels"], ["Late Delivery"])
        self.assertEqual(self.profile["coverage"]["states"]["deadline_not_classifiable_insufficient_eta_precision"], 1)

    def test_current_workload_is_descriptive_and_name_guarded(self):
        workload = self.profile["current_workload"]
        self.assertEqual(workload["by_current_status"], {"In Progress": ["30"], "Revisions": ["31"]})  # 32 carries another name on label 6
        self.assertEqual(workload["as_of"], NOW)

    def test_trend_is_per_cohort_and_month_with_sample_sizes(self):
        trend = self.profile["trend"]
        self.assertEqual({(row["cohort_key"], row["month"]): row["projects"] for row in trend["speed_by_cohort_month"]}, {("4", "2026-09"): 5, ("5", "2026-09"): 1})
        self.assertEqual(trend["deadline_by_month"], [{"month": "2026-09", "evaluated": 5, "early": 2, "on_time": 1, "late": 2}])

    def test_unverified_editor_has_no_profile(self):
        with self.assertRaises(ProfileError):
            build_editor_profile(self.result, self.contract, "editor-label-4", NOW)
        self.assertEqual([row["editor_id"] for row in profiled_editors(self.result)], ["editor-label-12", "editor-label-6"])

    def test_html_shows_profile_values_and_links_evidence(self):
        html = render_profile_html(self.profile, "https://example.invalid/items/{item_id}")
        for text in ("Will", "Speed by exact Video Type", "Faster than team median", "-33.3%", "Revisions (context only)",
                     "does not imply Editor fault", "ETA without a time", "https://example.invalid/items/1", "1-s2"):
            self.assertIn(text, html)
        self.assertNotIn("<script", html)

    def test_cli_builds_json_and_html_from_an_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            extract = Path(tmp) / "extract.json"
            extract.write_text(json.dumps({"retrieved_at": NOW, "activity": self.activity, "items": self.items}))
            self.assertEqual(profile_cli(["build", str(extract), "editor-label-6", tmp, "--generated-at", NOW]), 0)
            written = json.loads((Path(tmp) / "editor-label-6.json").read_text())
            self.assertEqual(written, self.profile)
            self.assertIn("<h1>Will</h1>", (Path(tmp) / "editor-label-6.html").read_text())


if __name__ == "__main__":
    unittest.main()
