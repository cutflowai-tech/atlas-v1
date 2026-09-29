"""Intelligence V2 document, determinism, governance, regression and gated-publication tests (Tasks 56-58, 63, 65-68).

Integration data is the deterministic contract 1.5 showcase extract (``demo.showcase_extract``), run through the real
pipeline, profile builder and Intelligence V2 engine. No real names or IDs.
"""

import copy
import json
import random
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_ingest import FakeMonday, items
from test_sync_run import T0, TOKEN, Clock, Monotonic, logs

from atlas_commander.contracts import schema_errors
from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.investigation import __main__ as cli
from atlas_commander.investigation import site
from atlas_commander.investigation.ai_guard import FORBIDDEN
from atlas_commander.investigation.engine import SCHEMA, IntelligenceError, build_intelligence, consistency_errors
from atlas_commander.investigation.html import render_intelligence_html
from atlas_commander.profile import build_editor_profile, profiled_editors
from atlas_commander.profile_cli import reconstruct_extract
from atlas_commander.runtime import load_contract_version
from atlas_sync import run as sync
from atlas_sync.config import load_sync_config

CONTRACT = load_contract_version("1.5.0")


class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extract = showcase_extract()
        cls.result = reconstruct_extract(cls.extract, CONTRACT)
        cls.profiles = {row["editor_id"]: build_editor_profile(cls.result, CONTRACT, row["editor_id"], GENERATED_AT) for row in profiled_editors(cls.result)}
        cls.review = build_intelligence(cls.result, CONTRACT, GENERATED_AT, mode="review", profiles=cls.profiles)
        cls.approved = build_intelligence(cls.result, CONTRACT, GENERATED_AT, profiles=cls.profiles)
        ids = set()
        for log in cls.extract["activity"]["boards"][0]["activity_logs"]:
            ids.add(str(log["id"]))
        cls.monday_ids = ids

    def test_documents_satisfy_the_schema_and_consistency_rules(self):
        for document in (self.review, self.approved):
            self.assertEqual(schema_errors(document, SCHEMA), [])
            self.assertEqual(consistency_errors(document), [])

    def test_review_is_never_publishable_and_approved_only_uses_approved_parameters_only(self):
        self.assertFalse(self.review["publishable"])
        self.assertTrue(any(finding["parameter_status"] == "proposed_not_approved" for finding in self.review["findings"]))
        self.assertTrue(self.approved["publishable"])
        self.assertTrue(self.approved["findings"])
        self.assertTrue(all(finding["parameter_status"] == "approved" for finding in self.approved["findings"]))
        for finding in self.approved["findings"]:
            self.assertTrue(all(use["status"] == "approved" for use in finding["parameters"]), finding["finding_type"])

    def test_approved_only_records_every_unapproved_detector(self):
        blocked = {row["detector"] for row in self.approved["examined_without_finding"] if "rule_not_approved" in row["reasons"]}
        self.assertIn("bottleneck.pre_editor_runway", blocked)
        self.assertIn("change.editor", blocked)
        runs = {row["detector"]: row for row in self.approved["detectors"]}
        self.assertTrue(runs["change.editor"]["rule_not_approved"])

    def test_build_is_deterministic_including_shuffled_monday_logs(self):
        again = build_intelligence(self.result, CONTRACT, GENERATED_AT, mode="review", profiles=self.profiles)
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.review, sort_keys=True))
        shuffled = copy.deepcopy(self.extract)
        random.Random(11).shuffle(shuffled["activity"]["boards"][0]["activity_logs"])
        other = build_intelligence(reconstruct_extract(shuffled, CONTRACT), CONTRACT, GENERATED_AT, mode="review")
        self.assertEqual(json.dumps(other, sort_keys=True), json.dumps(self.review, sort_keys=True))

    def test_every_evidence_record_traces_to_monday_events(self):
        for finding in self.review["findings"]:
            for block in [*finding["supporting_evidence"], *finding["contradicting_evidence"], *finding["context_evidence"]]:
                self.assertEqual(block["source"], "monday")
                for record in block["records"]:
                    for event_id in record["event_ids"]:
                        self.assertTrue(event_id in self.monday_ids or event_id.startswith("item-snapshot:"),
                                        f"{finding['finding_type']}: {event_id} is not a Monday event")

    def test_findings_explain_confidence_limitations_and_formula(self):
        for finding in self.review["findings"]:
            self.assertTrue(finding["confidence"]["factors"] and finding["confidence"]["why"], finding["finding_type"])
            self.assertTrue(finding["limitations"] and finding["text"]["limitations"], finding["finding_type"])
            self.assertTrue(all(block["calculation"] for block in finding["supporting_evidence"]), finding["finding_type"])
            self.assertTrue(finding["text"]["investigation_question"].endswith("?"), finding["finding_type"])
            self.assertIn(finding["evidence_level"], ("fact", "metric", "pattern", "association", "interpretation", "hypothesis"))

    def test_rendered_language_never_blames_diagnoses_or_predicts(self):
        text = json.dumps([finding["text"] for finding in self.review["findings"]] + self.review["executive_brief"]).lower()
        text = text.replace("not a prediction that these projects will be late", "").replace("not proof of cause", "")
        for pattern in FORBIDDEN:
            self.assertIsNone(re.search(pattern, text), pattern)
        for pattern in (r"\bwill be late\b", r"\bproves?\b", r"\bdefinitely\b"):
            self.assertIsNone(re.search(pattern, text), pattern)

    def test_editor_findings_never_interpret_revisions(self):
        for finding in self.review["findings"]:
            if finding["scope"]["kind"] == "editor":
                self.assertFalse([s for s in finding["statements"] if s["level"] != "fact" and "revision" in s["code"]], finding["finding_type"])

    def test_sections_brief_and_graph_reference_existing_findings(self):
        ids = {finding["finding_id"] for finding in self.review["findings"]}
        self.assertTrue(set(self.review["sections"]["top_findings"]["finding_ids"]) <= ids)
        self.assertLessEqual(len(self.review["executive_brief"]), 5)
        for entry in self.review["executive_brief"]:
            for key in ("what_happened", "is_it_unusual", "where", "evidence", "why_it_matters", "next_step"):
                self.assertTrue(entry[key], key)
        for edge in self.review["investigation_graph"]["edges"]:
            self.assertIn(edge["from"], ids)
            self.assertIn(edge["to"], ids)

    def test_top_findings_limit_is_unapproved_so_approved_only_lists_every_finding(self):
        top = self.approved["sections"]["top_findings"]
        self.assertIsNone(top["limit"])
        self.assertEqual(len(top["finding_ids"]), len([f for f in self.approved["findings"] if not (f["cluster"] or {}).get("suppressed_in_sections")]))

    def test_ranks_are_a_permutation_and_importance_is_separate_from_confidence(self):
        ranks = [finding["importance"]["rank"] for finding in self.review["findings"]]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))
        for finding in self.review["findings"]:
            self.assertNotIn("confidence", finding["importance"])
            self.assertIn("evidence", finding["importance"]["basis"])

    def test_no_score_rank_of_people_or_hr_field_exists(self):
        keys = set()

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    keys.add(key)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(self.review)
        for forbidden in ("score", "editor_rank", "leaderboard", "salary", "promotion", "disciplinary"):
            self.assertNotIn(forbidden, keys)

    def test_building_intelligence_does_not_change_profiles(self):
        before = json.dumps(self.profiles, sort_keys=True)
        build_intelligence(self.result, CONTRACT, GENERATED_AT, mode="review", profiles=self.profiles)
        self.assertEqual(json.dumps(self.profiles, sort_keys=True), before)
        fresh = build_editor_profile(self.result, CONTRACT, next(iter(self.profiles)), GENERATED_AT)
        self.assertEqual(json.dumps(fresh, sort_keys=True), json.dumps(self.profiles[next(iter(self.profiles))], sort_keys=True))

    def test_contracts_without_editor_intelligence_are_refused(self):
        contract = load_contract_version("1.4.0")
        with self.assertRaises(IntelligenceError):
            build_intelligence(reconstruct_extract(self.extract, contract), contract, GENERATED_AT)

    def test_zero_findings_is_a_valid_document(self):
        empty = {"retrieved_at": GENERATED_AT, "board_id": "5091110326", "ingestion": {"retrieved_at": GENERATED_AT},
                 "activity": {"boards": [{"activity_logs": []}]}, "items": {"items": []}}
        document = build_intelligence(reconstruct_extract(empty, CONTRACT), CONTRACT, GENERATED_AT, mode="review")
        self.assertEqual((document["findings"], document["executive_brief"]), ([], []))
        self.assertEqual(schema_errors(document, SCHEMA), [])

    def test_review_page_renders_every_finding_without_script_or_network(self):
        page = render_intelligence_html(self.review, "https://example.invalid/items/{item_id}")
        self.assertIn("Review only — not publishable", page)
        for finding in self.review["findings"]:
            self.assertIn(f'id="{finding["finding_id"]}"', page)
        self.assertNotIn("<script", page)
        self.assertIsNone(re.search(r'(src|href)="https?://(?!example\.invalid)', page))
        self.assertNotIn("Review only", render_intelligence_html(self.approved))

    def test_cli_writes_json_and_html(self):
        out = Path(tempfile.mkdtemp(prefix="atlas-v2-cli-"))
        extract = out / "extract.json"
        extract.write_text(json.dumps(self.extract))
        with mock.patch("sys.stdout"):
            self.assertEqual(cli.main([str(extract), str(out / "site"), "--generated-at", GENERATED_AT]), 0)
        document = json.loads((out / "site" / "intelligence-v2.json").read_text())
        self.assertEqual((document["mode"], document["publishable"]), ("approved_only", True))
        self.assertTrue((out / "site" / "intelligence-v2.html").read_text().startswith("<!doctype html>"))


class SiteArtifactTests(unittest.TestCase):
    """Feature gate, optional artifact and rollback safety (Tasks 66-68)."""

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="atlas-v2-sync-"))
        self.env = {"MONDAY_API_TOKEN": TOKEN, "ATLAS_DATA_DIR": str(self.data), "ATLAS_HISTORY_START": "2026-08-15T00:00:00Z",
                    "ATLAS_CONTRACT_VERSION": "1.5.0"}

    def attempt(self):
        return sync.run_once(self.env, transport=FakeMonday(logs(), items()), clock=Clock(), monotonic=Monotonic(), sleep=lambda seconds: None)

    def test_gate_off_by_default_builds_no_artifact(self):
        self.assertFalse(site.enabled())
        result = self.attempt()
        self.assertEqual(result.status, "success", result.as_dict())
        self.assertFalse((Path(result.staged_build_dir) / "site" / site.INTELLIGENCE_JSON).exists())

    def test_gate_on_builds_a_valid_approved_only_artifact(self):
        with mock.patch.object(site, "enabled", return_value=True):
            result = self.attempt()
        self.assertEqual(result.status, "success", result.as_dict())
        path = Path(result.staged_build_dir) / "site" / site.INTELLIGENCE_JSON
        document = json.loads(path.read_text())
        self.assertEqual((document["mode"], document["publishable"]), ("approved_only", True))
        metadata = json.loads((Path(result.staged_build_dir) / "build.json").read_text())
        self.assertIn(site.INTELLIGENCE_JSON, metadata["artifacts"]["files"])

    def test_review_or_foreign_artifact_is_rejected(self):
        with mock.patch.object(site, "enabled", return_value=True):
            result = self.attempt()
        build_site = Path(result.staged_build_dir) / "site"
        document = json.loads((build_site / site.INTELLIGENCE_JSON).read_text())
        extract = json.loads((Path(result.raw_run_dir) / "extract.json").read_text())
        contract = load_sync_config(self.env, now=T0).contract()
        review = {**document, "mode": "review", "publishable": False}
        (build_site / site.INTELLIGENCE_JSON).write_text(json.dumps(review))
        self.assertTrue(any("review mode" in problem for problem in site.site_problems(build_site / site.INTELLIGENCE_JSON, "1.5.0", extract["retrieved_at"])))
        (build_site / site.INTELLIGENCE_JSON).write_text(json.dumps(document))
        self.assertTrue(site.site_problems(build_site / site.INTELLIGENCE_JSON, "1.5.0", "2020-01-01T00:00:00Z"))
        self.assertEqual(site.site_problems(build_site / site.INTELLIGENCE_JSON, "1.5.0", extract["retrieved_at"]), [])
        self.assertTrue(site.site_problems(build_site / site.INTELLIGENCE_JSON, "1.4.0", extract["retrieved_at"]))
        (build_site / site.INTELLIGENCE_JSON).write_text("not json")
        with self.assertRaises(sync.BuildValidationError):
            sync.validate_site(build_site, sync.reconstruct_extract(extract, contract), contract, extract,
                               json.loads((Path(result.raw_run_dir) / "manifest.json").read_text()), TOKEN.encode())

    def test_optional_artifact_is_unexpected_under_contract_1_4(self):
        from atlas_commander import site_layout
        self.assertEqual(site_layout.optional_files("1.4.0"), [])
        self.assertEqual(site_layout.optional_files("1.5.0"), [site.INTELLIGENCE_JSON])
        self.assertNotIn(site.INTELLIGENCE_JSON, site_layout.required_files(["editor-label-6"], "1.5.0"))


if __name__ == "__main__":
    unittest.main()
