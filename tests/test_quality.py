"""Quality occurrences and revision context through the public pipeline (contract 1.2.0)."""

import json
import unittest

import monday_factory as mf

from atlas_commander.contracts import validate
from atlas_commander.pipeline import reconstruct_cycles, reconstruct_quality
from atlas_commander.quality import EDITOR_UNRESOLVED, NO_COMPLETED_CYCLE, UNMAPPED_QUALITY_LABEL, quality_summary, revision_context_summary
from atlas_commander.runtime import load_contract_version

NOW = "2026-09-28T00:00:00Z"
AHMED, UNMAPPED = 12, 4
ISSUE_NAMES = {1: "Late Delivery", 2: "Poor Communication", 3: "2- Quality Issue", 5: "3- Technical Issues", 99: "New Label"}


def issues(log_id, item, moment, ids, previous=(), names=None):
    chosen = lambda values: {"chosenValues": [{"id": v, "name": (names or ISSUE_NAMES).get(v, f"label-{v}")} for v in values]} if values else None
    log = mf.dropdown(log_id, item, mf.ISSUES, moment, list(ids), [(names or ISSUE_NAMES).get(v, f"label-{v}") for v in ids], previous=chosen(previous))
    if not ids:
        data = json.loads(log["data"])
        data["value"] = None
        log["data"] = json.dumps(data)
    return log


def project(item_id, editor=AHMED, end="2026-09-01T22:00:00Z", extra=()):
    logs = [mf.editor(f"{item_id}-ed", item_id, "2026-09-01T09:00:00Z", [editor]),
            mf.video_type(f"{item_id}-vt", item_id, "2026-09-01T09:00:01Z", [8]),
            mf.status(f"{item_id}-s1", item_id, "2026-09-01T10:00:00Z", "Create File", "In Progress")]
    if end:
        logs.append(mf.status(f"{item_id}-s2", item_id, end, "In Progress", "Ready For Approval"))
    return logs + list(extra)


class QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.2.0")

    def run_quality(self, *logs, items=None):
        result = reconstruct_cycles(mf.payload(*logs), self.contract, items_payload=items, ingestion={"retrieved_at": NOW})
        return result, reconstruct_quality(result, self.contract, NOW)

    def test_each_label_on_a_project_is_one_equal_weight_occurrence_with_evidence(self):
        _, quality = self.run_quality(*project("1", extra=[issues("q1", "1", "2026-09-02T00:00:00Z", [1]),
                                                           issues("q2", "1", "2026-09-02T01:00:00Z", [1, 2], previous=[1])]))
        self.assertEqual([(m["performance_label"], m["evidence"]["event_ids"]) for m in quality.occurrences],
                         [("Late Delivery", ["q1", "q2"]), ("Poor Communication", ["q2"])])
        for metric in quality.occurrences:
            self.assertEqual(validate(metric, "quality-metric.schema.json"), [])
            self.assertEqual((metric["editor_id"], metric["evidence"]["source_values"]["weight"]), ("editor-label-12", 1))
            self.assertEqual(metric["label_mapping_version"], "monday-performance-issues-v1.0")

    def test_removed_label_does_not_count(self):
        _, quality = self.run_quality(*project("1", extra=[issues("q1", "1", "2026-09-02T00:00:00Z", [1, 2]),
                                                           issues("q2", "1", "2026-09-03T00:00:00Z", [2], previous=[1, 2])]))
        self.assertEqual([m["performance_label"] for m in quality.occurrences], ["Poor Communication"])

    def test_current_item_value_is_authoritative(self):
        items = {"items": [{"id": "1", "board": {"id": mf.BOARD}, "column_values": [{"id": mf.ISSUES, "type": "dropdown", "value": json.dumps({"ids": [2]}), "text": ""}]}]}
        _, quality = self.run_quality(*project("1", extra=[issues("q1", "1", "2026-09-02T00:00:00Z", [1, 2])]), items=items)
        self.assertEqual([m["performance_label"] for m in quality.occurrences], ["Poor Communication"])
        self.assertIn(f"item-snapshot:1:{mf.ISSUES}@{NOW}", quality.occurrences[0]["evidence"]["event_ids"])

    def test_renamed_label_resolves_by_id_and_unknown_ids_are_quarantined(self):
        _, quality = self.run_quality(*project("1", extra=[issues("q1", "1", "2026-09-02T00:00:00Z", [3, 99], names={3: "Quality Issue", 99: "New Label"})]))
        self.assertEqual([m["performance_label"] for m in quality.occurrences], ["2- Quality Issue"])
        self.assertEqual([(q["label_id"], q["reason"]) for q in quality.quarantined], [("99", UNMAPPED_QUALITY_LABEL)])

    def test_unresolved_editor_or_no_completed_cycle_is_quarantined(self):
        _, quality = self.run_quality(*project("1", editor=UNMAPPED, extra=[issues("q1", "1", "2026-09-02T00:00:00Z", [1])]),
                                      *project("2", end=None, extra=[issues("q2", "2", "2026-09-02T00:00:00Z", [1])]))
        self.assertEqual(quality.occurrences, [])
        self.assertEqual(sorted((q["monday_item_id"], q["reason"]) for q in quality.quarantined), [("1", EDITOR_UNRESOLVED), ("2", NO_COMPLETED_CYCLE)])

    def test_summary_counts_are_equal_weight_and_traceable(self):
        result, quality = self.run_quality(*project("1", extra=[issues("q1", "1", "2026-09-02T00:00:00Z", [1, 2])]),
                                           *project("2", extra=[issues("q2", "2", "2026-09-02T00:00:00Z", [1])]), *project("3"))
        summary = quality_summary("editor-label-12", quality, result.cycles)
        self.assertEqual((summary["total_occurrences"], summary["projects_with_issues"], summary["completed_projects_attributed"]), (3, 2, 3))
        self.assertEqual(summary["by_label"][0], {"label": "Late Delivery", "occurrences": 2, "monday_item_ids": ["1", "2"]})

    def test_revisions_are_context_only(self):
        revision = [mf.status("r1", "1", "2026-09-03T00:00:00Z", "Ready For Approval", "Sent"),
                    mf.status("r2", "1", "2026-09-04T00:00:00Z", "Sent", "Revisions"),
                    mf.status("r3", "1", "2026-09-04T05:00:00Z", "Revisions", "Ready For Approval")]
        label = [issues("q1", "1", "2026-09-02T00:00:00Z", [1])]
        plain_result, plain = self.run_quality(*project("1", extra=label), *project("2"))
        revised_result, revised = self.run_quality(*project("1", extra=label + revision), *project("2"))
        self.assertEqual(quality_summary("editor-label-12", plain, plain_result.cycles)["total_occurrences"],
                         quality_summary("editor-label-12", revised, revised_result.cycles)["total_occurrences"])
        context = revision_context_summary("editor-label-12", revised_result.cycles)
        self.assertEqual((context["context_only"], context["projects_with_client_revisions"], context["client_revision_rate"]), (True, 1, 0.5))
        self.assertEqual(revised.occurrences[0]["revision_context"]["client_revision_events"], 1)

    def test_for_bonus_logs_never_create_quality_occurrences(self):
        bonus = mf.dropdown("b1", "1", "dropdown_mm3tyvvc", "2026-09-02T00:00:00Z", [1], ["1- Exceptional Quality"])
        _, quality = self.run_quality(*project("1", extra=[bonus]))
        self.assertEqual((quality.occurrences, quality.quarantined), ([], []))


if __name__ == "__main__":
    unittest.main()
