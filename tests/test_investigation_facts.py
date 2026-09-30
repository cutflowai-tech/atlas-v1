"""Intelligence V2 fact layer through the real Monday pipeline, and data-quality handling (Tasks 14, 15, 22, 62).

Synthetic Monday activity logs (``monday_factory``) go through ``reconstruct_cycles`` exactly as production data does, so these
tests prove how each Monday record becomes (or does not become) a fact. No real names or IDs.
"""

import random
import unittest

import monday_factory as mf

from atlas_commander.intelligence import completed_day_windows
from atlas_commander.investigation.facts import (
    EDITOR_PHASE,
    OPEN_VISIT,
    POST_EDITOR,
    PRE_EDITOR,
    UNKNOWN_STATUS_WITHIN_VISIT,
    build_facts,
)
from atlas_commander.pipeline import reconstruct_cycles, reconstruct_quality
from atlas_commander.runtime import load_contract_version

NOW = "2026-09-29T12:00:00Z"
CONTRACT = load_contract_version("1.5.0")
WILL, AHMED = (6, "Will"), (12, "Ahmed")


def project(item, editor=WILL, start="2026-09-20T08:00:00Z", ready="2026-09-20T18:00:00Z", eta=("2026-09-20", "20:00:00"), video=(4,), extra=()):
    logs = [mf.create_pulse(f"{item}-cp", item, "2026-09-20T05:00:00Z", {}),
            mf.editor(f"{item}-ed", item, "2026-09-20T06:00:00Z", [editor[0]], [editor[1]]),
            mf.video_type(f"{item}-vt", item, "2026-09-20T06:00:01Z", list(video)),
            mf.status(f"{item}-s0", item, "2026-09-20T06:30:00Z", "Waiting", "Create File"),
            mf.status(f"{item}-s1", item, start, "Create File", "In Progress"),
            mf.status(f"{item}-s2", item, ready, "In Progress", "Ready For Approval")]
    if eta:
        logs.append(mf.eta(f"{item}-eta", item, "2026-09-20T05:30:00Z", eta[0], eta[1]))
    return logs + list(extra)


def build(logs, items=None):
    result = reconstruct_cycles(mf.payload(*logs), CONTRACT, items_payload=items, ingestion={"retrieved_at": NOW})
    quality = reconstruct_quality(result, CONTRACT, NOW)
    return result, build_facts(result, CONTRACT, quality, completed_day_windows(NOW, 30, 30), NOW)


class TimelineTests(unittest.TestCase):
    def test_phases_follow_the_editor_interval_exactly(self):
        logs = project("101", extra=[mf.status("101-s3", "101", "2026-09-20T19:00:00Z", "Ready For Approval", "Sent"),
                                     mf.status("101-s4", "101", "2026-09-21T10:00:00Z", "Sent", "Revisions"),
                                     mf.status("101-s5", "101", "2026-09-21T14:00:00Z", "Revisions", "Ready For Approval")])
        _, facts = build(logs)
        visits = facts.timelines["101"].visits
        self.assertEqual([(v.status, v.phase) for v in visits], [("Create File", PRE_EDITOR), ("In Progress", EDITOR_PHASE), ("Ready For Approval", POST_EDITOR),
                                                                  ("Sent", POST_EDITOR), ("Revisions", POST_EDITOR), ("Ready For Approval", POST_EDITOR)])
        self.assertEqual(visits[1].duration_seconds, 10 * 3600)
        self.assertEqual(visits[-1].invalid_reason, OPEN_VISIT)
        fact = facts.projects[0]
        self.assertEqual((fact.duration_seconds, fact.review_wait_seconds, fact.delivered_at), (36000, 3600, "2026-09-20T19:00:00Z"))
        self.assertEqual(fact.client_revisions, 1)                              # context only; never part of execution time

    def test_retired_status_invalidates_the_visit_instead_of_repairing_it(self):
        logs = project("102", extra=[mf.status("102-x", "102", "2026-09-20T12:00:00Z", "In Progress", "Editing Now")])
        _, facts = build(logs)
        invalid = [v for v in facts.timelines["102"].visits if v.invalid_reason == UNKNOWN_STATUS_WITHIN_VISIT]
        self.assertEqual([v.status for v in invalid], ["In Progress"])
        self.assertIn("UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW", facts.projects[0].exclusions)
        self.assertEqual(facts.coverage["stage_visits_invalid"], 1)

    def test_duplicate_and_undone_transitions_do_not_create_stages(self):
        logs = project("103", extra=[mf.status("103-dup", "103", "2026-09-20T09:00:00Z", "Create File", "In Progress"),
                                     mf.status("103-undo", "103", "2026-09-20T09:30:00Z", "In Progress", "Sent", undo=True)])
        _, facts = build(logs)
        timeline = facts.timelines["103"]
        self.assertEqual(timeline.duplicate_transitions, 1)
        self.assertNotIn("Sent", [v.status for v in timeline.visits])

    def test_ready_before_start_is_excluded_not_reordered(self):
        logs = [mf.editor("104-ed", "104", "2026-09-20T06:00:00Z", [6], ["Will"]),
                mf.status("104-a", "104", "2026-09-20T07:00:00Z", "Create File", "Ready For Approval")]
        result, facts = build(logs)
        self.assertEqual(facts.projects, [])
        self.assertIn("MISSING_IN_PROGRESS", result.cycles[0].exclusions)


class ProjectFactTests(unittest.TestCase):
    def test_runway_uses_the_d19_eta_and_flags_late_setting(self):
        logs = project("201", eta=None, extra=[mf.eta("201-eta", "201", "2026-09-20T09:00:00Z", "2026-09-20", "16:00:00")])
        _, facts = build(logs)
        fact = facts.projects[0]
        self.assertEqual(fact.runway_seconds, 8 * 3600)
        self.assertTrue(fact.eta_observed_after_start)
        self.assertEqual(fact.deadline_result, "late")

    def test_missing_and_date_only_eta_are_never_guessed(self):
        _, facts = build(project("202", eta=None) + project("203", eta=("2026-09-20", None)))
        by_item = {fact.monday_item_id: fact for fact in facts.projects}
        self.assertIsNone(by_item["202"].runway_seconds)
        self.assertIsNone(by_item["202"].deadline_result)
        self.assertEqual(by_item["203"].requested_eta_issue, "REQUESTED_ETA_DATE_ONLY")
        self.assertIsNone(by_item["203"].deadline_result)

    def test_missing_editor_identity_is_unattributed(self):
        logs = [log for log in project("204") if log["id"] != "204-ed"]
        _, facts = build(logs)
        self.assertIsNone(facts.projects[0].editor_id)
        self.assertEqual(facts.coverage["unattributed"], 1)
        self.assertIsNone(facts.projects[0].deadline_result)

    def test_unknown_video_type_is_not_benchmark_eligible(self):
        _, facts = build(project("205", video=(99,)))
        self.assertFalse(facts.projects[0].benchmark_eligible)

    def test_malformed_label_is_quarantined_not_counted(self):
        logs = project("206", extra=[mf.dropdown("206-lab", "206", mf.ISSUES, "2026-09-21T00:00:00Z", [999], ["Mystery"])])
        _, facts = build(logs)
        self.assertEqual(facts.projects[0].labels, ())

    def test_shared_actor_never_identifies_a_person(self):
        logs = project("207", extra=[mf.status("207-z", "207", "2026-09-20T19:00:00Z", "Ready For Approval", "TOPAZ")])
        result, facts = build(logs)
        self.assertIn("unresolved", {t["role"] for t in result.transitions})
        self.assertEqual(facts.projects[0].editor_id, "editor-label-6")          # from Editor Name, never from the actor account
        for field in ("actor_id", "actor_monday_id"):
            self.assertFalse(hasattr(facts.projects[0], field))

    def test_concurrency_counts_other_open_first_cycles_of_the_same_editor(self):
        logs = project("301", start="2026-09-20T08:00:00Z", ready="2026-09-20T20:00:00Z")
        logs += project("302", start="2026-09-20T09:00:00Z", ready="2026-09-20T12:00:00Z")
        logs += project("303", start="2026-09-20T10:00:00Z", ready="2026-09-20T11:00:00Z")
        logs += project("304", editor=AHMED, start="2026-09-20T10:30:00Z", ready="2026-09-20T11:00:00Z")
        _, facts = build(logs)
        by_item = {fact.monday_item_id: fact.concurrency_at_start for fact in facts.projects}
        self.assertEqual(by_item, {"301": 0, "302": 1, "303": 2, "304": 0})

    def test_facts_do_not_depend_on_log_order(self):
        logs = project("401") + project("402", editor=AHMED) + project("403", start="2026-09-20T09:00:00Z")
        _, first = build(logs)
        shuffled = list(logs)
        random.Random(7).shuffle(shuffled)
        _, second = build(shuffled)
        self.assertEqual([vars(fact) for fact in first.projects], [vars(fact) for fact in second.projects])


class OpenWorkTests(unittest.TestCase):
    def test_open_work_from_snapshot_with_status_entry_time(self):
        logs = [mf.editor("501-ed", "501", "2026-09-28T06:00:00Z", [6], ["Will"]),
                mf.status("501-s1", "501", "2026-09-28T08:00:00Z", "Create File", "In Progress")]
        items = {"items": [{"id": "501", "board": {"id": mf.BOARD}, "column_values": [
            {"id": mf.EDITOR, "type": "dropdown", "value": '{"ids": [6]}', "text": "Will"},
            {"id": mf.STATUS, "type": "status", "value": '{"index": 9}', "text": "In Progress"},
            {"id": mf.ETA, "type": "date", "value": '{"date": "2026-09-29", "time": "10:00:00"}', "text": "2026-09-29 10:00"},
            {"id": mf.VIDEO_TYPE, "type": "dropdown", "value": '{"ids": [4]}', "text": "Class A"}]}]}
        _, facts = build(logs, items)
        work = facts.open_work[0]
        self.assertEqual((work.current_status, work.current_editor_id, work.cohort_key, work.requested_eta),
                         ("In Progress", "editor-label-6", "4", "2026-09-29T10:00:00Z"))
        self.assertEqual(work.status_entered_at, "2026-09-28T08:00:00Z")
        self.assertTrue(work.active)


if __name__ == "__main__":
    unittest.main()
