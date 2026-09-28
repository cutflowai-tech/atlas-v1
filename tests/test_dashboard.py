"""CEO Dashboard: a presentation layer over Editor Profiles that adds no metric and no judgement."""

import copy
import json
import re
import tempfile
import unittest
from html import escape
from pathlib import Path

from test_profile import NOW, dataset

from atlas_commander.dashboard import build_dashboard, editor_summary, month_name
from atlas_commander.dashboard_html import _hero, editor_card, render_dashboard_html, workload_chips
from atlas_commander.management import EDITOR_SLOTS, PENDING_RULES, RULE_NOT_APPROVED
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.profile import build_editor_profile
from atlas_commander.profile_cli import attribution_coverage
from atlas_commander.profile_cli import main as profile_cli
from atlas_commander.profile_html import render_profile_html
from atlas_commander.runtime import load_contract_version


def text(html):
    """Visible text of an HTML fragment (tags removed)."""
    return re.sub(r"<[^>]+>", "", html)


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

    def html(self, doc=None, pages=None):
        doc = doc or self.doc
        return render_dashboard_html(doc, pages or {s["editor_id"]: render_profile_html(self.profiles[s["editor_id"]]) for s in doc["editors"]})

    def test_html_uses_calm_empty_states_and_no_implementation_wording(self):
        html = self.html()
        for text in ("Not evaluated yet", "No supported signal yet", "Management insights are being calibrated.", "View profile",
                     "Deadline data unavailable", "No issue labels recorded", "Pattern detection is not active yet.", "Trend not evaluated yet",
                     "Client revision context", "Suggested action", "Team Pulse", "Performance History", "Data &amp; System"):
            self.assertIn(text, html)
        self.assertNotIn("Rule not approved yet", html)
        for rule in PENDING_RULES.values():  # every unevaluated field keeps its reason, under Data & System
            self.assertIn(escape(rule["reason"]), html)

    def test_editor_card_headline_follows_the_fixed_display_order(self):
        will, ahmed = (next(s for s in self.doc["editors"] if s["editor_id"] == e) for e in ("editor-label-6", "editor-label-12"))
        self.assertEqual(_hero(will)[0], "speed")
        self.assertIn('<bdi dir="ltr">33.3%</bdi><small>faster</small>', _hero(will)[1])
        self.assertIn("Class A only", text(_hero(will)[1]))            # the comparison never reads as an overall speed claim
        self.assertIn("n = 5 Editor projects", text(_hero(will)[1]))   # the sample size stays visible
        self.assertIn('<bdi dir="ltr">33.3%</bdi><small>slower</small>', _hero(ahmed)[1])
        bare = copy.deepcopy(ahmed)
        bare["speed"]["compared_cohorts"] = []
        self.assertEqual(_hero(bare)[0], "projects")              # no comparison and no classified deadline
        bare["deadline"].update(evaluated=1, early=1, on_time=0, late=0)
        self.assertEqual(_hero(bare)[0], "deadline")

    def test_revisions_never_look_like_issues(self):
        card = editor_card(self.will)
        issues = card.split("Issue signals", 1)[1].split("Positive", 1)[0]
        self.assertNotIn("Revision", issues)
        self.assertIn('class="chip context"><b><data value="1">1</data></b> <bdi>Revisions</bdi>', card)   # neutral dashed chip, not a warning
        self.assertNotIn("late", workload_chips(self.will["current_workload"]).lower())

    def test_timeline_events_come_from_the_profile(self):
        profile = self.profiles["editor-label-6"]
        deliveries = [e for e in self.will["events"] if e["kind"] == "delivery"]
        labels = [e for e in self.will["events"] if e["kind"] == "issue_label"]
        self.assertEqual(len(deliveries), sum(1 for row in profile["projects"] if row["state"] == "completed" and row["ready_for_approval_at"]))
        self.assertEqual(len(labels), profile["quality"]["negative"]["total_occurrences"])
        self.assertEqual({e["deadline_result"] for e in deliveries}, {"early", "on_time", "late", None})

    def test_every_evidence_link_opens_an_existing_drawer(self):
        html = self.html()
        opened = set(re.findall(r'data-drawer="([^"]+)"', html))
        defined = re.findall(r'<template id="([^"]+)"', html)
        self.assertEqual(len(defined), len(set(defined)))
        self.assertEqual(opened - set(defined), set())
        self.assertIn('data-drawer="p-editor-label-6-1"', html)   # a project is reachable from the timeline and the evidence list

    def test_html_escapes_names_and_embeds_the_full_report_unchanged(self):
        profile = copy.deepcopy(self.profiles["editor-label-6"])
        profile["editor"]["display_name"] = "<b>Will</b>"
        doc = build_dashboard([profile], NOW)
        html = render_dashboard_html(doc, {"editor-label-6": render_profile_html(profile)})
        self.assertNotIn("<h3><b>Will</b></h3>", html)
        self.assertIn("&lt;b&gt;Will&lt;/b&gt;", html)
        blob = html.split('id="atlas-reports">', 1)[1].split("</script>", 1)[0]
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
            self.assertIn("Management insights are being calibrated.", (out / "en" / "dashboard.html").read_text())
            self.assertIn("مؤشرات الإدارة ما زالت قيد الإعداد.", (out / "ar" / "dashboard.html").read_text())


if __name__ == "__main__":
    unittest.main()
