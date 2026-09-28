"""CEO Dashboard: a presentation layer over Editor Profiles that adds no metric and no judgement."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from test_profile import NOW, dataset

from atlas_commander.dashboard import build_dashboard, editor_summary, month_name
from atlas_commander.dashboard_html import render_dashboard_html
from atlas_commander.management import EDITOR_SLOTS, PENDING_RULES, RULE_NOT_APPROVED
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.profile import build_editor_profile
from atlas_commander.profile_cli import attribution_coverage
from atlas_commander.profile_cli import main as profile_cli
from atlas_commander.profile_html import render_profile_html
from atlas_commander.runtime import load_contract_version


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.4.0")
        cls.activity, cls.items = dataset()
        cls.result = reconstruct_cycles(cls.activity, cls.contract, items_payload=cls.items, ingestion={"retrieved_at": NOW})
        cls.profiles = {e: build_editor_profile(cls.result, cls.contract, e, NOW) for e in ("editor-label-6", "editor-label-12")}
        cls.doc = build_dashboard(cls.profiles.values(), NOW, mapped_editors=cls.contract["editor_attribution"]["entries"],
                                  attribution_coverage=attribution_coverage(cls.result))
        cls.will = next(s for s in cls.doc["editors"] if s["editor_id"] == "editor-label-6")

    def test_every_figure_is_copied_from_the_profile(self):
        profile = self.profiles["editor-label-6"]
        summary = profile["deadline"]["summary"]
        for key in ("evaluated", "early", "on_time", "late", "early_rate", "late_rate", "median_delta_seconds"):
            self.assertEqual(self.will["deadline"][key], summary[key], key)
        self.assertEqual(self.will["quality"]["total_occurrences"], profile["quality"]["negative"]["total_occurrences"])
        self.assertEqual(self.will["sample"]["completed_projects"], profile["coverage"]["completed_projects"])
        self.assertEqual(self.will["current_workload"]["by_current_status"],
                         {status: len(items) for status, items in profile["current_workload"]["by_current_status"].items()})
        class_a = next(c for c in self.will["speed"]["cohorts"] if c["cohort_key"] == "4")
        source = next(c for c in profile["speed"]["cohorts"] if c["cohort_key"] == "4")
        self.assertEqual((class_a["editor_median_seconds"], class_a["team_median_seconds"], class_a["conclusion"]),
                         (source["editor_median_seconds"], source["team_median_seconds"], source["conclusion"]))
        for block in ("speed", "deadline", "quality", "revisions", "current_workload", "sample"):
            self.assertIn("source", self.will[block])

    def test_unapproved_management_rules_stay_empty(self):
        self.assertEqual(set(self.will["intelligence"]), set(EDITOR_SLOTS))
        for slot in [*self.will["intelligence"].values(), *self.doc["team"]["intelligence"].values()]:
            self.assertEqual((slot["value"], slot["state"]), (None, RULE_NOT_APPROVED))
            self.assertTrue(slot["reason"])
        self.assertNotIn("score", json.dumps(self.doc).lower().replace("overall_score", "").replace("overall score", "").replace("scoring", ""))

    def test_snapshot_lists_engine_facts_only(self):
        questions = {block["question"]: block for block in self.will["snapshot"]}
        self.assertEqual(len(questions), 5)
        well = questions["What is this Editor doing well?"]
        self.assertEqual(well["facts"], ["Faster than the team median in Class A (5 projects)."])
        self.assertEqual(well["judgement"]["value"], None)
        attention = questions["Is there anything that may need management attention?"]
        self.assertIn("2 × Late Delivery (Monday Performance Issues).", attention["facts"])
        self.assertIsNone(attention["judgement"]["value"])

    def test_revisions_are_context_only(self):
        self.assertTrue(self.will["revisions"]["context_only"])
        # Revision counts never become a warning, an attention fact or a strength (a current Monday status named "Revisions"
        # may still appear as workload context).
        judged = [block for block in self.will["snapshot"] if block["question"] != "Is there relevant workload context?"]
        self.assertNotIn("revision", json.dumps([self.will["warnings"], judged]).lower())

    def test_monthly_history_uses_month_names_most_recent_first(self):
        self.assertEqual(month_name("2026-03"), "March 2026")
        self.assertEqual([m["month_name"] for m in self.will["monthly"]], ["September 2026"])
        self.assertTrue(self.will["monthly"][0]["partial"])  # retrieved in September 2026
        self.assertEqual({c["cohort_key"]: c["labels"] for c in self.will["monthly"][0]["speed_by_cohort"]}, {"4": ["Class A"], "5": ["Class B"]})

    def test_data_confidence_warnings_restate_profile_facts(self):
        codes = {w["code"] for w in self.will["warnings"]}
        self.assertEqual(codes, {"DEADLINE_NOT_CLASSIFIABLE", "PARTIAL_MONTH"})
        small = copy.deepcopy(self.profiles["editor-label-12"])
        small["coverage"]["completed_projects"] = 2
        small["speed"]["cohorts"] = []
        self.assertTrue({"SMALL_SAMPLE", "NO_SPEED_COMPARISON"} <= {w["code"] for w in editor_summary(small)["warnings"]})

    def test_team_view_is_factual(self):
        team = self.doc["team"]
        late = next(row for row in team["issue_labels_by_editor"] if row["label"] == "Late Delivery")
        self.assertEqual(late["editors"], {"editor-label-6": 2})
        self.assertEqual(team["workload_by_editor"]["rows"]["editor-label-12"], {"In Progress": 1})
        missing = {e["display_name"] for e in self.doc["editors_without_attributable_data"]}
        self.assertNotIn("Will", missing)
        self.assertIn("Michael", missing)
        coverage = self.doc["attribution_coverage"]
        self.assertEqual(coverage["completed"], coverage["attributed"] + sum(coverage["not_attributed_by_reason"].values()))

    def test_profiles_from_different_snapshots_are_rejected(self):
        other = copy.deepcopy(self.profiles["editor-label-12"])
        other["source"]["retrieved_at"] = "2026-09-29T00:00:00Z"
        with self.assertRaises(ValueError):
            build_dashboard([self.profiles["editor-label-6"], other], NOW)

    def test_html_shows_empty_states_and_embeds_profiles_escaped(self):
        profile = copy.deepcopy(self.profiles["editor-label-6"])
        profile["editor"]["display_name"] = "<b>Will</b>"
        doc = build_dashboard([profile], NOW)
        html = render_dashboard_html(doc, {"editor-label-6": render_profile_html(profile)})
        self.assertNotIn("<b>Will</b></h3>", html)
        self.assertIn("&lt;b&gt;Will&lt;/b&gt;", html)
        for text in ("Rule not approved yet", "No signal available", "Open Editor profile", "September 2026", "context only",
                     *(rule["label"] for rule in PENDING_RULES.values())):
            self.assertIn(text, html)
        blob = html.split('id="atlas-profiles">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(blob)["editor-label-6"], render_profile_html(profile))

    def test_cli_builds_every_profile_unchanged_and_the_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            extract = Path(tmp) / "extract.json"
            extract.write_text(json.dumps({"retrieved_at": NOW, "activity": self.activity, "items": self.items}))
            out = Path(tmp) / "out"
            self.assertEqual(profile_cli(["dashboard", str(extract), str(out), "--generated-at", NOW]), 0)
            for editor_id, profile in self.profiles.items():
                self.assertEqual(json.loads((out / "profiles" / f"{editor_id}.json").read_text()), profile)
            doc = json.loads((out / "dashboard.json").read_text())
            self.assertEqual([s["editor_id"] for s in doc["editors"]], ["editor-label-6", "editor-label-12"])
            self.assertEqual(doc["editors"][0]["profile_ref"], "profiles/editor-label-6.json")
            self.assertIn("Editor team overview", (out / "dashboard.html").read_text())


if __name__ == "__main__":
    unittest.main()
