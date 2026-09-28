"""deadline-v1.2 (contract 1.4.0): the Requested ETA is frozen at the first Ready For Approval.

Every case runs through the public pipeline (activity logs -> cycles -> deadline metric / profile).
"""

import json
import unittest

import monday_factory as mf

from atlas_commander.contracts import validate
from atlas_commander.cycles import ETA_AT_READY_FOR_APPROVAL, NO_ETA_AT_OR_BEFORE_READY_FOR_APPROVAL
from atlas_commander.metrics import MetricPolicy, deadline_eligible, deadline_result, deadline_summary
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.profile import build_editor_profile
from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION, load_contract_version

NOW = "2026-09-28T00:00:00Z"
WILL = 6
RFA = "2026-09-02T18:00:00Z"


def project(item_id, *eta_logs, rfa=RFA):
    """Will, Class A, In Progress 2026-09-01 10:00 -> Ready For Approval ``rfa``, plus the given ETA logs."""
    return [mf.editor(f"{item_id}-ed", item_id, "2026-09-01T09:00:00Z", [WILL]),
            mf.video_type(f"{item_id}-vt", item_id, "2026-09-01T09:00:01Z", [4]),
            mf.status(f"{item_id}-s1", item_id, "2026-09-01T10:00:00Z", "Create File", "In Progress"),
            mf.status(f"{item_id}-s2", item_id, rfa, "In Progress", "Ready For Approval"),
            *eta_logs]


def revision_reset(item_id, moment, new_date, new_time):
    """A client revision round: Sent -> Revisions, then the ETA reset seconds later (the pattern seen on the live board)."""
    return [mf.status(f"{item_id}-r0", item_id, "2026-09-02T19:00:00Z", "Ready For Approval", "Sent"),
            mf.status(f"{item_id}-r1", item_id, moment, "Sent", "Revisions"),
            mf.eta(f"{item_id}-eta-reset", item_id, moment.replace(":00Z", ":02Z"), new_date, new_time)]


def cleared_eta(log_id, item_id, moment):
    return mf._log(log_id, item_id, mf.ETA, moment, None, None, column_type="date")


def snapshot(item_id, date, time, changed_at):
    value = {"date": date, "time": time}
    if changed_at:
        value["changed_at"] = changed_at
    return {"id": item_id, "board": {"id": mf.BOARD}, "column_values": [{"id": mf.ETA, "type": "date", "value": json.dumps(value), "text": ""}]}


class DeadlineV12Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_version("1.4.0")
        cls.v13 = load_contract_version("1.3.0")

    def cycle(self, logs, contract=None, items=None):
        result = reconstruct_cycles(mf.payload(*logs), contract or self.contract, items_payload=items, ingestion={"retrieved_at": NOW})
        (cycle,) = [c for c in result.cycles if c.state == "completed"]
        return cycle

    def metric(self, logs, contract=None, items=None):
        contract = contract or self.contract
        result = deadline_result(self.cycle(logs, contract, items), MetricPolicy.from_contract(contract), NOW)
        return result["metric"] if result else None

    def test_contract_14_is_active_and_selects_the_eta_at_ready_for_approval(self):
        self.assertEqual(ACTIVE_CONTRACT_VERSION, "1.4.0")
        self.assertEqual((self.contract["deadline"]["rule_version"], self.contract["deadline"]["requested_eta_selection"]),
                         ("deadline-v1.2", ETA_AT_READY_FOR_APPROVAL))

    def test_a_eta_changed_after_ready_for_approval_is_ignored(self):
        logs = project("1", mf.eta("1-eta", "1", "2026-09-01T09:05:00Z", "2026-09-02", "20:00:00"),
                       mf.eta("1-eta-late", "1", "2026-09-03T08:00:00Z", "2026-09-05", "12:00:00"))
        metric = self.metric(logs)
        self.assertEqual((metric["requested_eta"], metric["requested_eta_observed_at"], metric["result"], metric["delta_seconds"]),
                         ("2026-09-02T20:00:00Z", "2026-09-01T09:05:00Z", "early", -7200))
        self.assertEqual([change["event_id"] for change in metric["ignored_later_requested_eta_changes"]], ["1-eta-late"])
        self.assertEqual((metric["contract_version"], metric["evidence"]["rule_version"]), ("1.2.0", "deadline-v1.2"))
        self.assertEqual(metric["evidence"]["source_values"]["selected_requested_eta"], "2026-09-02T20:00:00Z")
        self.assertIn("1-eta", metric["evidence"]["event_ids"])
        self.assertEqual(validate(metric, "deadline-metric-v1.2.schema.json"), [])

    def test_b_late_first_submission_stays_late_after_a_revision_eta_reset(self):
        logs = project("2", mf.eta("2-eta", "2", "2026-09-01T09:05:00Z", "2026-09-02", "12:00:00"),
                       *revision_reset("2", "2026-09-03T10:00:00Z", "2026-09-04", "10:00:00"))
        metric = self.metric(logs)
        self.assertEqual((metric["requested_eta"], metric["result"], metric["delta_seconds"]), ("2026-09-02T12:00:00Z", "late", 6 * 3600))
        self.assertEqual([change["requested_eta"] for change in metric["ignored_later_requested_eta_changes"]], ["2026-09-04T10:00:00Z"])
        old = self.metric(logs, contract=self.v13)  # the previous rule used the reset ETA
        self.assertEqual((old["requested_eta"], old["result"]), ("2026-09-04T10:00:00Z", "early"))

    def test_c_early_first_submission_stays_early_after_a_revision_eta_reset(self):
        logs = project("3", mf.eta("3-eta", "3", "2026-09-01T09:05:00Z", "2026-09-02", "20:00:00"),
                       *revision_reset("3", "2026-09-03T10:00:00Z", "2026-09-04", "10:00:00"))
        metric = self.metric(logs)
        self.assertEqual((metric["requested_eta"], metric["result"], metric["delta_seconds"]), ("2026-09-02T20:00:00Z", "early", -7200))

    def test_d_latest_of_several_pre_submission_etas_is_used(self):
        logs = project("4", mf.eta("4-a", "4", "2026-09-01T09:05:00Z", "2026-09-03", None),
                       mf.eta("4-b", "4", "2026-09-01T09:05:02Z", "2026-09-03", "06:00:00"),
                       mf.eta("4-c", "4", "2026-09-02T09:00:00Z", "2026-09-02", "18:00:00"))
        metric = self.metric(logs)
        self.assertEqual((metric["requested_eta"], metric["requested_eta_observed_at"], metric["result"], metric["delta_seconds"]),
                         ("2026-09-02T18:00:00Z", "2026-09-02T09:00:00Z", "on_time", 0))
        self.assertEqual(metric["ignored_later_requested_eta_changes"], [])

    def test_e_eta_first_set_after_ready_for_approval_is_not_used(self):
        logs = project("5", mf.eta("5-eta", "5", "2026-09-03T08:00:00Z", "2026-09-04", "10:00:00"))
        cycle = self.cycle(logs)
        self.assertEqual((cycle.requested_eta, cycle.requested_eta_issue), (None, NO_ETA_AT_OR_BEFORE_READY_FOR_APPROVAL))
        self.assertEqual([change["event_id"] for change in cycle.requested_eta_ignored_after_ready_for_approval], ["5-eta"])
        self.assertIsNone(deadline_result(cycle, MetricPolicy.from_contract(self.contract), NOW))
        summary = deadline_summary([], [cycle])
        self.assertEqual((summary["not_classifiable_missing_eta"], summary["not_evaluated"][0]["reasons"]),
                         (1, [NO_ETA_AT_OR_BEFORE_READY_FOR_APPROVAL]))

    def test_f_date_only_eta_before_ready_for_approval_stays_unclassifiable(self):
        logs = project("6", mf.eta("6-eta", "6", "2026-09-01T09:05:00Z", "2026-09-02", None),
                       *revision_reset("6", "2026-09-03T10:00:00Z", "2026-09-04", "10:00:00"))
        cycle = self.cycle(logs)
        self.assertEqual((cycle.requested_eta, cycle.requested_eta_issue), (None, "REQUESTED_ETA_DATE_ONLY"))
        self.assertFalse(deadline_eligible(cycle))  # a later timed ETA never backfills it
        self.assertEqual(deadline_summary([], [cycle])["not_classifiable_insufficient_eta_precision"], 1)

    def test_g_contract_13_keeps_the_latest_eta_rule(self):
        logs = project("7", mf.eta("7-eta", "7", "2026-09-01T09:05:00Z", "2026-09-02", "20:00:00"),
                       mf.eta("7-eta-late", "7", "2026-09-03T08:00:00Z", "2026-09-02", "12:00:00"))
        old = self.metric(logs, contract=self.v13)
        self.assertEqual((old["contract_version"], old["requested_eta_selection"], old["requested_eta"], old["result"]),
                         ("1.1.0", "latest-available-requested-eta", "2026-09-02T12:00:00Z", "late"))
        self.assertEqual(validate(old, "deadline-metric-v1.1.schema.json"), [])
        self.assertNotIn("ignored_later_requested_eta_changes", old)
        new = self.metric(logs)
        self.assertEqual((new["requested_eta"], new["result"]), ("2026-09-02T20:00:00Z", "early"))

    def test_cleared_eta_before_submission_falls_back_to_the_last_valid_value(self):
        logs = project("8", mf.eta("8-eta", "8", "2026-09-01T09:05:00Z", "2026-09-02", "20:00:00"), cleared_eta("8-clear", "8", "2026-09-01T09:06:00Z"))
        cycle = self.cycle(logs)
        self.assertEqual((cycle.requested_eta, cycle.requested_eta_event_id, cycle.requested_eta_skipped_event_ids), ("2026-09-02T20:00:00Z", "8-eta", ["8-clear"]))

    def test_item_snapshot_is_used_only_with_monday_changed_at_before_submission(self):
        before = self.cycle(project("9"), items={"items": [snapshot("9", "2026-09-02", "20:00:00", "2026-09-01T08:00:00.000Z")]})
        self.assertEqual((before.requested_eta, before.requested_eta_source, before.requested_eta_observed_at),
                         ("2026-09-02T20:00:00Z", "item_snapshot", "2026-09-01T08:00:00.000Z"))
        after = self.cycle(project("9"), items={"items": [snapshot("9", "2026-09-04", "10:00:00", "2026-09-03T08:00:00.000Z")]})
        self.assertEqual((after.requested_eta, after.requested_eta_issue), (None, NO_ETA_AT_OR_BEFORE_READY_FOR_APPROVAL))
        unknown = self.cycle(project("9"), items={"items": [snapshot("9", "2026-09-02", "20:00:00", None)]})
        self.assertEqual((unknown.requested_eta, unknown.requested_eta_issue), (None, NO_ETA_AT_OR_BEFORE_READY_FOR_APPROVAL))
        logged = self.cycle(project("9", mf.eta("9-eta", "9", "2026-09-01T09:05:00Z", "2026-09-02", "20:00:00")),
                            items={"items": [snapshot("9", "2026-09-04", "10:00:00", "2026-09-03T08:00:00.000Z")]})
        self.assertEqual((logged.requested_eta, logged.requested_eta_event_id), ("2026-09-02T20:00:00Z", "9-eta"))

    def test_revisions_stay_context_only_and_profile_14_shows_the_evidence(self):
        logs = project("10", mf.eta("10-eta", "10", "2026-09-01T09:05:00Z", "2026-09-02", "12:00:00"),
                       *revision_reset("10", "2026-09-03T10:00:00Z", "2026-09-04", "10:00:00"))
        result = reconstruct_cycles(mf.payload(*logs), self.contract, ingestion={"retrieved_at": NOW})
        profile = build_editor_profile(result, self.contract, "editor-label-6", NOW)
        self.assertEqual(validate(profile, "editor-profile-v1.4.schema.json"), [])
        self.assertEqual((profile["contract_version"], profile["deadline"]["requested_eta_selection"]), ("1.4.0", ETA_AT_READY_FOR_APPROVAL))
        (row,) = profile["projects"]
        self.assertEqual((row["deadline_result"], row["requested_eta"], row["requested_eta_observed_at"], row["requested_eta_changes_ignored_after_ready_for_approval"],
                          row["client_revision_events"]), ("late", "2026-09-02T12:00:00Z", "2026-09-01T09:05:00Z", 1, 1))
        self.assertEqual(profile["trend"]["deadline_by_month"][0]["late"], 1)


if __name__ == "__main__":
    unittest.main()
