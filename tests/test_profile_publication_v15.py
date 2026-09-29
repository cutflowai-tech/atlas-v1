"""Contract 1.5 P0 profile semantics and publication parity regressions."""

from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import monday_factory as mf
from test_profile import NOW, dataset

from atlas_commander.contracts import validate
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.profile import ACTIVE_WORK_STATUSES, AWAITING_APPROVAL_STATUS, NON_ACTIVE_STATUSES, build_editor_profile
from atlas_commander.profile_cli import build_all
from atlas_commander.runtime import load_contract_version


def _current(item_id: str, status: str) -> dict:
    return {
        "id": item_id,
        "board": {"id": mf.BOARD},
        "column_values": [
            {"id": mf.EDITOR, "type": "dropdown", "value": json.dumps({"ids": [6]}), "text": "Will"},
            {"id": mf.STATUS, "type": "status", "value": json.dumps({"index": mf.STATUS_INDEX.get(status, 0)}), "text": status},
        ],
    }


class ProfilePublicationV15Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = copy.deepcopy(load_contract_version("1.4.0"))
        cls.contract["contract_version"] = "1.5.0"
        activity, items = dataset()
        activity["boards"][0]["activity_logs"].append(
            mf.status("internal-r1", "5", "2026-09-05T01:00:00Z", "Ready For Approval", "Internal Revisions")
        )
        next_id = 40
        for status in (*ACTIVE_WORK_STATUSES, AWAITING_APPROVAL_STATUS, *NON_ACTIVE_STATUSES, "Unknown Future State"):
            items["items"].append(_current(str(next_id), status))
            next_id += 1
        cls.result = reconstruct_cycles(activity, cls.contract, items_payload=items, ingestion={"retrieved_at": NOW})
        cls.profile = build_editor_profile(cls.result, cls.contract, "editor-label-6", NOW)

    def test_active_work_is_exact_and_awaiting_approval_is_separate(self):
        workload = self.profile["current_workload"]
        active = workload["active_work"]
        self.assertEqual(set(active["by_status"]), set(ACTIVE_WORK_STATUSES))
        self.assertEqual(active["count"], sum(len(items) for items in active["by_status"].values()))
        self.assertEqual(len(active["evidence_refs"]), active["count"])
        self.assertNotIn(AWAITING_APPROVAL_STATUS, active["by_status"])
        self.assertEqual(workload["awaiting_approval"]["status"], AWAITING_APPROVAL_STATUS)
        self.assertEqual(workload["awaiting_approval"]["count"], 1)
        self.assertEqual(len(workload["awaiting_approval"]["evidence_refs"]), 1)
        excluded = workload["excluded_from_active"]["by_status"]
        self.assertTrue(set(NON_ACTIVE_STATUSES).issubset(excluded))
        self.assertIn("Unknown Future State", excluded)
        self.assertEqual(workload["capacity_classification"]["availability"], "rule_not_approved")

    def test_client_and_internal_revisions_are_separate_non_scoring_evidence(self):
        revisions = self.profile["revisions"]
        self.assertGreaterEqual(revisions["client"]["events"], 1)
        self.assertEqual(revisions["internal"]["events"], 1)
        self.assertEqual(revisions["client"]["evidence_event_ids"], ["r2"])
        self.assertEqual(revisions["internal"]["evidence_event_ids"], ["internal-r1"])
        self.assertFalse(revisions["client"]["affects_scoring"])
        self.assertFalse(revisions["internal"]["affects_scoring"])
        self.assertTrue(revisions["context_only"])

    def test_profile_has_metric_coverage_and_explicit_unavailable_states(self):
        self.assertEqual(validate(self.profile, "editor-profile-v1.5.schema.json"), [])
        coverage = self.profile["coverage"]["metrics"]
        for metric in ("speed", "deadline"):
            row = coverage[metric]
            self.assertEqual(row["eligible_records"], row["included_records"] + row["excluded_records"])
            self.assertIn("coverage_ratio", row)
            self.assertIn("exclusion_reasons", row)
        self.assertEqual(coverage["quality"]["availability"], "unavailable")
        self.assertEqual(coverage["classification"]["overall_status"]["availability"], "rule_not_approved")

    def test_locales_share_metrics_classifications_and_one_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            dashboard = build_all(self.result, self.contract, out, NOW)
            publication = json.loads((out / "publication.json").read_text())
            route_states = {(row["release_id"], row["snapshot_id"]) for row in publication["routes"].values()}
            self.assertEqual(route_states, {(publication["release_id"], publication["snapshot_id"])})
            self.assertEqual(dashboard["publication"], publication)

            pages = [(out / name).read_text() for name in ("index.html", "en/index.html", "ar/index.html", "en/dashboard.html", "ar/dashboard.html")]
            for page in pages:
                self.assertIn(f'<meta name="atlas-release-id" content="{publication["release_id"]}">', page)
                self.assertIn(f'<meta name="atlas-snapshot-id" content="{publication["snapshot_id"]}">', page)

            en = (out / "en" / "profiles" / "editor-label-6.html").read_text()
            ar = (out / "ar" / "profiles" / "editor-label-6.html").read_text()
            classifications = lambda html: Counter(re.findall(r'data-classification="([^"]+)"', html))
            self.assertEqual(classifications(en), classifications(ar))
            values = lambda html: Counter(re.findall(r'<data value="([^"]*)">', html))
            self.assertEqual(values(en), values(ar))


if __name__ == "__main__":
    unittest.main()
